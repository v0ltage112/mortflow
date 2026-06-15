"""Focused unit tests for small helper functions in the engine module.

These helpers are the building blocks used throughout the amortisation engine.
By keeping these tests explicit and well-commented we document the contract of
each helper and demonstrate why the behaviour matters to the larger model.
"""

from src.engine import day_count_divisor, pmt, property_value_on


# ---------------------------------------------------------------------------
# Payment helper (`pmt`)
# ---------------------------------------------------------------------------

def test_pmt_zero_rate():
    """Zero-interest payments should evenly split the principal across periods.

    Why we care
    -----------
    The `pmt` helper is a direct port of Excel's PMT function.  Zero-rate cases
    show up during introductory periods or interest holidays.  If this
    behaviour changes, the model would incorrectly accelerate principal
    repayments, triggering false alarms in downstream comparisons with bank
    statements.
    """

    assert abs(pmt(0.0, 10, 1000.0) - 100.0) <= 1e-9


# ---------------------------------------------------------------------------
# Day-count conventions
# ---------------------------------------------------------------------------

def test_day_count_divisor_mapping():
    """Validate the mapping from string codes to numeric divisors.

    Why we care
    -----------
    Interest accrual depends on the chosen day-count convention.  A typo or
    regression in this mapping would quietly corrupt accrued interest values.
    The assertions cover the most common conventions we ingest from lender
    documentation.
    """

    assert day_count_divisor("ACT/365") == 365.0
    assert day_count_divisor("act/360") == 360.0
    assert day_count_divisor("30/360") == 360.0


# ---------------------------------------------------------------------------
# Property valuation helper
# ---------------------------------------------------------------------------

def test_property_value_fallback_growth(inputs):
    """Without explicit valuation blocks the property value should equal price.

    Why we care
    -----------
    `property_value_on` is the shared entry point for the valuation curve.
    Before any revaluation data is provided we expect the function to fall back
    to the purchase price.  This keeps the model aligned with LTV expectations
    and ensures that the absence of valuation blocks does not introduce a spurious
    drift.
    """

    pv = property_value_on(inputs, inputs.drawdown_date)
    assert abs(pv - float(inputs.property_price)) <= 1e-6

