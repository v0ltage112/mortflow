# tools/portfolio.py
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path
from typing import Dict, List
import pandas as pd
import yaml

from src.engine import load_inputs  # to pass real inputs to KPIs if supported
from src.metrics import compute_baseline_kpis
# Phase 2 path resolver: output root and per-property paths come from the config
# layer instead of being assumed relative to the current working directory.
from src.paths import resolve_out_dir, resolve_relative

def slugify(name: str) -> str:
    s = name.strip().lower()
    for ch in [' ', '/', '\\', ',', '.', "'", '"', '&', '(', ')', '[', ']', ':', ';', '|', '?', '!']:
        s = s.replace(ch, '-')
    while '--' in s:
        s = s.replace('--', '-')
    return s.strip('-')

def load_portfolio(p: Path) -> Dict:
    raw = yaml.safe_load(p.read_text())
    assert "properties" in raw and isinstance(raw["properties"], list), "portfolio.yaml missing 'properties' list"
    return raw

def run_engine_cli(inputs_path: Path, actuals_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "src.engine",
        "--inputs", str(inputs_path),
        "--actuals", str(actuals_path),
        "--out", str(out_dir),
    ]
    subprocess.run(cmd, check=True)

# ---- XLSX formatting helpers (lightweight, values-only) ----------------------

def _header_map(ws):
    return {ws.cell(row=1, column=c).value: c for c in range(1, ws.max_column + 1)}

def fmt_money(ws, col_name):
    col = _header_map(ws).get(col_name)
    if not col: return
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=col).number_format = "€#,##0.00"

def fmt_pct(ws, col_name):
    col = _header_map(ws).get(col_name)
    if not col: return
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=col).number_format = "0.00%"

def fmt_date(ws, col_name):
    col = _header_map(ws).get(col_name)
    if not col: return
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=col).number_format = "yyyy-mm-dd"

def write_summary_xlsx(df: pd.DataFrame, path: Path):
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        df.to_excel(xl, index=False, sheet_name="Portfolio")
        ws = xl.sheets["Portfolio"]

        # bold header + autofilter + widths
        for cell in ws[1]:
            cell.font = cell.font.copy(bold=True)  # type: ignore[attr-defined]
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
        ]
        pct_cols = ["ltv_asof", "current_annual_rate"]
        date_cols = ["as_of_date", "next_payment_date", "payoff_date"]

        for c in money_cols: fmt_money(ws, c)
        for c in pct_cols: fmt_pct(ws, c)
        for c in date_cols: fmt_date(ws, c)

# ---- Main --------------------------------------------------------------------

def main():
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
        # Resolve per-property paths relative to the portfolio.yaml location so
        # relative entries do not depend on the current working directory.
        # resolve_relative leaves absolute paths untouched.
        inputs_path = resolve_relative(args.portfolio, p["inputs"])
        actuals_path = resolve_relative(args.portfolio, p["actuals"])
        slug = p.get("out_dir") or slugify(name)
        out_dir = out_root / slug

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
            "property_kind": str(p.get("property_kind", "")),
            "tax_enabled": bool(p.get("tax_enabled", False)),
            "out_dir": str(out_dir),
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
            "out_dir",
        ]
        cols = [c for c in prefer if c in df.columns] + [c for c in df.columns if c not in prefer]
        df = df[cols]

        df.to_csv(out_root / "portfolio_summary.csv", index=False)
        write_summary_xlsx(df, out_root / "portfolio_summary.xlsx")

    print(f"Wrote portfolio outputs under: {out_root.resolve()}")

if __name__ == "__main__":
    main()