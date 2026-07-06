# src/engine/calendar_ie.py
"""Irish business-day calendar and payment-date convention adjuster.

Finance-readable summary
------------------------
Banks post scheduled repayments only on working days. This module answers the
two questions the engine needs when it projects a future repayment date: is a
given date an Irish working day, and if a scheduled date is not, where does the
real payment land? It encodes the Irish bank-holiday calendar (weekends, the
fixed and rule-based public holidays, Good Friday as a bank/SEPA closure, and
the in-lieu substitute days) and applies the Modified Following convention BOI
uses for projected dates. It runs no mortgage maths and touches no money.

Only PROJECTED future dates use this. Actual posted dates always come from the
bank feed and are never adjusted here.

Technical summary
-----------------
Pure, offline, dependency-free (stdlib only). ``easter_sunday`` via the
Anonymous Gregorian computus; ``irish_bank_holidays`` returns the observed
holiday set for a year; ``is_business_day`` is 'not weekend and not holiday';
``next_business_day`` / ``prev_business_day`` step over non-working days;
``modified_following`` rolls forward to the next working day but back to the
last working day of the month when forward crosses the month boundary;
``adjust_for_convention`` dispatches on the profile convention string.

MAINTENANCE (read when the cross-check flags a divergence)
----------------------------------------------------------
The runtime calendar here is hand-owned on purpose: the golden master must be
deterministic and offline, so the engine never imports the third-party
``holidays`` package. To confirm this calendar is still correct, run:

    pip install -r requirements-dev.txt
    python -m tools.verify_calendar --from 2024 --to 2060

If it reports an UNEXPECTED difference, follow docs/calendar_maintenance.md. In
short: a genuinely new or changed statutory holiday is edited into
``irish_bank_holidays`` below; a legitimate library-only one-off (or our
deliberate Good Friday inclusion) is allow-listed in tools/verify_calendar.py.
Any change here moves projected dates, so it requires a golden re-baseline.

Phase 10 / S4 note: new module. Wiring the profile's payment_date_convention
(modified_following) into the projected payment date is the one deliberate
behaviour change of Phase 10; it moves the Gandon golden once, which S4
re-baselines.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from functools import lru_cache
from typing import List, Set

# Weekday numbers per datetime.date.weekday(): Monday=0 ... Sunday=6.
_SATURDAY = 5
_SUNDAY = 6

# The year St Brigid's Day became an Irish public holiday. Before this it did
# not exist, so the calendar must not invent it for earlier years.
_ST_BRIGID_FIRST_YEAR = 2023


def easter_sunday(year: int) -> date:
    """Return the Gregorian Easter Sunday for ``year`` (Anonymous computus).

    Finance note: Easter anchors two Irish bank closures, Good Friday (two days
    before) and Easter Monday (the day after). It is not a fixed date, so it is
    computed rather than looked up. The algorithm is exact for the Gregorian
    calendar with no upper-year limit, which is why a projection to 2059 needs
    no data table.
    """
    # Anonymous Gregorian algorithm (Meeus/Jones/Butcher). Integer-only.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the ``n``-th ``weekday`` of ``month`` (n=1 => first).

    Finance note: several Irish holidays are 'the first Monday of May' style
    rules; this finds that date for any year.
    """
    d = date(year, month, 1)
    # Days from the 1st to the first requested weekday, then whole weeks for n.
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """Return the last ``weekday`` of ``month`` (e.g. last Monday of October)."""
    # Start at the month end, then step back to the requested weekday.
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    back = (last.weekday() - weekday) % 7
    return last - timedelta(days=back)


def _st_brigids_day(year: int) -> date:
    """Return St Brigid's Day for ``year`` (public holiday from 2023).

    Finance note: the rule is the first Monday of February, except that when
    1 February is a Friday the holiday is 1 February itself.
    """
    first = date(year, 2, 1)
    if first.weekday() == 4:  # Friday
        return first
    return _nth_weekday(year, 2, 0, 1)  # first Monday


def _fixed_holidays(year: int) -> List[date]:
    """Return the fixed-date Irish holidays that observe a weekend substitute.

    Finance note: these four are tied to a calendar date and, when they fall on
    a weekend, the bank observes a substitute working-day holiday. They are
    returned here on their true date; substitution is applied by the caller.
    """
    return [
        date(year, 1, 1),    # New Year's Day
        date(year, 3, 17),   # St Patrick's Day
        date(year, 12, 25),  # Christmas Day
        date(year, 12, 26),  # St Stephen's Day
    ]


def _substitute_day(base: date, already: Set[date]) -> date:
    """Return the in-lieu substitute working day for a weekend fixed holiday.

    Finance note: when a fixed holiday lands on Saturday or Sunday the bank
    observes it on the next weekday that is not itself already a holiday. The
    'not already a holiday' step handles the Christmas / St Stephen's run, where
    the two substitutes fall on consecutive following weekdays.
    """
    d = base + timedelta(days=1)
    while d.weekday() >= _SATURDAY or d in already:
        d += timedelta(days=1)
    return d


@lru_cache(maxsize=None)
def irish_bank_holidays(year: int) -> frozenset:
    """Return the observed Irish bank-holiday dates in ``year``.

    Finance note: the full set of days BOI does not post on besides weekends:
    the statutory public holidays, Good Friday (a bank/SEPA closure, not a
    statutory public holiday), and the in-lieu substitutes for fixed holidays
    that fall on a weekend. Cached per year because the projection asks for the
    same years many times.

    MAINTENANCE: to add or remove a statutory holiday (a legislative change),
    edit this function, then re-run tools/verify_calendar.py and re-baseline the
    golden (docs/calendar_maintenance.md).
    """
    holidays: Set[date] = set()

    # Rule-based movable holidays.
    holidays.add(easter_sunday(year) - timedelta(days=2))   # Good Friday (bank/SEPA closure)
    holidays.add(easter_sunday(year) + timedelta(days=1))   # Easter Monday
    holidays.add(_nth_weekday(year, 5, 0, 1))               # first Monday of May
    holidays.add(_nth_weekday(year, 6, 0, 1))               # first Monday of June
    holidays.add(_nth_weekday(year, 8, 0, 1))               # first Monday of August
    holidays.add(_last_weekday(year, 10, 0))                # last Monday of October
    if year >= _ST_BRIGID_FIRST_YEAR:
        holidays.add(_st_brigids_day(year))                 # St Brigid's Day (2023+)

    # Fixed-date holidays plus their weekend substitute (observed) days.
    for base in _fixed_holidays(year):
        holidays.add(base)
        if base.weekday() >= _SATURDAY:
            holidays.add(_substitute_day(base, holidays))

    return frozenset(holidays)


def is_business_day(d: date) -> bool:
    """Return True when ``d`` is an Irish working day (not weekend, not holiday)."""
    if d.weekday() >= _SATURDAY:
        return False
    return d not in irish_bank_holidays(d.year)


def next_business_day(d: date) -> date:
    """Return the first working day on or after ``d`` moving forward."""
    cur = d
    while not is_business_day(cur):
        cur += timedelta(days=1)
    return cur


def prev_business_day(d: date) -> date:
    """Return the first working day on or before ``d`` moving backward."""
    cur = d
    while not is_business_day(cur):
        cur -= timedelta(days=1)
    return cur


def modified_following(d: date) -> date:
    """Adjust ``d`` to a working day using the Modified Following convention.

    Finance note: if ``d`` is already a working day it is unchanged. Otherwise
    roll forward to the next working day, unless that crosses into the next
    calendar month, in which case roll backward to the last working day of
    ``d``'s own month instead. This mirrors how BOI posts a scheduled debit.
    """
    if is_business_day(d):
        return d
    forward = next_business_day(d)
    # If rolling forward left the original month, fall back to the last working
    # day on or before ``d`` (Modified Following).
    if forward.month != d.month or forward.year != d.year:
        return prev_business_day(d)
    return forward


# Convention identifiers accepted from the lender profile (docs/lender_profile.md LP3).
CONVENTION_DAY_CLAMP = "day_clamp"
CONVENTION_MODIFIED_FOLLOWING = "modified_following"


def adjust_for_convention(d: date, convention: str) -> date:
    """Apply the profile's payment-date convention to a clamped date.

    Finance note: ``day_clamp`` is today's behaviour and returns the date
    unchanged; ``modified_following`` applies the Irish working-day rule. An
    unknown convention is treated as ``day_clamp`` so an unexpected value never
    silently moves dates.
    """
    if convention == CONVENTION_MODIFIED_FOLLOWING:
        return modified_following(d)
    return d


# Plain-English status line for troubleshooting; stderr only so stdout (and the
# golden-master subprocess output) stays byte-for-byte identical.
print("[engine.calendar_ie] Irish business-day calendar ready", file=sys.stderr)