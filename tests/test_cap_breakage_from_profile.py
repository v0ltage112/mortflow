# tests/test_cap_breakage_from_profile.py
"""Tests for the profile-derived overpayment cap and breakage.

These lock the retirement of the scalar ``overpayment_cap_pct`` and its
replacement by profile-derived resolvers:

* ``resolve_overpayment_cap_allowance`` / ``overpayment_cap_for_contract`` return
  max(percent of the monthly instalment, EUR floor) using the rule in force on
  the contract's start_date (LP4/LP7), and None when unresolvable.
* ``resolve_breakage_reference`` returns the catalogued formula and flags the
  charge "not computable" when the external R%/R1% money-market rates are absent
  (LP5/LP6).
* The strict-baseline sanitiser strips the new per-contract standing_overpayment
  and the lump_sums overlay so a strict baseline stays contract-only.

Phase 12 / S1 note: the overpayment-cap allowance is no longer reference-only.
The daily loop now emits it as the additive ``overpayment_cap_allowance_eur``
monthly column, so these tests also lock the real per-contract euro figures
(Gandon A1 212.34; Somerton B2 143.39 stepping to B3 182.38 at the refix) and
that ``build_monthly_schedule`` surfaces the column, carrying a null where the
allowance is unresolvable. The additive column moves the golden fixtures by
exactly one column, re-baselined at S3; see test_golden_master.py. See
docs/lender_profile.md and docs/contract_data_model.md Section B.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from src.engine.monthly import build_monthly_schedule
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


# ----------------- overpayment cap: real per-contract euro figures -----------
# Phase 12 / S1: the allowance is now an emitted output number, so lock the
# real Gandon and Somerton figures and the step at the Somerton refix.

def test_cap_allowance_real_gandon_contract():
    """Gandon A1: 10% of the EUR 2123.44 instalment gives the EUR 212.34 allowance."""
    prof = _sample_profile()
    gandon_a1 = Contract(
        id="gandon-a1",
        start_date=date(2024, 3, 26),
        end_date=date(2028, 3, 26),
        rate=0.0365,
        instalment=2123.44,
    )
    allowance = overpayment_cap_for_contract(prof, gandon_a1)
    assert allowance is not None
    assert round(allowance, 2) == 212.34


def test_cap_allowance_tracks_somerton_refix():
    """Somerton B2 -> B3: the allowance follows the active contract's instalment.

    REVIEW-006: the instalments and expected allowances are the real Property B
    sample figures (data_sample/property_b/inputs.sample.yaml), so this test
    locks the actual data rather than synthetic values.
    """
    prof = _sample_profile()
    somerton_b2 = Contract(
        id="somerton-b2",
        start_date=date(2022, 6, 23),
        end_date=date(2026, 6, 23),
        rate=0.0190,
        instalment=1218.82,
    )
    somerton_b3 = Contract(
        id="somerton-b3",
        start_date=date(2026, 6, 24),
        end_date=date(2030, 6, 23),
        rate=0.0310,
        instalment=1550.21,
    )
    b2_allowance = overpayment_cap_for_contract(prof, somerton_b2)
    b3_allowance = overpayment_cap_for_contract(prof, somerton_b3)
    assert b2_allowance is not None and round(b2_allowance, 2) == 121.88
    assert b3_allowance is not None and round(b3_allowance, 2) == 155.02
    # The refix lifts the allowance because the instalment steps up.
    assert b3_allowance > b2_allowance


# ----------------- overpayment cap: emitted on the monthly schedule ----------

def _month_row(ym, month_start, pay_date, eom_date):
    """A minimal month_tables-shaped row for build_monthly_schedule."""
    return dict(
        ym=ym,
        month_start=month_start,
        pay_date=pay_date,
        eom=eom_date,
        actual_interest_post_date=None,
        actual_interest_amount=0.0,
        has_actual_payment=False,
        recurring_extra=0.0,
    )


def test_monthly_schedule_emits_cap_allowance_column():
    """build_monthly_schedule surfaces the per-payment cap allowance as a column.

    Two modelled months carry a resolved allowance; a third (a closed month with
    no resolvable allowance) carries None, which must land as a pandas null so
    "unknown" stays distinct from a real zero.
    """
    months = pd.DataFrame([
        _month_row(202406, date(2024, 6, 1), date(2024, 6, 5), date(2024, 6, 30)),
        _month_row(202407, date(2024, 7, 1), date(2024, 7, 5), date(2024, 7, 31)),
        _month_row(202408, date(2024, 8, 1), date(2024, 8, 5), date(2024, 8, 31)),
    ])
    zeros = {202406: 0.0, 202407: 0.0, 202408: 0.0}
    contractual = {202406: 2123.44, 202407: 2123.44, 202408: 0.0}
    rate = {202406: 0.0365, 202407: 0.0365, 202408: 0.0365}
    # The daily loop resolved an allowance for the two payment months and None
    # for the closed month.
    cap_allowance = {202406: 212.34, 202407: 212.34, 202408: None}

    monthly = build_monthly_schedule(
        months,
        pd.DataFrame(columns=["date", "kind", "amount", "balance"]),
        pd.DataFrame(),
        dict(zeros), dict(zeros), dict(zeros), dict(zeros),
        rate,
        contractual,
        cap_allowance,
    )

    assert "overpayment_cap_allowance_eur" in monthly.columns
    vals = list(monthly.sort_values("ym")["overpayment_cap_allowance_eur"])
    assert vals[0] == 212.34
    assert vals[1] == 212.34
    # None becomes a pandas null in the emitted column.
    assert pd.isna(vals[2])


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