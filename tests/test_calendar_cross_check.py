# tests/test_calendar_cross_check.py
"""Optional guard: cross-check the owned calendar against `holidays`.

Skipped automatically when the dev-only `holidays` package is not installed, so
the normal suite and a fresh clone never depend on it. Install it
(`pip install -r requirements-dev.txt`) and this test actively enforces that the
owned calendar matches holidays.Ireland across the projection range.
"""
from __future__ import annotations

import pytest

# Skip the whole module cleanly when the dev-only library is absent.
holidays_mod = pytest.importorskip("holidays")

from tools.verify_calendar import unexpected_differences  # noqa: E402


def test_owned_calendar_matches_library_2024_2060():
    """No UNEXPECTED difference vs holidays.Ireland across the projection range."""
    diffs = unexpected_differences(2024, 2060, holidays_mod)
    assert not diffs, (
        "Owned Irish calendar diverged from holidays.Ireland. Run\n"
        "    python -m tools.verify_calendar --from 2024 --to 2060\n"
        "for the exact dates and the fix + golden-rebaseline runbook, or see "
        "docs/calendar_maintenance.md. Divergences: " + str(diffs)
    )