# tests/test_attribution_characterization.py
"""Characterization snapshot of the Monthly schedule after Phase 7 / S3 attribution.

Finance-readable summary
------------------------
Phase 7 / S3 introduced the payment attribution split (Contractual /
Overpayment / Lump / Difference) on top of the Monthly schedule. This file was
the pre-attribution snapshot; S3 re-baselines it to photograph the new,
agreed-validated behaviour so any future drift is deliberate and visible:

* it locks the exact set of Monthly columns now that the four attribution
  columns have landed,
* it confirms the attribution columns are present (the pre-S3 "none yet" guard
  is retired on purpose),
* it pins the conservation identity: contractual + overpayment + lump +
  difference equals the full debit, to the cent,
* it pins how principal is still derived (total inflow minus interest, floored
  at zero), unchanged by the relabelling,
* it pins a few known Property A figures (the modelling horizon and the drawdown
  month, now including the zeroed attribution cells).

Technical summary
-----------------
Runs run_engine in-process on the bundled data_sample/property_a sample (no CLI
/ subprocess), then asserts the post-S3 Monthly column set, the presence of the
attribution columns, the conservation identity, the unchanged principal
identity, representative cells, and the monthly-vs-events interest invariant. The
conserved figures match the committed golden fixtures; only the split columns
are new this session.
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

# The Monthly schedule columns after Phase 7 / S3: the S2 baseline set plus the
# four attribution columns the agreed-terms split introduces. This is the
# snapshot the next session must re-baseline if it changes the column set.
ATTRIBUTION_MONTHLY_COLS = {
    "ym", "month_start", "payment_date", "payment_amount", "extra_amount",
    "lump_amount", "contractual_payment", "interest_used", "principal_paid", "annual_rate",
    "bank_posted_interest_present", "posting_date", "posting_year",
    "model_eom_balance", "bank_eom_running_balance",
    "eom_diff_model_minus_bank", "property_value", "ltv_model_eom",
    "ltv_bank_eom",
    # Phase 7 / S3: the principled attribution split and its reconciliation flag.
    "total_paid", "overpayment", "payment_unattributed", "overpayment_mismatch",
}

# The attribution columns introduced by S3, called out so the presence check
# reads clearly and the retired "none yet" guard has an explicit replacement.
ATTRIBUTION_COLS = {
    "total_paid", "overpayment", "payment_unattributed", "overpayment_mismatch",
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


def test_monthly_columns_are_the_attribution_set(monthly: pd.DataFrame) -> None:
    """Lock the post-S3 Monthly column set exactly (the re-baselined snapshot)."""
    # Exact equality, not a subset: a new or dropped column must trip this.
    assert set(monthly.columns) == ATTRIBUTION_MONTHLY_COLS


def test_attribution_columns_present(monthly: pd.DataFrame) -> None:
    """The S3 attribution columns now exist (pre-S3 'none yet' guard retired)."""
    missing = ATTRIBUTION_COLS - set(monthly.columns)
    assert not missing, f"missing attribution column(s): {sorted(missing)}"


def test_conservation_identity(monthly: pd.DataFrame) -> None:
    """contractual + overpayment + lump + difference == total_paid, to the cent."""
    recon = (
        monthly["contractual_payment"]
        + monthly["overpayment"]
        + monthly["lump_amount"]
        + monthly["payment_unattributed"]
    )
    assert (recon - monthly["total_paid"]).abs().max() < MONEY_ATOL


def test_current_principal_split_identity(monthly: pd.DataFrame) -> None:
    """Principal is still total inflow minus interest, floored at zero.

    The attribution relabels how the debit is described; it does not change how
    principal is derived. Pinning the original identity proves the conserved
    quantities did not move when the split columns were added.
    """
    inflow = monthly["payment_amount"] + monthly["extra_amount"] + monthly["lump_amount"]
    expected_principal = (inflow - monthly["interest_used"]).clip(lower=0.0)
    gap = (monthly["principal_paid"] - expected_principal).abs()
    assert gap.max() < MONEY_ATOL


def test_representative_property_a_cells(monthly: pd.DataFrame) -> None:
    """Pin the modelling horizon and the drawdown month for Property A."""
    # Drawdown month 2024-03 through modelling end 2059-04 inclusive = 422 months.
    assert len(monthly) == 422
    march = monthly.loc[monthly["ym"] == 202403]
    assert len(march) == 1, "expected exactly one Monthly row for 2024-03"
    row = march.iloc[0]
    # The drawdown month carries the 297.00 interest posting and no instalment yet.
    assert round(float(row["interest_used"]), 2) == 297.00
    assert round(float(row["payment_amount"]), 2) == 0.00
    assert round(float(row["extra_amount"]), 2) == 0.00
    assert round(float(row["lump_amount"]), 2) == 0.00
    assert round(float(row["principal_paid"]), 2) == 0.00
    # With no instalment that month, every attribution leg is zero and unflagged.
    assert round(float(row["total_paid"]), 2) == 0.00
    assert round(float(row["overpayment"]), 2) == 0.00
    assert round(float(row["payment_unattributed"]), 2) == 0.00
    assert bool(row["overpayment_mismatch"]) is False


def test_monthly_interest_matches_events(engine_tables) -> None:
    """Total monthly interest must equal the sum of Interest events, to the cent."""
    monthly_df, _reconcile, events = engine_tables
    monthly_total = round(float(monthly_df["interest_used"].sum()), 2)
    events_total = round(
        float(events.loc[events["kind"] == "Interest", "amount"].sum()), 2
    )
    # A drift here means the monthly roll-up and the daily walk disagree.
    assert abs(monthly_total - events_total) < 0.01