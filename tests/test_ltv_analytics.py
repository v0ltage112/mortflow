"""Loan-to-value (LTV) regression tests.

These tests cover the valuation columns that underpin the downstream LTV
analytics.  Each test focuses on a different observable behaviour so that the
suite, taken as a whole, gives confidence that:

* monotone property-growth assumptions remain intact
* loan-to-value (LTV) ratios stay within plausible ranges
* the drawdown month is anchored to the purchase price

When any of these checks fail it normally signals a regression in how the
monthly engine populates valuation data, which in turn invalidates dashboards
and affordability metrics that are computed from the same series.
"""

# ---------------------------------------------------------------------------
# Growth behaviour
# ---------------------------------------------------------------------------

def test_property_value_monotone_growth(engine_outputs, inputs):
    """Property values should be non-decreasing when positive growth is assumed.

    Why we care
    -----------
    The engine projects property values forward using a deterministic growth
    rate.  A decrease would mean we either introduced rounding errors or
    accidentally applied a negative increment.  Such a regression would break
    all derivative metrics (e.g. projected equity, LTV curves), so we assert
    monotonicity with a tiny tolerance for floating point noise.
    """

    monthly, _, _ = engine_outputs
    pv = monthly["property_value"].dropna().tolist()

    # The valuation series must exist and contain at least one observation.
    assert pv, "property_value series is empty"

    # Validate pairwise monotonic growth.  We allow a 1e-6 slack to avoid false
    # failures caused by rounding differences across pandas / numpy versions.
    assert all(pv[i] <= pv[i + 1] + 1e-6 for i in range(len(pv) - 1)), "property_value should not decrease"


# ---------------------------------------------------------------------------
# LTV column sanity
# ---------------------------------------------------------------------------

def test_ltv_columns_present_and_reasonable(engine_outputs):
    """Ensure key loan-to-value columns exist and hold plausible numbers.

    Why we care
    -----------
    KPI dashboards and covenant monitoring rely on the `ltv_model_eom` series
    and the `ltv_after_event` field in the events table.  If these columns go
    missing or start emitting nonsense (negative or astronomically high ratios)
    we lose a critical guard-rail.  This test acts as an early warning for such
    schema or logic drift.
    """

    monthly, _, events = engine_outputs

    # --- Monthly sheet checks -------------------------------------------------
    for col in ("ltv_model_eom",):
        assert col in monthly.columns, f"Missing {col} in Monthly"
        vals = monthly[col].dropna()
        assert not vals.empty, f"{col} has no values"
        assert (vals >= 0).all(), f"{col} has negatives"
        assert (vals <= 2.0).all(), f"{col} has implausibly large values"

    # --- Events table checks --------------------------------------------------
    # The events stream should expose post-event LTV figures for scenario
    # analysis.  We mirror the same plausibility checks as for the monthly
    # table.
    assert "ltv_after_event" in events.columns, "Missing ltv_after_event in EventsDaily"
    ev = events["ltv_after_event"].dropna()
    assert not ev.empty, "ltv_after_event has no values"
    assert (ev >= 0).all(), "ltv_after_event has negatives"
    assert (ev <= 2.0).all(), "ltv_after_event has implausibly large values"


# ---------------------------------------------------------------------------
# Drawdown anchoring
# ---------------------------------------------------------------------------

def test_drawdown_property_value_equals_price(inputs, engine_outputs):
    """Anchor the valuation to the purchase price on the drawdown date.

    Why we care
    -----------
    The initial loan-to-value calculation assumes that property value equals
    the purchase price at drawdown.  If the engine drifts away from that
    invariant (e.g. due to an off-by-one month index) all historical LTV charts
    shift, misleading auditors and analysts.  The tolerance of ±€1 ensures we
    fail loudly if the anchor is lost while still tolerating cent-level rounding
    differences between libraries.
    """

    monthly, _, _ = engine_outputs

    # Find the monthly row that corresponds to the drawdown month; the table is
    # keyed by `ym` (YYYYMM).
    ym_dd = inputs.drawdown_date.year * 100 + inputs.drawdown_date.month
    row = monthly.loc[monthly["ym"] == ym_dd]
    assert not row.empty, "No Monthly row for the drawdown month"

    # Compare the stored property value against the configured purchase price.
    pv = float(row["property_value"].iloc[0])
    assert abs(pv - inputs.property_price) <= 1.0, f"Property value at drawdown deviates too much: {pv} vs {inputs.property_price}"
