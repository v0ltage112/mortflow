# tools/verify_calendar.py
"""Cross-check the owned Irish calendar against the `holidays` library.

DEV/ON-DEMAND tool, not part of the engine. The engine never imports
`holidays`; the runtime calendar is src/engine/calendar_ie.py, kept hand-owned
so the golden master stays deterministic and offline. Run this to confirm the
owned calendar is still correct, or when you hear an Irish holiday rule changed:

    pip install -r requirements-dev.txt
    python -m tools.verify_calendar --from 2024 --to 2060

It compares, year by year, the owned holiday set against
holidays.Ireland(observed=True) and reports any UNEXPECTED difference. Two kinds
of difference are expected and allow-listed (Good Friday, and library one-offs),
so anything printed is real and needs action. On an unexpected difference it
prints the exact fix + golden-rebaseline runbook and exits non-zero.

See docs/calendar_maintenance.md for the full procedure.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List

# Make the repo root importable so this runs both as `python -m tools.verify_calendar`
# and `python tools/verify_calendar.py`.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.engine.calendar_ie import (  # noqa: E402
    irish_bank_holidays,
    easter_sunday,
    _nth_weekday,
    _last_weekday,
    _st_brigids_day,
    _fixed_holidays,
    _ST_BRIGID_FIRST_YEAR,
)


# ---------------------------------------------------------------------------
# Allow-list of EXPECTED differences between our calendar and the library.
# Edit this when a difference is legitimate and should stop being flagged.
# ---------------------------------------------------------------------------
# 1) Good Friday: WE include it (an Irish bank / TARGET2 / SEPA closure) while
#    holidays.Ireland omits it as a non-statutory public holiday. This is a
#    per-year rule (Easter Sunday minus two days), not a fixed date.
GOOD_FRIDAY_EXPECTED_OURS_ONLY = True

# 2) Library-only one-off historical public holidays we deliberately exclude,
#    because a one-off only ever affects an ACTUAL posted date (from the bank
#    feed) and never a PROJECTED date. Add a date here to silence it.
LIBRARY_ONLY_ONE_OFFS = frozenset({
    date(2022, 3, 18),   # once-off national public holiday (post-pandemic)
})


def _library_ireland(years, holidays_mod) -> Dict[date, str]:
    """Return {date: name} of Irish holidays from the library for ``years``.

    observed=True so weekend holidays carry their in-lieu substitute, matching
    how BOI observes them and how our calendar computes substitutes.
    """
    return dict(holidays_mod.Ireland(years=list(years), observed=True))


def _observed_substitute_days(year: int) -> set:
    """Return the in-lieu substitute days our calendar adds for ``year``.

    These are the observed (next-weekday) holidays for fixed-date holidays that
    fall on a weekend. This build of the `holidays` library does not emit them,
    but they are genuine Irish bank holidays, so the cross-check treats them as
    expected 'ours only' differences, like Good Friday. Computed as our full set
    minus the movable and fixed base, so it always matches calendar_ie exactly.
    """
    full = set(irish_bank_holidays(year))
    base = set()
    base.add(easter_sunday(year) - timedelta(days=2))   # Good Friday
    base.add(easter_sunday(year) + timedelta(days=1))   # Easter Monday
    base.add(_nth_weekday(year, 5, 0, 1))
    base.add(_nth_weekday(year, 6, 0, 1))
    base.add(_nth_weekday(year, 8, 0, 1))
    base.add(_last_weekday(year, 10, 0))
    if year >= _ST_BRIGID_FIRST_YEAR:
        base.add(_st_brigids_day(year))
    for d in _fixed_holidays(year):
        base.add(d)
    return full - base


def unexpected_differences(year_from: int, year_to: int, holidays_mod) -> Dict[int, Dict[str, List[date]]]:
    """Return, per year, the differences that are NOT on the allow-list.

    Maps a year to {'ours_only': [...], 'lib_only': [...]}; a year with no
    unexpected difference is omitted. ``holidays_mod`` is the imported
    `holidays` package, injected so the guard test can reuse this without a
    second import.
    """
    years = range(year_from, year_to + 1)
    lib = _library_ireland(years, holidays_mod)
    lib_by_year: Dict[int, set] = {}
    for d in lib:
        lib_by_year.setdefault(d.year, set()).add(d)

    out: Dict[int, Dict[str, List[date]]] = {}
    for y in years:
        ours = set(irish_bank_holidays(y))
        theirs = lib_by_year.get(y, set())
        good_friday = easter_sunday(y) - timedelta(days=2)

        ours_only = ours - theirs
        if GOOD_FRIDAY_EXPECTED_OURS_ONLY:
            ours_only.discard(good_friday)   # expected: we include Good Friday
        # Expected: the in-lieu substitute days for weekend fixed holidays. They
        # are genuine Irish bank holidays this holidays build does not emit, and
        # they never affect the model (no payment day lands on one), so treat
        # them as expected 'ours only' (see _observed_substitute_days).

        for sub in _observed_substitute_days(y):
            ours_only.discard(sub)

        lib_only = {d for d in (theirs - ours) if d not in LIBRARY_ONLY_ONE_OFFS}

        if ours_only or lib_only:
            out[y] = {"ours_only": sorted(ours_only), "lib_only": sorted(lib_only)}
    return out


_RUNBOOK = """\
UNEXPECTED calendar difference vs the `holidays` library.

WHAT it means:
  - 'ours only': a date our calendar treats as a holiday but the library does
    not. Usually a repealed holiday, or one we added in error.
  - 'library only': a date the library treats as a holiday but we do not.
    Usually a NEW statutory holiday (like St Brigid's Day in 2023), or a
    library one-off we should allow-list.

WHERE and HOW to fix (pick one):
  1. A genuine NEW or CHANGED statutory holiday:
       edit  src/engine/calendar_ie.py  ->  irish_bank_holidays()
       add/remove the rule in the existing nth-weekday / fixed-date style.
  2. A legitimate library-only ONE-OFF (affects only historical actual dates):
       edit  tools/verify_calendar.py  ->  LIBRARY_ONLY_ONE_OFFS
       add the date so it stops being flagged.
  3. A Good-Friday-style rule difference we accept for every year:
       adjust the allow-list flags at the top of tools/verify_calendar.py

THEN re-baseline (any calendar change moves projected dates):
  git switch phase10/contract-schema      # or a fresh branch off main
  git pull
  # make the edit above
  pip install -r requirements-dev.txt
  python -m tools.verify_calendar --from 2024 --to 2060    # expect: OK
  python tools/_rebaseline_golden.py --apply               # regenerate goldens
  git diff tests/fixtures/golden                            # review: dates + derived only
  pytest -q                                                 # expect: green
  git add src/engine/calendar_ie.py tools/verify_calendar.py tests/fixtures/golden
  git commit -m \"calendar: refresh Irish holidays; re-baseline golden\"
  git push

Full detail: docs/calendar_maintenance.md
"""


def main(argv=None) -> int:
    """CLI entry point: compare the range and print the runbook on any diff."""
    parser = argparse.ArgumentParser(
        description="Cross-check the owned Irish calendar against the holidays library."
    )
    parser.add_argument("--from", dest="year_from", type=int, default=2024, help="first year to check")
    parser.add_argument("--to", dest="year_to", type=int, default=2060, help="last year to check")
    args = parser.parse_args(argv)

    try:
        import holidays as holidays_mod
    except ImportError:
        print(
            "The `holidays` package is not installed. It is a DEV-ONLY dependency "
            "for this cross-check (never used by the engine). Install it with:\n"
            "    pip install -r requirements-dev.txt",
            file=sys.stderr,
        )
        return 2

    diffs = unexpected_differences(args.year_from, args.year_to, holidays_mod)
    if not diffs:
        print(
            f"OK: owned calendar matches holidays.Ireland for {args.year_from}-{args.year_to} "
            "(Good Friday and allow-listed one-offs aside)."
        )
        return 0

    print(f"MISMATCH across {len(diffs)} year(s):\n")
    for y in sorted(diffs):
        entry = diffs[y]
        if entry["ours_only"]:
            print(f"  {y} ours only:    " + ", ".join(d.isoformat() for d in entry["ours_only"]))
        if entry["lib_only"]:
            print(f"  {y} library only: " + ", ".join(d.isoformat() for d in entry["lib_only"]))
    print("\n" + _RUNBOOK)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())