# tools/portfolio.py
"""Portfolio runner: run the engine once per property and roll up a summary.

Finance-readable summary
------------------------
This is the one button that runs every property in the portfolio and collects a
single side-by-side summary. It reads portfolio.yaml (the list of properties and
their on/off switches), runs the same python -m src.engine that a person would
run by hand per property, and gathers one headline row per property into a CSV
and a formatted Excel workbook. Every property is discovered from portfolio.yaml
alone; adding or removing a property is a config change, never a code change.

History
-------
Phase 6 / S5 added the valuation-only branch for a no-mortgage property. Phase 8
rebuilt the rollup (S2 moved slugify into the engine, S3 moved every CSV under a
csv/ sub-folder, S4 locked the column set and sourced every column explicitly,
S5 surfaced as_of_date as the first column). Phase 11 / S2 added an interim
currency guard: Property C reports in PKR, and the rollup's property_value
column is euro, so a non-euro value was left blank there rather than risk a
mixed-currency sum.

Phase 11 / S3 note: the interim guard is replaced with a permanent design. Two
columns are added: currency (the property's reporting currency) and
native_value (the property's value in that currency, always populated).
property_value stays euro-only, blank for a non-euro property, so it can always
be summed safely on its own. The only currency-safe total the runner produces
is grouped by currency (see build_currency_totals), written to
portfolio_totals_by_currency.csv and a second workbook sheet: the EUR row
aggregates Property A and B; the PKR row is Property C alone. Engine maths is
still untouched; this remains a read-and-aggregate layer only.

Phase 12 / S2 note: the rollup surfaces the live-position overpayment-cap state
for each mortgage property. Three columns are read straight off the current
monthly snapshot row (the same row the other live figures use):
overpayment_cap_allowance and overpayment_cap_headroom (both euro, taken from
the monthly overpayment_cap_allowance_eur / overpayment_cap_headroom_eur
columns) and overpayment_cap_flag (the ok / approaching / breached label the
engine already computed, so the rollup never re-derives the threshold). They sit
immediately after current_overpayment, moving the locked column set from 18 to
21. A valuation-only property has no loan and so leaves all three blank (the
reindex fills them). Engine maths is untouched; this stays a read-and-aggregate
layer.
"""
from __future__ import annotations
import argparse, subprocess, sys
import datetime as _dt
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
import yaml
from openpyxl.styles import Font

from src.engine import load_inputs
from src.metrics import compute_baseline_kpis
# One canonical slugify lives in the engine (Phase 8 / S2), so the workbook
# slug and this output-folder slug are produced by the same function.
from src.engine.helpers import slugify
# The canonical "no mortgage" kind set lives in the schema, so the engine, the
# tools and the tests cannot drift apart on what a valuation-only property is.
from src.engine.schema import VALUATION_ONLY_KINDS
# Output root and per-property paths come from the config layer (Phase 2)
# instead of being assumed relative to the current working directory.
from src.paths import resolve_out_dir, resolve_relative

# Kinds that carry no mortgage and therefore run the valuation-only path.
_VALUATION_ONLY_KINDS = VALUATION_ONLY_KINDS

# Default CSV sub-folder for the top-level portfolio rollup.
DEFAULT_CSV_SUBDIR = "csv"

# Locked final column order for the rollup (Phase 8 / S4, extended by S5's
# as_of_date and Phase 11 / S3's currency + native_value). Adding a column
# here is a deliberate, tested change; every row is reindexed onto this exact
# list, so a row that omits a column (a valuation-only property has no loan
# columns) is padded with a blank rather than silently shifting the others.
# Phase 12 / S2: the three overpayment-cap columns are surfaced right after the
# current overpayment, moving the lock from 18 to 21 columns.
LOCKED_SUMMARY_COLUMNS = [
    "as_of_date",
    "property_name", "property_kind", "tax_enabled", "currency",
    "current_balance", "property_value", "native_value", "ltv", "current_annual_rate",
    "contractual_payment", "current_overpayment",
    "overpayment_cap_allowance", "overpayment_cap_headroom", "overpayment_cap_flag",
    "total_overpaid_to_date",
    "total_difference", "overpayment_mismatch_months",
    "payoff_date", "current_year_interest", "tax_deductible_interest",
]

# Phase 11 / S3: column order for the per-currency totals file. One row per
# currency present among the enabled properties.
CURRENCY_TOTALS_COLUMNS = [
    "currency", "property_count", "total_native_value", "total_current_balance",
    "total_overpaid_to_date", "total_current_year_interest", "total_tax_deductible_interest",
]


def load_portfolio(p: Path) -> Dict:
    """Read portfolio.yaml into a dict and check it carries a properties list.

    A missing 'properties' list is a hard error: without it there would be
    nothing to run. This raises ValueError rather than using an assert, because
    assert statements are stripped under ``python -O`` and the check would then
    silently disappear.
    """
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("properties"), list):
        raise ValueError(
            f"portfolio.yaml at {p} is missing a 'properties' list; "
            "add a top-level 'properties:' list of property entries"
        )
    return raw


def run_engine_cli(inputs_path: Path, actuals_path: Optional[Path], out_dir: Path) -> None:
    """Run python -m src.engine once for a single property.

    Shells out to exactly the command a person would type by hand, so the
    portfolio runner and a manual run produce identical per-property files. A
    valuation-only property has no bank loan to reconcile, so actuals_path is
    None and --actuals is left off; the engine then takes its no-mortgage
    valuation-only path.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "src.engine", "--inputs", str(inputs_path)]
    if actuals_path is not None:
        cmd += ["--actuals", str(actuals_path)]
    cmd += ["--out", str(out_dir)]
    subprocess.run(cmd, check=True)


# ---- Shared coercion helpers -------------------------------------------------

def _to_date(value) -> Optional[_dt.date]:
    """Coerce a date-like value (date, Timestamp, or ISO string) to a date.

    Returns None for anything unreadable as a date, so every caller can treat a
    missing or malformed date as 'unknown' rather than crashing.
    """
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def _count_true(series: pd.Series) -> int:
    """Count truthy flags in a column that may be bool, numeric, or text.

    A CSV round-trip can surface 'True'/'False' strings instead of real bools,
    so this coerces both shapes to one integer count.
    """
    filled = series.fillna(False)
    if filled.dtype == bool:
        return int(filled.sum())
    text = filled.astype(str).str.strip().str.lower()
    return int(text.isin(["true", "1", "yes"]).sum())


def _is_eur_currency(currency) -> bool:
    """Return True when a property reports in euro, the rollup's base currency.

    A missing or blank currency is treated as euro, matching the engine's own
    default, so an existing euro property behaves exactly as before this
    function existed.
    """
    return str(currency or "EUR").strip().upper() == "EUR"


def _derive_as_of(csv_dir: Path, inputs_path: Path) -> Optional[_dt.date]:
    """Return the deterministic 'as-of' date the current snapshot is taken at.

    Mirrors the engine CLI: start from the newest reconciled bank actual, then
    prefer a newer portal snapshot date from reconcile.snapshots when one
    exists. Returns None when neither source is available, and the caller
    falls back to the final monthly row.
    """
    as_of: Optional[_dt.date] = None
    reconcile_csv = csv_dir / "reconcile.csv"
    if reconcile_csv.exists():
        rec = pd.read_csv(reconcile_csv, parse_dates=["bank_date"])
        if "model_balance" in rec.columns:
            rec = rec.dropna(subset=["model_balance"])
        if not rec.empty and "bank_date" in rec.columns:
            as_of = _to_date(rec["bank_date"].max())
    try:
        raw = yaml.safe_load(Path(inputs_path).read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    snaps = ((raw or {}).get("reconcile") or {}).get("snapshots") or []
    snap_dates = [d for d in (_to_date(s.get("date")) for s in snaps) if d is not None]
    if snap_dates:
        latest_snap = max(snap_dates)
        if as_of is None or latest_snap > as_of:
            as_of = latest_snap
    return as_of


def _current_row(monthly: pd.DataFrame, as_of: Optional[_dt.date]) -> pd.Series:
    """Return the last monthly row on or before the as-of date (the live position).

    The schedule projects all the way to payoff, so its final row is the
    payoff month, not 'now'. Falls back to the final row when as_of is
    unknown.
    """
    if as_of is not None and "month_start" in monthly.columns:
        month_starts = monthly["month_start"].apply(_to_date)
        mask = month_starts.apply(lambda d: d is not None and d <= as_of)
        if mask.any():
            return monthly.loc[mask].iloc[-1]
    return monthly.iloc[-1]


def _tax_deductible_for_year(csv_dir: Path, year: Optional[int]) -> Optional[float]:
    """Return the Section 97 allowable interest for a year from tax_year.csv.

    A missing file, missing column, or absent year returns None so the column
    blanks gracefully rather than guessing.
    """
    if year is None:
        return None
    tax_csv = csv_dir / "tax_year.csv"
    if not tax_csv.exists():
        return None
    tax = pd.read_csv(tax_csv)
    if "year" not in tax.columns or "allowable_interest_s97" not in tax.columns:
        return None
    hit = tax.loc[tax["year"] == year]
    if hit.empty:
        return None
    value = hit.iloc[0]["allowable_interest_s97"]
    return float(value) if pd.notna(value) else None


# ---- XLSX formatting helpers (lightweight, values-only) ----------------------

def _header_map(ws):
    """Map each column header text to its 1-based column index."""
    return {ws.cell(row=1, column=c).value: c for c in range(1, ws.max_column + 1)}


def fmt_money(ws, col_name):
    """Apply a euro money format to a named column, if it is present."""
    col = _header_map(ws).get(col_name)
    if not col:
        return
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=col).number_format = "\u20ac#,##0.00"


def fmt_pct(ws, col_name):
    """Apply a percent format to a named column, if it is present."""
    col = _header_map(ws).get(col_name)
    if not col:
        return
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=col).number_format = "0.00%"


def fmt_date(ws, col_name):
    """Apply an ISO date format to a named column, if it is present."""
    col = _header_map(ws).get(col_name)
    if not col:
        return
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=col).number_format = "yyyy-mm-dd"


def fmt_number(ws, col_name):
    """Apply a plain thousands-separated number format, with no currency symbol.

    Used for a column that can hold more than one currency across rows
    (native_value, and every column on the per-currency totals sheet), where a
    single money symbol would misstate the unit. The adjacent currency column
    carries the unit instead.
    """
    col = _header_map(ws).get(col_name)
    if not col:
        return
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=col).number_format = "#,##0.00"


def write_summary_xlsx(df: pd.DataFrame, path: Path, totals: Optional[pd.DataFrame] = None):
    """Write the portfolio summary, and an optional per-currency totals sheet, to Excel.

    This is the one-look portfolio sheet: bold header, autofilter, table
    stripes, and money / percent / date / number formats so the rolled-up
    numbers read cleanly. Phase 11 / S3: when totals is given, a second
    "Totals by currency" sheet is added, so the EUR aggregate (Property A and
    B) and the PKR aggregate (Property C) are visible side by side without
    ever being added into one mixed-currency figure.
    """
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        df.to_excel(xl, index=False, sheet_name="Portfolio")
        ws = xl.sheets["Portfolio"]

        for cell in ws[1]:
            cell.font = Font(bold=True)
        ws.auto_filter.ref = ws.dimensions
        for col in range(1, ws.max_column + 1):
            ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = 24

        try:
            from openpyxl.worksheet.table import Table, TableStyleInfo
            ref = f"A1:{ws.cell(row=1, column=ws.max_column).column_letter}{ws.max_row}"
            tbl = Table(displayName="TblPortfolio", ref=ref)
            tbl.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
            ws.add_table(tbl)
        except Exception:
            pass

        # Phase 12 / S2: the two euro overpayment-cap columns join the money
        # set; overpayment_cap_flag is text and needs no number format.
        money_cols = [
            "current_balance", "property_value", "contractual_payment",
            "current_overpayment", "overpayment_cap_allowance", "overpayment_cap_headroom",
            "total_overpaid_to_date", "total_difference",
            "current_year_interest", "tax_deductible_interest",
        ]
        pct_cols = ["ltv", "current_annual_rate"]
        date_cols = ["as_of_date", "payoff_date"]
        # native_value can hold more than one currency across rows, so it gets
        # a plain number, not a fixed money symbol.
        number_cols = ["native_value"]

        for c in money_cols:
            fmt_money(ws, c)
        for c in pct_cols:
            fmt_pct(ws, c)
        for c in date_cols:
            fmt_date(ws, c)
        for c in number_cols:
            fmt_number(ws, c)

        if totals is not None and not totals.empty:
            totals.to_excel(xl, index=False, sheet_name="Totals by currency")
            ws_t = xl.sheets["Totals by currency"]
            for cell in ws_t[1]:
                cell.font = Font(bold=True)
            ws_t.auto_filter.ref = ws_t.dimensions
            for col in range(1, ws_t.max_column + 1):
                ws_t.column_dimensions[ws_t.cell(row=1, column=col).column_letter].width = 26
            for c in [
                "total_native_value", "total_current_balance",
                "total_overpaid_to_date", "total_current_year_interest",
                "total_tax_deductible_interest",
            ]:
                fmt_number(ws_t, c)


# ---- Summary-row helpers -----------------------------------------------------

def _is_valuation_only(p: Dict) -> bool:
    """Decide whether a portfolio entry runs the no-mortgage valuation-only path.

    A missing actuals line is the primary signal (it is what makes the engine
    omit the loan path); an explicit owned-outright kind is also accepted.
    """
    if not p.get("actuals"):
        return True
    return str(p.get("property_kind", "")).strip().lower() in _VALUATION_ONLY_KINDS


def _finalize_currency_fields(row: Dict, currency) -> Dict:
    """Tag a rollup row with its reporting currency and a currency-pure native value.

    property_value is a euro column; summing it must never mix currencies, so
    it is filled only for a euro property. native_value carries the same
    figure in the property's own reporting currency for every property, euro
    or not, so a non-euro property's real value is still visible on its own
    row without ever risking a cross-currency sum. Grouping by currency and
    summing native_value within each group (build_currency_totals) is the
    only currency-safe way to total this figure across more than one
    property.
    """
    native_value = row.get("property_value")
    row["currency"] = str(currency or "EUR").strip().upper()
    row["native_value"] = native_value
    if not _is_eur_currency(currency):
        row["property_value"] = None
    return row


def build_currency_totals(df: pd.DataFrame) -> pd.DataFrame:
    """Return one aggregate row per currency, so a total never mixes currencies.

    This is the only place the rollup produces a summed total. Grouping by
    currency before summing is what keeps a PKR property's value out of the
    euro aggregate: the EUR row totals every euro property's native_value; the
    PKR row totals every PKR property's native_value, separately.
    """
    if df.empty:
        return pd.DataFrame(columns=CURRENCY_TOTALS_COLUMNS)
    groups = []
    for currency, group in df.groupby("currency", dropna=False):
        groups.append({
            "currency": currency,
            "property_count": int(len(group)),
            "total_native_value": float(group["native_value"].fillna(0.0).sum()),
            "total_current_balance": float(group["current_balance"].fillna(0.0).sum()),
            "total_overpaid_to_date": float(group["total_overpaid_to_date"].fillna(0.0).sum()),
            "total_current_year_interest": float(group["current_year_interest"].fillna(0.0).sum()),
            "total_tax_deductible_interest": float(group["tax_deductible_interest"].fillna(0.0).sum()),
        })
    return pd.DataFrame(groups).reindex(columns=CURRENCY_TOTALS_COLUMNS)


def _mortgage_summary_row(
    monthly: pd.DataFrame,
    events: pd.DataFrame,
    prop_inputs,
    csv_dir: Path,
    inputs_path: Path,
    name: str,
    kind: str,
    tax_enabled: bool,
    currency: str,
) -> Dict:
    """Build one locked portfolio-summary row for a mortgage-bearing property.

    Phase 11 / S3: currency and native_value are added by
    _finalize_currency_fields at the end, so a mortgage property is tagged the
    same way a valuation-only property is, rather than assuming euro silently.

    Phase 12 / S2: the live-position overpayment-cap state is read straight off
    the current monthly snapshot row: overpayment_cap_allowance and
    overpayment_cap_headroom from the monthly euro columns, and
    overpayment_cap_flag as the label the engine already computed (the rollup
    never re-applies the threshold).
    """
    as_of = _derive_as_of(csv_dir, inputs_path)
    current = _current_row(monthly, as_of)

    current_month = _to_date(current.get("month_start"))
    current_year = as_of.year if as_of is not None else (current_month.year if current_month else None)

    try:
        kpis = compute_baseline_kpis(prop_inputs, monthly, events)
    except TypeError:
        kpis = compute_baseline_kpis(monthly)
    payoff_date = kpis.get("payoff_date")

    if as_of is not None and "month_start" in monthly.columns:
        month_starts = monthly["month_start"].apply(_to_date)
        to_date_mask = month_starts.apply(lambda d: d is not None and d <= as_of)
        total_overpaid_to_date = float(monthly.loc[to_date_mask, "overpayment"].fillna(0.0).sum())
    elif "overpayment" in monthly.columns:
        total_overpaid_to_date = float(monthly["overpayment"].fillna(0.0).sum())
    else:
        total_overpaid_to_date = None

    current_year_interest = None
    if current_year is not None and "posting_year" in monthly.columns and "interest_used" in monthly.columns:
        year_mask = monthly["posting_year"] == current_year
        current_year_interest = float(monthly.loc[year_mask, "interest_used"].fillna(0.0).sum())

    total_difference = float(monthly["difference"].fillna(0.0).sum()) if "difference" in monthly.columns else None
    mismatch_months = _count_true(monthly["overpayment_mismatch"]) if "overpayment_mismatch" in monthly.columns else None

    tax_deductible_interest = _tax_deductible_for_year(csv_dir, current_year) if tax_enabled else None

    def _cell(col: str) -> Optional[float]:
        """Read a numeric cell from the current snapshot row as a float or None."""
        if col not in current.index:
            return None
        value = current[col]
        return float(value) if pd.notna(value) else None

    def _flag(col: str) -> Optional[str]:
        """Read a text flag from the current snapshot row as a str or None.

        The overpayment-cap flag is text (ok / approaching / breached) and is a
        pandas null in a month with no resolvable allowance, so a NaN reads
        back as None rather than the string 'nan'.
        """
        if col not in current.index:
            return None
        value = current[col]
        if value is None:
            return None
        if not isinstance(value, str) and pd.isna(value):
            return None
        return str(value)

    row = {
        "as_of_date": as_of,
        "property_name": name,
        "property_kind": kind,
        "tax_enabled": tax_enabled,
        "current_balance": _cell("model_eom_balance"),
        "property_value": _cell("property_value"),
        "ltv": _cell("ltv_model_eom"),
        "current_annual_rate": _cell("annual_rate"),
        "contractual_payment": _cell("contractual"),
        "current_overpayment": _cell("overpayment"),
        # Phase 12 / S2: the live-position overpayment-cap state, read straight
        # off the current monthly snapshot row (the flag is computed once in the
        # engine, so the rollup only surfaces it).
        "overpayment_cap_allowance": _cell("overpayment_cap_allowance_eur"),
        "overpayment_cap_headroom": _cell("overpayment_cap_headroom_eur"),
        "overpayment_cap_flag": _flag("overpayment_cap_flag"),
        "total_overpaid_to_date": total_overpaid_to_date,
        "total_difference": total_difference,
        "overpayment_mismatch_months": mismatch_months,
        "payoff_date": _to_date(payoff_date),
        "current_year_interest": current_year_interest,
        "tax_deductible_interest": tax_deductible_interest,
    }
    return _finalize_currency_fields(row, currency)


def _derive_valuation_as_of(inputs_path: Path) -> Optional[_dt.date]:
    """Return the deterministic as-of date for a valuation-only property.

    A valuation-only property has no bank feed, so there is no observed
    "latest actual" to anchor the snapshot the way ``_derive_as_of`` does for a
    mortgage property. The date therefore comes from the property's own config,
    in this order:

    1. ``valuation.as_of_date`` when set (explicit and deterministic).
    2. ``modelling.end_date``, the projection horizon (deterministic fallback).

    Returns None only when neither is available, in which case the caller falls
    back to the final schedule row and its own month.

    This replaces an earlier ``date.today()`` call. That call made the rollup,
    and therefore the golden master, change every day: the locked
    ``portfolio_summary.csv`` fixture drifted as soon as the wall clock moved
    past the date it was captured on. Deriving the date from config keeps the
    output reproducible on any machine on any day.
    """
    try:
        raw = yaml.safe_load(Path(inputs_path).read_text(encoding="utf-8"))
    except Exception:
        # A missing or malformed inputs file is not fatal here: the caller
        # falls back to the final schedule row.
        raw = {}
    raw = raw or {}
    # An explicit valuation.as_of_date wins; otherwise use the modelling horizon.
    as_of = _to_date((raw.get("valuation") or {}).get("as_of_date"))
    if as_of is not None:
        return as_of
    return _to_date((raw.get("modelling") or {}).get("end_date"))


def _valuation_summary_row(
    csv_dir: Path,
    name: str,
    kind: str,
    tax_enabled: bool,
    currency: str,
    as_of: Optional[_dt.date] = None,
) -> Dict:
    """Build one locked portfolio-summary row for a valuation-only property.

    Phase 11 / S3: property_value is always set to the native figure here; the
    S2 interim guard now lives entirely in _finalize_currency_fields, which
    every row (mortgage or valuation-only) passes through the same way.

    Phase 12 / S2: a valuation-only property has no loan, so the three
    overpayment-cap columns are simply omitted here and the reindex fills them
    blank, exactly like every other loan-only column.

    Determinism (BACKLOG-001): ``as_of`` is supplied by the caller from
    ``_derive_valuation_as_of`` (config-driven), never from the wall clock. The
    snapshot is the last schedule month on or before ``as_of``. When ``as_of``
    is None the final schedule row is used and its own month becomes the
    reported date, so the row is still fully deterministic.
    """
    val_csv = csv_dir / "valuation_schedule.csv"
    if not val_csv.exists():
        raise FileNotFoundError(f"Expected valuation CSV missing: {val_csv}")
    sched = pd.read_csv(val_csv, parse_dates=["month_start"])
    month_starts = sched["month_start"].apply(_to_date)
    if as_of is not None:
        # Snapshot at the last month on or before the configured as-of date.
        mask = month_starts.apply(lambda d: d is not None and d <= as_of)
        current = sched.loc[mask].iloc[-1] if mask.any() else sched.iloc[-1]
        snapshot_date = as_of
    else:
        # No configured date: use the final schedule row and its own month.
        current = sched.iloc[-1]
        snapshot_date = _to_date(current["month_start"])
    native_value = float(current["property_value"])

    row: Dict = {
        "as_of_date": snapshot_date,
        "property_name": name,
        "property_kind": kind,
        "tax_enabled": tax_enabled,
        "property_value": native_value,
    }
    return _finalize_currency_fields(row, currency)


# ---- Main --------------------------------------------------------------------

def main():
    """Run every enabled property and write the rolled-up portfolio summary.

    Reads portfolio.yaml, runs each switched-on property through the engine,
    and gathers one headline row per property. Every property in the run is
    discovered from portfolio.yaml; nothing here names a specific property.
    """
    ap = argparse.ArgumentParser(description="Portfolio runner (delegates to engine CLI per property)")
    ap.add_argument("--portfolio", type=Path, required=True, help="Path to data/portfolio.yaml")
    ap.add_argument("--out", type=Path, default=None, help="Root output folder (overrides config)")
    ap.add_argument("--only", type=str, default=None, help="Run only this property name (exact match)")
    args = ap.parse_args()

    port = load_portfolio(args.portfolio)
    props = port["properties"]
    if args.only:
        props = [p for p in props if str(p.get("name", "")) == args.only]

    out_root = resolve_out_dir(str(args.out) if args.out is not None else None)
    out_root.mkdir(parents=True, exist_ok=True)

    rows: List[Dict] = []
    for p in props:
        if not p.get("enabled", False):
            continue

        name = str(p["name"])
        kind = str(p.get("property_kind", ""))
        tax_enabled = bool(p.get("tax_enabled", False))
        inputs_path = resolve_relative(args.portfolio, p["inputs"])
        slug = p.get("out_dir") or slugify(name)
        out_dir = out_root / slug

        prop_inputs = load_inputs(inputs_path)
        csv_subdir = prop_inputs.output.csv_subdir
        csv_dir = (out_dir / csv_subdir) if csv_subdir else out_dir
        currency = prop_inputs.output.currency

        if _is_valuation_only(p):
            run_engine_cli(inputs_path, None, out_dir)
            # Determinism (BACKLOG-001): the as-of date comes from the property's
            # own config, not the wall clock, so the rollup is reproducible.
            val_as_of = _derive_valuation_as_of(inputs_path)
            rows.append(_valuation_summary_row(csv_dir, name, kind, tax_enabled, currency, val_as_of))
            continue

        actuals_path = resolve_relative(args.portfolio, p["actuals"])

        run_engine_cli(inputs_path, actuals_path, out_dir)

        monthly_csv = csv_dir / "schedule_monthly.csv"
        events_csv = csv_dir / "events_daily.csv"
        if not monthly_csv.exists():
            raise FileNotFoundError(f"Expected monthly CSV missing: {monthly_csv}")
        monthly = pd.read_csv(
            monthly_csv,
            parse_dates=["month_start", "payment_date", "posting_date"],
        )
        events = pd.read_csv(events_csv, parse_dates=["date"]) if events_csv.exists() else pd.DataFrame()

        rows.append(
            _mortgage_summary_row(
                monthly, events, prop_inputs, csv_dir, inputs_path, name, kind, tax_enabled, currency
            )
        )

    if rows:
        df = pd.DataFrame(rows)
        df = df.reindex(columns=LOCKED_SUMMARY_COLUMNS)

        raw_rollup_subdir = (port.get("output") or {}).get("csv_subdir", DEFAULT_CSV_SUBDIR)
        # chr(92) is a backslash; stripping it too (alongside a forward slash)
        # tolerates a Windows-style separator in the configured sub-folder.
        rollup_subdir = ("" if raw_rollup_subdir is None else str(raw_rollup_subdir)).strip().strip("/" + chr(92))
        rollup_csv_dir = (out_root / rollup_subdir) if rollup_subdir else out_root
        rollup_csv_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(rollup_csv_dir / "portfolio_summary.csv", index=False)

        totals = build_currency_totals(df)
        totals.to_csv(rollup_csv_dir / "portfolio_totals_by_currency.csv", index=False)

        write_summary_xlsx(df, out_root / "portfolio_summary.xlsx", totals=totals)

        summary_line = ", ".join(f"{r.currency} ({r.property_count})" for r in totals.itertuples())
        print(f"[tools.portfolio] currency totals: {summary_line}")

    print(f"Wrote portfolio outputs under: {out_root.resolve()}")


if __name__ == "__main__":
    main()