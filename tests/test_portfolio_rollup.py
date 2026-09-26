"""Tests for the portfolio rollup: locked columns, currency tagging, and the
per-currency totals file.

Phase 11 / S3 extends the S2 version for two new rollup columns (currency,
native_value) and the new portfolio_totals_by_currency.csv. The rollup
fixture below returns both artefacts from one pipeline run, so every test
that used to read the summary dataframe directly now reads rollup.summary.

Phase 12 / S3 extends the locked column set again for the overpayment cap:
three additive rollup columns (overpayment_cap_allowance,
overpayment_cap_headroom, overpayment_cap_flag) land between
current_overpayment and total_overpaid_to_date, moving the lock from 18 to 21
columns. The cap columns are additive only; no existing column moved or changed
meaning.
"""

from __future__ import annotations

from dataclasses import dataclass
import sys
from pathlib import Path

import pandas as pd
import pytest

import tools.portfolio as portfolio


# Locked column order (Phase 8 / S4, extended by S5's as_of_date, Phase 11 / S3's
# currency + native_value, and Phase 12 / S3's three overpayment cap columns). A
# test failure here means a column was added, removed, or reordered without
# updating this lock deliberately.
EXPECTED_PORTFOLIO_COLUMNS = [
    "as_of_date",
    "property_name", "property_kind", "tax_enabled", "currency",
    "current_balance", "property_value", "native_value", "ltv", "current_annual_rate",
    "contractual_payment", "current_overpayment",
    # Phase 12 / S3: the overpayment cap trio sits with the overpayment figures
    # it qualifies, before the cumulative total-to-date column.
    "overpayment_cap_allowance", "overpayment_cap_headroom", "overpayment_cap_flag",
    "total_overpaid_to_date",
    "total_difference", "overpayment_mismatch_months",
    "payoff_date", "current_year_interest", "tax_deductible_interest",
]


@dataclass
class RollupResult:
    """The two artefacts a single portfolio run produces: the row-per-property
    summary and the row-per-currency totals.
    """

    summary: pd.DataFrame
    totals_by_currency: pd.DataFrame


@pytest.fixture(scope="module")
def rollup(tmp_path_factory) -> RollupResult:
    """Run the sample portfolio once and load both output CSVs.

    Module-scoped so the comparatively slow engine run happens once for every
    test in this file, matching the module's own portfolio.yaml (Property A
    and Property C enabled). A module-scoped fixture cannot request the
    function-scoped monkeypatch fixture, so sys.argv is patched through
    pytest's MonkeyPatch context manager instead.
    """
    out_dir = tmp_path_factory.mktemp("portfolio_rollup")
    manifest = Path(__file__).resolve().parent.parent / "data_sample" / "portfolio.yaml"
    argv = ["tools/portfolio.py", "--portfolio", str(manifest), "--out", str(out_dir)]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sys, "argv", argv)
        portfolio.main()
    csv_dir = out_dir / "csv"
    summary = pd.read_csv(csv_dir / "portfolio_summary.csv")
    totals = pd.read_csv(csv_dir / "portfolio_totals_by_currency.csv")
    return RollupResult(summary=summary, totals_by_currency=totals)


def test_portfolio_summary_has_locked_columns(rollup):
    """The summary CSV has exactly the locked columns, in the locked order."""
    assert list(rollup.summary.columns) == EXPECTED_PORTFOLIO_COLUMNS


def test_rollup_row_is_populated_and_sane(rollup):
    """Property A (euro, mortgage-bearing) reports sane values on every locked column."""
    row = rollup.summary.loc[rollup.summary["property_name"] == "Property A"].iloc[0]
    assert row["currency"] == "EUR"
    # A euro property's native figure is the same number in both columns.
    assert row["native_value"] == row["property_value"]
    assert row["current_balance"] > 0
    assert 0 <= row["ltv"] <= 1
    assert pd.notna(row["payoff_date"])


def test_rollup_property_c_is_valuation_only(rollup):
    """Property C (PKR, no mortgage) has its loan columns blank and its value
    columns split correctly: native_value populated, property_value blank.

    This is the permanent shape, not an interim guard: property_value stays
    a euro-only column, so a PKR figure never lands there.
    """
    row = rollup.summary.loc[rollup.summary["property_name"] == "Property C"].iloc[0]
    assert row["currency"] == "PKR"
    assert pd.notna(row["native_value"])
    assert row["native_value"] > 0
    assert pd.isna(row["property_value"])
    assert pd.isna(row["current_balance"])
    assert pd.isna(row["payoff_date"])


def test_valuation_only_as_of_is_config_driven_not_today():
    """A valuation-only row's as-of date comes from config, never the wall clock.

    Regression guard for BACKLOG-001. The rollup previously used
    ``date.today()`` for a valuation-only property, so the locked
    ``portfolio_summary.csv`` fixture drifted every day and the golden master
    failed as soon as the calendar moved past the capture date. The date must
    now be derived from the property's own config (``valuation.as_of_date``,
    else ``modelling.end_date``), so the output is reproducible on any day.
    """
    import datetime as _dt

    from tools.portfolio import _derive_valuation_as_of

    inputs_path = (
        Path(__file__).resolve().parent.parent
        / "data_sample"
        / "property_c"
        / "inputs.sample.yaml"
    )
    as_of = _derive_valuation_as_of(inputs_path)
    # The sample pins an explicit date, so the result is that exact date.
    assert as_of == _dt.date(2026, 7, 17)
    # And it is emphatically not "today", which is what made the fixture drift.
    assert as_of != _dt.date.today()


def test_valuation_only_as_of_falls_back_to_modelling_end(tmp_path):
    """Without ``valuation.as_of_date`` the as-of falls back to ``modelling.end_date``.

    Proves the deterministic fallback path, so a config that omits the explicit
    date still produces a reproducible rollup rather than reaching for the clock.
    """
    import datetime as _dt

    from tools.portfolio import _derive_valuation_as_of

    cfg = tmp_path / "inputs.yaml"
    cfg.write_text(
        "valuation:\n"
        "  base_date: 2020-01-01\n"
        "  base_value: 1000000\n"
        "  growth_pa: 0.03\n"
        "modelling:\n"
        "  end_date: 2040-06-01\n",
        encoding="utf-8",
    )
    assert _derive_valuation_as_of(cfg) == _dt.date(2040, 6, 1)


def test_currency_totals_keep_eur_and_pkr_separate(rollup):
    """The per-currency totals file has one row per currency, and each total
    is exactly the sum of that currency's own native_value values.

    Grouping before summing is what proves a currency never leaks into the
    other's aggregate: computing the two totals independently from the
    summary and comparing them against the totals file closes that loop.
    """
    totals = rollup.totals_by_currency
    assert set(totals["currency"]) == {"EUR", "PKR"}
    eur_total = totals.loc[totals["currency"] == "EUR"].iloc[0]
    pkr_total = totals.loc[totals["currency"] == "PKR"].iloc[0]
    eur_rows = rollup.summary.loc[rollup.summary["currency"] == "EUR"]
    pkr_rows = rollup.summary.loc[rollup.summary["currency"] == "PKR"]
    assert eur_total["property_count"] == len(eur_rows)
    assert pkr_total["property_count"] == len(pkr_rows)
    assert eur_total["total_native_value"] == pytest.approx(eur_rows["native_value"].sum())
    assert pkr_total["total_native_value"] == pytest.approx(pkr_rows["native_value"].sum())