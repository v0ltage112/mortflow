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
"Input schema" section. Behaviour is unchanged; only the module header,
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
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import yaml

from .helpers import ensure_date, ym_int, growth_to_decimal


# --- Property kind taxonomy -------------------------------------------------
# A property "kind" is plain-English shorthand for what a property is and which
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
# "residence" or "BTL" and still resolve to the right module defaults.
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

# A file with no kind (or only the legacy "mode") behaves as before: an
# investment property with mortgage, tax, and valuation all on.
DEFAULT_KIND = "investment"

# Phase 6 / S4: recognised payment-holiday modes. Parsed and validated but not
# yet applied to the schedule (parse-and-defer), so a typo is caught early while
# behaviour stays locked.
_VALID_PAYMENT_HOLIDAY_MODES = {"interest_only", "full_deferral"}


@dataclass
class RateBlock:
    """Continuous rate assumption for a span of model months.

    Finance note: each block says "from month X to month Y the annual rate is
    Z". Together the blocks are the loan's interest-rate path, which drives both
    accrued interest and any payment recalculation at a refix.
    """

    start_month: int       # 1-based from drawdown
    end_month: int
    annual_rate: float     # decimal p.a., e.g. 0.0365
    kind: str              # 'fixed' or 'variable' (informational)


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

    Finance note: this answers "which property is this, and which parts of the
    model run for it". The kind sets sensible defaults (a let property runs the
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
    gate which files appear and which currency symbol the workbook uses. The
    defaults match what the engine wrote before these knobs were honoured, so an
    unchanged config produces an unchanged set of files.
    """

    write_excel: bool = True            # write the .xlsx workbook
    write_csv: bool = True              # write the .csv artefacts
    include_daily_events: bool = True   # include the daily events sheet + events_daily.csv
    currency: str = "EUR"               # ISO code; selects the workbook money symbol
    locale: str = "en_IE"               # locale tag; recorded (see note below)


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


@dataclass
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
    overpayment_cap_pct: float
    rate_blocks: List[RateBlock]
    strategy_at_refix: str              # 'RecalculatePayment' | 'TermReduction'
    overpay_rules: List[dict]           # standing extras (by start month)
    lump_sums: List[dict]               # exact-date one-offs: {date, amount}
    modelling_end_date: Optional[date]
    day_count: str = "ACT/365"
    # Phase 2: how to treat recurring extras when there *is* a bank payment line that month.
    # "true"  -> assume extra included in the bank Payment (suppress separate Extra)
    # "false" -> always post a separate Extra
    # "auto"  -> behave like "true" (default)
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
    and locale). Every default reproduces the pre-S4 behaviour, so a file with no
    ``output`` block, or one that omits a key, writes exactly what the engine
    wrote before these knobs were honoured.
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

    return OutputConfig(
        write_excel=_flag("write_excel", True),
        write_csv=_flag("write_csv", True),
        include_daily_events=_flag("include_daily_events", True),
        currency=currency,
        locale=locale,
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

    return Inputs(
        property_price=float(loan.get("property_price", 0.0)),
        principal_at_drawdown=float(loan.get("principal_at_drawdown", 0.0)),
        drawdown_date=drawdown,
        total_term_months=int(loan.get("total_term_months", 0)),
        first_payment_date=first_pay,
        known_first_payment=float(loan.get("known_first_payment", 0.0)),
        repayment_day_default=int(loan.get("repayment_day_default", 1)),
        property_growth_pa=float(loan.get("property_growth_pa", 0.0)),
        overpayment_cap_pct=float(loan.get("overpayment_cap_pct", 0.10)),
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


print("[engine.schema] input schema and loaders ready", file=sys.stderr)