# src/engine/monthly.py
"""Monthly scaffolding and the post-loop monthly-schedule assembly.

Finance-readable summary
------------------------
This module builds the calendar backbone of the model and turns the raw
day-by-day simulation results into the monthly schedule the business reads.
It works out which interest rate applies in each month, how far into the
future to project, the list of months to model, and a pre-digested per-month
view of the bank's payment and interest activity. After the daily engine has
walked the loan, this module assembles the final per-month table: the amounts
paid, the interest charged, the principal repaid, the interest posting dates,
and the month-end balances for both the model and the bank. These rows feed
the Monthly schedule sheet and the tax outputs.

Technical summary
-----------------
Holds the monthly scaffolding (``build_rate_lookup``, ``derive_modelling_end``,
``month_span``, ``month_tables``) and ``build_monthly_schedule``, the post-loop
assembly that consumes the daily loop's per-month collector dicts and produces
the ``monthly`` DataFrame (per-month frame, posting date/year, model and bank
end-of-month balances). Depends only on ``helpers`` and ``schema``; it must
never import ``simulate``.

Phase 5 / S3 note: lifted verbatim out of ``simulate.py``. Behaviour is
unchanged; only the module location and imports differ. The golden master
still reads 46 passed, 2 skipped, plus the S1 characterization test.
"""

from __future__ import annotations

import sys
from datetime import date
from typing import Dict, List

import pandas as pd

from .helpers import (
    clamp_day,
    ensure_date,
    eom,
    month_index,
    ym_int,
)
from .schema import Inputs, RateBlock


# =====================================================================
# Monthly scaffolding
# =====================================================================

def build_rate_lookup(blocks: List[RateBlock]):
    """Return a callable mapping model month numbers to annual rates.

    Finance note: the loan's rate changes at refix dates. This turns the list of
    rate blocks into a quick "what rate applies in month N?" lookup that drives
    daily interest.
    """
    def rate_of_month(m: int) -> float:
        for rb in blocks:
            if rb.start_month <= m <= rb.end_month:
                return rb.annual_rate
        return blocks[-1].annual_rate
    return rate_of_month


def derive_modelling_end(inputs: Inputs) -> date:
    """Return the last date to simulate based on inputs and optional overrides.

    Finance note: this sets how far into the future the projection runs. It
    honours an explicit modelling end date, otherwise it falls back to the
    contractual end of term.
    """
    if inputs.modelling_end_date:
        return inputs.modelling_end_date
    y = inputs.drawdown_date.year + (inputs.drawdown_date.month - 1 + inputs.total_term_months) // 12
    m = (inputs.drawdown_date.month - 1 + inputs.total_term_months) % 12 + 1
    return date(y, m, 5)


def month_span(start: date, end: date) -> List[date]:
    """Return a list of first-of-month dates between ``start`` and ``end``.

    Finance note: this is the calendar backbone of the schedule, one entry per
    month from drawdown to the modelling horizon, so every month gets a row even
    when nothing happened in it.
    """
    out: List[date] = []
    cur = date(start.year, start.month, 1)
    lim = date(end.year, end.month, 1)
    while cur <= lim:
        out.append(cur)
        cur = date(cur.year + (cur.month // 12), (cur.month % 12) + 1, 1)
    return out


def month_tables(inputs: Inputs, actuals: pd.DataFrame) -> pd.DataFrame:
    """Build a per-month summary table consumed by the daily engine.

    Finance note: this lines up each calendar month with the bank's payment and
    interest activity (and any standing overpayments), giving the day-by-day
    simulation a clean, pre-digested view of what should happen each month.

    The table distils raw bank activity into the bare minimum metadata the
    simulation needs.  Deriving this table up-front keeps the inner daily loop
    simple and fast.
    """
    end = derive_modelling_end(inputs)
    mstarts = month_span(inputs.drawdown_date, end)
    g = actuals.groupby("ym", dropna=False)

    # Expand standing extras into {month_num: amount}
    recurring_by_month: Dict[int, float] = {}
    for rule in inputs.overpay_rules:
        s = int(rule["start_month"])
        amt = float(rule["amount"])
        endm = rule.get("end_month", None)
        rep = str(rule.get("repeat", "monthly")).lower()
        if rep == "monthly":
            i = s
            while i <= inputs.total_term_months and (endm is None or i <= int(endm)):
                recurring_by_month[i] = recurring_by_month.get(i, 0.0) + amt
                i += 1
        else:
            recurring_by_month[s] = recurring_by_month.get(s, 0.0) + amt

    rows = []
    for ms in mstarts:
        ym = ym_int(ms)
        mnum = month_index(inputs.drawdown_date, ms)
        eom_d = eom(ms)
        grp = g.get_group(ym) if ym in g.groups else None

        pay_date = None
        pay_total = 0.0
        post_date = None
        post_amt = 0.0

        if grp is not None:
            pays = grp[grp["type"] == "Payment"]
            if not pays.empty:
                pay_date = ensure_date(min(pays["date"]))
                pay_total = float(-pays["amount"].sum())  # input has payments negative
            ints = grp[grp["type"] == "Interest"]
            if not ints.empty:
                post_date = ensure_date(min(ints["date"]))
                post_amt = float(ints["amount"].sum())

        # Default payment date only if no actual payment that month
        def_pay = None
        if ms >= date(inputs.first_payment_date.year, inputs.first_payment_date.month, 1):
            def_pay = clamp_day(ms.year, ms.month, inputs.repayment_day_default)

        rows.append(
            dict(
                month_start=ms,
                eom=eom_d,
                ym=ym,
                month_num=mnum,
                actual_payment_date=pay_date,
                actual_payment_total=pay_total,
                actual_interest_post_date=post_date,
                actual_interest_amount=post_amt,
                default_payment_date=def_pay,
                recurring_extra=recurring_by_month.get(mnum, 0.0),
            )
        )
    return pd.DataFrame(rows)


# =====================================================================
# Monthly schedule assembly (post daily loop)
# =====================================================================

def build_monthly_schedule(
    months: pd.DataFrame,
    events_df: pd.DataFrame,
    actuals: pd.DataFrame,
    month_paid: Dict[int, float],
    month_extras: Dict[int, float],
    month_lumps: Dict[int, float],
    month_interest_used: Dict[int, float],
    month_rate: Dict[int, float],
) -> pd.DataFrame:
    """Assemble the final per-month schedule after the daily loop has run.

    Finance note: this is where the day-by-day results become the monthly
    schedule a finance reader actually sees. For every month it totals the
    payment, any standing extra, any lump sum, and the interest charged, derives
    the principal repaid, records the interest posting date, and lines up the
    month-end balances for both the model and the bank so the two can be
    compared. These rows drive the Monthly schedule sheet and the tax outputs.

    Technical note: pure relocation of the post-loop assembly from
    ``run_engine``. The per-month collector dicts (``month_paid``,
    ``month_extras``, ``month_lumps``, ``month_interest_used``, ``month_rate``)
    are passed in explicitly so this module never reaches back into
    ``simulate``. As before, it mutates ``events_df`` in place by adding the
    ``ym`` helper column used to align events to their calendar month; this
    matches the pre-S3 behaviour exactly.
    """
    # Plain-English progress line for troubleshooting (stderr only; never stdout).
    print(
        f"[engine.monthly] build_monthly_schedule: assembling {len(months)} monthly rows",
        file=sys.stderr,
    )

    # Per-month frame build ----------------------------------------------------
    rows = []
    for _, r in months.iterrows():
        ymkey = int(r.ym)
        pay = month_paid[ymkey]; extra = month_extras[ymkey]; lump = month_lumps[ymkey]
        interest_used = month_interest_used[ymkey]
        principal = max(0.0, (pay + extra + lump) - interest_used)
        rows.append(dict(
            ym=ymkey,
            month_start=r.month_start,
            payment_date=r.pay_date,
            payment_amount=round(pay, 2),
            extra_amount=round(extra, 2),
            lump_amount=round(lump, 2),
            interest_used=round(interest_used, 2),
            principal_paid=round(principal, 2),
            annual_rate=month_rate[ymkey],
            bank_posted_interest_present=(float(r.actual_interest_amount or 0.0) > 0.0)
        ))
    monthly = pd.DataFrame(rows)

    # Posting date/year --------------------------------------------------------
    monthly["posting_date"] = [
        r.actual_interest_post_date if pd.notna(r.actual_interest_post_date) else r.eom
        for _, r in months.iterrows()
    ]
    monthly["posting_year"] = pd.to_datetime(monthly["posting_date"]).dt.year

    # Add model month-end balance from events (last event in that month).
    if not events_df.empty:
        events_df["ym"] = events_df["date"].apply(ym_int)
        eom_bal = events_df.groupby("ym", as_index=True)["balance"].last().rename("model_eom_balance")
        monthly = monthly.merge(eom_bal, left_on="ym", right_index=True, how="left")

    # Add bank month-end running balance (last bank line in that month, if provided).
    if "run_balance" in actuals.columns:
        bank_month_end = (
            actuals
            .assign(ym=lambda d: d["date"].apply(ym_int))
            .sort_values("date")
            .groupby("ym", as_index=True)["run_balance"]
            .last()
            .rename("bank_eom_running_balance")
        )
        monthly = monthly.merge(bank_month_end, left_on="ym", right_index=True, how="left")
        if "model_eom_balance" in monthly.columns:
            monthly["eom_diff_model_minus_bank"] = monthly["model_eom_balance"] - monthly["bank_eom_running_balance"]

    return monthly


print("[engine.monthly] monthly scaffolding and schedule assembly ready", file=sys.stderr)