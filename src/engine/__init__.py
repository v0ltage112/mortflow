# src/engine/__init__.py
"""Public facade for the mortgage engine package.

Finance-readable summary
------------------------
This file is the front door of the engine. It does no calculation itself; it
simply re-exports the same names callers used to import from the old single
``engine.py`` so that every existing tool, test, and report keeps working
unchanged after the code was split into modules. If a name a script relied on
were missing here, that script would break, so the list below is the contract
the rest of the project depends on.

Technical summary
-----------------
Re-export facade. Pulls the public surface from the new submodules
(``helpers``, ``schema``, ``simulate``, ``report``) and exposes it as
``src.engine`` so that ``from src.engine import X`` stays byte-identical for all
callers. CLI behaviour lives in ``__main__`` so ``python -m src.engine`` still
runs ``main()``.

Phase 5 / S1 note: structural only. No behaviour change.
"""

from __future__ import annotations

import sys

# Generic date/numeric helpers.
from .helpers import (
    ensure_date,
    ym_int,
    eom,
    month_index,
    clamp_day,
    pmt,
    day_count_divisor,
)

# Input schema (dataclasses) and loaders.
from .schema import (
    RateBlock,
    ValuationBlock,
    Inputs,
    load_inputs,
    load_actuals,
)

# Valuation helpers (extracted in Phase 5 / S2).
from .valuation import property_value_on

# Monthly scaffolding and schedule assembly (extracted in Phase 5 / S3).
from .monthly import (
    build_rate_lookup,
    derive_modelling_end,
    month_span,
    month_tables,
)

# Simulation: payment helper and the core engine.
from .simulate import (
    payment_for_month,
    run_engine,
)

# Reporting / portal-metrics helper used by the smoke tests and the CLI.
from .report import compute_portal_style_metrics

# The complete public surface that callers may import from ``src.engine``.
# Keeping this explicit makes the byte-identical re-export contract obvious and
# guards against an accidental omission breaking a downstream import.
__all__ = [
    # helpers
    "ensure_date",
    "ym_int",
    "eom",
    "month_index",
    "clamp_day",
    "pmt",
    "day_count_divisor",
    # schema
    "RateBlock",
    "ValuationBlock",
    "Inputs",
    "load_inputs",
    "load_actuals",
    # simulate
    "property_value_on",
    "build_rate_lookup",
    "derive_modelling_end",
    "month_span",
    "month_tables",
    "payment_for_month",
    "run_engine",
    # report
    "compute_portal_style_metrics",
]

print("[engine] package facade ready (src.engine re-exports loaded)", file=sys.stderr)