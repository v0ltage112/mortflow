# tests/test_overpayment_cap_headroom.py
"""Tests for the Phase 12 / S2 overpayment-cap headroom, flag, and cumulative.

This file was committed empty at Phase 12 / S2 and is authored here for real
(BACKLOG-002). It locks the behaviour of ``overpayment_cap_flag`` (the
ok / approaching / breached label) and the three additive monthly columns the
assembly emits alongside the Phase 12 / S1 allowance:

* ``overpayment_cap_headroom_eur`` - the month's allowance minus its recognised
  voluntary overpayment (positive is room left, negative is the amount over).
* ``overpayment_cap_flag`` - the ok / approaching / breached label.
* ``overpayment_cumulative_eur`` - a context-only lifetime running total.

The BOI cap is per payment, does not roll over, and has no calendar reset, so
each month is judged against its own allowance rather than a running annual
pool. The amber trip point is the single module constant
``OVERPAYMENT_CAP_APPROACHING_THRESHOLD`` (0.90).

Boundary semantics locked here (see ``overpayment_cap_flag``):

* ``used > allowance`` is a breach.
* ``used == allowance`` is NOT a breach: the breach test is strictly greater,
  so an overpayment exactly equal to the allowance reads as "approaching".
* ``used >= 0.90 * allowance`` (but not over the allowance) is "approaching".
* Anything below that is "ok".
* A null allowance returns None, so "unknown" never reads as free headroom.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from src.engine.monthly import (
    OVERPAYMENT_CAP_APPROACHING_THRESHOLD,
    OVERPAYMENT_CAP_FLAG_APPROACHING,
    OVERPAYMENT_CAP_FLAG_BREACHED,
    OVERPAYMENT_CAP_FLAG_OK,
    build_monthly_schedule,
    overpayment_cap_flag,
)


# --------------------------- flag: null allowance ----------------------------

def test_flag_none_when_allowance_unresolvable():
    """A null allowance returns None, distinct from "ok" (no free headroom)."""
    assert overpayment_cap_flag(0.0, None) is None
    assert overpayment_cap_flag(500.0, None) is None


# --------------------------- flag: ok / approaching / breached ---------------

def test_flag_ok_below_approaching_threshold():
    """A small overpayment against a healthy allowance is "ok"."""
    # 50 of 100 is well below the 90% trip point.
    assert overpayment_cap_flag(50.0, 100.0) == OVERPAYMENT_CAP_FLAG_OK


def test_flag_ok_just_below_threshold():
    """Just below the 90% trip point is still "ok"."""
    just_below = OVERPAYMENT_CAP_APPROACHING_THRESHOLD * 100.0 - 0.01
    assert overpayment_cap_flag(just_below, 100.0) == OVERPAYMENT_CAP_FLAG_OK


def test_flag_approaching_at_exact_threshold():
    """Exactly at the 90% trip point is "approaching" (the boundary is inclusive)."""
    at_threshold = OVERPAYMENT_CAP_APPROACHING_THRESHOLD * 100.0
    assert overpayment_cap_flag(at_threshold, 100.0) == OVERPAYMENT_CAP_FLAG_APPROACHING


def test_flag_approaching_just_below_allowance():
    """Just under the allowance is "approaching", not yet a breach."""
    assert overpayment_cap_flag(99.99, 100.0) == OVERPAYMENT_CAP_FLAG_APPROACHING


def test_flag_exactly_at_allowance_is_approaching_not_breached():
    """Exactly equal to the allowance is "approaching": breach is strictly greater.

    This is the subtle boundary. The breach test is ``used > allowance``, so an
    overpayment exactly equal to the cap has not exceeded it and reads as
    "approaching". Locked deliberately so a future change to the comparison
    operator is caught.
    """
    assert overpayment_cap_flag(100.0, 100.0) == OVERPAYMENT_CAP_FLAG_APPROACHING


def test_flag_breached_just_above_allowance():
    """A cent over the allowance is a breach."""
    assert overpayment_cap_flag(100.01, 100.0) == OVERPAYMENT_CAP_FLAG_BREACHED


def test_flag_breached_well_above_allowance():
    """A large overpayment against a small allowance is a breach."""
    assert overpayment_cap_flag(500.0, 100.0) == OVERPAYMENT_CAP_FLAG_BREACHED


# --------------------------- flag: non-positive allowance --------------------

def test_flag_zero_allowance_with_no_overpayment_is_ok():
    """A zero allowance with nothing paid against it has nothing to flag."""
    assert overpayment_cap_flag(0.0, 0.0) == OVERPAYMENT_CAP_FLAG_OK


def test_flag_zero_allowance_with_any_overpayment_is_breached():
    """Any positive overpayment against a zero allowance is a breach."""
    assert overpayment_cap_flag(0.01, 0.0) == OVERPAYMENT_CAP_FLAG_BREACHED


def test_flag_negative_allowance_follows_the_same_rule():
    """A negative allowance behaves like zero: any payment is a breach."""
    assert overpayment_cap_flag(0.0, -5.0) == OVERPAYMENT_CAP_FLAG_OK
    assert overpayment_cap_flag(1.0, -5.0) == OVERPAYMENT_CAP_FLAG_BREACHED


# --------------------------- flag: real Gandon figure ------------------------

def test_flag_real_gandon_allowance_boundaries():
    """The real Gandon allowance (EUR 212.34) flags at the expected points."""
    allowance = 212.34
    assert overpayment_cap_flag(200.0, allowance) == OVERPAYMENT_CAP_FLAG_APPROACHING
    assert overpayment_cap_flag(212.34, allowance) == OVERPAYMENT_CAP_FLAG_APPROACHING
    assert overpayment_cap_flag(212.35, allowance) == OVERPAYMENT_CAP_FLAG_BREACHED
    assert overpayment_cap_flag(100.0, allowance) == OVERPAYMENT_CAP_FLAG_OK


# --------------------------- schedule: emitted columns -----------------------

def _month_row(ym, month_start, pay_date, eom_date, recurring_extra=0.0):
    """A minimal month_tables-shaped row for build_monthly_schedule."""
    return dict(
        ym=ym,
        month_start=month_start,
        pay_date=pay_date,
        eom=eom_date,
        actual_interest_post_date=None,
        actual_interest_amount=0.0,
        has_actual_payment=False,
        recurring_extra=recurring_extra,
    )


def _build(months, contractual, cap_allowance):
    """Assemble a monthly schedule from minimal inputs, with no debits or interest."""
    zeros = {int(r["ym"]): 0.0 for r in months}
    rate = {int(r["ym"]): 0.0365 for r in months}
    return build_monthly_schedule(
        pd.DataFrame(months),
        pd.DataFrame(columns=["date", "kind", "amount", "balance"]),
        pd.DataFrame(),
        dict(zeros), dict(zeros), dict(zeros), dict(zeros),
        rate,
        contractual,
        cap_allowance,
    )


def test_schedule_emits_headroom_flag_and_cumulative_columns():
    """The three Phase 12 / S2 columns are emitted on the monthly schedule."""
    months = [
        _month_row(202406, date(2024, 6, 1), date(2024, 6, 5), date(2024, 6, 30), recurring_extra=200.0),
        _month_row(202407, date(2024, 7, 1), date(2024, 7, 5), date(2024, 7, 31), recurring_extra=200.0),
    ]
    contractual = {202406: 2123.44, 202407: 2123.44}
    cap_allowance = {202406: 212.34, 202407: 212.34}

    monthly = _build(months, contractual, cap_allowance)

    for col in ("overpayment_cap_headroom_eur", "overpayment_cap_flag", "overpayment_cumulative_eur"):
        assert col in monthly.columns


def test_schedule_headroom_is_allowance_minus_overpayment():
    """Headroom is the month's allowance minus its recognised overpayment."""
    months = [
        _month_row(202406, date(2024, 6, 1), date(2024, 6, 5), date(2024, 6, 30), recurring_extra=200.0),
    ]
    contractual = {202406: 2123.44}
    cap_allowance = {202406: 212.34}

    monthly = _build(months, contractual, cap_allowance)
    row = monthly.iloc[0]

    # 212.34 allowance - 200.00 overpayment = 12.34 headroom.
    assert row["overpayment_cap_headroom_eur"] == 12.34
    assert row["overpayment_cap_flag"] == OVERPAYMENT_CAP_FLAG_APPROACHING


def test_schedule_headroom_goes_negative_when_over_the_cap():
    """A negative headroom is the amount by which the overpayment exceeds the cap."""
    months = [
        _month_row(202406, date(2024, 6, 1), date(2024, 6, 5), date(2024, 6, 30), recurring_extra=250.0),
    ]
    contractual = {202406: 2123.44}
    cap_allowance = {202406: 212.34}

    monthly = _build(months, contractual, cap_allowance)
    row = monthly.iloc[0]

    # 212.34 - 250.00 = -37.66, i.e. 37.66 over the cap.
    assert row["overpayment_cap_headroom_eur"] == -37.66
    assert row["overpayment_cap_flag"] == OVERPAYMENT_CAP_FLAG_BREACHED


def test_schedule_cap_columns_are_null_when_allowance_unresolvable():
    """A month with no resolvable allowance carries nulls, not zeros.

    "Unknown" must stay distinct from a real zero so it never reads as free
    headroom.
    """
    months = [
        _month_row(202406, date(2024, 6, 1), date(2024, 6, 5), date(2024, 6, 30), recurring_extra=200.0),
    ]
    contractual = {202406: 2123.44}
    cap_allowance = {202406: None}

    monthly = _build(months, contractual, cap_allowance)
    row = monthly.iloc[0]

    assert pd.isna(row["overpayment_cap_headroom_eur"])
    assert pd.isna(row["overpayment_cap_flag"])


def test_schedule_cumulative_is_a_running_total_of_overpayment():
    """The cumulative column is a lifetime running total of recognised overpayment."""
    months = [
        _month_row(202406, date(2024, 6, 1), date(2024, 6, 5), date(2024, 6, 30), recurring_extra=200.0),
        _month_row(202407, date(2024, 7, 1), date(2024, 7, 5), date(2024, 7, 31), recurring_extra=200.0),
        _month_row(202408, date(2024, 8, 1), date(2024, 8, 5), date(2024, 8, 31), recurring_extra=200.0),
    ]
    contractual = {202406: 2123.44, 202407: 2123.44, 202408: 2123.44}
    cap_allowance = {202406: 212.34, 202407: 212.34, 202408: 212.34}

    monthly = _build(months, contractual, cap_allowance).sort_values("ym")
    cumulative = list(monthly["overpayment_cumulative_eur"])

    # 200, then 400, then 600.
    assert cumulative == [200.0, 400.0, 600.0]


def test_schedule_cumulative_does_not_feed_the_flag():
    """The cumulative total is context only: it never changes the per-payment flag.

    Each month is judged against its own allowance, so a large cumulative total
    does not by itself breach a later month's cap.
    """
    months = [
        _month_row(202406, date(2024, 6, 1), date(2024, 6, 5), date(2024, 6, 30), recurring_extra=200.0),
        _month_row(202407, date(2024, 7, 1), date(2024, 7, 5), date(2024, 7, 31), recurring_extra=200.0),
    ]
    contractual = {202406: 2123.44, 202407: 2123.44}
    cap_allowance = {202406: 212.34, 202407: 212.34}

    monthly = _build(months, contractual, cap_allowance).sort_values("ym")

    # Cumulative reaches 400, well above the 212.34 allowance, yet both months
    # are judged on their own 200.00 overpayment and stay "approaching".
    assert list(monthly["overpayment_cumulative_eur"]) == [200.0, 400.0]
    assert list(monthly["overpayment_cap_flag"]) == [
        OVERPAYMENT_CAP_FLAG_APPROACHING,
        OVERPAYMENT_CAP_FLAG_APPROACHING,
    ]


# --------------------------- REVIEW-008: observed overpayment ----------------

def _build_with_debit(months, contractual, cap_allowance, paid):
    """Assemble a schedule where the month's debit exceeds the agreed split.

    The excess lands in the Difference residual, exactly as a real bank-side
    overpayment does. ``paid`` is the full monthly debit per ``ym``.
    """
    rate = {int(r["ym"]): 0.0365 for r in months}
    zeros = {int(r["ym"]): 0.0 for r in months}
    return build_monthly_schedule(
        pd.DataFrame(months),
        pd.DataFrame(columns=["date", "kind", "amount", "balance"]),
        pd.DataFrame(),
        dict(paid), dict(zeros), dict(zeros), dict(zeros),
        rate,
        contractual,
        cap_allowance,
    )


def test_cap_flag_sees_an_unagreed_bank_overpayment():
    """REVIEW-008: a bank-side overpayment beyond the agreed extra still flags.

    The agreed standing extra is 200.00, but the borrower actually paid 500.00
    through the bank, so 300.00 lands in the Difference residual. The cap is a
    limit on money actually overpaid, so the month must read "breached" against
    the 212.34 allowance, not "approaching" on the agreed 200.00 alone.
    """
    months = [
        _month_row(202406, date(2024, 6, 1), date(2024, 6, 5), date(2024, 6, 30), recurring_extra=200.0),
    ]
    contractual = {202406: 2123.44}
    cap_allowance = {202406: 212.34}
    # The bank debited 2423.44 = 2123.44 contractual + 200 agreed + 100 unagreed.
    paid = {202406: 2423.44}

    monthly = _build_with_debit(months, contractual, cap_allowance, paid)
    row = monthly.iloc[0]

    # The unagreed 100.00 sits in the Difference residual.
    assert row["difference"] == 100.0
    # Used = 200 agreed + 100 unagreed = 300, over the 212.34 allowance.
    assert row["overpayment_cap_headroom_eur"] == round(212.34 - 300.0, 2)
    assert row["overpayment_cap_flag"] == OVERPAYMENT_CAP_FLAG_BREACHED


def test_cap_flag_ignores_an_underpayment():
    """A negative Difference is an underpayment, not an overpayment.

    The borrower paid less than the agreed split, so the Difference is negative.
    That must not be treated as negative overpayment (which would inflate the
    headroom); the used amount floors the Difference at zero.
    """
    months = [
        _month_row(202406, date(2024, 6, 1), date(2024, 6, 5), date(2024, 6, 30), recurring_extra=200.0),
    ]
    contractual = {202406: 2123.44}
    cap_allowance = {202406: 212.34}
    # The bank debited 2000.00, less than the agreed 2323.44 split.
    paid = {202406: 2000.0}

    monthly = _build_with_debit(months, contractual, cap_allowance, paid)
    row = monthly.iloc[0]

    assert row["difference"] < 0
    # Used stays at the agreed 200.00, so headroom is unchanged at 12.34.
    assert row["overpayment_cap_headroom_eur"] == 12.34
    assert row["overpayment_cap_flag"] == OVERPAYMENT_CAP_FLAG_APPROACHING
