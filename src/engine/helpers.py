# src/engine/helpers.py
"""Generic date and numeric helpers for the mortgage engine.

Finance-readable summary
------------------------
This module is the small toolbox of date and arithmetic helpers the engine
leans on. It runs before any mortgage logic and does not, by itself, produce a
final reported number. What it guarantees is the plumbing: every date becomes a
real calendar date, month-ends and payment days are always valid, the monthly
payment formula (PMT) behaves like a bank spreadsheet, and the day-count
divisor matches the loan's interest convention. If any of these were wrong,
every downstream figure (interest, balance, LTV) would silently inherit the
error, so keeping this layer clean protects the whole model.

Technical summary
-----------------
Pure, mortgage-unaware functions: date normalisation, month arithmetic, an
Excel-style PMT, and the day-count divisor. No project state lives here, which
keeps the module a safe dependency-free leaf.

Phase 5 / S1 note: this file was lifted verbatim out of the original
``src/engine.py`` "Helpers" section. Behaviour is unchanged; only the module
header, per-function finance notes, and the stderr status line were added.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta

import pandas as pd


def ensure_date(x) -> date:
    """Return a :class:`datetime.date` regardless of the input type.

    Finance note: dates arrive as text, spreadsheet timestamps, or YAML values.
    Pinning them all to one true calendar date up front is what stops a payment
    or interest posting from later landing on the wrong day and shifting the
    final numbers.

    The project routinely deals with ``datetime``, ``pandas`` and YAML sourced
    values.  Normalising everything to a native ``date`` early keeps downstream
    code free from type-guarding clutter.
    """
    if isinstance(x, date):                 # already a native date: pass through
        return x
    if isinstance(x, pd.Timestamp):         # pandas timestamp: drop the time part
        return x.date()
    # Fall back to parsing an ISO yyyy-mm-dd string (YAML/CSV sourced value).
    return datetime.strptime(str(x), "%Y-%m-%d").date()


def ym_int(d: date) -> int:
    """Return a ``YYYYMM`` integer that is convenient for joins/grouping.

    Finance note: many monthly totals (interest, payments) are grouped by
    calendar month. Turning a date into a single 202403-style number makes those
    monthly groupings exact and fast.
    """
    return d.year * 100 + d.month


def eom(d: date) -> date:
    """Return the calendar month-end for ``d``.

    Finance note: interest is posted at month-end when the bank gives no explicit
    posting date, so a correct month-end keeps interest in the right month and
    therefore the right tax year.
    """
    nm = d.replace(day=28) + timedelta(days=4)   # jump safely into the next month
    return nm - timedelta(days=nm.day)            # step back to this month's last day


def month_index(d0: date, d: date) -> int:
    """Return the 1-based number of months between ``d0`` and ``d``.

    Finance note: the rate schedule and payment recalculations are keyed off
    "month 1, month 2, ..." from drawdown, so this index decides which interest
    rate and payment apply in a given month.
    """
    return (d.year - d0.year) * 12 + (d.month - d0.month) + 1


def clamp_day(y: int, m: int, day: int) -> date:
    """Clamp ``(y, m, day)`` to that month's last valid day.

    Finance note: a standing payment day such as "the 31st" does not exist in
    every month. Clamping to the real month-end keeps projected payment dates
    valid so payments are not silently dropped.

    This protects against invalid dates such as 31 February when we need to
    project payment dates into future months.
    """
    last = eom(date(y, m, 1)).day
    return date(y, m, min(day, last))


def pmt(rate_m: float, n_months: int, pv: float) -> float:
    """Excel-like PMT (end-of-period) returning a positive payment amount.

    Finance note: this is the standard mortgage repayment formula. When a rate
    changes and the bank recalculates the instalment, this is the number it
    targets, so it feeds the projected payment in every scheduled month.
    """
    if n_months <= 0:                  # no remaining term: repay the whole balance
        return abs(pv)
    if abs(rate_m) < 1e-12:            # zero-rate: simply spread principal evenly
        return pv / n_months
    r = rate_m
    return pv * (r / (1 - (1 + r) ** (-n_months)))


def day_count_divisor(label: str) -> float:
    """Return the divisor implied by the day-count convention string.

    Finance note: daily interest is balance * rate / divisor. Choosing 360 vs
    365 changes every day's interest, so this mapping must match the loan
    contract.
    """
    lab = (label or "ACT/365").upper()
    if lab in {"ACT/360", "30/360"}:
        return 360.0
    return 365.0


# Plain-English status line for troubleshooting; stderr only so the CLI's stdout
# (and the golden-master subprocess output) stays byte-for-byte identical.
print("[engine.helpers] date and numeric helpers ready", file=sys.stderr)