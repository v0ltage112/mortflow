# src/engine/schema.py
"""Input schema and loaders for the mortgage engine.

Finance-readable summary
------------------------
This module defines the shape of the modelling inputs (the property, its loan,
the rate path, any revaluations, and which modules apply) and reads them from
the YAML config and the bank statement CSV. It runs right at the start of every
model run. Nothing here does mortgage maths; its job is to turn the files an
analyst edits into clean, typed numbers the engine can trust. If a field is
mis-read here, every figure in the final Monthly, Reconcile, and Tax outputs
would be wrong, so this layer is deliberately strict and explicit.

Technical summary
-----------------
Dataclasses ``RateBlock``, ``ValuationBlock``, ``PropertyMeta``, ``OutputConfig``,
``PaymentHoliday`` and ``Inputs`` plus the ``load_inputs`` (YAML) and
``load_actuals`` (CSV) loaders.

Phase 5 / S1 note: lifted verbatim out of the original ``src/engine.py``
\"Input schema\" section. Behaviour is unchanged; only the module header,
per-function finance notes, and the stderr status line were added. Date and
month helpers now come from ``.helpers`` instead of being defined alongside.

Phase 5 / S6 note: the local ``_to_dec`` helper that lived inside
``load_inputs`` was removed; growth normalisation now calls the shared
``helpers.growth_to_decimal`` so the whole-percent-vs-decimal rule has one
definition across the package. Behaviour is identical.

Phase 6 / S2 note: added an explicit property *kind* and three independent
module toggles (mortgage / tax / valuation) carried on ``PropertyMeta``. The
loader now reads the previously ignored ``meta`` block, tolerates a missing
``loan`` block when the mortgage module is off (no crash on an owned-outright
property), and parses YAML through a strict loader that raises on duplicate
mapping keys instead of silently keeping the last block. Behaviour is unchanged
for a mortgage-on, tax-on investment property such as Property A.

Phase 6 / S4 note: two previously ignored blocks are now read. The ``output``
block is parsed into ``OutputConfig`` (write the workbook, write the CSVs,
include the daily events, currency, locale) and the writer path honours it; the
``bank.payment_holidays`` block is parsed and validated into ``PaymentHoliday``
records but is *not yet applied* to the schedule (parse-and-defer). Every default
reproduces the pre-S4 behaviour exactly: a file with no ``output`` block writes
the same artefacts as before, with euro formatting, and a parsed-only payment-
holiday window changes no figure, so Gandon's golden master stays green.
Activating payment holidays is a separate, validated change with a golden
re-baseline.

Phase 8 / S3 note: ``OutputConfig`` gains a ``csv_subdir`` field (default
\"csv\"). It names the sub-folder under each property's output directory that the
engine writes every CSV into, leaving the headline ``<slug>_model.xlsx`` at the
property root. Reading it here keeps the one parse point with the rest of the
output knobs; the writer paths and the portfolio/baseline tools honour it. An
empty string restores the previous flat layout. No modelled number changes; only
the CSV paths move.

Phase 10 / S1 note: additive introduction of the date-based contract schema
(Section A of docs/contract_data_model.md) and the lender profile. New
dataclasses ``FollowOn``, ``StandingOverpayment``, ``PaymentEvent``,
``Contract`` and ``Loan`` are parsed alongside the legacy fields; ``Inputs`` is
now a frozen dataclass with an explicit ``.copy()`` / ``.clone()`` and carries
the new ``lender``, ``contracts``, ``loan_v2`` and ``profile`` fields. No engine
code consumes the new fields yet (that begins in S2), so every current figure
and the Gandon golden master stay byte-identical.

Phase 10 / S2 note: ``load_inputs`` now sources the loan-level scalars from the
new-schema keys when a ``contracts:`` array is present (``loan_v2`` resolved):
``property_price`` from ``loan.property_value``, ``principal_at_drawdown`` from
``loan.drawdown_amount``, ``known_first_payment`` from the first contract's
``instalment``, and ``repayment_day_default`` from ``loan.repayment_day`` (via
``_repayment_day_to_int``). Legacy files (no contracts) still read the old keys
unchanged, so the still-legacy Property B/C samples and the Gandon golden stay
byte-identical. The rate path and the recurring overpayment are consumed from
the contracts by monthly.py / simulate.py; rate_blocks and overpay_rules stay
empty for a converted file.

Phase 10 / S3 note: the scalar ``overpayment_cap_pct`` is retired from
``Inputs`` and its loader. It was dead code: read into ``Inputs`` (the legacy
\"10% of the opening balance per year\") but never consumed for any output
figure. The overpayment cap is now resolved from the lender profile per
contract (``resolve_overpayment_cap_allowance`` / ``overpayment_cap_for_contract``:
max(percent of the monthly instalment, EUR floor), using the rule in force on
the contract's start_date, LP4/LP7), and the breakage-charge reference is wired
from the profile (``resolve_breakage_reference``: the catalogued formula,
flagged \"not computable\" when the external R%/R1% money-market rates are absent,
LP5/LP6). Both are reference-only resolvers consumed by no output figure, so
every current number and the golden master stay byte-identical. The sample files
keep an inert ``overpayment_cap_pct`` key, which the loader now ignores.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import yaml

from .helpers import ensure_date, ym_int, growth_to_decimal, month_index
from .profile import LenderProfile, resolve_lender_profile


# --- Property kind taxonomy -------------------------------------------------
# A property \"kind\" is plain-English shorthand for what a property is and which
# parts of the model apply to it. It sets the default on/off state of the three
# independent modules; any default can still be overridden per module in the
# meta block. The three kinds modelled today:
#   investment     : a let property. Mortgage on, rental tax on, valuation on.
#   primary        : your own home with a mortgage. Mortgage on, tax off
#                    (no rental return), valuation on.
#   owned_outright : a property with no mortgage. Mortgage off, tax off,
#                    valuation on (value tracking only).
# The mapping is data, not branching logic, so adding a future kind is one line.
KIND_DEFAULT_TOGGLES: Dict[str, Dict[str, bool]] = {
    "investment":     {"mortgage": True,  "tax": True,  "valuation": True},
    "primary":        {"mortgage": True,  "tax": False, "valuation": True},
    "owned_outright": {"mortgage": False, "tax": False, "valuation": True},
}

# Friendly spellings map to a single canonical kind so a config can say
# \"residence\" or \"BTL\" and still resolve to the right module defaults.
_KIND_ALIASES: Dict[str, str] = {
    "investment": "investment",
    "btl": "investment",
    "rental": "investment",
    "let": "investment",
    "primary": "primary",
    "residence": "primary",
    "ppr": "primary",
    "home": "primary",
    "owned_outright": "owned_outright",
    "owned-outright": "owned_outright",
    "outright": "owned_outright",
    "owned": "owned_outright",
}

# A file with no kind (or only the legacy \"mode\") behaves as before: an
# investment property with mortgage, tax, and valuation all on.
DEFAULT_KIND = "investment"

# Phase 6 / S4: recognised payment-holiday modes. Parsed and validated but not
# yet applied to the schedule (parse-and-defer), so a typo is caught early while
# behaviour stays locked.
_VALID_PAYMENT_HOLIDAY_MODES = {"interest_only", "full_deferral"}


@dataclass
class RateBlock:
    """Continuous rate assumption for a span of model months.

    Finance note: each block says \"from month X to month Y the annual rate is
    Z\". Together the blocks are the loan's interest-rate path, which drives both
    accrued interest and any payment recalculation at a refix.
    """

    start_month: int       # 1-based from drawdown
    end_month: int
    annual_rate: float     # decimal p.a., e.g. 0.0365
    kind: str              # 'fixed' or 'variable' (informational)


@dataclass
class ContractualStep:
    """One agreed contractual instalment, effective from a model month.

    Finance note: the contractual ladder generalises the single
    ``known_first_payment`` into a list of agreed instalments, one per
    contractual step (drawdown, then each refix the bank has confirmed). Each
    step says \"from this model month the agreed monthly instalment is this euro
    amount\". Steps the bank has not confirmed yet are simply left out of the
    ladder, and the engine keeps falling back to the recalculated model PMT,
    which is clearly a projection rather than an agreed figure. This is the
    agreed-terms source of truth that the Phase 7 payment attribution reconciles
    the observed bank debit against; on its own it changes no modelled number.
    """

    start_month: int        # 1-based model month from drawdown this step applies from
    amount: float           # agreed contractual instalment in euro
    source: str = "agreed"  # 'agreed' (bank-confirmed) | 'projection' (model PMT fallback)


# --- Phase 10 / S1: date-based contract model (additive) ---
# Section A of docs/contract_data_model.md replaces the month-number rate model
# with a date-based contracts array: loan-level facts (one drawdown of new money)
# separated from contract-level facts (a sequence of rate agreements). As of
# Phase 10 / S2 the rate path and the recurring overpayment are consumed from
# these shapes; the legacy fields remain as the fallback for un-migrated files.

@dataclass
class FollowOn:
    """A directional roll-to rate for after a contract's fixed period (A2).

    Finance note: non-binding. Projections past a contract's end_date use it
    only as a clearly flagged provisional assumption; adding a refix contract
    supersedes it.
    """

    rate: Optional[float] = None
    rate_type: str = "variable"
    basis: str = ""
    indicative: bool = True
    note: str = ""


@dataclass
class StandingOverpayment:
    """A recurring voluntary overpayment window attached to a contract (A3)."""

    amount: float
    start_date: date
    end_date: Optional[date] = None
    note: str = ""


@dataclass
class PaymentEvent:
    """A date-based, contract-scoped payment event (A4).

    Finance note: covers a payment break (interest-only plus capitalise) and a
    formalised part-capital instalment increase (contractual, not an
    overpayment).
    """

    type: str                       # payment_holiday | part_capital_increase | ...
    start_date: date
    end_date: Optional[date] = None
    treatment: str = ""             # interest_only | capitalise | instalment_increase
    amount: Optional[float] = None
    note: str = ""


@dataclass
class Contract:
    """One rate agreement over a loan's life (Section A Contract object).

    Finance note: a fixed period plus a directional follow-on. A refix advances
    no new money, so it is a new Contract on the same loan. instalment is the
    contractual monthly repayment; None means the engine derives it via PMT.
    """

    id: str
    start_date: date
    end_date: Optional[date] = None
    rate: float = 0.0
    rate_type: str = "fixed"
    instalment: Optional[float] = None
    follow_on: Optional[FollowOn] = None
    standing_overpayment: Optional[StandingOverpayment] = None
    payment_events: List[PaymentEvent] = field(default_factory=list)
    overpayment_cap_override: Optional[dict] = None
    breakage_override: Optional[dict] = None


@dataclass
class Loan:
    """Loan-level facts for the new schema: one drawdown of new money (Section A).

    Finance note: money advanced is a loan fact; the rate agreements over time
    are the contracts. A property has exactly one loan and one or more
    contracts.
    """

    property_id: str
    lender: str
    drawdown_amount: float
    drawdown_date: date
    total_term_months: int
    property_value: float
    contracts: List[Contract] = field(default_factory=list)
    maturity_date: Optional[date] = None
    repayment_day: Optional[str] = None   # int-as-value or 'month_end'; projected dates only
    property_growth_pa: float = 0.0


@dataclass
class ValuationBlock:
    """A user-specified revaluation of the property.

    Finance note: a valuation block pins a new property value and growth rate
    from a given date (for example a surveyor revaluation at a refix). It feeds
    the property value and therefore the loan-to-value figures.
    """

    start: date          # effective date of new base valuation
    base_value: float    # the revalued amount from which growth applies
    growth_pa: float     # decimal p.a. (0.01 => 1%)


@dataclass
class PropertyMeta:
    """Identity and module switches for one property.

    Finance note: this answers \"which property is this, and which parts of the
    model run for it\". The kind sets sensible defaults (a let property runs the
    rental-tax module, your own home does not); the three toggles let you flip a
    single module without changing the kind.
    """

    property_id: str          # stable folder-style id, e.g. 'property-a'
    name: str                 # human label, e.g. 'Property A'
    kind: str                 # canonical: investment | primary | owned_outright
    mortgage_enabled: bool    # run the loan schedule and reconcile
    tax_enabled: bool         # run the Form 11 rental-tax module
    valuation_enabled: bool   # track property value (and LTV when a loan exists)


@dataclass
class OutputConfig:
    """Which output artefacts to write and how to format money.

    Finance note: these switches decide what the run leaves on disk and how
    currency is shown. They do not change a single modelled figure; they only
    gate which files appear, which currency symbol the workbook uses, and which
    sub-folder the CSVs land in. The defaults match what the engine wrote before
    these knobs were honoured, so an unchanged config produces an unchanged set
    of files (bar the Phase 8 csv/ sub-folder, which is the new default layout).
    """

    write_excel: bool = True            # write the .xlsx workbook
    write_csv: bool = True              # write the .csv artefacts
    include_daily_events: bool = True   # include the daily events sheet + events_daily.csv
    currency: str = "EUR"               # ISO code; selects the workbook money symbol
    locale: str = "en_IE"               # locale tag; recorded (see note below)
    # Phase 8 / S3: sub-folder under each property's output directory that every
    # CSV is written into; the headline .xlsx stays at the property root. Default
    # \"csv\" gives <slug>_model.xlsx + csv/. An empty string (or null) restores the
    # flat layout with the CSVs beside the workbook.
    csv_subdir: str = "csv"


@dataclass
class PaymentHoliday:
    """A bank payment-holiday window (parsed and validated, not yet applied).

    Finance note: a payment holiday is a period where the borrower pays reduced
    or no instalments and unpaid interest may be capitalised. Activating one
    changes the early-month figures and therefore the locked golden master, so
    Phase 6 deliberately only reads and validates the block. Turning it into
    real schedule behaviour is a separate, validated, re-baselined change.
    """

    start: date          # first day of the holiday window
    end: date            # last day of the holiday window (inclusive)
    mode: str            # 'interest_only' | 'full_deferral'
    capitalise: bool     # whether unpaid interest is added to the balance


@dataclass(frozen=True)
class Inputs:
    """Canonical representation of the YAML modelling configuration.

    Finance note: this is the single, validated picture of the property the
    engine runs on (price, principal, term, payment day, rate path, overpayment
    rules, and which modules apply). Every reported number is derived from these
    fields.
    """

    property_price: float
    principal_at_drawdown: float
    drawdown_date: date
    total_term_months: int
    first_payment_date: date
    known_first_payment: float
    repayment_day_default: int
    property_growth_pa: float           # decimal (0.01 -> 1% p.a.). If >1, treated as %
    rate_blocks: List[RateBlock]
    strategy_at_refix: str              # 'RecalculatePayment' | 'TermReduction'
    overpay_rules: List[dict]           # standing extras (by start month)
    lump_sums: List[dict]               # exact-date one-offs: {date, amount}
    modelling_end_date: Optional[date]
    day_count: str = "ACT/365"
    # Phase 2: how to treat recurring extras when there *is* a bank payment line that month.
    # \"true\"  -> assume extra included in the bank Payment (suppress separate Extra)
    # \"false\" -> always post a separate Extra
    # \"auto\"  -> behave like \"true\" (default)
    merge_extra_mode: str = "auto"
    valuation_blocks: List[ValuationBlock] = field(default_factory=list)  # optional; overrides simple growth if provided
    reconcile_ok_abs_eur: float = 0.01
    posting_order: str = "debit_then_post"  # 'debit_then_post' | 'post_then_debit'
    # Phase 6 / S2: identity + module toggles. Optional default keeps the
    # dataclass field order valid; load_inputs always populates it.
    meta: Optional[PropertyMeta] = None
    # Phase 6 / S4: output artefact switches + currency/locale. Optional default
    # keeps the dataclass field order valid; load_inputs always populates it.
    output: OutputConfig = field(default_factory=OutputConfig)
    # Phase 6 / S4: parsed-and-validated payment-holiday windows. Not applied to
    # the schedule yet (parse-and-defer); kept so a future phase can activate it.
    payment_holidays: List[PaymentHoliday] = field(default_factory=list)
    # Phase 7 / S1: the agreed contractual ladder and the dedicated tolerance for
    # the payment-level Difference column. Both are optional with behaviour-
    # preserving defaults: an empty ladder means the engine keeps using
    # known_first_payment and the RecalculatePayment fallback exactly as before,
    # and the tolerance is unused until S3 emits the column.
    contractual_ladder: List[ContractualStep] = field(default_factory=list)
    payment_unattributed_ok_abs_eur: float = 0.01

    # --- NEW in Phase 10 / S1: append after the last existing field ---
    # The new date-based contract schema and the resolved lender profile,
    # parsed additively. Defaults keep legacy files (no `contracts:` key)
    # byte-identical: no contracts, no loan_v2, no profile.
    lender: Optional[str] = None
    contracts: List[Contract] = field(default_factory=list)
    loan_v2: Optional[Loan] = None
    profile: Optional[LenderProfile] = None

    def copy(self, **changes) -> "Inputs":
        """Return a new Inputs with the given fields replaced (frozen-safe clone).

        Finance note: Inputs is immutable (a frozen dataclass), so scenario work
        never mutates the baseline in place. ``inputs.copy(merge_extra_mode=...)``
        returns an independent Inputs with just those fields changed; the
        original is untouched. ``.clone()`` is an alias. Design decision #5 and
        the foundation for the Phase 14 clone-and-perturb scenarios.
        """
        return replace(self, **changes)

    # Alias so either name reads naturally at the call site.
    clone = copy


def _resolve_kind(raw_kind: Optional[str]) -> str:
    """Normalise a user-entered kind to one of the canonical kinds.

    Finance note: lets the config say 'residence' or 'BTL' and still land on the
    right module defaults. An unknown kind is a hard error so a typo never
    silently runs the wrong modules.
    """
    if raw_kind is None:
        return DEFAULT_KIND
    key = str(raw_kind).strip().lower()
    if key not in _KIND_ALIASES:
        # Fail loud: a misspelled kind must not silently fall back to a default
        # that would run the wrong set of modules.
        raise ValueError(
            f"Unknown property kind {raw_kind!r}. "
            f"Use one of: {sorted(set(_KIND_ALIASES.values()))}."
        )
    return _KIND_ALIASES[key]


def _repayment_day_to_int(value) -> int:
    """Normalise a new-schema ``repayment_day`` to the integer clamp_day expects.

    Finance note: the new Loan schema records the projected payment day either as
    a day-of-month integer or as the word ``month_end``. The engine's month
    scaffolding clamps a day-of-month into each month, so a month-end instruction
    becomes 31 (clamp_day then pins it to the real last day). A missing value
    falls back to the 1st, matching the legacy ``repayment_day_default`` default.
    """
    if value is None:
        return 1
    s = str(value).strip().lower()
    if s in {"month_end", "eom", "end_of_month", "month-end"}:
        return 31
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return 1


def _resolve_meta(raw: dict) -> PropertyMeta:
    """Build :class:`PropertyMeta` from the optional ``meta`` block.

    Finance note: reads the property's identity and works out which modules run.
    The kind sets the defaults; an explicit 'mortgage / tax / valuation' line in
    meta overrides only that one module. A file with no meta behaves exactly as
    before: an investment property with mortgage, tax, and valuation all on.
    """
    meta_raw = (raw.get("meta") or {})
    # 'kind' is the going-forward key; 'mode' is the legacy spelling still read.
    kind = _resolve_kind(meta_raw.get("kind", meta_raw.get("mode")))
    defaults = KIND_DEFAULT_TOGGLES[kind]

    def _toggle(name: str) -> bool:
        # Explicit override wins, in either the bare ('tax') or suffixed
        # ('tax_enabled') spelling; otherwise inherit the kind default.
        if meta_raw.get(name) is not None:
            return bool(meta_raw[name])
        alt = f"{name}_enabled"
        if meta_raw.get(alt) is not None:
            return bool(meta_raw[alt])
        return defaults[name]

    return PropertyMeta(
        property_id=str(meta_raw.get("property_id", "")),
        name=str(meta_raw.get("name", "")),
        kind=kind,
        mortgage_enabled=_toggle("mortgage"),
        tax_enabled=_toggle("tax"),
        valuation_enabled=_toggle("valuation"),
    )


def _resolve_output(raw: dict) -> OutputConfig:
    """Build :class:`OutputConfig` from the optional ``output`` block.

    Finance note: reads the output switches an analyst can set (write the
    workbook, write the CSVs, include the daily-events detail, pick a currency
    and locale, and choose the CSV sub-folder name). Every default reproduces the
    pre-S4 behaviour for the switches, so a file with no ``output`` block, or one
    that omits a key, writes exactly what the engine wrote before these knobs
    were honoured (the CSVs now sit under the default ``csv/`` sub-folder).
    """
    out_raw = (raw.get("output") or {})

    def _flag(name: str, default: bool) -> bool:
        # A missing key inherits the behaviour-preserving default; an explicit
        # value is coerced so 'true'/1/yes/on all read as True.
        val = out_raw.get(name)
        if val is None:
            return default
        if isinstance(val, str):
            return val.strip().lower() in {"1", "true", "yes", "on"}
        return bool(val)

    # Currency is recorded upper-cased and locale as-is; empty or missing values
    # fall back to the euro/Irish defaults that match today's behaviour.
    currency = str(out_raw.get("currency") or "EUR").strip().upper()
    locale = str(out_raw.get("locale") or "en_IE").strip()

    # Phase 8 / S3: the CSV sub-folder name. A missing key defaults to \"csv\"; an
    # explicit empty string (or null) restores the flat layout with the CSVs
    # beside the workbook. Trimming any surrounding slashes keeps it a single
    # safe folder name regardless of how it is typed.
    raw_csv_subdir = out_raw.get("csv_subdir", "csv")
    csv_subdir = ("" if raw_csv_subdir is None else str(raw_csv_subdir)).strip().strip("/\\\\")

    return OutputConfig(
        write_excel=_flag("write_excel", True),
        write_csv=_flag("write_csv", True),
        include_daily_events=_flag("include_daily_events", True),
        currency=currency,
        locale=locale,
        csv_subdir=csv_subdir,
    )


def _resolve_payment_holidays(bank_cfg: dict) -> List[PaymentHoliday]:
    """Parse and validate ``bank.payment_holidays`` without applying it.

    Finance note: reads each declared payment-holiday window and checks it is
    well formed (a real date range and a recognised mode) so a typo is caught
    early. Phase 6 stops here on purpose: the windows are not yet fed into the
    schedule, because doing so would move Gandon's locked early-month figures.
    Activation is a separate, validated change with a golden re-baseline.
    """
    holidays: List[PaymentHoliday] = []
    for ph in (bank_cfg.get("payment_holidays") or []):
        # A window must carry both ends; a half-open window is a config error.
        start = ensure_date(ph["start"])
        end = ensure_date(ph["end"])
        if end < start:
            raise ValueError(
                f"payment holiday end {end} is before start {start}; "
                "fix the window in the bank block"
            )
        mode = str(ph.get("mode", "interest_only")).strip().lower()
        if mode not in _VALID_PAYMENT_HOLIDAY_MODES:
            raise ValueError(
                f"unknown payment-holiday mode {mode!r}; "
                f"use one of {sorted(_VALID_PAYMENT_HOLIDAY_MODES)}"
            )
        # 'capitalise' defaults to True: unpaid interest is normally rolled up.
        capitalise = bool(ph.get("capitalise", True))
        holidays.append(PaymentHoliday(start=start, end=end, mode=mode, capitalise=capitalise))
    return holidays


class _StrictLoader(yaml.SafeLoader):
    """A SafeLoader that refuses duplicate mapping keys.

    Finance note: stock YAML silently keeps the last of two blocks with the same
    name, so a file with two 'tax:' sections would quietly drop one set of
    rules. This loader turns that into a loud error, so a duplicated block is
    fixed deliberately rather than masked.
    """


def _no_duplicate_keys(loader: _StrictLoader, node, deep: bool = False) -> dict:
    """Construct a mapping, raising on any repeated key.

    The actual mapping is built by the normal SafeLoader machinery (so nested
    structures and types behave exactly as before); this only pre-checks the
    keys at each mapping level for duplicates.
    """
    seen: set = set()
    for key_node, _value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None,
                f"duplicate key {key!r} in YAML mapping; keep one canonical block",
                key_node.start_mark,
            )
        seen.add(key)
    return loader.construct_mapping(node, deep=deep)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys
)


def _load_yaml_strict(path: Path) -> dict:
    """Read a YAML file with duplicate-key detection enabled."""
    return yaml.load(Path(path).read_text(), Loader=_StrictLoader)


def _resolve_contractual_ladder(raw: dict, drawdown_date: Optional[date]) -> List[ContractualStep]:
    """Parse the optional ``contractual_ladder`` block into sorted steps.

    Finance note: reads the agreed instalment ladder an analyst enters from the
    bank's confirmation letters. Each entry carries the agreed monthly instalment
    plus when it takes effect, given either as a 1-based model ``month`` or as an
    ISO ``date`` (for example the date printed on the bank letter). Dates are
    normalised to the model month so the ladder lines up with the rest of the
    engine, which counts months from drawdown. A file with no ladder returns an
    empty list, which preserves today's behaviour: the engine falls back to
    known_first_payment and the recalculated PMT.

    Technical note: additive and side-effect free. The ladder may sit at the top
    level (alongside rate_blocks) or inside the loan block; the top level wins to
    mirror how rate_blocks are read. Within an entry an explicit ``month`` wins
    over a ``date``. A ``date`` needs a known drawdown date to normalise; a date
    supplied without one is a hard error rather than a silent guess.
    """
    # Top level first (mirrors rate_blocks), then the loan block as a fallback.
    entries = raw.get("contractual_ladder")
    if entries is None:
        entries = (raw.get("loan") or {}).get("contractual_ladder")
    if not entries:
        # No ladder declared: empty list keeps known_first_payment / PMT behaviour.
        return []

    steps: List[ContractualStep] = []
    for e in entries:
        # Resolve the effective month: an explicit month index wins; otherwise a
        # date is converted to the 1-based model month counted from drawdown.
        if e.get("month") is not None:
            start_month = int(e["month"])
        elif e.get("date") is not None:
            if drawdown_date is None:
                raise ValueError(
                    "a contractual_ladder entry uses a date but the loan has no "
                    "drawdown_date to normalise it against; use a month index or "
                    "add the loan block"
                )
            # month_index(drawdown, date) returns the 1-based model month.
            start_month = month_index(drawdown_date, ensure_date(e["date"]))
        else:
            raise ValueError("each contractual_ladder entry needs a 'month' or a 'date'")
        amount = float(e["amount"])  # agreed instalment in euro; required per entry
        # 'agreed' marks a bank-confirmed step; 'projection' is reserved for a
        # future fallback row. Default to agreed since the ladder holds confirmed terms.
        source = str(e.get("source", "agreed")).strip().lower()
        steps.append(ContractualStep(start_month=start_month, amount=amount, source=source))
    # Sort by effective month so every consumer reads the ladder in time order.
    steps.sort(key=lambda s: s.start_month)
    return steps


def _resolve_follow_on(raw: Optional[dict]) -> Optional[FollowOn]:
    """Parse a contract ``follow_on`` block; None when absent."""
    if not raw:
        return None
    return FollowOn(
        rate=(None if raw.get("rate") is None else float(raw["rate"])),
        rate_type=str(raw.get("rate_type", "variable")),
        basis=str(raw.get("basis", "") or ""),
        indicative=bool(raw.get("indicative", True)),
        note=str(raw.get("note", "") or ""),
    )


def _resolve_standing_overpayment(raw: Optional[dict]) -> Optional[StandingOverpayment]:
    """Parse a contract ``standing_overpayment`` block; None when absent."""
    if not raw:
        return None
    return StandingOverpayment(
        amount=float(raw["amount"]),
        start_date=ensure_date(raw["start_date"]),
        end_date=(ensure_date(raw["end_date"]) if raw.get("end_date") else None),
        note=str(raw.get("note", "") or ""),
    )


def _resolve_payment_events(entries) -> List[PaymentEvent]:
    """Parse a contract ``payment_events`` list; empty when absent."""
    out: List[PaymentEvent] = []
    for e in (entries or []):
        out.append(
            PaymentEvent(
                type=str(e.get("type", "")),
                start_date=ensure_date(e["start_date"]),
                end_date=(ensure_date(e["end_date"]) if e.get("end_date") else None),
                treatment=str(e.get("treatment", "") or ""),
                amount=(None if e.get("amount") is None else float(e["amount"])),
                note=str(e.get("note", "") or ""),
            )
        )
    return out


def _payment_holiday_from_event(event: PaymentEvent) -> Optional[PaymentHoliday]:
    """Map a contract ``payment_event`` of type ``payment_holiday`` to a legacy PaymentHoliday.

    Finance note: Phase 10 moved the payment break off the legacy
    ``bank.payment_holidays`` block and onto the contract as a ``payment_event``
    (docs/contract_data_model.md Section A4). The engine still exposes the
    parsed-and-deferred break through ``Inputs.payment_holidays`` so the S4
    validation, and any future activation, read one list regardless of which
    schema a file uses. The event's ``treatment`` carries the legacy ``mode``
    when it names a recognised one ('interest_only' | 'full_deferral'); any
    other treatment falls back to 'interest_only'. Unpaid interest on a break
    capitalises, so ``capitalise`` is True, matching the pre-migration default.

    Returns None for a non-holiday event or one missing an end date, so an
    unrelated or half-open event is skipped rather than guessed. A reversed
    window (end before start) is a config error and raises, mirroring the legacy
    bank-block validation.
    """
    # Only payment-holiday events map to the legacy holiday view; other event
    # types (for example a part_capital_increase) are not holidays.
    if event.type != "payment_holiday":
        return None
    # A holiday needs a closed window; a half-open event cannot be validated or
    # applied, so skip it rather than invent an end date.
    if event.end_date is None:
        return None
    # A reversed window is a config error, exactly as the legacy bank block treats it.
    if event.end_date < event.start_date:
        raise ValueError(
            f"payment holiday end {event.end_date} is before start "
            f"{event.start_date}; fix the window on the contract payment_event"
        )
    # The new-schema treatment carries the legacy mode when it names one;
    # anything else (or a blank) degrades to the interest-only default.
    treatment = (event.treatment or "").strip().lower()
    mode = treatment if treatment in _VALID_PAYMENT_HOLIDAY_MODES else "interest_only"
    # Unpaid interest on a break capitalises; the legacy default was True.
    return PaymentHoliday(
        start=event.start_date,
        end=event.end_date,
        mode=mode,
        capitalise=True,
    )


def _payment_holidays_from_contracts(contracts: List[Contract]) -> List[PaymentHoliday]:
    """Derive legacy PaymentHoliday records from every contract's payment_events.

    Finance note: gathers each ``payment_holiday`` payment_event across the
    loan's contracts and expresses it in the legacy PaymentHoliday shape, so a
    migrated file (holiday on the contract) and an un-migrated file (holiday in
    ``bank.payment_holidays``) both surface the same parsed-and-deferred break.
    A file with no contracts, or contracts with no holiday events, yields an
    empty list, so legacy samples are untouched.
    """
    out: List[PaymentHoliday] = []
    for contract in contracts:
        for event in contract.payment_events:
            holiday = _payment_holiday_from_event(event)
            if holiday is not None:
                out.append(holiday)
    return out


def _resolve_contracts(loan: dict) -> List[Contract]:
    """Parse the new-schema ``loan.contracts`` array (Section A).

    Finance note: reads the date-based contract objects that replace the
    month-number rate model. Returns an empty list when a file carries no
    ``contracts:`` key, which is every un-migrated legacy file, so nothing
    changes for those samples. Contracts are sorted by start_date.
    """
    out: List[Contract] = []
    for c in (loan.get("contracts") or []):
        out.append(
            Contract(
                id=str(c["id"]),
                start_date=ensure_date(c["start_date"]),
                end_date=(ensure_date(c["end_date"]) if c.get("end_date") else None),
                rate=float(c.get("rate", 0.0)),
                rate_type=str(c.get("rate_type", "fixed")),
                instalment=(None if c.get("instalment") is None else float(c["instalment"])),
                follow_on=_resolve_follow_on(c.get("follow_on")),
                standing_overpayment=_resolve_standing_overpayment(c.get("standing_overpayment")),
                payment_events=_resolve_payment_events(c.get("payment_events")),
                overpayment_cap_override=c.get("overpayment_cap_override"),
                breakage_override=c.get("breakage_override"),
            )
        )
    out.sort(key=lambda k: k.start_date)
    return out


def _resolve_loan_v2(loan: dict, contracts: List[Contract], meta: PropertyMeta) -> Optional[Loan]:
    """Build the new-schema :class:`Loan` when a ``contracts:`` array is present.

    Finance note: parse of the loan-level facts (one drawdown of new money).
    Returns None for legacy files (no ``contracts:`` key), so the un-migrated
    samples and the Gandon golden are untouched. property_id falls back to the
    meta block, which is where the sample files carry it.
    """
    if not loan.get("contracts"):
        return None
    return Loan(
        property_id=str(loan.get("property_id", getattr(meta, "property_id", "")) or ""),
        lender=str(loan.get("lender", "") or ""),
        drawdown_amount=float(loan.get("drawdown_amount", 0.0)),
        drawdown_date=ensure_date(loan["drawdown_date"]),
        total_term_months=int(loan.get("total_term_months", 0)),
        property_value=float(loan.get("property_value", 0.0)),
        contracts=contracts,
        maturity_date=(ensure_date(loan["maturity_date"]) if loan.get("maturity_date") else None),
        repayment_day=loan.get("repayment_day"),
        property_growth_pa=float(loan.get("property_growth_pa", 0.0)),
    )


def load_inputs(path: Path) -> Inputs:
    """Parse the YAML modelling configuration into an :class:`Inputs` object.

    Finance note: this reads the analyst-edited config file and produces the one
    validated picture the model runs on. Defaults and unit-normalisation (for
    example treating a growth of 3 as 3%) happen here, so this is where the
    assumptions behind every final number are locked in.
    """
    # Strict parse: a repeated top-level block (for example two 'tax:' sections)
    # is now an error rather than a silent last-wins.
    raw = _load_yaml_strict(path)

    # Identity + module toggles. Resolved first so a no-mortgage property can
    # legitimately skip the loan block below.
    meta = _resolve_meta(raw)

    # The loan block is optional when the mortgage module is off. An
    # owned-outright property may omit it entirely; loan-derived fields then
    # fall back to neutral defaults so Inputs still constructs (the valuation-
    # only path in S3 does not read them). A mortgage-on property with a loan
    # block present is unchanged.
    loan = (raw.get("loan") or {})
    if meta.mortgage_enabled and not loan:
        raise ValueError(
            "mortgage module is enabled but the 'loan' block is missing; "
            "add a loan block or set the property kind/toggle to mortgage off"
        )

    blocks = [RateBlock(**rb) for rb in (raw.get("rate_blocks") or [])]
    strat = raw.get("strategy_at_refix", "RecalculatePayment")
    overp = raw.get("overpay_rules", [])
    lumps = raw.get("lump_sums", [])
    mod = raw.get("modelling", {})
    end_date = mod.get("end_date", None)

    # Phase 2 - read bank.merge_standing_extra_into_payment
    bank_cfg = (raw.get("bank") or {})
    merge_mode_raw = str(bank_cfg.get("merge_standing_extra_into_payment", "auto")).strip().lower()
    if merge_mode_raw in {"1", "true", "yes"}:
        merge_mode = "true"
    elif merge_mode_raw in {"0", "false", "no"}:
        merge_mode = "false"
    else:
        merge_mode = "auto"

    # Phase 6 / S4: output artefact switches + currency/locale. Defaults
    # reproduce the pre-S4 behaviour, so an unchanged config writes unchanged
    # files.
    output_cfg = _resolve_output(raw)

    # Phase 6 / S4: payment-holiday windows are parsed and validated but not yet
    # applied to the schedule (parse-and-defer). Reading them here keeps the one
    # validation point with the rest of the loader; activation moves the golden
    # master and is a separate, validated change.
    payment_holidays = _resolve_payment_holidays(bank_cfg)

    # Optional property valuation blocks (re/valuations + growth regime changes)
    vblocks_raw = (loan.get("valuation_blocks") or [])
    vblocks: List[ValuationBlock] = []
    for vb in vblocks_raw:
        vblocks.append(
            ValuationBlock(
                start=ensure_date(vb["start"]),
                base_value=float(vb["value"]),
                # Growth normalisation now lives in helpers.growth_to_decimal
                # (one definition shared by schema, valuation, and the CLI).
                growth_pa=growth_to_decimal(vb.get("growth_pa", loan.get("property_growth_pa", 0.0))),
            )
        )
    vblocks = sorted(vblocks, key=lambda b: b.start)

    # Reconcile config (absolute EUR tolerance)
    rec_cfg = (raw.get("reconcile") or {})
    try:
        ok_abs = float(rec_cfg.get("ok_abs_eur", 0.01))
    except Exception:
        ok_abs = 0.01

    # Bank posting order
    post_ord = str(bank_cfg.get("posting_order", "debit_then_post")).strip().lower()
    if post_ord not in {"post_then_debit", "debit_then_post"}:
        post_ord = "debit_then_post"

    # Loan-derived dates are read only when present; a no-mortgage file leaves
    # them as None and the valuation-only path (S3) does not consult them.
    drawdown = ensure_date(loan["drawdown_date"]) if loan.get("drawdown_date") else None
    first_pay = ensure_date(loan["first_payment_date"]) if loan.get("first_payment_date") else None

    # Phase 7 / S1: resolve the agreed contractual ladder (dates normalised to
    # model months using the drawdown date) and the dedicated payment-level
    # Difference tolerance. Both are additive: an absent block leaves the ladder
    # empty and the tolerance at its default, so this session changes no figure.
    contractual_ladder = _resolve_contractual_ladder(raw, drawdown)
    attribution_cfg = (raw.get("attribution") or {})
    try:
        payment_unattributed_ok_abs = float(attribution_cfg.get("payment_unattributed_ok_abs_eur", 0.01))
    except Exception:
        # A malformed value degrades to the safe default rather than crashing the run.
        payment_unattributed_ok_abs = 0.01

    # Phase 10 / S1: parse of the new date-based contract schema and the lender
    # profile. A legacy file (no `contracts:` key, no `lender`) leaves contracts
    # empty, loan_v2 None, and profile None.
    lender = (loan.get("lender") if loan else None)
    contracts = _resolve_contracts(loan)
    loan_v2 = _resolve_loan_v2(loan, contracts, meta)

    # Phase 10 / S5: the payment break moved from the legacy bank.payment_holidays
    # block onto the contract as a payment_event (docs/contract_data_model.md
    # Section A4). Derive the legacy PaymentHoliday view from the contracts and
    # union it with any bank block, de-duped on the (start, end) window, so
    # Inputs.payment_holidays surfaces the parsed-and-deferred break for both the
    # migrated and the un-migrated schema without double-counting a file that
    # still carries both. Reference/validation-only: no output figure consumes
    # payment_holidays, so the golden master stays byte-identical.
    _seen_holiday_windows = {(h.start, h.end) for h in payment_holidays}
    for _ph in _payment_holidays_from_contracts(contracts):
        if (_ph.start, _ph.end) not in _seen_holiday_windows:
            payment_holidays.append(_ph)
            _seen_holiday_windows.add((_ph.start, _ph.end))

    profile: Optional[LenderProfile] = None
    if lender:
        lenders_dir = Path(path).resolve().parent.parent / "lenders"
        try:
            profile = resolve_lender_profile(str(lender), lenders_dir)
        except FileNotFoundError:
            # A lender key without a discoverable profile is not fatal: the
            # profile stays None so the parse never breaks a run.
            profile = None

    # Phase 10 / S2: when the new-schema contracts array is present (loan_v2
    # resolved), the loan-level scalar facts are sourced from the new keys and
    # the known first payment is the first contract's agreed instalment. Legacy
    # files (no contracts) keep sourcing the old keys unchanged, so those runs
    # and the still-legacy Property B/C samples stay byte-identical.
    if loan_v2 is not None:
        property_price_val = float(loan.get("property_value", loan.get("property_price", 0.0)))
        principal_val = float(loan.get("drawdown_amount", loan.get("principal_at_drawdown", 0.0)))
        first_contract_instalment = (
            contracts[0].instalment if (contracts and contracts[0].instalment is not None) else None
        )
        known_first_val = (
            float(first_contract_instalment)
            if first_contract_instalment is not None
            else float(loan.get("known_first_payment", 0.0))
        )
        repayment_day_val = _repayment_day_to_int(
            loan.get("repayment_day", loan.get("repayment_day_default", 1))
        )
    else:
        property_price_val = float(loan.get("property_price", 0.0))
        principal_val = float(loan.get("principal_at_drawdown", 0.0))
        known_first_val = float(loan.get("known_first_payment", 0.0))
        repayment_day_val = int(loan.get("repayment_day_default", 1))

    return Inputs(
        property_price=property_price_val,
        principal_at_drawdown=principal_val,
        drawdown_date=drawdown,
        total_term_months=int(loan.get("total_term_months", 0)),
        first_payment_date=first_pay,
        known_first_payment=known_first_val,
        repayment_day_default=repayment_day_val,
        property_growth_pa=float(loan.get("property_growth_pa", 0.0)),
        rate_blocks=blocks,
        strategy_at_refix=str(strat),
        overpay_rules=overp,
        lump_sums=lumps,
        modelling_end_date=(ensure_date(end_date) if end_date else None),
        day_count=str(mod.get("day_count", "ACT/365")),
        merge_extra_mode=merge_mode,
        valuation_blocks=vblocks,
        reconcile_ok_abs_eur=ok_abs,
        posting_order=post_ord,
        meta=meta,
        output=output_cfg,
        payment_holidays=payment_holidays,
        contractual_ladder=contractual_ladder,
        payment_unattributed_ok_abs_eur=payment_unattributed_ok_abs,
        lender=lender,
        contracts=contracts,
        loan_v2=loan_v2,
        profile=profile,
    )


def load_actuals(csv_path: Path) -> pd.DataFrame:
    """Load bank statement events from the CSV exported by the lender.

    Finance note: this is the real bank activity (drawdown, payments, interest
    postings) the model reconciles against. Getting the sign convention and the
    month grouping right here is what lets the Reconcile sheet compare model and
    bank like for like.

    The helper keeps the transformation logic in one place so that tests and
    CLI invocations agree on how to interpret the CSV.  Amount sign conventions
    match the bank feed: payments are negative while interest and drawdown
    amounts are positive.
    """
    df = pd.read_csv(csv_path, parse_dates=["date"])
    df["date"] = df["date"].dt.date
    df["ym"] = df["date"].apply(ym_int)
    df["type"] = df["type"].astype(str).str.strip().str.title()
    if "run_balance" not in df.columns:
        df["run_balance"] = np.nan
    return df


# =====================================================================
# Phase 10 / S3: profile-derived overpayment cap and breakage reference
# =====================================================================
# The scalar overpayment_cap_pct is retired (see the module note). These
# resolvers read the going-forward cap allowance and breakage-charge reference
# from the lender profile. Both are reference-only: no output figure consumes
# them, so the golden master stays byte-identical. They live here, next to the
# schema that carries the resolved profile and contracts, so there is a single
# place that turns the profile rulebook into per-contract figures.


def resolve_overpayment_cap_allowance(
    profile: Optional[LenderProfile],
    instalment: Optional[float],
    anchor: Optional[date],
) -> Optional[float]:
    """Return the per-payment voluntary-overpayment allowance in euro, or None.

    Finance note: the retired scalar cap (the legacy \"10% of the opening balance
    per year\") is replaced by the lender profile's overpayment_cap rule in force
    on ``anchor`` (LP4/LP7). For the BOI-style rule this is
    ``max(percent * monthly instalment, floor_eur)``, assessed per payment. The
    result is a reference figure only; no output number consumes it.

    Returns None when the allowance cannot be resolved: no profile, no anchor,
    no instalment (the allowance is a fraction of the monthly repayment), no cap
    rule in force, or a basis this engine does not model. Returning None rather
    than 0.0 keeps \"unknown\" distinct from \"no headroom\".
    """
    if profile is None or anchor is None or instalment is None:
        return None
    try:
        rule = profile.rule_on(ensure_date(anchor))
    except ValueError:
        # No rule version in force on or before the anchor: treat as unresolved
        # rather than raising, since this is reference-only wiring.
        return None
    cap = rule.overpayment_cap
    if cap is None or cap.basis != "percent_of_monthly_repayment":
        return None
    percent = cap.percent or 0.0
    floor = cap.floor_eur or 0.0
    return max(percent * float(instalment), floor)


def overpayment_cap_for_contract(
    profile: Optional[LenderProfile], contract: Optional[Contract]
) -> Optional[float]:
    """Return the overpayment-cap allowance for one contract, anchored on its start.

    Finance note: LP7 anchors the cap on the contract period, so the allowance
    uses the rule in force on the contract's ``start_date`` applied to that
    contract's monthly ``instalment``. Returns None when the contract states no
    instalment or the profile cannot resolve a rule. Reference-only.
    """
    if contract is None:
        return None
    return resolve_overpayment_cap_allowance(profile, contract.instalment, contract.start_date)


@dataclass
class BreakageReference:
    """A resolved early-repayment-charge reference for a contract (LP5/LP6).

    Finance note: the breakage charge follows the lender's catalogued formula
    (BOI: ``principal_x_rate_differential_x_remaining_years``). The rate
    differential needs two external money-market rates, R% (funding) and R1%
    (deposit), resolved on the breakage-quote date. When the profile carries no
    formula, or those rates are absent on the quote date, the charge is flagged
    ``computable = False`` (\"not computable\") rather than guessed. This is a
    reference only: no output figure consumes it.
    """

    formula: Optional[str]
    computable: bool
    funding_rate: Optional[float] = None   # R%
    deposit_rate: Optional[float] = None   # R1%
    note: str = ""


def resolve_breakage_reference(
    profile: Optional[LenderProfile],
    anchor: Optional[date],
    quote_date: Optional[date] = None,
) -> Optional[BreakageReference]:
    """Return the breakage-formula reference for a contract, or None.

    Finance note: reads the breakage formula from the rule in force on the
    contract ``anchor`` (LP5) and the external R%/R1% money-market rates on the
    breakage ``quote_date`` (LP6). The charge is \"not computable\"
    (``computable = False``) when the profile carries no breakage formula, no
    quote date is supplied, or the money-market rates are absent on that date;
    docs/lender_profile.md states R%/R1% are external and nullable. Returns None
    only when there is no profile or no anchor to resolve against. Reference-only.
    """
    if profile is None or anchor is None:
        return None
    try:
        rule = profile.rule_on(ensure_date(anchor))
    except ValueError:
        return None
    breakage = rule.breakage
    if breakage is None or not breakage.formula:
        return BreakageReference(
            formula=(breakage.formula if breakage is not None else None),
            computable=False,
            note="not computable: the lender profile carries no breakage formula",
        )
    quote = ensure_date(quote_date) if quote_date is not None else None
    mm = profile.money_market_on(quote) if quote is not None else None
    if mm is None or mm.funding_rate is None or mm.deposit_rate is None:
        return BreakageReference(
            formula=breakage.formula,
            computable=False,
            note="not computable: external R%/R1% money-market rates absent on the quote date",
        )
    return BreakageReference(
        formula=breakage.formula,
        computable=True,
        funding_rate=mm.funding_rate,
        deposit_rate=mm.deposit_rate,
        note="",
    )


print("[engine.schema] input schema and loaders ready", file=sys.stderr)