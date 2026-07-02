# tests/test_profile_loader.py
"""Tests for the Phase 10 / S1 lender profile loader and rule resolver.

These lock the additive profile layer introduced in Phase 10 / S1: the committed
sample profile parses, rules resolve by anchor date (latest effective_from <=
anchor), the sample-vs-local fallback behaves, and the legacy inputs still parse
with no contracts and no profile so the refactor stays byte-identical. See
docs/lender_profile.md.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path

import pytest

from src.engine.profile import (
    LenderProfile,
    load_lender_profile,
    parse_lender_profile,
    resolve_lender_profile,
)
from src.engine.schema import load_inputs


REPO_ROOT = Path(__file__).resolve().parents[1]
LENDERS_DIR = REPO_ROOT / "data_sample" / "lenders"
SAMPLE_PROFILE = LENDERS_DIR / "sample_lender.yaml"
PROPERTY_A = REPO_ROOT / "data_sample" / "property_a" / "inputs.sample.yaml"


def test_sample_profile_loads_and_parses():
    """The committed sample profile loads into a typed LenderProfile."""
    prof = load_lender_profile(SAMPLE_PROFILE)
    assert isinstance(prof, LenderProfile)
    assert prof.lender_id == "sample_lender"
    assert len(prof.rule_versions) == 1
    assert prof.money_market_rates == []


def test_rule_resolution_by_anchor_date():
    """Resolving on an in-range date returns the locked BOI-style rule values."""
    prof = load_lender_profile(SAMPLE_PROFILE)
    rv = prof.rule_on(date(2025, 1, 1))
    assert rv.effective_from == date(2020, 1, 1)
    assert rv.payment_date_convention == "modified_following"
    assert rv.day_count == "ACT/365"
    # Overpayment cap: max(10% of monthly repayment, EUR 65), per payment.
    assert rv.overpayment_cap.basis == "percent_of_monthly_repayment"
    assert rv.overpayment_cap.percent == 0.10
    assert rv.overpayment_cap.floor_eur == 65.00
    assert rv.overpayment_cap.rolls_over is False
    # Breakage formula type is the BOI differential formula.
    assert rv.breakage.formula == "principal_x_rate_differential_x_remaining_years"


def test_rule_resolution_latest_effective_from_wins():
    """With several versions, the latest effective_from <= anchor is chosen."""
    prof = parse_lender_profile(
        {
            "lender_id": "test",
            "rule_versions": [
                {"effective_from": date(2020, 1, 1), "day_count": "ACT/365"},
                {"effective_from": date(2024, 6, 1), "day_count": "ACT/360"},
            ],
        }
    )
    assert prof.rule_on(date(2024, 5, 31)).day_count == "ACT/365"
    assert prof.rule_on(date(2024, 6, 1)).day_count == "ACT/360"
    assert prof.rule_on(date(2030, 1, 1)).day_count == "ACT/360"


def test_rule_before_first_version_raises():
    """An anchor before every version is a hard error, not a silent guess."""
    prof = load_lender_profile(SAMPLE_PROFILE)
    with pytest.raises(ValueError):
        prof.rule_on(date(2019, 12, 31))


def test_money_market_series_empty_returns_none():
    """The sample publishes no market rates, so breakage is not computable."""
    prof = load_lender_profile(SAMPLE_PROFILE)
    assert prof.money_market_on(date(2025, 5, 28)) is None


def test_money_market_resolution_by_quote_date():
    """Money-market rates resolve on the latest as_of <= the quote date."""
    prof = parse_lender_profile(
        {
            "lender_id": "test",
            "rule_versions": [{"effective_from": date(2020, 1, 1)}],
            "money_market_rates": [
                {"as_of": date(2025, 1, 1), "funding_rate": 0.030, "deposit_rate": 0.020},
                {"as_of": date(2025, 6, 1), "funding_rate": 0.035, "deposit_rate": 0.025},
            ],
        }
    )
    assert prof.money_market_on(date(2025, 5, 1)).funding_rate == 0.030
    assert prof.money_market_on(date(2025, 6, 1)).deposit_rate == 0.025
    assert prof.money_market_on(date(2019, 1, 1)) is None


def test_resolve_prefers_local_over_sample(tmp_path):
    """resolve_lender_profile uses the sample, then a local file when it appears."""
    (tmp_path / "sample_lender.yaml").write_text(SAMPLE_PROFILE.read_text())
    prof = resolve_lender_profile("boi", tmp_path)
    assert prof.lender_id == "sample_lender"
    (tmp_path / "boi.local.yaml").write_text(
        "lender_id: boi\n"
        "rule_versions:\n"
        "  - effective_from: 2020-01-01\n"
        "    day_count: ACT/365\n"
    )
    prof2 = resolve_lender_profile("boi", tmp_path)
    assert prof2.lender_id == "boi"


def test_resolve_missing_profile_raises(tmp_path):
    """No lender file and no sample is a hard error."""
    with pytest.raises(FileNotFoundError):
        resolve_lender_profile("boi", tmp_path)


def test_profile_with_no_versions_rejected():
    """A profile that declares no rule_versions cannot answer a query."""
    with pytest.raises(ValueError):
        parse_lender_profile({"lender_id": "empty", "rule_versions": []})


def test_legacy_inputs_parse_additively_no_contracts():
    """The legacy Property A sample parses with no contracts and no profile.

    This is the byte-identical guarantee for S1: a file with no ``contracts:``
    key and no ``lender`` leaves the new fields empty, so nothing the engine
    reads changes.
    """
    inputs = load_inputs(PROPERTY_A)
    assert inputs.contracts == []
    assert inputs.lender is None
    assert inputs.loan_v2 is None
    assert inputs.profile is None


def test_inputs_is_frozen_and_copy_clones():
    """Inputs is immutable; .copy()/.clone() return independent instances."""
    inputs = load_inputs(PROPERTY_A)
    with pytest.raises(FrozenInstanceError):
        inputs.overpayment_cap_pct = 0.5  # type: ignore[misc]
    clone = inputs.copy(overpayment_cap_pct=0.25)
    assert clone.overpayment_cap_pct == 0.25
    assert inputs.overpayment_cap_pct == 0.10
    assert clone is not inputs
    clone2 = inputs.clone(merge_extra_mode="false")
    assert clone2.merge_extra_mode == "false"