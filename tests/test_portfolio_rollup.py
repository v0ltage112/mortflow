# tests/test_portfolio_rollup.py
"""Phase 8 / S4: pin the rebuilt portfolio rollup.

Finance-readable summary
------------------------
S4 rebuilt the one-look portfolio summary so every promised column is populated
and correctly sourced: the live position (current balance, property value, LTV,
current rate, contractual payment, current overpayment) read from the monthly
schedule at the as-of date, the agreed overpayment to date, the Phase 7
attribution health (total Difference and the count of mismatch months), the
current-year interest, the projected payoff date, and the Section 97
tax-deductible interest when rental tax is on. This test runs the real pipeline
against the bundled sample portfolio and checks that the rollup carries exactly
the locked columns, in order, and that each enabled row is genuinely populated
and sane, so a silently dropped column fails loudly.

Phase 8 / S5: the rollup gains an explicit ``as_of_date`` first column so the
snapshot date the whole row is taken at is visible. The locked column list below
moves from 15 to 16 columns, and the populated-row check also confirms the
as-of date reads as an ISO date.

Phase 11 / S1: Property B is now enabled in the sample portfolio, so the rollup
carries two rows (Property A and Property B). The row-count check expects both
enabled rows, and the populated-and-sane check selects the Property A row by
name (not by position) so it stays correct regardless of row order.

Phase 11 / S2: Property C (Paragon) is now enabled on the valuation-only path in
PKR, so the sample rollup carries three rows (Property A, Property B, Property
C). The row-count check expects all three enabled rows. Property C is owned
outright with no mortgage and reports in PKR, so its loan-driven columns are
empty and the interim currency guard in tools/portfolio.py holds its value out
of the euro ``property_value`` column (the currency-aware column lands in S3).
The Property A populated-and-sane check is unchanged: it selects Property A by
name, so it stays correct regardless of row count or order. A dedicated check
locks Property C's valuation-only shape.

Technical summary
-----------------
Runs tools.baseline then tools.portfolio against data_sample/portfolio.yaml into
a temp out dir (mirroring the golden-master and characterization invocations),
reads the produced csv/portfolio_summary.csv, and asserts the column contract
and a populated Property A row. It pins the column order exactly and otherwise
uses value ranges plus the deterministic fixed-window rate, so it survives an S5
fixture re-baseline while still catching an empty or mis-sourced column.
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest


# The locked final column order for the rebuilt rollup (Phase 8 / S4, extended in
# S5). This is the contract the runner writes and the order a reviewer reads left
# to right. Phase 8 / S5 adds as_of_date as the first column (15 -> 16), matching
# the runner's LOCKED_SUMMARY_COLUMNS and the characterization test.
EXPECTED_PORTFOLIO_COLUMNS = [
    "as_of_date",
    "property_name", "property_kind", "tax_enabled",
    "current_balance", "property_value", "ltv", "current_annual_rate",
    "contractual_payment", "current_overpayment", "total_overpaid_to_date",
    "total_difference", "overpayment_mismatch_months",
    "payoff_date", "current_year_interest", "tax_deductible_interest",
]


def _find_repo_root(start: Path) -> Path:
    """Return the repo root by walking up until tools/ and data_sample/ are found.

    Mirrors the resolver in the golden-master and characterization suites so all
    three agree on the root no matter how deep the test file sits.
    """
    for candidate in (start, *start.parents):
        if (candidate / "tools").is_dir() and (candidate / "data_sample").is_dir():
            return candidate
    raise RuntimeError(
        "Could not locate the mortflow repo root: no ancestor of "
        f"{start} contains both tools/ and data_sample/."
    )


REPO_ROOT = _find_repo_root(Path(__file__).resolve().parent)
DATA_SAMPLE = REPO_ROOT / "data_sample"
SAMPLE_PORTFOLIO = DATA_SAMPLE / "portfolio.yaml"

# Phase 8 / S3: the rollup CSV lives under a top-level csv/ subfolder.
CSV_SUBDIR = "csv"


def _run_pipeline(out_dir: Path) -> None:
    """Regenerate the rollup into out_dir via the real CLIs (baseline, portfolio).

    Mirrors the golden-master setup: the data and out roots are forced through
    the environment, UTF-8 stdio keeps the child's status lines encodable on
    every platform, and the bundled sample portfolio is the single input.
    """
    env = dict(os.environ)
    env["MORTGAGE_DATA_DIR"] = str(DATA_SAMPLE)
    env["MORTGAGE_OUT_DIR"] = str(out_dir)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    for module in ("tools.baseline", "tools.portfolio"):
        subprocess.run(
            [
                sys.executable, "-m", module,
                "--portfolio", str(SAMPLE_PORTFOLIO),
                "--out", str(out_dir),
            ],
            cwd=str(REPO_ROOT),  # repo root must be importable under -m
            env=env,
            check=True,  # raise immediately if either CLI exits non-zero
        )


@pytest.fixture(scope="module")
def rollup(tmp_path_factory: pytest.TempPathFactory) -> pd.DataFrame:
    """Run the sample pipeline once and return the rollup as a DataFrame."""
    out_dir = tmp_path_factory.mktemp("portfolio_rollup_s4")
    _run_pipeline(out_dir)
    csv_path = out_dir / CSV_SUBDIR / "portfolio_summary.csv"
    assert csv_path.exists(), f"portfolio_summary.csv was not produced at {csv_path}."
    return pd.read_csv(csv_path)


def test_rollup_columns_locked(rollup: pd.DataFrame) -> None:
    """The rollup has exactly the locked columns, in the locked order."""
    produced = list(rollup.columns)
    assert produced == EXPECTED_PORTFOLIO_COLUMNS, (
        "portfolio_summary.csv columns changed.\n"
        f"  Expected: {EXPECTED_PORTFOLIO_COLUMNS}\n"
        f"  Produced: {produced}\n"
        f"  Missing now:    {[c for c in EXPECTED_PORTFOLIO_COLUMNS if c not in produced] or 'none'}\n"
        f"  New/unexpected: {[c for c in produced if c not in EXPECTED_PORTFOLIO_COLUMNS] or 'none'}"
    )


def test_rollup_has_all_enabled_rows(rollup: pd.DataFrame) -> None:
    """Property A, B, and C are all enabled, so the rollup has three rows.

    Phase 11 / S1 enabled Property B, and Phase 11 / S2 enabled Property C
    (valuation-only, PKR) in the sample portfolio, so the rollup now carries
    exactly three rows. The check is on the set of property names rather than
    their order, because the row order is an implementation detail of the
    runner.
    """
    assert len(rollup) == 3, f"expected exactly three rollup rows, got {len(rollup)}"
    assert set(rollup["property_name"]) == {"Property A", "Property B", "Property C"}


def test_rollup_row_is_populated_and_sane(rollup: pd.DataFrame) -> None:
    """Every promised column is populated and within a sane range for Property A.

    This is the heart of the S4 fix: before the rebuild several columns were
    silently dropped. Rather than pin exact euro amounts (which an S5 fixture
    re-baseline would move), this asserts each figure is present and plausible,
    plus the one fully deterministic value: the as-of date falls inside the first
    fixed-rate window, so the current annual rate must be 3.65%.

    Phase 11 / S1: with Property B now in the rollup, the Property A row is
    selected explicitly by name so this check no longer depends on row order.
    """
    # Select the Property A row by name (Property B and C are also present).
    a_rows = rollup[rollup["property_name"] == "Property A"]
    assert len(a_rows) == 1, "expected exactly one Property A row in the rollup"
    row = a_rows.iloc[0]
    # Phase 8 / S5: the as-of date is now an explicit first column. For Property A
    # it is the deterministic mid-2026 snapshot date, so it reads as an ISO date
    # string (yyyy-mm-dd).
    assert isinstance(row["as_of_date"], str) and row["as_of_date"][:4].isdigit()
    # Rental tax is on for Property A.
    assert bool(row["tax_enabled"]) is True
    # Live position: a real outstanding balance against a real property value,
    # giving a loan-to-value strictly between 0 and 1.
    assert row["current_balance"] > 0.0
    assert row["property_value"] > 0.0
    assert 0.0 < row["ltv"] < 1.0
    assert row["current_balance"] < row["property_value"]
    # The as-of date (mid-2026) sits inside the first fixed-rate block (months 1
    # to 48 at 3.65%), so the current rate is deterministic.
    assert math.isclose(row["current_annual_rate"], 0.0365, abs_tol=1e-9)
    # Contractual instalment and overpayment are present and non-negative.
    assert row["contractual_payment"] > 0.0
    assert row["current_overpayment"] >= 0.0
    assert row["total_overpaid_to_date"] >= 0.0
    # Attribution health: a finite Difference and a non-negative whole-number
    # count of mismatch months.
    assert math.isfinite(row["total_difference"])
    assert row["overpayment_mismatch_months"] >= 0
    assert float(row["overpayment_mismatch_months"]).is_integer()
    # Projected payoff date is present and reads as an ISO date.
    assert isinstance(row["payoff_date"], str) and row["payoff_date"][:4].isdigit()
    # Current-year interest is a real positive figure.
    assert row["current_year_interest"] > 0.0
    # Property A has rental tax on, so the Section 97 deductible interest for the
    # current year is populated and positive.
    assert row["tax_deductible_interest"] > 0.0


def test_rollup_property_c_is_valuation_only(rollup: pd.DataFrame) -> None:
    """Property C is valuation-only (owned outright, PKR): euro live-position columns are blank.

    Phase 11 / S2 enabled Property C (Paragon) on the valuation-only path in
    PKR. It carries no mortgage, so the loan-driven columns are empty, and the
    interim currency guard in tools/portfolio.py holds its PKR value out of the
    euro ``property_value`` column so it never contaminates the euro aggregate.
    The real PKR value lives in Property C's own valuation output. This locks
    the interim S2 shape; S3 revisits ``property_value`` once the rollup is
    currency-aware.
    """
    c_rows = rollup[rollup["property_name"] == "Property C"]
    assert len(c_rows) == 1, "expected exactly one Property C row in the rollup"
    row = c_rows.iloc[0]
    # Owned outright, valuation-only: an owned-outright kind and no rental tax.
    assert str(row["property_kind"]) == "owned_outright"
    assert bool(row["tax_enabled"]) is False
    # The as-of date is still a real ISO date (the valuation snapshot date).
    assert isinstance(row["as_of_date"], str) and row["as_of_date"][:4].isdigit()
    # Interim currency guard: the euro property_value is intentionally blank for
    # a PKR property so it never enters the euro aggregate (the currency-aware
    # column arrives in S3).
    assert pd.isna(row["property_value"])
    # No mortgage means the loan-driven position columns are empty too.
    assert pd.isna(row["current_balance"])
    assert pd.isna(row["ltv"])
    assert pd.isna(row["current_annual_rate"])