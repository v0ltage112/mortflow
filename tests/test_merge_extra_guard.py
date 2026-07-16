# tests/test_merge_extra_guard.py
"""Regression tests for the "merge recurring extras" feature flag.

Background
----------
Phase 2 of the engine introduced the ability to merge standing order overpayments
into the regular payment when an actual bank payment already exists for that
month.  These tests lock that behaviour so refactors cannot silently reintroduce
duplicate "Extra" entries or lose projected extras when actuals are missing.

Phase 11 / S2 note
------------------
Property A converted to the date-based contracts schema in Phase 10 / S2, and
every real residence (Property B / Somerton, Property C / Paragon) uses that
schema natively. A contracts-based property's recurring standing overpayment is
read from each contract's own ``standing_overpayment`` window; ``month_tables``
in ``src/engine/monthly.py`` reads the legacy ``overpay_rules`` only when a
property carries no contracts at all. These guards used to probe the merge flag
by setting only ``overpay_rules``, which silently stopped reaching Property A
the moment it converted. The guard kept "passing" only because Property A's
real contract-level standing overpayment happens to also be EUR 200 from month
17, so the hardcoded expectation matched the property's own real figure by
coincidence rather than the injection actually taking effect. That went
unnoticed until Somerton, whose real standing overpayment is EUR 140, entered
the behavioural matrix in Phase 11 / S2 and exposed the EUR 60 gap. The three
tests below now build their probe scenario through
``_probe_overpayment_inputs``, which injects the amount through whichever
mechanism the property's own schema actually reads, so the guard exercises the
merge flag for real on every enabled property, sample or real, contracts-based
or legacy.
"""
from datetime import date
from dataclasses import replace
from typing import Optional

import pandas as pd

from src.engine import month_index, run_engine
from src.engine.schema import StandingOverpayment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_actuals_row(pay_date: date, amount: float) -> pd.DataFrame:
    """Build a one-row actuals frame that mimics a bank export.

    Why we care
    -----------
    Tests in this module need precise control over actual payment lines.  The
    helper reproduces the sanitisation performed by :func:`load_actuals` so that
    the engine sees exactly what it would in production (title-cased types and
    the derived `ym` column used for grouping).
    """
    df = pd.DataFrame(
        [{"date": pay_date, "type": "Payment", "amount": -abs(amount), "run_balance": None}]
    )
    df["type"] = df["type"].astype(str).str.strip().str.title()
    df["ym"] = df["date"].apply(lambda d: d.year * 100 + d.month)
    return df


def _probe_overpayment_inputs(
    inputs, amount: float, window_start: date, window_end: Optional[date] = None
):
    """Return ``inputs`` with a single probe standing overpayment, schema-aware.

    Why we care
    -----------
    ``month_tables`` (src/engine/monthly.py) reads the recurring overpayment
    from two different places depending on the property's schema: a
    contracts-based property sums each contract's own ``standing_overpayment``
    window and ignores ``overpay_rules`` entirely; a still-legacy property (no
    ``contracts``) reads ``overpay_rules``. To probe the merge flag on any
    property, real or sample, this clears every contract's native standing
    overpayment (so the probe amount is not silently added on top of a
    residence's own real voluntary overpayment) and attaches exactly one
    override, on whichever contract's date span covers ``window_start``, when
    the property has contracts; a property with no contracts falls back to
    setting ``overpay_rules`` exactly as the pre-Phase-11 version of this test
    file did.
    """
    if inputs.contracts:
        new_contracts = []
        injected = False
        for c in inputs.contracts:
            # Strip any real standing overpayment first, so the probe amount is
            # the only recurring extra in play for this scenario.
            cleared = replace(c, standing_overpayment=None)
            covers_window = cleared.start_date <= window_start and (
                cleared.end_date is None or cleared.end_date >= window_start
            )
            if not injected and covers_window:
                cleared = replace(
                    cleared,
                    standing_overpayment=StandingOverpayment(
                        amount=amount, start_date=window_start, end_date=window_end
                    ),
                )
                injected = True
            new_contracts.append(cleared)
        assert injected, (
            f"No contract on this property's loan covers {window_start}; "
            "cannot inject a probe standing overpayment"
        )
        return replace(inputs, contracts=new_contracts)
    # Legacy fallback: no contracts, so overpay_rules is what month_tables reads.
    start_m = month_index(inputs.drawdown_date, window_start)
    end_m = month_index(inputs.drawdown_date, window_end) if window_end else None
    return replace(
        inputs,
        overpay_rules=[
            {"start_month": start_m, "amount": amount, "repeat": "monthly", "end_month": end_m}
        ],
    )


# ---------------------------------------------------------------------------
# merge_extra_mode = true
# ---------------------------------------------------------------------------
def test_merge_extra_enabled_no_separate_extra(inputs):
    """Do not emit a standalone extra when a bank payment already includes it.

    Why we care
    -----------
    When `merge_extra_mode` is set to `true` the engine should fold recurring
    extras into the observed bank payment.  Seeing an additional "Extra" event
    would double-count cash leaving the account and ruin both reconciliations
    and KPI calculations.
    """
    pay_date = date(2025, 7, 5)  # month 17 from 2024-03 (in sample fixtures)
    ym = pay_date.year * 100 + pay_date.month
    window_start = date(2025, 7, 1)

    # Phase 11 / S2: inject the probe overpayment through whichever schema this
    # property actually reads it from, so the guard exercises the merge flag
    # for real regardless of the property's schema.
    test_inputs = replace(
        _probe_overpayment_inputs(inputs, 200.0, window_start),
        merge_extra_mode="true",  # Phase-2 knob
    )

    # In reality this amount would be "scheduled payment + 200", but any value
    # that represents the bank lump sum works for the guard.
    actuals = _make_actuals_row(pay_date, amount=test_inputs.known_first_payment + 200.0)

    monthly, _, events = run_engine(test_inputs, actuals)

    # No 'Extra' event should appear on that date.
    extras_today = events[(events["date"] == pay_date) & (events["kind"] == "Extra")]
    assert extras_today.empty, f"Expected NO Extra event on {pay_date}, found:\n{extras_today}"

    # Phase 7 / S4: the merge-split extra_amount column is retired. The merge
    # behaviour is now observable only in the events log (asserted above). The
    # monthly schedule's overpayment column reports the AGREED standing extra and
    # is independent of the merge flag, so it reads 200.00 here regardless of
    # merging.
    mrow = monthly.loc[monthly["ym"] == ym]
    assert not mrow.empty, "Monthly row missing"
    assert abs(float(mrow["overpayment"].iloc[0]) - 200.0) <= 1e-6


# ---------------------------------------------------------------------------
# merge_extra_mode = false
# ---------------------------------------------------------------------------
def test_merge_extra_disabled_posts_extra(inputs):
    """Emit a distinct extra when the merge flag is disabled.

    Why we care
    -----------
    This is the complement to the previous test: when merging is off we expect
    the engine to post a separate "Extra" event for transparency while also
    surfacing the amount in the monthly table.  Diverging from this behaviour
    would surprise users who rely on the legacy reporting format.
    """
    pay_date = date(2025, 7, 5)
    ym = pay_date.year * 100 + pay_date.month
    window_start = date(2025, 7, 1)

    test_inputs = replace(
        _probe_overpayment_inputs(inputs, 200.0, window_start),
        merge_extra_mode="false",
    )

    actuals = _make_actuals_row(pay_date, amount=test_inputs.known_first_payment + 200.0)

    monthly, _, events = run_engine(test_inputs, actuals)

    # We should see a distinct Extra event for exactly 200.00.
    extras_today = events[(events["date"] == pay_date) & (events["kind"] == "Extra")]
    assert not extras_today.empty, f"Expected an Extra event on {pay_date}, found none."
    amt = float(extras_today["amount"].sum())
    assert abs(amt - 200.0) <= 1e-6, f"Extra posted {amt}, expected 200.00"

    # Phase 7 / S4: extra_amount is retired. The agreed overpayment column reads
    # the standing extra (200.00) here, matching the Extra event asserted above.
    mrow = monthly.loc[monthly["ym"] == ym]
    assert not mrow.empty, "Monthly row missing"
    assert abs(float(mrow["overpayment"].iloc[0]) - 200.0) <= 1e-6


# ---------------------------------------------------------------------------
# Projections with merged extras
# ---------------------------------------------------------------------------
def test_merge_extra_projection_month_adds_into_payment(inputs):
    """Projected months without actuals still include the standing extra.

    Why we care
    -----------
    The monthly planner often extends beyond the available bank statements.  We
    need to confirm that projected payments in those months absorb the recurring
    extra instead of dropping it altogether.
    """
    # Start a recurring €200 from 2025-07; provide *no* actuals at all.
    window_start = date(2025, 7, 1)
    test_inputs = replace(
        _probe_overpayment_inputs(inputs, 200.0, window_start),
        merge_extra_mode="true",
    )

    actuals = pd.DataFrame(columns=["date", "type", "amount", "run_balance", "ym"])

    monthly, _, events = run_engine(test_inputs, actuals)

    # The first scheduled payment on/after 2025-07 should equal base + 200.  We
    # look at the events stream to find that payment.
    first_pay = (
        events[(events["kind"] == "Payment") & (events["date"] >= date(2025, 7, 1))]
        .sort_values("date")
        .head(1)
    )
    assert not first_pay.empty, "No scheduled Payment found from 2025-07 onwards"

    observed = float(first_pay["amount"].iloc[0])
    expected = float(inputs.known_first_payment + 200.0)
    assert abs(observed - expected) <= 1e-6, f"Scheduled payment {observed} vs expected {expected}"

    # Ensure no separate 'Extra' on the same date: projections should mirror the
    # merged view that users see on real bank-payment months.
    pay_dt = first_pay["date"].iloc[0]
    extras_same_day = events[(events["date"] == pay_dt) & (events["kind"] == "Extra")]
    assert extras_same_day.empty, f"Unexpected Extra on scheduled payment date {pay_dt}"