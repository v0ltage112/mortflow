"""Shared fixtures and discovery helpers for the entire test suite.

This module centralises property discovery so every test exercises the same
scenarios.  Tweaks to data loading or CLI options therefore happen in one
place, keeping the rest of the suite focused on behavioural assertions.

Highlights
----------
* Loads enabled properties from the resolved ``portfolio.yaml``.
* Supports ``--prop`` (case-insensitive substring filter) for selective runs.
* Provides cached fixtures for inputs, actuals, and engine outputs.
* Offers ``--diag`` to print discovery diagnostics when debugging.

If something goes wrong
-----------------------
* "No enabled properties matched" – double-check ``portfolio.yaml`` and
  the value passed via ``--prop``.
* Import errors – ensure the repo root was injected into ``sys.path`` (handled
  near the top of this file).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List
import sys

import pytest
import yaml

# Make repo root importable (so `src` resolves cleanly)
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Engine API
from src.engine import load_inputs, load_actuals, run_engine, compute_portal_style_metrics  # type: ignore
# P2/S2: config-aware path resolution, shared with engine.py and the tools.
from src.paths import resolve_data_dir, resolve_relative  # type: ignore


# --------------------------- CLI options --------------------------------------
def pytest_addoption(parser):
    """Register CLI switches that control property discovery."""
    parser.addoption(
        "--prop",
        action="append",
        default=[],
        help="Filter properties by substring match against name/slug (e.g. --prop property-a).",
    )
    parser.addoption(
        "--diag",
        action="store_true",
        help="Print diagnostic info about discovered property cases during collection.",
    )


# --------------------------- helpers ------------------------------------------
def _slugify(name: str) -> str:
    """Convert a property name to a filesystem-friendly slug."""
    s = name.strip().lower()
    for ch in [' ', '/', '\\', ',', '.', "'", '"', '&', '(', ')', '[', ']', ':', ';', '|', '?', '!']:
        s = s.replace(ch, '-')
    while '--' in s:
        s = s.replace('--', '-')
    return s.strip('-')


@dataclass(frozen=True)
class Case:
    """Representation of a single property scenario pulled from YAML."""
    name: str
    slug: str
    kind: str
    inputs_path: Path
    actuals_path: Path
    out_dir: Path


def _load_cases(prop_filters: List[str]) -> List[Case]:
    """Build the list of enabled properties from the resolved ``portfolio.yaml``.

    A property is included when it's marked ``enabled`` and matches the optional
    ``--prop`` filters supplied on the command line.  The portfolio file is
    located via the shared resolver, and each property's ``inputs`` and
    ``actuals`` are resolved relative to the ``portfolio.yaml`` folder so the
    data tree is self-contained and relocatable (P2/S2).
    """
    pf = [p.lower() for p in (prop_filters or [])]
    # P2/S2: locate portfolio.yaml via the resolver (CLI > env > paths.local.yaml > ./data).
    # With no config this is <repo_root>/data/portfolio.yaml, so a plain repo-root run is unchanged.
    port_path = resolve_data_dir() / "portfolio.yaml"
    raw = yaml.safe_load(port_path.read_text())
    props = raw.get("properties", []) if isinstance(raw, dict) else []
    cases: List[Case] = []
    for p in props:
        if not p.get("enabled", False):
            continue
        name = p["name"]
        slug = _slugify(name)
        # substring filter on name or slug
        if pf and not any(f in slug or f in name.lower() for f in pf):
            continue
        cases.append(
            Case(
                name=name,
                slug=slug,
                kind=p.get("property_kind", ""),
                # P2/S2: resolve child paths relative to portfolio.yaml's own folder,
                # mirroring tools/portfolio.py and tools/baseline.py. portfolio.yaml now
                # stores folder-relative paths (e.g. "gandon/inputs.yaml"), not repo-relative.
                inputs_path=resolve_relative(port_path, p["inputs"]),
                actuals_path=resolve_relative(port_path, p["actuals"]),
                out_dir=Path("out") / (p.get("out_dir") or slug),
            )
        )
    return cases


# ---------------------- parametrisation hook ----------------------------------
def pytest_generate_tests(metafunc):
    """Parametrise the ``case`` fixture with discovered properties."""
    if "case" in metafunc.fixturenames:
        prop_filters = metafunc.config.getoption("--prop")
        cases = _load_cases(prop_filters)
        if metafunc.config.getoption("--diag"):
            print("\n[diag] discovered cases:")
            if not cases:
                print("  (none) – check portfolio.yaml and --prop filter")
            for c in cases:
                print(f"  - {c.slug}  | kind={c.kind}  | inputs={c.inputs_path}  | actuals={c.actuals_path}")
        if not cases:
            pytest.skip("No enabled properties matched (--prop filter or portfolio settings).", allow_module_level=True)
        metafunc.parametrize("case", cases, ids=[c.slug for c in cases], scope="session")


# --------------------------- fixtures -----------------------------------------
@pytest.fixture(scope="session")
def inputs_path(case: Case) -> Path:
    """Path to the YAML inputs for the current property case."""
    return case.inputs_path


@pytest.fixture(scope="session")
def actuals_path(case: Case) -> Path:
    """Path to the bank-actuals CSV for the current property case."""
    return case.actuals_path


@pytest.fixture(scope="session")
def inputs(inputs_path: Path):
    """Parsed loan inputs for the active case."""
    return load_inputs(inputs_path)


@pytest.fixture(scope="session")
def actuals_df(actuals_path: Path):
    """Loaded bank transactions for the active case."""
    return load_actuals(actuals_path)


@pytest.fixture(scope="session")
def engine_outputs(inputs, actuals_df):
    """Run the engine once per case and cache the result for reuse."""
    monthly, reconcile, events = run_engine(inputs, actuals_df)
    import pandas as pd
    assert all(isinstance(df, pd.DataFrame) for df in (monthly, reconcile, events))
    return monthly, reconcile, events


# Optional: pick a portal snapshot date from YAML if present
@pytest.fixture(scope="session")
def portal_snapshot_date(inputs_path: Path):
    """Pick the most recent portal snapshot date declared in YAML (if any)."""
    from datetime import date, datetime
    raw = yaml.safe_load(Path(inputs_path).read_text())
    snaps = (raw.get("reconcile", {}) or {}).get("snapshots", []) or []
    if not snaps:
        return None

    def as_date(x):
        if isinstance(x, date):
            return x
        return datetime.strptime(str(x), "%Y-%m-%d").date()

    latest = max(snaps, key=lambda s: as_date(s["date"]))
    return as_date(latest["date"])


@pytest.fixture(scope="session")
def portal_metrics(engine_outputs, inputs, portal_snapshot_date):
    """Precompute portal-style metrics when a snapshot date is available."""
    monthly, _, events = engine_outputs
    if portal_snapshot_date is None:
        return {}
    return compute_portal_style_metrics(portal_snapshot_date, inputs, events, monthly)