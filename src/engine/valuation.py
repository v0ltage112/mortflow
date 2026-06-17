# src/engine/valuation.py
"""Property valuation and LTV helpers for the mortgage engine.

Finance-readable summary
------------------------
This module decides what each property is worth on any given day. The number it
returns is the denominator behind every loan-to-value figure in the report: if
the value is wrong, every LTV column on the monthly schedule and on the daily
events log is wrong by the same proportion. It starts from the purchase price
recorded at drawdown, grows it at the assumed annual rate, and switches to a
revaluation block whenever the inputs pin a new base value from a later date.

Technical summary
-----------------
Pure functions, no state. ``property_value_on`` walks the ordered list of
valuation blocks (implicit drawdown block plus any user overrides) and compounds
at the active block's growth rate. ``_months_between`` returns the whole-month
gap between two dates for compounding. The growth-input normaliser lives in
``helpers.growth_to_decimal`` and is imported.

Phase 5 / S2 note: lifted verbatim out of ``src/engine/simulate.py``. Behaviour
is unchanged; only the module header and a stderr status line are new. The 46
passed, 2 skipped golden master plus the S1 characterization test stay green.

Phase 5 / S6 note: the local ``_growth_to_decimal`` was removed and replaced by
the shared ``helpers.growth_to_decimal`` so the whole-percent-vs-decimal rule
has a single definition across the package. Behaviour is identical.
"""

from __future__ import annotations

import sys
from datetime import date
from typing import List

from .helpers import growth_to_decimal
from .schema import Inputs, ValuationBlock


def _months_between(d0: date, d1: date) -> int:
    """Return the whole-month gap between two dates.

    Finance note: property growth compounds per year, so the number of months
    since the last valuation decides how much the value has grown by ``d1``.
    """
    return (d1.year - d0.year) * 12 + (d1.month - d0.month)


def property_value_on(inputs: "Inputs", dt: date) -> float:
    """Return the modelled property valuation on ``dt``.

    Finance note: this is the property value used for loan-to-value. It starts
    from the purchase price at drawdown and grows at the assumed rate, unless a
    revaluation block pins a new value from a later date. LTV (balance / value)
    depends directly on this number.

    The valuation logic supports "revaluation blocks" where a user pins a new
    base value and growth rate from a particular date.  The implicit block at
    drawdown captures the original purchase price so that the behaviour is
    consistent whether or not custom blocks are provided.
    """
    base_price = float(inputs.property_price or 0.0)
    if base_price <= 0.0:
        return 0.0

    eff_blocks: List[ValuationBlock] = []
    imp_growth = growth_to_decimal(getattr(inputs, "property_growth_pa", 0.0))
    eff_blocks.append(ValuationBlock(start=inputs.drawdown_date, base_value=base_price, growth_pa=imp_growth))

    if inputs.valuation_blocks:
        eff_blocks.extend(inputs.valuation_blocks)
        eff_blocks = sorted(eff_blocks, key=lambda b: b.start)

    active = None
    for b in eff_blocks:
        if b.start <= dt:
            active = b
        else:
            break

    if active is None:
        return base_price

    months = _months_between(active.start, dt)
    return float(active.base_value * ((1.0 + active.growth_pa) ** (months / 12.0)))


# Plain-English status line for troubleshooting; stderr only so the CLI's stdout
# (and the golden-master subprocess output) stays byte-for-byte identical.
print("[engine.valuation] property valuation helpers ready", file=sys.stderr)