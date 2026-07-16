# tests/test_portfolio_manifest.py
"""Tests proving the portfolio manifest refactor: portfolio.yaml is the only
source of truth for which properties run.

Phase 11 / S3 replaces a hardcoded property list in tools/portfolio.py with
discovery from portfolio.yaml (enabled + kind per property). These tests
build small temporary manifests in tmp_path that point at the already-bundled
Property B (mortgage) and Property C (valuation-only, PKR) sample data, so no
new fixture data is added here. Disabling, adding, or filtering a property is
proven to be a config change only, never a code change.
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Optional
import pandas as pd
import yaml

import tools.portfolio as portfolio

# Repo-root-relative paths to the sample data already bundled for S1 and S2.
# Resolved once here so every manifest entry below can point at an absolute
# path, since the manifests themselves live in tmp_path, not data_sample/.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROPERTY_B_INPUTS = _REPO_ROOT / "data_sample" / "property_b" / "inputs.sample.yaml"
_PROPERTY_B_ACTUALS = _REPO_ROOT / "data_sample" / "property_b" / "actuals.sample.csv"
_PROPERTY_C_INPUTS = _REPO_ROOT / "data_sample" / "property_c" / "inputs.sample.yaml"


def _write_manifest(path: Path, properties: list) -> None:
    """Write a minimal portfolio.yaml with the given property entries.

    Mirrors the shape tools.portfolio.load_portfolio expects: a top-level
    'properties' list. No 'output' block is set, so the rollup falls back to
    tools.portfolio.DEFAULT_CSV_SUBDIR.
    """
    path.write_text(yaml.safe_dump({"properties": properties}))


def _run_portfolio(manifest_path: Path, out_dir: Path, monkeypatch, only: Optional[str] = None) -> pd.DataFrame:
    """Run tools.portfolio.main() against a manifest and return the summary rows.

    Monkeypatches sys.argv so main()'s own argparse call picks up the given
    manifest and output folder, exactly like a real command-line invocation.
    """
    argv = ["tools/portfolio.py", "--portfolio", str(manifest_path), "--out", str(out_dir)]
    if only is not None:
        argv += ["--only", only]
    monkeypatch.setattr(sys, "argv", argv)
    portfolio.main()
    # main() writes the summary CSV only when at least one property runs. A
    # run with no enabled matches (for example --only naming a disabled
    # property) writes nothing, which is a valid empty result, so a missing
    # file is returned as an empty frame with the locked columns rather than
    # raising a FileNotFoundError.
    summary_csv = out_dir / "csv" / "portfolio_summary.csv"
    if not summary_csv.exists():
        return pd.DataFrame(columns=portfolio.LOCKED_SUMMARY_COLUMNS)
    return pd.read_csv(summary_csv)


def test_disabling_a_property_removes_it_with_no_code_change(tmp_path, monkeypatch):
    """A two-property manifest, rerun with the second entry disabled, drops that row.

    Property B stays enabled throughout so this isolates the effect of the
    enabled flag alone, not a change in which properties exist.
    """
    manifest = tmp_path / "portfolio.yaml"
    properties = [
        {
            "name": "Manifest Test B",
            "property_kind": "investment",
            "tax_enabled": False,
            "enabled": True,
            "inputs": str(_PROPERTY_B_INPUTS),
            "actuals": str(_PROPERTY_B_ACTUALS),
        },
        {
            "name": "Manifest Test C",
            "property_kind": "owned_outright",
            "tax_enabled": False,
            "enabled": True,
            "inputs": str(_PROPERTY_C_INPUTS),
        },
    ]
    _write_manifest(manifest, properties)

    both_enabled = _run_portfolio(manifest, tmp_path / "run_both", monkeypatch)
    assert set(both_enabled["property_name"]) == {"Manifest Test B", "Manifest Test C"}

    properties[1]["enabled"] = False
    _write_manifest(manifest, properties)

    one_enabled = _run_portfolio(manifest, tmp_path / "run_one", monkeypatch)
    assert set(one_enabled["property_name"]) == {"Manifest Test B"}


def test_adding_a_property_is_picked_up_with_no_code_change(tmp_path, monkeypatch):
    """A manifest that grows a new entry between runs surfaces that property
    with no change to tools/portfolio.py, and the new property's own inputs
    file (not the manifest) is what sets its currency.
    """
    manifest = tmp_path / "portfolio.yaml"
    properties = [
        {
            "name": "Manifest Test B",
            "property_kind": "investment",
            "tax_enabled": False,
            "enabled": True,
            "inputs": str(_PROPERTY_B_INPUTS),
            "actuals": str(_PROPERTY_B_ACTUALS),
        },
    ]
    _write_manifest(manifest, properties)
    before = _run_portfolio(manifest, tmp_path / "run_before", monkeypatch)
    assert set(before["property_name"]) == {"Manifest Test B"}

    # Add a second entry, a clone of the bundled valuation-only PKR sample
    # under a new name. No entry here sets a currency: that comes only from
    # the property's own inputs file.
    properties.append({
        "name": "Manifest Test C (added)",
        "property_kind": "owned_outright",
        "tax_enabled": False,
        "enabled": True,
        "inputs": str(_PROPERTY_C_INPUTS),
    })
    _write_manifest(manifest, properties)
    after = _run_portfolio(manifest, tmp_path / "run_after", monkeypatch)

    assert set(after["property_name"]) == {"Manifest Test B", "Manifest Test C (added)"}
    added_row = after.loc[after["property_name"] == "Manifest Test C (added)"].iloc[0]
    # Currency propagation is per-property: the added entry inherits PKR from
    # its own inputs file, even though portfolio.yaml never mentions currency.
    assert added_row["currency"] == "PKR"
    assert pd.notna(added_row["native_value"])


def test_only_flag_still_filters_the_discovered_set(tmp_path, monkeypatch):
    """--only narrows the already-discovered enabled set; it does not bypass discovery.

    A disabled property passed to --only must still be excluded, proving
    --only filters on top of the enabled flag rather than overriding it.
    """
    manifest = tmp_path / "portfolio.yaml"
    properties = [
        {
            "name": "Manifest Test B",
            "property_kind": "investment",
            "tax_enabled": False,
            "enabled": True,
            "inputs": str(_PROPERTY_B_INPUTS),
            "actuals": str(_PROPERTY_B_ACTUALS),
        },
        {
            "name": "Manifest Test C",
            "property_kind": "owned_outright",
            "tax_enabled": False,
            "enabled": False,
            "inputs": str(_PROPERTY_C_INPUTS),
        },
    ]
    _write_manifest(manifest, properties)

    only_enabled = _run_portfolio(manifest, tmp_path / "run_only_enabled", monkeypatch, only="Manifest Test B")
    assert set(only_enabled["property_name"]) == {"Manifest Test B"}

    only_disabled = _run_portfolio(manifest, tmp_path / "run_only_disabled", monkeypatch, only="Manifest Test C")
    assert only_disabled.empty