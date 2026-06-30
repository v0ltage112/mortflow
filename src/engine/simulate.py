# src/engine/simulate.py
"""Scheduled-payment helper and the core daily mortgage simulation.

Finance-readable summary
------------------------
This module is the simulation engine. ``run_engine`` is now a thin
orchestrator: it runs the day-by-day walk of the loan, then hands the raw
results to the monthly, valuation, and reconcile helpers to build the tables
the business reports on (the daily event log, the monthly schedule with
interest, principal, balances and LTV, and the bank-versus-model reconcile).
The day-by-day walk itself lives in ``_simulate_daily`` so a reader can follow
the simulation and the reporting steps separately.

Technical summary
-----------------
Holds the scheduled-payment helper (``payment_for_month``), the daily simulator
(``_simulate_daily``) with its explicit result contract (``DailyRunResult``),
and the public entry point (``run_engine``). Monthly scaffolding and schedule
assembly live in ``monthly.py``; property valuation in ``valuation.py``; the
model-vs-bank reconcile in ``reconcile.py``. ``run_engine`` calls
``_simulate_daily`` and then those helpers in fixed order, returning the same
``(monthly, reconcile, events_df)`` tuple, in the same order and with the same
columns, as before.

Phase 5 / S5 note: ``run_engine`` was thinned into an orchestrator and the
daily loop (plus its setup) was extracted into ``_simulate_daily`` returning a
``DailyRunResult``. Pure relocation: the daily accrual, the pre/post-debit
interest posting order, the Payment/Extra/Lump debit application, and the
final-payment trim are byte-for-byte the same lines, only moved. No behaviour
change; the golden master and the S1 characterization test stay green.

Phase 7 / S2 note: an additive contractual-baseline column is computed here.
On each payment day the loop records the contractual instalment agreed for that
month into a new ``month_contractual`` collector: the agreed ladder amount
(from the Phase 7 / S1 schema) where the bank has confirmed a step, otherwise
the model's projected scheduled payment (the same ``payment_for_month`` value
the engine already uses). This is strictly read-only with respect to the loan
maths: it never touches the balance, the debit applied, the carried-forward
base payment, or the interest posting, so every existing figure (total paid,
interest, principal, balance, payoff) stays byte-identical to v1.7.0. The value
is threaded through ``DailyRunResult`` to ``build_monthly_schedule``, which
emits it as the new ``contractual_payment`` monthly column.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .helpers import (
    day_count_divisor,
    ensure_date,
    eom,
    month_index,
    pmt,
    ym_int,
)
from .schema import Inputs
from .valuation import property_value_on
from .monthly import (
    build_rate_lookup,
    derive_modelling_end,
    month_tables,
    build_monthly_schedule,
)
from .reconcile import build_reconcile


# =====================================================================
# Engine (daily simulation)
# =====================================================================

def payment_for_month(
    inputs: Inputs, mnum: int, annual_rate: float, balance: float, months: pd.DataFrame, last_known_payment_base: float
) -> float:
    """Return the scheduled payment for a model month when none is provided.

    Finance note: in months where the bank statement has no payment line, this
    decides the instalment to assume: the known first payment, a recalculated
    PMT at a refix, or the last base payment carried forward. It sets projected
    principal and interest in unobserved months.

    The logic mimics how lenders adjust standing orders:

    * First payment month uses the known value from the inputs file.
    * At the beginning of a new rate block, and only when the strategy is
      ``RecalculatePayment``, we recompute a PMT using the remaining term and
      current balance.
    * Otherwise the last known *base* payment (excluding recurring extras) is
      carried forward.
    """
    if mnum == month_index(inputs.drawdown_date, inputs.first_payment_date):
        return inputs.known_first_payment

    is_block_start = any((mnum == rb.start_month) for rb in inputs.rate_blocks)
    if inputs.strategy_at_refix == "RecalculatePayment" and is_block_start:
        remaining = max(0, inputs.total_term_months - (mnum - 1))
        return pmt(annual_rate / 12.0, remaining, balance)

    return last_known_payment_base


def _ladder_amount_for_month(inputs: Inputs, mnum: int) -> Optional[float]:
    """Return the agreed contractual instalment in effect for a model month.

    Finance note: walks the agreed contractual ladder (the drawdown instalment,
    then each refix the bank has confirmed) and returns the most recent agreed
    amount that has taken effect by this month. Returns ``None`` when no agreed
    step applies yet, which is the signal for the caller to fall back to the
    projected model payment. On its own this reads the agreed terms only and
    changes no modelled figure.

    Technical note: ``inputs.contractual_ladder`` is sorted ascending by
    ``start_month`` in the schema loader, so the last step whose ``start_month``
    is not in the future is the one in effect; the loop stops at the first
    future step.
    """
    agreed: Optional[float] = None
    for step in inputs.contractual_ladder:
        if step.start_month <= mnum:
            agreed = step.amount          # a later confirmed step overrides an earlier one
        else:
            break                          # ladder is time-sorted; no later step applies yet
    return agreed


@dataclass
class DailyRunResult:
    """Raw output of the daily simulation loop, before any reporting tables.

    Finance note: this is the loan's day-by-day walk handed back before the
    monthly schedule, the LTV columns, or the bank reconcile are built. It
    carries the per-day event log and the per-month money totals those reports
    are assembled from, with nothing pre-aggregated yet.

    Technical note: the explicit contract between ``_simulate_daily`` (the
    producer) and ``run_engine`` (the consumer), so the orchestrator never
    reaches into loop internals. ``months`` is the prepared month table the
    monthly assembly needs; the dicts are the per-``YYYYMM`` collectors the
    loop populates (amounts paid, recurring extras, lump sums, interest used,
    the annual rate applied each month, and the Phase 7 / S2 contractual
    baseline).

    Phase 7 / S2 adds ``month_contractual``: the agreed (or projected)
    contractual instalment recorded per ``YYYYMM`` on each payment day, used to
    build the additive ``contractual_payment`` monthly column.
    """
    months: pd.DataFrame
    events: List[Dict]
    month_paid: Dict[int, float]
    month_extras: Dict[int, float]
    month_lumps: Dict[int, float]
    month_interest_used: Dict[int, float]
    month_rate: Dict[int, float]
    month_contractual: Dict[int, float]


def _simulate_daily(inputs: Inputs, actuals: pd.DataFrame) -> DailyRunResult:
    """Walk the loan day by day, returning the raw event log and month totals.

    Finance note: this is the heart of the model. Starting from the drawdown
    balance it accrues interest every day, applies payments, standing extras and
    lump sums, posts interest on the bank's posting day, and mirrors the bank's
    final-payment trimming so the loan closes at exactly zero. It produces no
    report tables itself; it returns the daily events and the per-month money
    totals that ``run_engine`` then turns into the monthly schedule, LTV
    columns, and reconcile.

    Technical note: the daily mechanics are unchanged from Phase 5 / S5. Phase 7
    / S2 adds a read-only contractual-baseline capture on payment days (see the
    CONTRACTUAL BASELINE block); it consults the agreed ladder and, as a
    fallback, the existing ``payment_for_month`` projection, without mutating
    any simulation state.
    """
    rate_of = build_rate_lookup(inputs.rate_blocks)
    months = month_tables(inputs, actuals)

    # ------------------------------------------------------------------
    # Precompute month lookups to avoid per-day DataFrame slicing.  The
    # simulation loop is tight and runs for potentially thousands of days, so
    # we prefer constant-time lookups over repeated groupby operations.
    # ------------------------------------------------------------------
    months = months.copy()
    months["pay_date"] = months.apply(
        lambda r: r.actual_payment_date if pd.notna(r.actual_payment_date) else r.default_payment_date,
        axis=1
    )
    months["has_actual_payment"] = months["actual_payment_total"] > 0
    months_by_ym = {int(r.ym): r for _, r in months.iterrows()}

    # One-off lump-sum overpayments keyed by exact date for O(1) lookups.
    lumps_by_date = {ensure_date(x["date"]): float(x["amount"]) for x in inputs.lump_sums} if inputs.lump_sums else {}

    # Rolling state of the simulation.
    start = inputs.drawdown_date
    end = derive_modelling_end(inputs)
    balance = float(inputs.principal_at_drawdown)
    accrued = 0.0

    # Base scheduled payment tracker (without standing extras).
    last_known_payment_base = float(inputs.known_first_payment)

    # Merge behaviour for recurring extras versus payments.  Users can ask the
    # model to explicitly separate recurring extras even if the bank merges
    # them into the payment line.
    merge_mode = (inputs.merge_extra_mode or "auto").strip().lower()
    # In actual-payment months: 'auto' behaves like 'true'
    actuals_merge_extras = (merge_mode in {"auto", "true"})
    # In scheduled months: only 'true' merges extras into the Payment
    scheduled_merge_extras = (merge_mode == "true")

    # Per-month collector dictionaries – keyed by ``YYYYMM`` integers.
    month_interest_used: Dict[int, float] = {int(r.ym): 0.0 for _, r in months.iterrows()}
    month_paid: Dict[int, float] = {int(r.ym): 0.0 for _, r in months.iterrows()}
    month_extras: Dict[int, float] = {int(r.ym): 0.0 for _, r in months.iterrows()}
    month_lumps: Dict[int, float] = {int(r.ym): 0.0 for _, r in months.iterrows()}
    month_rate: Dict[int, float] = {int(r.ym): rate_of(int(r.month_num)) for _, r in months.iterrows()}
    # Phase 7 / S2: agreed (or projected) contractual instalment per month.
    # Seeded at zero for every month and populated on payment days. Additive and
    # read-only: it never feeds back into the balance or any conserved total.
    month_contractual: Dict[int, float] = {int(r.ym): 0.0 for _, r in months.iterrows()}

    # Event log (only days where something happens).
    events: List[Dict] = []

    # Daily walk ----------------------------------------------------------------
    cur = start
    while cur <= end and balance > 0.01:
        ym = ym_int(cur)
        mrow = months_by_ym[ym]
        mnum = int(mrow.month_num)
        annual = month_rate[ym]

        # Accrual for the day ----------------------------------------------------
        daily_rate = annual / day_count_divisor(inputs.day_count)
        accrued += balance * daily_rate

        # Snapshot start-of-day principal (excl. unposted interest).
        start_balance_today = balance
        day_events_start_idx = len(events)
        loan_cleared_today = False

        # Values used regardless of whether today is a payment day or not.
        recurring_amt = float(mrow.recurring_extra or 0.0)
        lump_today = float(lumps_by_date.get(cur, 0.0))
        payment_today = 0.0
        extra_today = 0.0
        base_sched: Optional[float] = None

        is_payment_day = (pd.notna(mrow.pay_date) and ensure_date(mrow.pay_date) == cur)
        has_actual_payment = bool(mrow.has_actual_payment)

        if is_payment_day and has_actual_payment:
            # ACTUAL month: the bank decided the debit; optionally un-merge extras.
            payment_today = float(mrow.actual_payment_total)
            if not actuals_merge_extras and recurring_amt > 0.0:
                # Split bank debit into base + extra, capped by the actual amount
                base = max(0.0, payment_today - recurring_amt)
                extra_today = min(recurring_amt, payment_today)
                payment_today = base
            else:
                extra_today = 0.0

        elif is_payment_day:
            # SCHEDULED month: compute base PMT (no bank line).
            base_sched = payment_for_month(inputs, mnum, annual, balance, months, last_known_payment_base)
            if scheduled_merge_extras and recurring_amt > 0.0:
                payment_today = base_sched + recurring_amt
                extra_today = 0.0
            else:
                payment_today = base_sched
                extra_today = recurring_amt

        else:
            # Not a payment day; only lumps may occur.
            pass

        # Carry forward ONLY if we computed a new base scheduled payment.
        if base_sched is not None:
            last_known_payment_base = base_sched

        # ---------------- CONTRACTUAL BASELINE (Phase 7 / S2) ----------------
        # On a payment day, record the contractual instalment agreed for this
        # month. The agreed ladder wins; where the bank has not confirmed a step
        # the model's projected scheduled payment is used instead (clearly a
        # projection, not an agreed figure). This is read-only: it does not
        # change the balance, the debit applied, the carried-forward base, or the
        # interest posting, so no existing monthly figure moves.
        if is_payment_day:
            agreed_amt = _ladder_amount_for_month(inputs, mnum)
            if agreed_amt is not None:
                contractual_today = agreed_amt           # bank-confirmed agreed instalment
            elif base_sched is not None:
                contractual_today = base_sched           # scheduled month: reuse the PMT just computed
            else:
                # Actual month with no agreed step: project the model PMT using
                # the same pre-debit balance and rate the scheduled path uses.
                contractual_today = payment_for_month(
                    inputs, mnum, annual, balance, months, last_known_payment_base
                )
            month_contractual[ym] = round(contractual_today, 2)

        # Logic to calculate potential interest posting amount
        interest_to_post = 0.0
        should_post_interest = False
        post_date = mrow.actual_interest_post_date if pd.notna(mrow.actual_interest_post_date) else eom(cur)
        post_date = ensure_date(post_date)
        
        if cur == post_date:
            should_post_interest = True
            if (mrow.actual_interest_amount or 0.0) > 0:
                interest_to_post = float(mrow.actual_interest_amount)
            else:
                interest_to_post = round(accrued, 2)

        # ---------------- PRE-DEBIT POSTING ----------------
        if inputs.posting_order == "post_then_debit" and should_post_interest:
            balance += interest_to_post
            accrued = 0.0
            month_interest_used[ym] = interest_to_post
            events.append(dict(date=cur, kind="Interest", amount=interest_to_post, balance=round(balance, 2)))
            should_post_interest = False  # Consumed

        # ---------------- DEBITS ----------------
        # Apply debits in the order Payment → Extra → Lump to mirror the intent
        # of the inputs and make the later "trim" logic deterministic.
        # STRICT ROUNDING: All debits must be 2 decimal places before hitting the balance.
        payment_today = round(payment_today, 2)
        extra_today = round(extra_today, 2)
        lump_today = round(lump_today, 2)

        if payment_today > 0:
            balance -= payment_today
            month_paid[ym] += payment_today
            events.append(dict(date=cur, kind="Payment", amount=payment_today, balance=round(balance, 2)))

        if extra_today > 0:
            balance -= extra_today
            month_extras[ym] += extra_today
            events.append(dict(date=cur, kind="Extra", amount=extra_today, balance=round(balance, 2)))

        if lump_today > 0:
            balance -= lump_today
            month_lumps[ym] += lump_today
            events.append(dict(date=cur, kind="Lump", amount=lump_today, balance=round(balance, 2)))

        # ---- Final-payment trim (bank behaviour) ----
        if balance < -1e-9:
            overshoot = -balance
            # walk today's events backwards: Lump -> Extra -> Payment (reverse of application)
            # CAUTION: If we posted interest first, we DO NOT trim the interest event.
            # We only trim user debits (Payment/Extra/Lump).
            i = len(events) - 1
            while overshoot > 1e-9 and i >= day_events_start_idx:
                ev = events[i]
                if ev["kind"] in {"Payment", "Extra", "Lump"} and ev["amount"] > 0:
                    take = min(overshoot, float(ev["amount"]))
                    new_amt = round(float(ev["amount"]) - take, 2)
                    if ev["kind"] == "Payment":
                        month_paid[ym] -= take
                    elif ev["kind"] == "Extra":
                        month_extras[ym] -= take
                    else:
                        month_lumps[ym] -= take
                    overshoot = round(overshoot - take, 2)

                    if new_amt <= 0.0 + 1e-9:
                        events.pop(i)
                    else:
                        ev["amount"] = new_amt
                i -= 1

            # Recompute balances for today's remaining events from start_balance_today
            # (Note: start_balance_today does not include the interest if it was posted today.
            #  So we must account for that if post_then_debit happened)
            
            # Simple re-run balance calculation for stability:
            b_recalc = start_balance_today
            for j in range(day_events_start_idx, len(events)):
                e = events[j]
                op = 1.0 if e["kind"] == "Interest" else -1.0
                b_recalc += (float(e["amount"]) * op)
                e["balance"] = round(b_recalc, 2)

            balance = max(0.0, b_recalc) # Should be 0.0
            loan_cleared_today = True
            accrued = 0.0  # suppress interest posting later today (if debit-then-post)

        # ---------------- POST-DEBIT POSTING ----------------
        # Interest posting on bank date if present; else EOM.  The posting is
        # suppressed if the loan was cleared earlier today to mimic the bank's
        # behaviour.
        if inputs.posting_order == "debit_then_post" and should_post_interest and not loan_cleared_today:
            balance += interest_to_post
            accrued = 0.0
            month_interest_used[ym] = interest_to_post
            events.append(dict(date=cur, kind="Interest", amount=interest_to_post, balance=round(balance, 2)))

        # Next day --------------------------------------------------------------
        cur += timedelta(days=1)

    # Hand the raw walk back to the orchestrator; no report assembly here.
    return DailyRunResult(
        months=months,
        events=events,
        month_paid=month_paid,
        month_extras=month_extras,
        month_lumps=month_lumps,
        month_interest_used=month_interest_used,
        month_rate=month_rate,
        month_contractual=month_contractual,
    )


def run_engine(inputs: Inputs, actuals: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the daily simulation, then build the three reporting tables.

    Finance note: this is the public entry point the tools and tests call. It
    runs the day-by-day walk (``_simulate_daily``), then assembles the three
    tables the business reports on: the monthly schedule, the bank-versus-model
    reconcile, and the daily events log with property value and LTV attached.

    The function returns three DataFrames:

    ``monthly``
        Per-month schedule used for reporting and tax computations.

    ``reconcile``
        A join between modelled and bank events that supports audits and
        tolerance checks.

    ``events_df``
        The canonical event log with one row per bank-like transaction
        generated by the engine.

    Technical note: thinned in Phase 5 / S5. The setup and the daily loop now
    live in ``_simulate_daily``; this function consumes its ``DailyRunResult``
    and calls ``build_monthly_schedule``, ``property_value_on``, and
    ``build_reconcile`` in the same order as before, so the returned tuple and
    its columns are unchanged apart from the additive Phase 7 / S2
    ``contractual_payment`` column passed through to the monthly assembly.
    """
    # Plain-English progress line for troubleshooting (stderr only; never stdout).
    print("[engine.simulate] run_engine: starting daily simulation", file=sys.stderr)

    # Day-by-day walk: events + per-month collectors + the prepared month table.
    sim = _simulate_daily(inputs, actuals)

    # ------------------ Build outputs ------------------

    # Event log DataFrame — stable ordering (Payment, Extra, Lump, Interest).
    if sim.events:
        order = {"Payment": 0, "Extra": 1, "Lump": 2, "Interest": 3}
        events_df = pd.DataFrame(sim.events)
        events_df["__order"] = events_df["kind"].map(order).fillna(99).astype(int)
        events_df = events_df.sort_values(["date", "__order"]).drop(columns="__order")
    else:
        events_df = pd.DataFrame(columns=["date", "kind", "amount", "balance"])

    # Per-event property value & LTV after each event
    if not events_df.empty:
        try:
            events_df["property_value"] = events_df["date"].apply(lambda d: property_value_on(inputs, ensure_date(d)))
            events_df["ltv_after_event"] = events_df["balance"] / events_df["property_value"]
        except Exception:
            events_df["property_value"] = np.nan
            events_df["ltv_after_event"] = np.nan

    # Monthly schedule, posting dates, and EOM balances are assembled in the
    # monthly module.  The per-month collector dicts populated by the daily
    # loop are passed in explicitly so monthly.py never reaches back here. The
    # Phase 7 / S2 contractual collector rides along to emit contractual_payment.
    monthly = build_monthly_schedule(
        sim.months,
        events_df,
        actuals,
        sim.month_paid,
        sim.month_extras,
        sim.month_lumps,
        sim.month_interest_used,
        sim.month_rate,
        sim.month_contractual,
        # Phase 7 / S3: the dedicated tolerance that decides when an actual
        # month is flagged as not reconciling to the agreed split.
        payment_unattributed_ok_abs_eur=inputs.payment_unattributed_ok_abs_eur,
    )

    # Property value (at EOM) and LTVs ----------------------------------------
    try:
        monthly["property_value"] = monthly["month_start"].apply(lambda ms: property_value_on(inputs, eom(ensure_date(ms))))
        if "model_eom_balance" in monthly.columns:
            monthly["ltv_model_eom"] = monthly["model_eom_balance"] / monthly["property_value"]
        if "bank_eom_running_balance" in monthly.columns:
            monthly["ltv_bank_eom"] = monthly["bank_eom_running_balance"] / monthly["property_value"]
    except Exception:
        monthly["property_value"] = np.nan
        monthly["ltv_model_eom"] = np.nan
        if "bank_eom_running_balance" in monthly.columns:
            monthly["ltv_bank_eom"] = np.nan

    # Reconcile model vs bank events.  The join, the diff, and the
    # tolerance labels were lifted into reconcile.py in Phase 5 / S4;
    # behaviour is unchanged.
    rec = build_reconcile(events_df, actuals, inputs)

    # Plain-English completion line for troubleshooting (stderr only).
    print(
        f"[engine.simulate] run_engine: built {len(monthly)} monthly rows, "
        f"{len(rec)} reconcile rows, {len(events_df)} events",
        file=sys.stderr,
    )
    return monthly, rec, events_df


print("[engine.simulate] scaffolding and engine ready", file=sys.stderr)