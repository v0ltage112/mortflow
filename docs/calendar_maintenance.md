# Irish calendar maintenance and golden re-baseline

The engine's projected repayment dates use an owned Irish business-day calendar,
`src/engine/calendar_ie.py`. It is hand-maintained on purpose: the golden master
must be deterministic and offline, so the engine never imports the third-party
`holidays` package. This doc is the runbook for keeping it correct over the life
of the model (the schedule projects to ~2059).

## When to check

- On a hunch that an Irish holiday rule changed (the last change was St Brigid's
  Day in 2023).
- Before a release, as a periodic sanity check.

## How to check (cross-check against the library)

    pip install -r requirements-dev.txt
    python -m tools.verify_calendar --from 2024 --to 2060

- Clean run: prints `OK: ...` and exits 0. Nothing to do.
- Divergence: prints the exact dates and a remediation runbook, and exits 1.
  The optional guard test `tests/test_calendar_cross_check.py` runs the same
  check (skipped automatically when `holidays` is not installed).

## How to interpret and fix a divergence

The tool reports two kinds of difference:

- "ours only": a date we treat as a holiday but the library does not. Usually a
  repealed holiday, or one we added in error.
- "library only": a date the library treats as a holiday but we do not. Usually
  a NEW statutory holiday, or a library one-off we should allow-list.

Pick the matching fix:

1. A genuine new or changed statutory holiday ->
   edit `src/engine/calendar_ie.py`, function `irish_bank_holidays()`. Add or
   remove the rule using the existing `_nth_weekday` / `_last_weekday` /
   fixed-date style. St Brigid's Day is the worked example of adding one.
2. A legitimate library one-off (a special day that only ever affects a
   historical actual date, never a projected one) ->
   edit `tools/verify_calendar.py`, `LIBRARY_ONLY_ONE_OFFS`, adding the date so
   it stops being flagged. Do NOT add it to `calendar_ie.py`.
3. A Good-Friday-style rule we accept every year ->
   adjust the allow-list flags at the top of `tools/verify_calendar.py`.

Good Friday is intentionally ours-only (a bank / TARGET2 / SEPA closure the
library omits as non-statutory) and is already allow-listed, so it is never
flagged.

## Any calendar change requires a golden re-baseline

Changing the calendar moves projected payment dates, which moves the derived
projected columns (interest, principal, balance, payoff) in the golden. That is
expected. Re-baseline in one reviewed commit:

    git switch phase10/contract-schema        # or a fresh working branch off main
    git pull
    # 1. make the calendar edit above
    pip install -r requirements-dev.txt
    python -m tools.verify_calendar --from 2024 --to 2060   # expect: OK
    pytest -q                                                # golden FAILS (dates moved) - expected
    python tools/_rebaseline_golden.py                       # dry run: lists fixtures that will change
    python tools/_rebaseline_golden.py --apply               # regenerate the fixtures
    git diff tests/fixtures/golden                            # review: changes confined to projected dates + derived columns
    pytest -q                                                 # expect: green
    git add src/engine/calendar_ie.py tools/verify_calendar.py tests/fixtures/golden
    git commit -m "calendar: refresh Irish holidays; re-baseline golden"
    git push

`tools/_rebaseline_golden.py` is a throwaway helper: keep it out of commits
(delete it after use) unless you decide to make it a permanent tool.

## Why owned, not the library

The `holidays` package encodes the same rules, but its data can shift between
releases, which would move the golden on an unrelated upgrade. Owning ~50 tested
lines keeps every calendar change deliberate and offline. The library stays a
dev-only cross-check, never a runtime dependency.