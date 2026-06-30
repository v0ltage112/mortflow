# tests/test_run_engine_characterization.py
"""Characterization test for run_engine against the Property A sample data.

Finance-readable summary
------------------------
This test runs the engine end to end on the bundled Property A sample and locks
the three things the rest of the business relies on: the Monthly schedule, the
Reconcile sheet, and the daily Events log. It checks the exact set of columns,
the number of rows, and a handful of known figures (the first month's interest,
the drawdown-month property value, the first reconciliation line). If a future
refactor changes any of these, the engine's reported numbers have moved and the
test fails on purpose, which is the safety net for the Phase 5 restructuring.

Technical summary
-----------------
Loads inputs/actuals from data_sample/property_a, runs run_engine in-process
(no CLI / subprocess), and asserts column sets, row counts, representative cell
values to 2 decimal places, and a cross-table interest-consistency invariant.
The pinned figures were verified against the committed golden reconcile fixture.
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


@pytest.fixture(scope="module")
def engine_result():
    """Run the engine once on the Property A sample and share the three tables."""
    inputs = load_inputs(INPUTS_PATH)
    actuals = load_actuals(ACTUALS_PATH)
    monthly, reconcile, events = run_engine(inputs, actuals)
    return monthly, reconcile, events


def _row_by_ym(df: pd.DataFrame, ym: int) -> pd.Series:
    """Return the single monthly row for a YYYYMM key (fails if absent/duplicated)."""
    hit = df.loc[df["ym"] == ym]
    assert len(hit) == 1, f"expected exactly one monthly row for {ym}, got {len(hit)}"
    return hit.iloc[0]


def test_run_engine_returns_three_dataframes(engine_result):
    """run_engine must always return the (monthly, reconcile, events) triple."""
    monthly, reconcile, events = engine_result
    assert isinstance(monthly, pd.DataFrame)
    assert isinstance(reconcile, pd.DataFrame)
    assert isinstance(events, pd.DataFrame)


def test_monthly_columns_and_rowcount(engine_result):
    """Lock the Monthly schedule's column set and the full modelling horizon."""
    monthly, _, _ = engine_result
    expected_cols = {
        "ym", "month_start", "payment_date",
        # Phase 7 / S4: final attribution vocabulary (payment_amount and
        # extra_amount retired; lump_amount -> lump, payment_unattributed ->
        # difference, contractual_payment -> contractual).
        "contractual", "overpayment", "lump", "total_paid", "difference",
        "interest_used", "principal_paid", "annual_rate",
        "bank_posted_interest_present", "posting_date", "posting_year",
        "model_eom_balance", "bank_eom_running_balance",
        "eom_diff_model_minus_bank", "property_value", "ltv_model_eom",
        "ltv_bank_eom",
        "overpayment_mismatch",
}
    assert set(monthly.columns) == expected_cols
    # Drawdown month 2024-03 through modelling end 2059-04 inclusive = 422 months.
    assert len(monthly) == 422


def test_reconcile_columns_and_rowcount(engine_result):
    """Lock the Reconcile sheet's column set and the reconciled bank lines."""
    _, reconcile, _ = engine_result
    expected_cols = {
        "bank_date", "type", "amount", "bank_running_balance", "ym",
        "model_amount", "model_balance", "diff_model_minus_bank",
        "ok_within_1c", "ok_within_abs_eur", "ok_label", "ok_reason",
    }
    assert set(reconcile.columns) == expected_cols
    # The sample actuals carry 39 Payment/Interest lines (the Drawdown row is excluded).
    assert len(reconcile) == 39


def test_events_columns_and_nonempty(engine_result):
    """Lock the Events log's column set and that the daily walk produced rows."""
    _, _, events = engine_result
    expected_cols = {
        "date", "kind", "amount", "balance", "property_value",
        "ltv_after_event", "ym",
    }
    assert set(events.columns) == expected_cols
    assert len(events) > 0


def test_first_month_representative_cells(engine_result):
    """Pin the drawdown month (2024-03): interest, payment, principal, rate, value."""
    monthly, _, _ = engine_result
    first = _row_by_ym(monthly, 202403)
    # March 2024 carries the actual interest posting of 297.00 and no payment yet.
    assert round(float(first["interest_used"]), 2) == 297.00
    assert round(float(first["contractual"]), 2) == 0.00
    assert round(float(first["principal_paid"]), 2) == 0.00
    assert float(first["annual_rate"]) == 0.0365
    # On the drawdown month-end no growth has accrued yet, so value == purchase price.
    assert round(float(first["property_value"]), 2) == 550000.00


def test_first_reconcile_line(engine_result):
    """Pin the first reconciliation line (2024-03-28 Interest) against the bank."""
    _, reconcile, _ = engine_result
    first = reconcile.sort_values("bank_date").iloc[0]
    assert str(first["type"]) == "Interest"
    assert round(float(first["model_amount"]), 2) == 297.00
    assert round(float(first["model_balance"]), 2) == 495297.00
    assert abs(float(first["diff_model_minus_bank"])) < 0.005


def test_first_event_is_interest_posting(engine_result):
    """The first modelled event is the 2024-03-28 interest posting of 297.00."""
    _, _, events = engine_result
    first = events.sort_values(["date"]).iloc[0]
    assert str(first["kind"]) == "Interest"
    assert round(float(first["amount"]), 2) == 297.00
    assert round(float(first["balance"]), 2) == 495297.00


def test_interest_consistency_monthly_vs_events(engine_result):
    """Total monthly interest must equal the sum of Interest events (to the cent)."""
    monthly, _, events = engine_result
    monthly_total = round(float(monthly["interest_used"].sum()), 2)
    events_total = round(
        float(events.loc[events["kind"] == "Interest", "amount"].sum()), 2
    )
    assert abs(monthly_total - events_total) < 0.01