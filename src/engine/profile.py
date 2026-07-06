# src/engine/profile.py
"""Lender profile loader and effective-dated rule resolver.

Finance-readable summary
------------------------
A lender profile is the per-lender rulebook: the overpayment-cap allowance, the
breakage-fee formula, the payment-date convention, and the interest day-count,
each recorded as an append-only, effective-dated version, plus the private
money-market rate series the breakage formula consumes. This module reads that
profile from YAML and answers the two questions the engine will ask in later
sessions: which rule version was in force on a given date, and which
money-market rates applied to a given breakage quote. It runs no mortgage
maths; it is a typed, date-aware view of docs/lender_profile.md.

Technical summary
-----------------
Dataclasses OverpaymentCapRule, BreakageRule, RuleVersion, MoneyMarketRate and
LenderProfile, plus parse_lender_profile (dict -> LenderProfile),
load_lender_profile (path -> LenderProfile) and resolve_lender_profile (lender
key + search dir -> LenderProfile, preferring <lender>.local.yaml over
sample_lender.yaml). Resolution is by date: rule_on(anchor) returns the version
with the greatest effective_from that is not after the anchor; money_market_on
(quote_date) does the same over the rate series. Depends only on the stdlib,
PyYAML, and helpers.ensure_date; it must never import schema.

Phase 10 / S1 note: new module, introduced additively alongside the existing
schema. Nothing in the engine consumes a resolved profile yet; load_inputs
attaches one only when a loan carries a lender key, which no committed sample
does until S2. See docs/lender_profile.md and docs/contract_data_model.md
Section B.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import List, Optional

import yaml

from .helpers import ensure_date


@dataclass
class OverpaymentCapRule:
    """The voluntary-overpayment allowance for a rule version (LP4).

    Finance note: the BOI rule is percent_of_monthly_repayment with percent 0.10
    and a EUR 65 floor, assessed per payment and non-rolling. Encoded as data so
    a different lender rule is a new record, not a code change.
    """

    basis: str                        # e.g. 'percent_of_monthly_repayment'
    percent: Optional[float] = None   # decimal, e.g. 0.10
    floor_eur: Optional[float] = None # per-payment floor in euro
    rolls_over: bool = False          # unused monthly headroom does not accumulate


@dataclass
class BreakageRule:
    """The early-repayment-charge formula reference for a rule version (LP5)."""

    formula: str                      # e.g. 'principal_x_rate_differential_x_remaining_years'


@dataclass
class RuleVersion:
    """One effective-dated block of universal rules (LP2/LP3).

    Finance note: the rules in force from effective_from until the next version
    supersedes it. Resolution picks the latest effective_from that is not after
    the anchor date.
    """

    effective_from: date
    rationale: str = ""
    overpayment_cap: Optional[OverpaymentCapRule] = None
    breakage: Optional[BreakageRule] = None
    payment_date_convention: str = "day_clamp"
    day_count: str = "ACT/365"


@dataclass
class MoneyMarketRate:
    """A dated pair of external BOI money-market rates for breakage (LP6).

    Finance note: R% (funding_rate) and R1% (deposit_rate) are private, external
    market inputs resolved on the breakage-quote date. They are nullable: when
    absent the breakage charge is 'not computable'.
    """

    as_of: date
    funding_rate: Optional[float] = None   # R%
    deposit_rate: Optional[float] = None   # R1%
    note: str = ""


@dataclass
class LenderProfile:
    """A named, effective-dated lender rulebook (docs/lender_profile.md)."""

    lender_id: str
    display_name: str = ""
    rule_versions: List[RuleVersion] = field(default_factory=list)
    money_market_rates: List[MoneyMarketRate] = field(default_factory=list)

    def rule_on(self, anchor: date) -> RuleVersion:
        """Return the rule version in force on ``anchor`` (latest effective_from <= anchor).

        Finance note: rules are append-only and dated; the one that applies is
        the most recent version that had already taken effect by the anchor
        date. Raises when the profile carries no version on or before the
        anchor, because guessing a rule would silently misstate an allowance or
        charge.
        """
        anchor = ensure_date(anchor)
        eligible = [rv for rv in self.rule_versions if rv.effective_from <= anchor]
        if not eligible:
            earliest = min((rv.effective_from for rv in self.rule_versions), default=None)
            raise ValueError(
                f"lender profile {self.lender_id!r} has no rule version effective "
                f"on or before {anchor}; earliest is {earliest}"
            )
        return max(eligible, key=lambda rv: rv.effective_from)

    def money_market_on(self, quote_date: date) -> Optional[MoneyMarketRate]:
        """Return the money-market rates for a breakage quote date (latest as_of <= quote_date).

        Finance note: breakage rates resolve on the quote date, not the contract
        date. Returns None when the series is empty or predates every entry, in
        which case the breakage charge is 'not computable'.
        """
        quote_date = ensure_date(quote_date)
        eligible = [mm for mm in self.money_market_rates if mm.as_of <= quote_date]
        if not eligible:
            return None
        return max(eligible, key=lambda mm: mm.as_of)


def _parse_overpayment_cap(raw: Optional[dict]) -> Optional[OverpaymentCapRule]:
    """Parse the overpayment_cap block; None when absent."""
    if not raw:
        return None
    return OverpaymentCapRule(
        basis=str(raw.get("basis", "")),
        percent=(None if raw.get("percent") is None else float(raw["percent"])),
        floor_eur=(None if raw.get("floor_eur") is None else float(raw["floor_eur"])),
        rolls_over=bool(raw.get("rolls_over", False)),
    )


def _parse_breakage(raw: Optional[dict]) -> Optional[BreakageRule]:
    """Parse the breakage block; None when absent."""
    if not raw:
        return None
    return BreakageRule(formula=str(raw.get("formula", "")))


def _parse_rule_version(raw: dict) -> RuleVersion:
    """Parse one rule_versions entry into a :class:`RuleVersion`."""
    return RuleVersion(
        effective_from=ensure_date(raw["effective_from"]),
        rationale=str(raw.get("rationale", "") or ""),
        overpayment_cap=_parse_overpayment_cap(raw.get("overpayment_cap")),
        breakage=_parse_breakage(raw.get("breakage")),
        payment_date_convention=str(raw.get("payment_date_convention", "day_clamp")),
        day_count=str(raw.get("day_count", "ACT/365")),
    )


def _parse_money_market_rate(raw: dict) -> MoneyMarketRate:
    """Parse one money_market_rates entry into a :class:`MoneyMarketRate`."""
    return MoneyMarketRate(
        as_of=ensure_date(raw["as_of"]),
        funding_rate=(None if raw.get("funding_rate") is None else float(raw["funding_rate"])),
        deposit_rate=(None if raw.get("deposit_rate") is None else float(raw["deposit_rate"])),
        note=str(raw.get("note", "") or ""),
    )


def parse_lender_profile(raw: dict) -> LenderProfile:
    """Build a :class:`LenderProfile` from an already-parsed YAML mapping.

    Finance note: turns the profile document into a typed rulebook. Rule
    versions are sorted by effective date so resolution is unambiguous, and a
    profile with no versions is rejected because it can answer no rule query.
    """
    if not isinstance(raw, dict):
        raise ValueError("lender profile must be a YAML mapping")
    versions = [_parse_rule_version(rv) for rv in (raw.get("rule_versions") or [])]
    if not versions:
        raise ValueError(
            f"lender profile {raw.get('lender_id')!r} declares no rule_versions"
        )
    versions.sort(key=lambda rv: rv.effective_from)
    rates = [_parse_money_market_rate(mm) for mm in (raw.get("money_market_rates") or [])]
    rates.sort(key=lambda mm: mm.as_of)
    return LenderProfile(
        lender_id=str(raw.get("lender_id", "")),
        display_name=str(raw.get("display_name", "") or ""),
        rule_versions=versions,
        money_market_rates=rates,
    )


def load_lender_profile(path: Path) -> LenderProfile:
    """Read and parse a lender profile YAML file into a :class:`LenderProfile`."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text())
    return parse_lender_profile(raw)


def resolve_lender_profile(lender: str, lenders_dir: Path) -> LenderProfile:
    """Locate and load the profile for ``lender`` under ``lenders_dir``.

    Finance note: mirrors the local-vs-sample split (LP1). A private
    ``<lender>.local.yaml`` wins when present (real BOI rules, git-ignored);
    otherwise the committed ``sample_lender.yaml`` is used, so a fresh clone
    still runs. Raises when neither a lender-specific file nor the sample
    exists.
    """
    lenders_dir = Path(lenders_dir)
    candidates = [
        lenders_dir / f"{lender}.local.yaml",
        lenders_dir / f"{lender}.yaml",
        lenders_dir / "sample_lender.yaml",
    ]
    for cand in candidates:
        if cand.exists():
            return load_lender_profile(cand)
    raise FileNotFoundError(
        f"no lender profile for {lender!r} under {lenders_dir}; expected one of: "
        + ", ".join(c.name for c in candidates)
    )


print("[engine.profile] lender profile loader and resolver ready", file=sys.stderr)