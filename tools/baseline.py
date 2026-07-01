# tools/baseline.py
"""Baseline builder: freeze the contract-only mortgage schedule per property.

Finance-readable summary
------------------------
A "baseline" is the clean, contract-only version of a mortgage: the schedule you
would get with no voluntary overpayments, no one-off lump sums, and no bank
habit of folding a standing extra into the monthly payment. It is the reference
the golden-master test locks, so later refactors can be proven not to move a
single cent. This tool builds that baseline for each enabled property in a
portfolio (or for one property on its own) and writes the frozen CSVs plus a
KPI sheet.

Phase 6 / S5 note: a no-mortgage, owned-outright property has no loan and no
actuals file, so there is nothing to baseline. Such a property is skipped here;
its value over time is produced by the engine's valuation-only path and rolled
up by tools/portfolio.py instead. Without this skip the loop would raise
KeyError on the missing actuals path and take the whole run down with it.

Phase 8 / S3 note: the three frozen baseline CSVs (``baseline_monthly.csv``,
``baseline_reconcile.csv``, ``baseline_events_daily.csv``) are now written into
the property's ``output.csv_subdir`` sub-folder (default ``csv``) rather than
beside the KPI workbook, matching the engine's writer paths. The
``baseline_kpis.xlsx`` and the ``baseline.effective.inputs.yaml`` snapshot stay
at the property root. CSV contents are unchanged, so the golden master (which
compares CSV values) stays green; only the paths moved.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import copy
import sys
import yaml
import pandas as pd

from src.engine import load_inputs, load_actuals, run_engine
from src.metrics import compute_baseline_kpis
# Phase 2 path resolver: output root and per-property paths come from the config
# layer instead of being assumed relative to the current working directory.
from src.paths import resolve_out_dir, resolve_relative


# Phase 6 / S5: property kinds that carry no mortgage. A baseline freezes the
# contractual mortgage schedule, so a no-loan property has nothing to baseline.
# Mirrors the owned-outright spellings the schema accepts.
_VALUATION_ONLY_KINDS = {"owned_outright", "owned-outright", "outright", "owned"}


# ---------------- utilities ----------------

def _slug(name: str) -> str:
    """Turn a property name into a filesystem-safe output folder slug.

    Finance note: the slug is the per-property subfolder name (for example
    'Property A' -> 'property-a'), so each property's frozen baseline lands in
    its own predictable place.
    """
    s = name.strip().lower()
    for ch in [' ', '/', '\\', ',', '.', "'", '"', '&', '(', ')', '[', ']', ':', ';', '|', '?', '!']:
        s = s.replace(ch, '-')
    while '--' in s:
        s = s.replace('--', '-')
    return s.strip('-')


def _read_yaml(p: Path) -> dict:
    """Read a YAML file into a plain dict."""
    return yaml.safe_load(p.read_text())


def _write_yaml(p: Path, data: dict) -> None:
    """Write a dict back to YAML, keeping key order for a readable diff."""
    p.write_text(yaml.safe_dump(data, sort_keys=False))


def _is_valuation_only(p: dict) -> bool:
    """Return True when a portfolio entry has no mortgage to baseline.

    Finance note: a baseline is the contract-only mortgage schedule. An
    owned-outright property has no loan, so it declares no `actuals` file and
    there is nothing to freeze. A missing `actuals` line is the primary signal;
    an explicit owned-outright kind is also accepted.
    """
    if not p.get("actuals"):
        return True
    return str(p.get("property_kind", "")).strip().lower() in _VALUATION_ONLY_KINDS


def _sanitize_for_strict_baseline(cfg: dict) -> dict:
    """
    Return a deep-copied inputs dict with user overlays removed.

    - Removes recurring overpays and one-off lumps.
    - Turns off merging extras into the base payment (to avoid hidden +€200).
    - Leaves contractual holidays and rate blocks intact.
    """
    c = copy.deepcopy(cfg)

    # Remove overpay and lump overlays completely
    c["overpay_rules"] = []
    c["lump_sums"] = []

    # Bank merging of extras into base → force off for baseline clarity
    bank = c.get("bank") or {}
    bank["merge_standing_extra_into_payment"] = False
    c["bank"] = bank

    return c


def _write_outputs(out_dir: Path, monthly, reconcile, events, csv_subdir: str) -> None:
    """Write the three frozen baseline CSVs into the property's csv/ sub-folder.

    Phase 8 / S3: the baseline CSVs are demoted into ``csv_subdir`` (default
    "csv"), matching the engine writer paths, so a property folder shows the
    baseline_kpis.xlsx and the effective-inputs YAML at its root and the frozen
    CSVs under csv/. An empty csv_subdir restores the old flat layout. CSV
    contents are unchanged, so the golden master (which compares CSV values)
    stays green.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    # The frozen CSVs go under csv_subdir; an empty value keeps them at out_dir.
    csv_dir = (out_dir / csv_subdir) if csv_subdir else out_dir
    csv_dir.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(csv_dir / "baseline_monthly.csv", index=False)
    reconcile.to_csv(csv_dir / "baseline_reconcile.csv", index=False)
    events.to_csv(csv_dir / "baseline_events_daily.csv", index=False)


def _run_single(inputs_path: Path, actuals_path: Path, out_dir: Path, *, strict_baseline: bool) -> dict:
    """
    Load inputs, optionally sanitise to strict baseline, run engine, write artefacts,
    compute baseline KPI dict (values-only).
    """
    raw = _read_yaml(inputs_path)
    effective = _sanitize_for_strict_baseline(raw) if strict_baseline else raw

    # Persist the *effective* inputs to make runs reproducible/auditable.
    eff_path = out_dir / "baseline.effective.inputs.yaml"
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_yaml(eff_path, effective)

    # Run with the effective config (not the raw)
    inputs = load_inputs(eff_path)
    actuals = load_actuals(actuals_path)
    monthly, reconcile, events = run_engine(inputs, actuals)

    # Phase 8 / S3: route the frozen CSVs into the property's csv/ sub-folder
    # (the knob the schema parsed onto inputs.output). The KPI workbook and the
    # effective-inputs YAML below stay at the property root.
    _write_outputs(out_dir, monthly, reconcile, events, inputs.output.csv_subdir)

    # KPIs (BC: pass inputs/monthly/events for richer fields, e.g. as_of_date)
    k = compute_baseline_kpis(inputs, monthly, events)
    # Write a compact XLSX row for humans
    pd.DataFrame([k]).to_excel(out_dir / "baseline_kpis.xlsx", index=False)
    return k


def _load_portfolio(path: Path) -> list[dict]:
    raw = _read_yaml(path)
    props = raw.get("properties") or []
    if not isinstance(props, list):
        raise ValueError("portfolio.yaml must contain a 'properties' list")
    # keep only enabled properties
    return [p for p in props if p.get("enabled", True)]


# ---------------- CLI entry ----------------

def main():
    ap = argparse.ArgumentParser(description="S0 Baseline builder(s)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--portfolio", type=Path, help="Path to portfolio.yaml (build for each enabled property)")
    g.add_argument("--inputs", type=Path, help="Single property: inputs.yaml")
    ap.add_argument("--actuals", type=Path, help="Single property: actuals.csv (required with --inputs)")
    # --out is optional now.  When omitted, the output root is resolved through
    # the config layer (CLI > MORTGAGE_OUT_DIR > paths.local.yaml > <repo>/out).
    ap.add_argument("--out", type=Path, default=None, help="Root output folder (overrides config)")
    ap.add_argument("--strict-baseline", action="store_true",
                    help="Sanitise overlays (overpay/lumps/merge) for contract-only baseline")
    args = ap.parse_args()

    # Resolve the output root through the config layer.  Passing the raw CLI value
    # (or None) keeps an explicit --out as the highest-priority source.
    out_root = resolve_out_dir(str(args.out) if args.out is not None else None)
    out_root.mkdir(parents=True, exist_ok=True)

    if args.portfolio:
        rows = []
        for p in _load_portfolio(args.portfolio):
            name = p.get("name", "property")
            kind = p.get("property_kind", "")
            # Phase 6 / S5: a no-mortgage property has no actuals and no
            # contractual schedule to freeze. Skip it here (the engine's
            # valuation-only path and tools/portfolio.py handle it) rather than
            # raising KeyError on the missing actuals path.
            if _is_valuation_only(p):
                print(
                    f"[baseline] Skipping {name} ({kind or 'no kind'}): "
                    "valuation-only, no mortgage baseline.",
                    file=sys.stderr,
                )
                continue
            # Resolve per-property paths relative to the portfolio.yaml location so
            # relative entries do not depend on the current working directory.
            in_path = resolve_relative(args.portfolio, p["inputs"])
            ac_path = resolve_relative(args.portfolio, p["actuals"])
            out_dir = out_root / _slug(p.get("out_dir", name))
            print(f"[baseline] Building {'STRICT ' if args.strict_baseline else ''}baseline → {name} ({kind})")
            k = _run_single(in_path, ac_path, out_dir, strict_baseline=args.strict_baseline)
            rows.append({"property_name": name, "property_kind": kind} | k)

        # Portfolio-level sheet for quick comparison
        pd.DataFrame(rows).to_excel(out_root / "portfolio_baseline_kpis.xlsx", index=False)
        print(f"Wrote portfolio baselines to: {out_root}")
        return

    # Single property mode
    if not args.inputs or not args.actuals:
        ap.error("--inputs and --actuals are both required when not using --portfolio")

    out_dir = out_root / _slug(args.inputs.parent.name)
    print(f"[baseline] Building {'STRICT ' if args.strict_baseline else ''}baseline (single) → {out_dir}")
    _run_single(args.inputs, args.actuals, out_dir, strict_baseline=args.strict_baseline)
    print(f"Wrote outputs to: {out_dir}")


if __name__ == "__main__":
    main()