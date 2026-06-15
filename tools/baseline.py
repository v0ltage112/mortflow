# tools/baseline.py
from __future__ import annotations
from pathlib import Path
import argparse
import copy
import yaml
import pandas as pd

from src.engine import load_inputs, load_actuals, run_engine
from src.metrics import compute_baseline_kpis
# Phase 2 path resolver: output root and per-property paths come from the config
# layer instead of being assumed relative to the current working directory.
from src.paths import resolve_out_dir, resolve_relative


# ---------------- utilities ----------------

def _slug(name: str) -> str:
    s = name.strip().lower()
    for ch in [' ', '/', '\\', ',', '.', "'", '"', '&', '(', ')', '[', ']', ':', ';', '|', '?', '!']:
        s = s.replace(ch, '-')
    while '--' in s:
        s = s.replace('--', '-')
    return s.strip('-')


def _read_yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text())


def _write_yaml(p: Path, data: dict) -> None:
    p.write_text(yaml.safe_dump(data, sort_keys=False))


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


def _write_outputs(out_dir: Path, monthly, reconcile, events) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(out_dir / "baseline_monthly.csv", index=False)
    reconcile.to_csv(out_dir / "baseline_reconcile.csv", index=False)
    events.to_csv(out_dir / "baseline_events_daily.csv", index=False)


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

    _write_outputs(out_dir, monthly, reconcile, events)

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