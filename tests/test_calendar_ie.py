# tests/test_calendar_ie.py
"""Unit tests for the owned Irish business-day calendar (Phase 10 / S4).

Pure and offline: these lock the calendar's rule-based dates and the Modified
Following convention against known-good values, so a future edit that breaks a
rule fails here immediately. The library cross-check lives separately in
tests/test_calendar_cross_check.py (skipped unless ``holidays`` is installed).
"""
from __future__ import annotations

from datetime import date
import types

from src.engine.calendar_ie import (
    easter_sunday,
    irish_bank_holidays,
    is_business_day,
    modified_following,
    adjust_for_convention,
)
from src.engine.monthly import _payment_convention_on


def test_easter_sunday_known_years():
    """Computus reproduces published Easter Sundays."""
    assert easter_sunday(2024) == date(2024, 3, 31)
    assert easter_sunday(2025) == date(2025, 4, 20)
    assert easter_sunday(2026) == date(2026, 4, 5)


def test_good_friday_and_easter_monday_are_holidays():
    """Good Friday (Easter - 2) and Easter Monday (Easter + 1) are non-working."""
    hols = irish_bank_holidays(2025)
    assert date(2025, 4, 18) in hols   # Good Friday
    assert date(2025, 4, 21) in hols   # Easter Monday


def test_st_patricks_weekend_substitute_2024():
    """17 Mar 2024 is a Sunday, so Monday 18 Mar is the observed substitute."""
    hols = irish_bank_holidays(2024)
    assert date(2024, 3, 17) in hols
    assert date(2024, 3, 18) in hols


def test_christmas_run_substitutes_2021():
    """25 Dec 2021 Sat and 26 Dec 2021 Sun give substitutes 27 and 28 Dec."""
    hols = irish_bank_holidays(2021)
    assert {date(2021, 12, 27), date(2021, 12, 28)} <= hols


def test_st_brigid_rule_and_start_year():
    """St Brigid's Day follows the first-Monday rule and only exists from 2023."""
    # 2024: 1 Feb is Thursday -> first Monday, 5 Feb 2024.
    assert date(2024, 2, 5) in irish_bank_holidays(2024)
    # 2025: 1 Feb is Saturday -> first Monday, 3 Feb 2025.
    assert date(2025, 2, 3) in irish_bank_holidays(2025)
    # Before 2023 it did not exist: the first Monday of Feb 2022 (7 Feb) is not
    # a holiday.
    assert date(2022, 2, 7) not in irish_bank_holidays(2022)


def test_first_feb_friday_is_st_brigid():
    """When 1 February is a Friday, the holiday is 1 February itself."""
    # 1 February 2030 is a Friday.
    assert date(2030, 2, 1).weekday() == 4
    assert date(2030, 2, 1) in irish_bank_holidays(2030)


def test_is_business_day_weekend_and_holiday():
    """Weekends and holidays are non-working; an ordinary Friday is working."""
    assert not is_business_day(date(2025, 8, 30))   # Saturday
    assert not is_business_day(date(2025, 8, 31))   # Sunday
    assert not is_business_day(date(2025, 12, 25))  # Christmas Day
    assert is_business_day(date(2025, 8, 29))       # Friday, not a holiday


def test_modified_following_rolls_forward():
    """A Saturday mid-month rolls forward to the next working day."""
    # 5 July 2025 is a Saturday; next working day is Monday 7 July.
    assert modified_following(date(2025, 7, 5)) == date(2025, 7, 7)


def test_modified_following_rolls_back_at_month_end():
    """A weekend month-end rolls back rather than into the next month."""
    # 31 Aug 2025 is a Sunday; forward would cross into September, so it rolls
    # back to the last working day of August, Friday 29 Aug.
    assert modified_following(date(2025, 8, 31)) == date(2025, 8, 29)


def test_modified_following_noop_on_business_day():
    """A working day is returned unchanged."""
    assert modified_following(date(2025, 7, 7)) == date(2025, 7, 7)


def test_adjust_for_convention_day_clamp_is_noop():
    """day_clamp and any unknown convention leave the date unchanged."""
    weekend = date(2025, 7, 5)
    assert adjust_for_convention(weekend, "day_clamp") == weekend
    assert adjust_for_convention(weekend, "unknown_value") == weekend


def test_adjust_for_convention_modified_following():
    """modified_following applies the Irish working-day rule."""
    assert adjust_for_convention(date(2025, 7, 5), "modified_following") == date(2025, 7, 7)


def test_payment_convention_defaults_to_day_clamp_without_profile():
    """No resolved profile means the historical day_clamp behaviour."""
    stub = types.SimpleNamespace(profile=None)
    assert _payment_convention_on(stub, date(2030, 1, 5)) == "day_clamp"


def test_payment_convention_reads_profile():
    """A resolved profile supplies the convention for the anchor date."""
    rule = types.SimpleNamespace(payment_date_convention="modified_following")
    profile = types.SimpleNamespace(rule_on=lambda anchor: rule)
    stub = types.SimpleNamespace(profile=profile)
    assert _payment_convention_on(stub, date(2030, 1, 5)) == "modified_following"