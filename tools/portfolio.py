# tools/portfolio.py
"""Portfolio runner: run the engine once per property and roll up a summary.

Finance-readable summary
------------------------
This is the one button that runs every property in the portfolio and collects a
single side-by-side summary. It reads portfolio.yaml (the list of properties and
their on/off switches), runs the same ``python -m src.engine`` per property that
a person would run by hand, and gathers one headline row per property into a CSV
and a formatted Excel workbook.

Phase 6 / S5 note: the runner now handles a mixed portfolio cleanly. A property
with a mortgage runs exactly as before (it passes ``--actuals`` and reads the
monthly schedule for KPIs). A property with no mortgage (owned-outright,
declared in portfolio.yaml without an ``actuals`` line) runs through the
engine's valuation-only path: ``--actuals`` is omitted and the summary row is
built from ``valuation_schedule.csv`` instead of the loan schedule. Per-property
enable already worked via the ``enabled`` flag and is unchanged.

Technical summary
-----------------
``run_engine_cli`` now takes an optional actuals path and only appends
``--actuals`` when one is given. The main loop classifies each enabled property
as mortgage-bearing or valuation-only (missing ``actuals`` or an owned-outright
kind), runs the right engine path, and appends the matching summary row.
``_valuation_summary_row`` reads the value-over-time CSV for the no-loan case.
The combined DataFrame unions both row shapes; loan-only columns are simply
blank for a valuation-only property.
"""
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
import yaml
from openpyxl.styles import Font  # Phase 6 / S6: build bold fonts directly (Font.copy() is deprecated)

from src.engine import load_inputs  # to pass real inputs to KPIs if supported
from src.metrics import compute_baseline_kpis
# Phase 2 path resolver: output root and per-property paths come from the config
# layer instead of being assumed relative to the current working directory.
from src.paths import resolve_out_dir, resolve_relative

# Phase 6 / S5: kinds that carry no mortgage and therefore run the valuation-only
# path. Mirrors the canonical owned-outright spellings the schema accepts so the
# runner agrees with the engine without importing schema internals.
_VALUATION_ONLY_KINDS = {"owned_outright", "owned-outright", "outright", "owned"}

def slugify(name: str) -> str:
    """Turn a property name into a filesystem-safe output folder slug.

    Finance note: the slug is the per-property subfolder under the output root
    (for example 'Property A' -> 'property-a'), so each property's files land in
    their own predictable place.
    """
    s = name.strip().lower()
    for ch in [' ', '/', '\\', ',', '.', "'", '"', '&', '(', ')', '[', ']', ':', ';', '|', '?', '!']:
        s = s.replace(ch, '-')
    while '--' in s:
        s = s.replace('--', '-')
    return s.strip('-')

def load_portfolio(p: Path) -> Dict:
    """Read portfolio.yaml into a dict and check it carries a properties list.

    Finance note: portfolio.yaml is the master list of which properties exist
    and which are switched on. A missing 'properties' list is a hard error
    because there would be nothing to run.
    """
    raw = yaml.safe_load(p.read_text())
    assert "properties" in raw and isinstance(raw["properties"], list), "portfolio.yaml missing 'properties' list"
    return raw

def run_engine_cli(inputs_path: Path, actuals_path: Optional[Path], out_dir: Path) -> None:
    """Run ``python -m src.engine`` once for a single property.

    Finance note: this shells out to exactly the command a person would type by
    hand, so the portfolio runner and a manual run produce identical per-property
    files. A valuation-only property has no bank loan to reconcile, so
    ``actuals_path`` is None and ``--actuals`` is left off; the engine then takes
    its no-mortgage valuation-only path.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    # Build the command incrementally: --actuals is only added for a mortgage
    # property. Omitting it is what routes an owned-outright property to the
    # engine's valuation-only path.
    cmd = [sys.executable, "-m", "src.engine", "--inputs", str(inputs_path)]
    if actuals_path is not None:
        cmd += ["--actuals", str(actuals_path)]
    cmd += ["--out", str(out_dir)]
    subprocess.run(cmd, check=True)

# ---- XLSX formatting helpers (lightweight, values-only) ----------------------

def _header_map(ws):
    """Map each column header text to its 1-based column index."""
    return {ws.cell(row=1, column=c).value: c for c in range(1, ws.max_column + 1)}

def fmt_money(ws, col_name):
    """Apply a euro money format to a named column, if it is present."""
    col = _header_map(ws).get(col_name)
    if not col: return
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=col).number_format = "\u20ac#,##0.00"

def fmt_pct(ws, col_name):
    """Apply a percent format to a named column, if it is present."""
    col = _header_map(ws).get(col_name)
    if not col: return
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=col).number_format = "0.00%"

def fmt_date(ws, col_name):
    """Apply an ISO date format to a named column, if it is present."""
    col = _header_map(ws).get(col_name)
    if not col: return
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=col).number_format = "yyyy-mm-dd"

def write_summary_xlsx(df: pd.DataFrame, path: Path):
    """Write the portfolio summary DataFrame to a formatted Excel workbook.

    Finance note: this is the one-look portfolio sheet. It bolds the header,
    adds a filter and table stripes, and applies money / percent / date formats
    so the rolled-up numbers read cleanly.
    """
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        df.to_excel(xl, index=False, sheet_name="Portfolio")
        ws = xl.sheets["Portfolio"]

        # bold header + autofilter + widths
        for cell in ws[1]:
            # Phase 6 / S6: openpyxl 3.x deprecated Font.copy(); build a new bold
            # Font instead. Header cells start from the default font, so a plain
            # bold Font reproduces the previous styling exactly and clears the
            # DeprecationWarning. Values and the golden master are unaffected.
            cell.font = Font(bold=True)
        ws.auto_filter.ref = ws.dimensions
        for col in range(1, ws.max_column + 1):
            ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = 24

        # Table stripes if available
        try:
            from openpyxl.worksheet.table import Table, TableStyleInfo
            ref = f"A1:{ws.cell(row=1, column=ws.max_column).column_letter}{ws.max_row}"
            tbl = Table(displayName="TblPortfolio", ref=ref)
            tbl.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
            ws.add_table(tbl)
        except Exception:
            pass

        # Basic number formats
        money_cols = [
            "total_interest", "total_principal", "total_paid_all",
            "next_payment_amount", "property_value_asof", "principal_excl_unposted",
            # Phase 6 / S5: horizon value for a valuation-only property.
            "valuation_horizon_value",
        ]
        pct_cols = ["ltv_asof", "current_annual_rate"]
        date_cols = [
            "as_of_date", "next_payment_date", "payoff_date",
            # Phase 6 / S5: horizon date for a valuation-only property.
            "valuation_horizon_date",
        ]

        for c in money_cols: fmt_money(ws, c)
        for c in pct_cols: fmt_pct(ws, c)
        for c in date_cols: fmt_date(ws, c)

# ---- Summary-row helpers -----------------------------------------------------

def _is_valuation_only(p: Dict) -> bool:
    """Decide whether a portfolio entry runs the no-mortgage valuation-only path.

    Finance note: an owned-outright property has no bank loan, so it declares no
    ``actuals`` file and the engine only tracks its value. A missing ``actuals``
    line is the primary signal (it is what makes the engine omit the loan path);
    an explicit owned-outright kind is also accepted for clarity.
    """
    if not p.get("actuals"):
        return True
    return str(p.get("property_kind", "")).strip().lower() in _VALUATION_ONLY_KINDS

def _valuation_summary_row(out_dir: Path, name: str, kind: str, tax_enabled: bool, slug: str) -> Dict:
    """Build one portfolio-summary row for a valuation-only property.

    Finance note: an owned-outright property has no loan KPIs (no payoff date,
    no interest, no LTV). Its one meaningful summary is value over time, so this
    row carries the value at the base date and the value at the modelling
    horizon, read from valuation_schedule.csv. The loan-only columns are absent
    for this row and show blank in the combined portfolio summary.
    """
    val_csv = out_dir / "valuation_schedule.csv"
    if not val_csv.exists():
        raise FileNotFoundError(f"Expected valuation CSV missing: {val_csv}")
    sched = pd.read_csv(val_csv, parse_dates=["month_start"])
    first = sched.iloc[0]
    last = sched.iloc[-1]
    return {
        "property_name": name,
        "property_kind": kind,
        "tax_enabled": tax_enabled,
        # Base-date value reuses the shared 'as-of' / 'property value' columns so
        # it lines up with the mortgage rows in the same sheet.
        "as_of_date": first["month_start"],
        "property_value_asof": float(first["property_value"]),
        # Horizon value is the end of the modelled value series.
        "valuation_horizon_date": last["month_start"],
        "valuation_horizon_value": float(last["property_value"]),
        "out_dir": slug,
    }

# ---- Main --------------------------------------------------------------------

def main():
    """Run every enabled property and write the rolled-up portfolio summary.

    Finance note: reads portfolio.yaml, runs each switched-on property through
    the engine (a mortgage property with its bank actuals, an owned-outright
    property through the valuation-only path), and gathers one headline row per
    property into a CSV and a formatted Excel workbook.
    """
    ap = argparse.ArgumentParser(description="Portfolio runner (delegates to engine CLI per property)")
    ap.add_argument("--portfolio", type=Path, required=True, help="Path to data/portfolio.yaml")
    # --out is optional now.  When omitted, the output root is resolved through
    # the config layer (CLI > MORTGAGE_OUT_DIR > paths.local.yaml > <repo>/out).
    ap.add_argument("--out", type=Path, default=None, help="Root output folder (overrides config)")
    ap.add_argument("--only", type=str, default=None, help="Run only this property name (exact match)")
    args = ap.parse_args()

    port = load_portfolio(args.portfolio)
    props = port["properties"]
    if args.only:
        props = [p for p in props if str(p.get("name", "")) == args.only]

    # Resolve the output root through the config layer.  Passing the raw CLI value
    # (or None) keeps an explicit --out as the highest-priority source.
    out_root = resolve_out_dir(str(args.out) if args.out is not None else None)
    out_root.mkdir(parents=True, exist_ok=True)

    rows: List[Dict] = []
    for p in props:
        if not p.get("enabled", False):
            continue

        name = str(p["name"])
        kind = str(p.get("property_kind", ""))
        tax_enabled = bool(p.get("tax_enabled", False))
        # Resolve per-property paths relative to the portfolio.yaml location so
        # relative entries do not depend on the current working directory.
        # resolve_relative leaves absolute paths untouched.
        inputs_path = resolve_relative(args.portfolio, p["inputs"])
        slug = p.get("out_dir") or slugify(name)
        out_dir = out_root / slug

        # Phase 6 / S5: a no-mortgage property runs the valuation-only path. It
        # has no bank actuals and emits valuation_schedule.csv rather than the
        # loan schedule, so it gets its own run + summary branch.
        if _is_valuation_only(p):
            # No --actuals: the engine skips schedule/reconcile/tax and writes
            # the value-over-time outputs.
            run_engine_cli(inputs_path, None, out_dir)
            rows.append(_valuation_summary_row(out_dir, name, kind, tax_enabled, slug))
            continue

        # Mortgage property: unchanged behaviour. Pass the bank actuals and read
        # the monthly schedule for KPIs.
        actuals_path = resolve_relative(args.portfolio, p["actuals"])

        # 1) Run engine CLI for FULL outputs (XLSX + CSVs [+ tax if enabled])
        run_engine_cli(inputs_path, actuals_path, out_dir)

        # 2) KPI intake for summary
        #    - Support both metric APIs:
        #      A) compute_baseline_kpis(inputs, monthly, events)
        #      B) compute_baseline_kpis(monthly)
        monthly_csv = out_dir / "schedule_monthly.csv"
        events_csv = out_dir / "events_daily.csv"
        if not monthly_csv.exists():
            raise FileNotFoundError(f"Expected monthly CSV missing: {monthly_csv}")

        monthly = pd.read_csv(
            monthly_csv,
            parse_dates=["month_start", "payment_date", "posting_date"],
        )

        # Build kpis with best available signature
        try:
            inputs = load_inputs(inputs_path)
            events = pd.read_csv(events_csv, parse_dates=["date"]) if events_csv.exists() else pd.DataFrame()
            kpis = compute_baseline_kpis(inputs, monthly, events)  # newer signature
        except TypeError:
            kpis = compute_baseline_kpis(monthly)  # legacy one-arg signature

        # 3) Append one row for portfolio view
        rows.append({
            **kpis,
            "property_name": name,
            "property_kind": kind,
            "tax_enabled": tax_enabled,
            # Record the relative slug, not the absolute path, so the portfolio
            # summary is machine-independent and can be locked as a fixture.
            "out_dir": slug,
        })

    # 4) Write portfolio summary (CSV + nicely formatted XLSX)
    if rows:
        df = pd.DataFrame(rows)

        # Preferred readable order (only if present)
        prefer = [
            "property_name", "property_kind", "tax_enabled",
            "as_of_date", "payoff_date", "months_to_clear", "years_to_clear",
            "current_annual_rate", "next_payment_date", "next_payment_amount",
            "total_interest", "total_principal", "total_paid_all",
            "principal_excl_unposted", "property_value_asof", "ltv_asof",
            # Phase 6 / S5: valuation-only horizon columns sit beside the value.
            "valuation_horizon_date", "valuation_horizon_value",
            "out_dir",
        ]
        cols = [c for c in prefer if c in df.columns] + [c for c in df.columns if c not in prefer]
        df = df[cols]

        df.to_csv(out_root / "portfolio_summary.csv", index=False)
        write_summary_xlsx(df, out_root / "portfolio_summary.xlsx")

    print(f"Wrote portfolio outputs under: {out_root.resolve()}")

if __name__ == "__main__":
    main()