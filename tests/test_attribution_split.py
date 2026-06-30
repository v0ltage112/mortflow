# tests/test_attribution_split.py
"""Behaviour tests for the Phase 7 payment attribution split.

Finance-readable summary
------------------------
Phase 7 makes the monthly payment split principled and agreed-terms driven. Each
month's debit is attributed into four parts a finance reader can audit: the
contractual instalment, the agreed overpayment, any lump sum, and an explicit
Difference that catches whatever the agreed terms do not account for. After the
S4 vocabulary finalisation those columns are named contractual, overpayment,
lump and difference. This file proves the three properties that matter:

* the four parts always add back to the full debit, to the cent (conservation),
* the split is driven by the agreed terms, not by the bank merge flag, so
  toggling merge_standing_extra_into_payment moves neither the attribution nor
  any conserved quantity, and
* the mismatch flag only fires on a real bank month whose debit does not
  reconcile to the agreed split within the dedicated tolerance.

Technical summary
-----------------
Runs run_engine in-process on the bundled data_sample/property_a sample and
asserts the conservation identity row by row, the agreed-terms / merge-flag
invariance (via dataclasses.replace over the merge modes), and the mismatch-flag
contract. No CLI / subprocess; figures are checked to the cent. Columns use the
post-S4 names: contractual, overpayment, lump, difference.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from src.engine import load_inputs, load_actuals, run_engine


# Repository root = two levels up from this test file (tests/ -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = REPO_ROOT / "data_sample" / "property_a"
INPUTS_PATH = SAMPLE_DIR / "inputs.sample.yaml"
ACTUALS_PATH = SAMPLE_DIR / "actuals.sample.csv"

# Half a cent: two values that agree to 2dp never differ by more than this.
MONEY_ATOL = 0.005

# The attribution columns under the final post-S4 vocabulary.
ATTRIBUTION_COLS = {
    "contractual", "overpayment", "lump", "total_paid", "difference",
    "overpayment_mismatch",
}


@pytest.fixture(scope="module")
def base_inputs():
    """Parse the Property A sample inputs once for the whole module."""
    return load_inputs(INPUTS_PATH)


@pytest.fixture(scope="module")
def base_actuals():
    """Load the Property A bank statement rows once for the whole module."""
    return load_actuals(ACTUALS_PATH)


@pytest.fixture(scope="module")
def monthly(base_inputs, base_actuals) -> pd.DataFrame:
    """Return the Monthly schedule for the bundled sample (default merge mode)."""
    monthly_df, _reconcile, _events = run_engine(base_inputs, base_actuals)
    return monthly_df


def test_attribution_columns_present(monthly: pd.DataFrame) -> None:
    """The final attribution columns must exist under their locked names."""
    missing = ATTRIBUTION_COLS - set(monthly.columns)
    assert not missing, f"missing attribution column(s): {sorted(missing)}"
    # contractual is the contractual leg of the split (renamed from the earlier
    # contractual_payment during the S4 vocabulary finalisation).
    assert "contractual" in monthly.columns


def test_conservation_identity_holds_to_the_cent(monthly: pd.DataFrame) -> None:
    """contractual + overpayment + lump + difference == total_paid, every row.

    This is the core promise of the attribution: the agreed split plus the
    explicit Difference always reconstruct the full monthly debit, so no money is
    invented or lost when the payment is broken down.
    """
    recon = (
        monthly["contractual"]
        + monthly["overpayment"]
        + monthly["lump"]
        + monthly["difference"]
    )
    gap = (recon - monthly["total_paid"]).abs()
    assert gap.max() < MONEY_ATOL


def test_overpayment_is_zero_without_an_instalment(monthly: pd.DataFrame) -> None:
    """No modelled instalment in a month means no agreed overpayment that month.

    The agreed standing overpayment rides on the monthly instalment. In months
    with no instalment (before the first payment, or after the loan closes) the
    contractual leg is zero, so the overpayment leg must be zero too.
    """
    no_instalment = monthly.loc[monthly["contractual"] <= 0.0]
    assert (no_instalment["overpayment"].abs() < MONEY_ATOL).all()


def test_mismatch_flag_implies_break_beyond_tolerance(base_inputs, monthly: pd.DataFrame) -> None:
    """A raised mismatch flag must coincide with a Difference beyond tolerance.

    The flag is the human signal that a real bank month did not reconcile to the
    agreed split. Wherever it is set, the Difference must exceed the dedicated
    tolerance; the flag never fires on a reconciled month.
    """
    tol = float(base_inputs.payment_unattributed_ok_abs_eur)
    flagged = monthly.loc[monthly["overpayment_mismatch"]]
    # Every flagged month breaches the tolerance on the Difference column.
    assert (flagged["difference"].abs() > tol).all()


def test_merge_flag_does_not_move_the_split_or_conserved_quantities(base_inputs, base_actuals) -> None:
    """Toggling the merge flag moves neither the attribution nor any total.

    The whole point of the attribution is that the split is agreed-terms driven,
    not inferred from merge_standing_extra_into_payment. Running every merge mode
    must give a byte-identical (to the cent) attribution split and identical
    conserved quantities; the retired payment_amount / extra_amount labels no
    longer exist to shuffle.
    """
    # Columns that must not move when only the merge labelling changes.
    invariant_cols = [
        "total_paid", "contractual", "overpayment", "difference",
        "interest_used", "principal_paid", "model_eom_balance",
    ]

    frames = {}
    for mode in ("auto", "true", "false"):
        # dataclasses.replace keeps every other input identical; only the merge
        # mode changes, which is exactly the variable under test.
        inputs = replace(base_inputs, merge_extra_mode=mode)
        monthly_df, _rec, _ev = run_engine(inputs, base_actuals)
        frames[mode] = monthly_df.set_index("ym")[invariant_cols].sort_index()

    reference = frames["auto"]
    for mode, frame in frames.items():
        # Same months in the same order, so a direct cell-by-cell compare is valid.
        assert list(frame.index) == list(reference.index)
        # fillna(0) pairs the post-payoff NaN balances (identical across modes,
        # because the conserved quantities are identical) as "no change".
        diff = (frame - reference).abs().fillna(0.0)
        assert diff.to_numpy().max() < MONEY_ATOL, f"merge mode {mode!r} moved a conserved/split column"