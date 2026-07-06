# tests/test_cap_breakage_from_profile.py
"""Tests for the Phase 10 / S3 profile-derived overpayment cap and breakage.

These lock the retirement of the scalar ``overpayment_cap_pct`` and its
replacement by profile-derived resolvers:

* ``resolve_overpayment_cap_allowance`` / ``overpayment_cap_for_contract`` return
  max(percent of the monthly instalment, EUR floor) using the rule in force on
  the contract's start_date (LP4/LP7), and None when unresolvable.
* ``resolve_breakage_reference`` returns the catalogued formula and flags the
  charge \"not computable\" when the external R%/R1% money-market rates are absent
  (LP5/LP6).
* The strict-baseline sanitiser strips the new per-contract standing_overpayment
  and the lump_sums overlay so a strict baseline stays contract-only.

None of these figures is consumed for an output number, so the golden master
stays byte-identical (see test_golden_master.py). See docs/lender_profile.md and
docs/contract_data_model.md Section B.
"""

from __future__ import annotations

from datetime import date

from src.engine.profile import parse_lender_profile
from src.engine.schema import (
    BreakageReference,
    Contract,
    overpayment_cap_for_contract,
    resolve_breakage_reference,
    resolve_overpayment_cap_allowance,
)
from tools.baseline import _sanitize_for_strict_baseline


def _sample_profile():
    """A BOI-style profile: 10% / EUR 65 cap, differential breakage, no rates."""
    return parse_lender_profile(
        {
            "lender_id": "sample_lender",
            "rule_versions": [
                {
                    "effective_from": date(2020, 1, 1),
                    "overpayment_cap": {
                        "basis": "percent_of_monthly_repayment",
                        "percent": 0.10,
                        "floor_eur": 65.00,
                        "rolls_over": False,
                    },
                    "breakage": {
                        "formula": "principal_x_rate_differential_x_remaining_years"
                    },
                    "payment_date_convention": "modified_following",
                    "day_count": "ACT/365",
                },
            ],
        }
    )


def _profile_with_market_rates():
    """The sample profile plus a dated R%/R1% money-market series."""
    return parse_lender_profile(
        {
            "lender_id": "sample_lender",
            "rule_versions": [
                {
                    "effective_from": date(2020, 1, 1),
                    "breakage": {
                        "formula": "principal_x_rate_differential_x_remaining_years"
                    },
                },
            ],
            "money_market_rates": [
                {"as_of": date(2025, 1, 1), "funding_rate": 0.030, "deposit_rate": 0.020},
            ],
        }
    )


# --------------------------- overpayment cap ---------------------------------

def test_cap_allowance_uses_percent_when_above_floor():
    """percent * instalment wins when it exceeds the euro floor."""
    prof = _sample_profile()
    # 10% of 2123.44 = 212.344, well above the EUR 65 floor.
    allowance = resolve_overpayment_cap_allowance(prof, 2123.44, date(2024, 3, 26))
    assert allowance is not None
    assert abs(allowance - 212.344) < 1e-9


def test_cap_allowance_uses_floor_when_percent_below():
    """The EUR floor wins when percent * instalment is smaller."""
    prof = _sample_profile()
    # 10% of 500 = 50, below the EUR 65 floor, so the floor applies.
    allowance = resolve_overpayment_cap_allowance(prof, 500.0, date(2024, 3, 26))
    assert allowance == 65.00


def test_cap_for_contract_anchors_on_start_date():
    """overpayment_cap_for_contract uses the contract instalment and start date."""
    prof = _sample_profile()
    contract = Contract(
        id="A1",
        start_date=date(2024, 3, 26),
        end_date=date(2028, 2, 29),
        rate=0.0365,
        instalment=2123.44,
    )
    allowance = overpayment_cap_for_contract(prof, contract)
    assert allowance is not None
    assert abs(allowance - 212.344) < 1e-9


def test_cap_allowance_none_when_unresolvable():
    """No profile, no instalment, or no anchor resolves to None (not zero)."""
    prof = _sample_profile()
    assert resolve_overpayment_cap_allowance(None, 2123.44, date(2024, 3, 26)) is None
    assert resolve_overpayment_cap_allowance(prof, None, date(2024, 3, 26)) is None
    assert resolve_overpayment_cap_allowance(prof, 2123.44, None) is None
    # A contract with no stated instalment has no monthly figure to take a % of.
    open_contract = Contract(id="A3", start_date=date(2032, 4, 1), rate=0.04, instalment=None)
    assert overpayment_cap_for_contract(prof, open_contract) is None


# --------------------------- breakage reference ------------------------------

def test_breakage_reference_not_computable_without_market_rates():
    """The sample publishes no R%/R1% rates, so breakage is not computable."""
    prof = _sample_profile()
    ref = resolve_breakage_reference(prof, date(2024, 3, 26), quote_date=date(2025, 5, 28))
    assert isinstance(ref, BreakageReference)
    assert ref.formula == "principal_x_rate_differential_x_remaining_years"
    assert ref.computable is False
    assert ref.funding_rate is None and ref.deposit_rate is None


def test_breakage_reference_computable_with_market_rates():
    """With R%/R1% present on the quote date the reference is computable."""
    prof = _profile_with_market_rates()
    ref = resolve_breakage_reference(prof, date(2024, 3, 26), quote_date=date(2025, 5, 28))
    assert ref is not None
    assert ref.computable is True
    assert ref.funding_rate == 0.030
    assert ref.deposit_rate == 0.020


def test_breakage_reference_none_without_profile_or_anchor():
    """No profile or no anchor resolves to None."""
    prof = _sample_profile()
    assert resolve_breakage_reference(None, date(2024, 3, 26)) is None
    assert resolve_breakage_reference(prof, None) is None


# --------------------------- strict-baseline sanitiser -----------------------

def test_sanitizer_strips_per_contract_standing_overpayment():
    """The new-schema per-contract standing_overpayment is removed for baseline."""
    cfg = {
        "loan": {
            "lender": "boi",
            "contracts": [
                {
                    "id": "A1",
                    "start_date": date(2024, 3, 26),
                    "rate": 0.0365,
                    "instalment": 2123.44,
                    "standing_overpayment": {
                        "amount": 200.0,
                        "start_date": date(2025, 7, 1),
                        "end_date": None,
                    },
                },
            ],
        },
        "lump_sums": [{"date": date(2026, 1, 1), "amount": 5000.0}],
        "overpay_rules": [{"start_month": 17, "amount": 200.0, "repeat": "monthly"}],
        "bank": {"merge_standing_extra_into_payment": True},
    }
    clean = _sanitize_for_strict_baseline(cfg)

    # The per-contract recurring extra is gone.
    assert "standing_overpayment" not in clean["loan"]["contracts"][0]
    # The overlays are cleared and merging is forced off.
    assert clean["lump_sums"] == []
    assert clean["overpay_rules"] == []
    assert clean["bank"]["merge_standing_extra_into_payment"] is False
    # The contract itself (rate, instalment) is left intact.
    assert clean["loan"]["contracts"][0]["instalment"] == 2123.44
    # The original dict is not mutated (deep copy).
    assert "standing_overpayment" in cfg["loan"]["contracts"][0]