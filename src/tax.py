# src/tax.py
"""
Tax reporting layer for Irish Form 11 (investment property):
- Computes allowable mortgage interest under s97(2J) by tax year.
- Uses engine's Monthly sheet (posted interest, posting_date).
- Tenancy intake is kept separate for privacy and future rent/RPZ work.
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yaml


# -------------------------- helpers --------------------------

def _ensure_date(x) -> date:
    if isinstance(x, date):
        return x
    return pd.to_datetime(str(x)).date()


def _eom(d: date) -> date:
    first_next = (d.replace(day=1) + pd.offsets.MonthBegin(1)).date()
    return (first_next - timedelta(days=1))


def _days_in_month(d: date) -> int:
    return (_eom(d) - d.replace(day=1)).days + 1


@dataclass
class Tenancy:
    id: str
    start: date
    end: Optional[date]  # None = ongoing
    rent_amount: float
    rent_frequency: str
    pay_in_advance: bool
    rent_due_day: Optional[int]
    security_deposit: Optional[float]
    rtb_registered: Optional[bool]
    rtb_registration_number: Optional[str]
    rtb_registration_date: Optional[date]
    rpz: Optional[dict]
    admin_charges: Optional[dict]


@dataclass
class TenancyPolicy:
    gaps_count_as_available: bool = True


def load_tenancies(preferred_path: Path, fallback_path: Path) -> Tuple[List[Tenancy], TenancyPolicy, Dict]:
    """
    Load tenancy set from YAML; prefer local (private), else sample.
    Returns (tenancies, policy, raw_dict_for_audit).
    """
    path = preferred_path if preferred_path.exists() else fallback_path
    raw = yaml.safe_load(Path(path).read_text())

    tenancies: List[Tenancy] = []
    for t in (raw.get("tenancies") or []):
        rtb = t.get("rtb") or {}
        tenancies.append(
            Tenancy(
                id=str(t.get("id")),
                start=_ensure_date(t["start"]),
                end=(_ensure_date(t["end"]) if t.get("end") else None),
                rent_amount=float(t.get("rent_amount", 0.0)),
                rent_frequency=str(t.get("rent_frequency", "monthly")),
                pay_in_advance=bool(t.get("pay_in_advance", True)),
                rent_due_day=(int(t["rent_due_day"]) if t.get("rent_due_day") else None),
                security_deposit=(float(t["security_deposit"]) if t.get("security_deposit") else None),
                rtb_registered=bool(rtb.get("registered")) if "registered" in rtb else None,
                rtb_registration_number=rtb.get("registration_number"),
                rtb_registration_date=(_ensure_date(rtb["registration_date"]) if rtb.get("registration_date") else None),
                rpz=t.get("rpz"),
                admin_charges=t.get("admin_charges"),
            )
        )

    pol_raw = (raw.get("policy") or {})
    policy = TenancyPolicy(gaps_count_as_available=bool(pol_raw.get("gaps_count_as_available", True)))
    return tenancies, policy, raw


def _build_availability_calendar(tenancies: List[Tenancy], start: date, end: date,
                                 policy: TenancyPolicy) -> Dict[date, bool]:
    """
    Day-level map: date -> True if 'let OR available for letting' (s97(2J) intent).
    - Days covered by a tenancy are True.
    - Gaps between tenancies are True if policy.gaps_count_as_available is True.
    """
    cal: Dict[date, bool] = {}
    cur = start
    while cur <= end:
        cal[cur] = False
        cur += timedelta(days=1)

    # Mark let days
    for t in tenancies:
        s = max(start, t.start)
        e = min(end, t.end or end)
        cur = s
        while cur <= e:
            cal[cur] = True
            cur += timedelta(days=1)

    # Mark gaps as available if policy allows
    if policy.gaps_count_as_available and tenancies:
        # Sort by start
        ts = sorted(tenancies, key=lambda x: x.start)
        for i in range(len(ts) - 1):
            g_s = ts[i].end or ts[i].start  # if ongoing (None), no gap
            g_e = ts[i + 1].start
            if g_s and g_e:
                cur = g_s + timedelta(days=1)
                while cur < g_e and cur <= end:
                    if cur >= start:
                        cal[cur] = True
                    cur += timedelta(days=1)

    return cal


def _deductible_pct_for_year(mapping: Dict, year: int) -> float:
    if mapping is None:
        return 1.0
    if str(year) in mapping:
        return float(mapping[str(year)])
    return float(mapping.get("default", 1.0))


def compute_tax_year_table(
    monthly: pd.DataFrame,
    inputs_raw: dict,
    tenancies: List[Tenancy],
    policy: TenancyPolicy,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Compute Form 11-focused table:
      Year, Interest Posted, Allowable Interest (s97(2J)), Principal (info), Deductible %, Occupancy ratio.
    Also returns a TenancyLog sheet (audit).
    """
    # Engine guarantees these
    if "posting_date" not in monthly.columns or "interest_used" not in monthly.columns:
        raise ValueError("Monthly table missing 'posting_date' or 'interest_used'.")

    # Figure modelling span & availability calendar
    dd = pd.to_datetime(inputs_raw["loan"]["drawdown_date"]).date()
    end_date = pd.to_datetime(inputs_raw.get("modelling", {}).get("end_date")).date() \
        if inputs_raw.get("modelling", {}).get("end_date") else monthly["posting_date"].max().date()
    avail = _build_availability_calendar(tenancies, dd, end_date, policy)

    # Month-level occupancy ratio
    md = monthly.copy()
    md["posting_date"] = pd.to_datetime(md["posting_date"])
    md["posting_year"] = md["posting_date"].dt.year

    occ_ratios: List[float] = []
    for _, r in md.iterrows():
        mstart = pd.to_datetime(r["month_start"]).date()
        total = _days_in_month(mstart)
        true_days = 0
        cur = mstart
        while cur <= _eom(mstart):
            if avail.get(cur, False):
                true_days += 1
            cur += timedelta(days=1)
        occ_ratios.append(true_days / total if total > 0 else 0.0)
    md["occupancy_ratio"] = occ_ratios

    # Deductible % by year (default 100%)
    tax_cfg = (inputs_raw.get("tax") or {})
    year_pct_map = (tax_cfg.get("deductible_percentage_by_year") or {"default": 1.0})

    # Compute per-month allowable interest
    md["deductible_pct"] = md["posting_year"].astype(int).map(lambda y: _deductible_pct_for_year(year_pct_map, y))
    md["allowable_interest_s97"] = md["interest_used"] * md["occupancy_ratio"] * md["deductible_pct"]

    # Aggregate per year
    agg = (
        md.groupby("posting_year", as_index=False)
          .agg(
              interest_posted=("interest_used", "sum"),
              allowable_interest_s97=("allowable_interest_s97", "sum"),
              principal_paid=("principal_paid", "sum"),
              avg_occupancy_ratio=("occupancy_ratio", "mean"),
              deductible_pct=("deductible_pct", "first")  # normally constant over a year
          )
          .rename(columns={"posting_year": "year"})
          .sort_values("year")
    )

    # TenancyLog (audit)
    ten_log = pd.DataFrame(
        [
            {
                "id": t.id,
                "start": t.start,
                "end": t.end,
                "rent_amount": t.rent_amount,
                "rent_frequency": t.rent_frequency,
                "pay_in_advance": t.pay_in_advance,
                "rent_due_day": t.rent_due_day,
                "security_deposit": t.security_deposit,
                "rtb_registered": t.rtb_registered,
                "rtb_registration_number": t.rtb_registration_number,
                "rtb_registration_date": t.rtb_registration_date,
                "has_rpz_block": bool(t.rpz),
            }
            for t in tenancies
        ]
    )

    # Round for presentation (engine keeps values; this is reporting)
    for c in ("interest_posted", "allowable_interest_s97", "principal_paid"):
        if c in agg.columns:
            agg[c] = agg[c].round(2)
    if "avg_occupancy_ratio" in agg.columns:
        agg["avg_occupancy_ratio"] = agg["avg_occupancy_ratio"].round(6)

    return agg, ten_log
# src/tax.py (append near the bottom)

def compute_tax_monthly_audit(
    monthly: pd.DataFrame,
    inputs_raw: dict,
    tenancies: List[Tenancy],
    policy: TenancyPolicy,
) -> pd.DataFrame:
    """
    Month-level audit used to explain the TaxYear aggregation.
    Columns:
      ym, month_start, posting_date, posting_year,
      interest_used, principal_paid,
      days_let_or_available, days_in_month, occupancy_ratio,
      deductible_pct, allowable_interest_s97
    """
    if "posting_date" not in monthly.columns or "interest_used" not in monthly.columns:
        raise ValueError("Monthly table missing 'posting_date' or 'interest_used'.")

    dd = pd.to_datetime(inputs_raw["loan"]["drawdown_date"]).date()
    end_date = pd.to_datetime(inputs_raw.get("modelling", {}).get("end_date")).date() \
        if inputs_raw.get("modelling", {}).get("end_date") else monthly["posting_date"].max().date()
    avail = _build_availability_calendar(tenancies, dd, end_date, policy)

    md = monthly.copy()
    md["posting_date"] = pd.to_datetime(md["posting_date"])
    md["posting_year"] = md["posting_date"].dt.year

    # month-level occupancy calculation
    days_let = []
    days_total = []
    occ = []
    for _, r in md.iterrows():
        mstart = pd.to_datetime(r["month_start"]).date()
        deom = _eom(mstart)
        total = (deom - mstart).days + 1
        true_days = 0
        cur = mstart
        while cur <= deom:
            if avail.get(cur, False):
                true_days += 1
            cur += timedelta(days=1)
        days_total.append(total)
        days_let.append(true_days)
        occ.append(true_days / total if total else 0.0)

    md["days_let_or_available"] = days_let
    md["days_in_month"] = days_total
    md["occupancy_ratio"] = occ

    tax_cfg = (inputs_raw.get("tax") or {})
    year_pct_map = (tax_cfg.get("deductible_percentage_by_year") or {"default": 1.0})
    md["deductible_pct"] = md["posting_year"].astype(int).map(lambda y: _deductible_pct_for_year(year_pct_map, y))

    md["allowable_interest_s97"] = md["interest_used"] * md["occupancy_ratio"] * md["deductible_pct"]

    cols = [
        "ym", "month_start", "posting_date", "posting_year",
        "interest_used", "principal_paid",
        "days_let_or_available", "days_in_month", "occupancy_ratio",
        "deductible_pct", "allowable_interest_s97"
    ]
    # ensure ym exists (engine usually sets it)
    if "ym" not in md.columns:
        md["ym"] = pd.to_datetime(md["month_start"]).dt.year * 100 + pd.to_datetime(md["month_start"]).dt.month

    out = md[cols].copy()
    # round presentation fields
    out["occupancy_ratio"] = out["occupancy_ratio"].round(6)
    for c in ("interest_used", "principal_paid", "allowable_interest_s97"):
        out[c] = out[c].round(2)
    return out
