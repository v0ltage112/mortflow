"""Valuation-only regression tests for Property C (PKR).

The owned-outright Property C sample has no mortgage, so it runs the engine's
valuation-only path: the model tracks what the apartment is worth over time in
rupees and writes nothing else (no loan schedule, no reconciliation, no tax).
These tests pin two things Phase 11 / S2 introduces:

1. The value series itself: it starts at the base value on the base date and
   grows at the configured annual rate, one row per month, and the loan,
   reconcile, and tax outputs are absent.
2. The interim currency guard in the portfolio rollup: a non-euro property must
   not drop its native value into the euro `property_value` column, so PKR never
   contaminates the euro aggregate before the S3 currency column lands.

Every figure here is checked against the bundled fictitious sample
(data_sample/property_c/inputs.sample.yaml), not real Property C values.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.engine import load_inputs
from src.engine.valuation_only import run_valuation_only
from tools.portfolio import _valuation_summary_row, _is_eur_currency


def _find_repo_root(start: Path) -> Path:
    """Return the repo root: the first ancestor holding tools/ and data_sample/."""
    for candidate in (start, *start.parents):
        if (candidate / "tools").is_dir() and (candidate / "data_sample").is_dir():
            return candidate
    raise RuntimeError(f"Could not locate the repo root above {start}.")


REPO_ROOT = _find_repo_root(Path(__file__).resolve().parent)
SAMPLE_C = REPO_ROOT / "data_sample" / "property_c" / "inputs.sample.yaml"

# The sample's fictitious anchor. Kept in step with inputs.sample.yaml; if the
# sample changes, update these three numbers too.
SAMPLE_BASE_VALUE = 10_000_000.0
SAMPLE_GROWTH_PA = 0.035
GROWTH_ATOL = 1.0  # rupee tolerance on the reproduced growth figure


@pytest.fixture(scope="module")
def valuation_run(tmp_path_factory: pytest.TempPathFactory):
    """Run the valuation-only path once for the sample C; return (out_dir, schedule).

    Running the real entry point (rather than hand-building a series) means this
    test also exercises the workbook writer, so a currency mask that cannot
    render PKR would surface here rather than silently passing.
    """
    out_dir = tmp_path_factory.mktemp("property_c_out")
    inputs = load_inputs(SAMPLE_C)
    schedule = run_valuation_only(inputs, SAMPLE_C, out_dir)
    return out_dir, schedule


def test_value_anchored_at_base_value(valuation_run) -> None:
    """The first modelled month equals the base value on the base date."""
    _out_dir, schedule = valuation_run
    assert not schedule.empty, "valuation-only run produced an empty series"
    first_value = float(schedule.iloc[0]["property_value"])
    # The series is anchored to the base value on the base date.
    assert abs(first_value - SAMPLE_BASE_VALUE) <= GROWTH_ATOL, (
        f"first value {first_value:,.2f} should equal the base value "
        f"{SAMPLE_BASE_VALUE:,.2f}"
    )


def test_value_grows_at_configured_rate(valuation_run) -> None:
    """Twelve months on, the value has compounded by one year of growth."""
    _out_dir, schedule = valuation_run
    # Need at least 13 monthly rows (month 0 plus a full year) to compare.
    assert len(schedule) > 12, "series too short to check one year of growth"
    base = float(schedule.iloc[0]["property_value"])
    after_year = float(schedule.iloc[12]["property_value"])
    expected = base * (1.0 + SAMPLE_GROWTH_PA)
    # Whole-month growth compounds monthly, so twelve months lands on the annual
    # factor within a rupee (a small relative tolerance covers rounding).
    assert abs(after_year - expected) <= max(GROWTH_ATOL, expected * 1e-6), (
        f"value after 12 months {after_year:,.2f} should be about "
        f"{expected:,.2f} (base grown by {SAMPLE_GROWTH_PA:.1%})"
    )


def test_value_series_is_non_decreasing(valuation_run) -> None:
    """A positive growth rate means the value never falls month to month."""
    _out_dir, schedule = valuation_run
    values = [float(v) for v in schedule["property_value"].tolist()]
    for earlier, later in zip(values, values[1:]):
        assert later >= earlier - GROWTH_ATOL, (
            "value series dipped despite a non-negative growth rate"
        )


def test_no_loan_reconcile_or_tax_outputs(valuation_run) -> None:
    """A no-mortgage property emits only the valuation output, nothing loan-like."""
    out_dir, _schedule = valuation_run
    # The valuation CSV is written under the csv/ sub-folder.
    assert (out_dir / "csv" / "valuation_schedule.csv").exists(), (
        "valuation_schedule.csv should be produced under csv/"
    )
    # None of the mortgage-path artefacts should exist for an owned-outright run.
    forbidden = [
        "schedule_monthly.csv",
        "reconcile.csv",
        "events_daily.csv",
        "tax_year.csv",
        "tax_audit.csv",
    ]
    for name in forbidden:
        assert not (out_dir / "csv" / name).exists(), (
            f"{name} should not exist for a valuation-only property"
        )
        assert not (out_dir / name).exists(), (
            f"{name} should not exist at the property root either"
        )


def _write_valuation_csv(csv_dir: Path, value: float) -> None:
    """Write a one-row valuation_schedule.csv so the rollup helper can read it."""
    csv_dir.mkdir(parents=True, exist_ok=True)
    with (csv_dir / "valuation_schedule.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["month_start", "ym", "property_value"])
        # A date on or before today so _valuation_summary_row selects this row.
        writer.writerow(["2020-01-01", "202001", f"{value:.2f}"])


def test_currency_guard_blanks_non_euro_value(tmp_path: Path) -> None:
    """A PKR property keeps its value out of the euro property_value column."""
    csv_dir = tmp_path / "csv"
    _write_valuation_csv(csv_dir, 10_000_000.0)
    row = _valuation_summary_row(csv_dir, "Property C", "owned_outright", False, "PKR")
    # The euro column must be absent/blank so a naive euro sum cannot pick it up.
    assert row.get("property_value") is None, (
        "a PKR property must not populate the euro property_value column"
    )
    # The descriptive columns are still present so the row exists on the rollup.
    assert row["property_name"] == "Property C"
    assert row["property_kind"] == "owned_outright"


def test_currency_guard_keeps_euro_value(tmp_path: Path) -> None:
    """A euro property still populates the euro property_value column as before."""
    csv_dir = tmp_path / "csv"
    _write_valuation_csv(csv_dir, 720_000.0)
    row = _valuation_summary_row(csv_dir, "Property EUR", "owned_outright", False, "EUR")
    assert row.get("property_value") == pytest.approx(720_000.0), (
        "a euro property should keep its value in the euro property_value column"
    )


def test_is_eur_currency_defaults_to_euro() -> None:
    """A missing or blank currency is treated as euro (the engine default)."""
    assert _is_eur_currency("EUR")
    assert _is_eur_currency(None)
    assert _is_eur_currency("")
    assert not _is_eur_currency("PKR")