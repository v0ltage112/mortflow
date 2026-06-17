# src/engine/schema.py
"""Input schema and loaders for the mortgage engine.

Finance-readable summary
------------------------
This module defines the shape of the modelling inputs (the loan, its rate path,
any revaluations) and reads them from the YAML config and the bank statement
CSV. It runs right at the start of every model run. Nothing here does mortgage
maths; its job is to turn the files an analyst edits into clean, typed numbers
the engine can trust. If a field is mis-read here, every figure in the final
Monthly, Reconcile, and Tax outputs would be wrong, so this layer is
deliberately strict and explicit.

Technical summary
-----------------
Dataclasses ``RateBlock``, ``ValuationBlock`` and ``Inputs`` plus the
``load_inputs`` (YAML) and ``load_actuals`` (CSV) loaders.

Phase 5 / S1 note: lifted verbatim out of the original ``src/engine.py``
"Input schema" section. Behaviour is unchanged; only the module header,
per-function finance notes, and the stderr status line were added. Date and
month helpers now come from ``.helpers`` instead of being defined alongside.

Phase 5 / S6 note: the local ``_to_dec`` helper that lived inside
``load_inputs`` was removed; growth normalisation now calls the shared
``helpers.growth_to_decimal`` so the whole-percent-vs-decimal rule has one
definition across the package. Behaviour is identical.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import yaml

from .helpers import ensure_date, ym_int, growth_to_decimal


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
class Inputs:
    """Canonical representation of the YAML modelling configuration.

    Finance note: this is the single, validated picture of the loan that the
    engine runs on (price, principal, term, payment day, rate path, overpayment
    rules, and so on). Every reported number is derived from these fields.
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


def load_inputs(path: Path) -> Inputs:
    """Parse the YAML modelling configuration into an :class:`Inputs` object.

    Finance note: this reads the analyst-edited config file and produces the one
    validated loan picture the model runs on. Defaults and unit-normalisation
    (for example treating a growth of 3 as 3%) happen here, so this is where the
    assumptions behind every final number are locked in.
    """
    raw = yaml.safe_load(Path(path).read_text())
    loan = raw["loan"]
    blocks = [RateBlock(**rb) for rb in raw["rate_blocks"]]
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

    return Inputs(
        property_price=float(loan["property_price"]),
        principal_at_drawdown=float(loan["principal_at_drawdown"]),
        drawdown_date=ensure_date(loan["drawdown_date"]),
        total_term_months=int(loan["total_term_months"]),
        first_payment_date=ensure_date(loan["first_payment_date"]),
        known_first_payment=float(loan["known_first_payment"]),
        repayment_day_default=int(loan["repayment_day_default"]),
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