# tests/test_attribution_characterization.py
"""Characterization snapshot of the Monthly schedule before Phase 7 attribution.

Finance-readable summary
------------------------
Phase 7 adds a payment attribution split (Contractual / Overpayment / Lump /
Difference) on top of today's Monthly schedule. Before changing anything, this
test photographs the current behaviour so the change in S3 is deliberate and
visible:

* it locks the exact set of Monthly columns as they stand today,
* it confirms none of the future attribution columns exist yet,
* it pins how money is split today: each month's principal is whatever is left
  of (payment + extra + lump) after that month's interest, floored at zero,
* it pins a few known Property A figures (the modelling horizon and the
  drawdown month).

When S3 introduces the attribution columns this test fails on purpose, which is
the signal to re-baseline the snapshot against the new, agreed split.

Technical summary
-----------------
Runs run_engine in-process on the bundled data_sample/property_a sample (no CLI
/ subprocess), then asserts the Monthly column set, the absence of the planned
S3 columns, the current principal identity row by row, representative cells, and
the monthly-vs-events interest invariant. Figures match the committed golden
fixtures and the existing run_engine characterization test.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.engine import load_inputs, load_actuals, run_engine


# Repository root = two levels up from this test file (tests/ -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = REPO_ROOT / "data_sample" / "property_a"
INPUTS_PATH = SAMPLE_DIR / "inputs.sample.yaml"
ACTUALS_PATH = SAMPLE_DIR / "actuals.sample.csv"

# Half a cent: two monetary values that agree to 2dp never differ by more.
MONEY_ATOL = 0.005

# The Monthly schedule columns as they stand today, before any attribution
# split is added. This is the snapshot S3 will deliberately break.
PRE_ATTRIBUTION_MONTHLY_COLS = {
    "ym", "month_start", "payment_date", "payment_amount", "extra_amount",
    "lump_amount", "interest_used", "principal_paid", "annual_rate",
    "bank_posted_interest_present", "posting_date", "posting_year",
    "model_eom_balance", "bank_eom_running_balance",
    "eom_diff_model_minus_bank", "property_value", "ltv_model_eom",
    "ltv_bank_eom",
}

# Column names Phase 7 / S3 is expected to introduce for the attribution split.
# None exist today; this set documents the intended additions and guards against
# one slipping in before the agreed S3 change.
FUTURE_ATTRIBUTION_COLS = {
    "contractual", "overpayment", "payment_unattributed", "total_paid",
    "difference",
}


@pytest.fixture(scope="module")
def engine_tables():
    """Run the engine once on the Property A sample and share the three tables."""
    inputs = load_inputs(INPUTS_PATH)            # parse the agreed YAML config
    actuals = load_actuals(ACTUALS_PATH)         # load the real bank statement rows
    return run_engine(inputs, actuals)


@pytest.fixture(scope="module")
def monthly(engine_tables) -> pd.DataFrame:
    """Return just the Monthly schedule for the column and split assertions."""
    monthly_df, _reconcile, _events = engine_tables
    return monthly_df


def test_monthly_columns_are_the_pre_attribution_set(monthly: pd.DataFrame) -> None:
    """Lock today's Monthly column set exactly (the pre-attribution snapshot)."""
    # Exact equality, not a subset: a new or dropped column must trip this.
    assert set(monthly.columns) == PRE_ATTRIBUTION_MONTHLY_COLS


def test_no_attribution_columns_yet(monthly: pd.DataFrame) -> None:
    """Confirm none of the planned S3 attribution columns exist today."""
    present = set(monthly.columns)
    # Any overlap means an attribution column landed before the agreed S3 change.
    leaked = present & FUTURE_ATTRIBUTION_COLS
    assert not leaked, f"unexpected attribution column(s) already present: {sorted(leaked)}"


def test_current_principal_split_identity(monthly: pd.DataFrame) -> None:
    """Pin how money is split today, month by month, before attribution.

    Today the engine has no contractual / overpayment / lump split: each month
    it takes total inflow (payment + extra + lump), removes that month's
    interest, and whatever remains (never below zero) is principal. This is the
    behaviour S3 replaces with the agreed attribution, so locking it here makes
    that change show up loudly.
    """
    inflow = monthly["payment_amount"] + monthly["extra_amount"] + monthly["lump_amount"]
    # The current rule, lifted from monthly.build_monthly_schedule.
    expected_principal = (inflow - monthly["interest_used"]).clip(lower=0.0)
    # Compare row by row to the cent; the largest drift must stay under half a cent.
    gap = (monthly["principal_paid"] - expected_principal).abs()
    assert gap.max() < MONEY_ATOL


def test_representative_property_a_cells(monthly: pd.DataFrame) -> None:
    """Pin the modelling horizon and the drawdown month for Property A."""
    # Drawdown month 2024-03 through modelling end 2059-04 inclusive = 422 months.
    assert len(monthly) == 422
    # The drawdown month carries the 297.00 interest posting and no instalment yet.
    march = monthly.loc[monthly["ym"] == 202403]
    assert len(march) == 1, "expected exactly one Monthly row for 2024-03"
    row = march.iloc[0]
    assert round(float(row["interest_used"]), 2) == 297.00
    assert round(float(row["payment_amount"]), 2) == 0.00
    assert round(float(row["extra_amount"]), 2) == 0.00
    assert round(float(row["lump_amount"]), 2) == 0.00
    assert round(float(row["principal_paid"]), 2) == 0.00


def test_monthly_interest_matches_events(engine_tables) -> None:
    """Total monthly interest must equal the sum of Interest events, to the cent."""
    monthly_df, _reconcile, events = engine_tables
    monthly_total = round(float(monthly_df["interest_used"].sum()), 2)
    events_total = round(
        float(events.loc[events["kind"] == "Interest", "amount"].sum()), 2
    )
    # A drift here means the monthly roll-up and the daily walk disagree.
    assert abs(monthly_total - events_total) < 0.01