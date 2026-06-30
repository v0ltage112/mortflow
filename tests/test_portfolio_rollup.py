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
the locked columns, in order, and that the single sample row is genuinely
populated and sane, so a silently dropped column fails loudly.

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


# The locked final column order for the rebuilt rollup (Phase 8 / S4). This is
# the contract the runner writes and the order a reviewer reads left to right.
EXPECTED_PORTFOLIO_COLUMNS = [
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


def test_rollup_single_sample_row(rollup: pd.DataFrame) -> None:
    """Only Property A is enabled in the sample portfolio, so there is one row."""
    assert len(rollup) == 1, f"expected exactly one rollup row, got {len(rollup)}"
    assert rollup.iloc[0]["property_name"] == "Property A"


def test_rollup_row_is_populated_and_sane(rollup: pd.DataFrame) -> None:
    """Every promised column is populated and within a sane range for Property A.

    This is the heart of the S4 fix: before the rebuild several columns were
    silently dropped. Rather than pin exact euro amounts (which an S5 fixture
    re-baseline would move), this asserts each figure is present and plausible,
    plus the one fully deterministic value: the as-of date falls inside the first
    fixed-rate window, so the current annual rate must be 3.65%.
    """
    row = rollup.iloc[0]

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