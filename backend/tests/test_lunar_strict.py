from __future__ import annotations

from datetime import date

import pytest

from app.models import Reminder
from app.services.lunar import (
    candidate_target_dates,
    lunar_to_solar,
    lunar_to_solar_with_policy,
    lunar_year_for_solar_date,
)
from app.services.reminders import next_upcoming_date


def recurring_lunar_reminder(**overrides) -> Reminder:
    values = {
        "title": "农历提醒",
        "calendar_type": "lunar",
        "month": 4,
        "day": 8,
        "is_leap_month": True,
        "is_recurring": True,
        "enabled": True,
        "leap_month_policy": "skip",
        "missing_day_policy": "last_day",
    }
    values.update(overrides)
    return Reminder(**values)


def test_lunar_year_range_is_1901_to_2099() -> None:
    assert lunar_to_solar(1901, 1, 1, False) == date(1901, 2, 19)
    assert lunar_to_solar(2099, 1, 1, False) == date(2099, 1, 21)
    with pytest.raises(ValueError, match="1901 and 2099"):
        lunar_to_solar(1900, 1, 1, False)
    with pytest.raises(ValueError, match="1901 and 2099"):
        lunar_to_solar(2100, 1, 1, False)


def test_leap_month_policy_is_explicit() -> None:
    assert lunar_to_solar_with_policy(2021, 4, 8, True, leap_month_policy="skip") is None
    assert lunar_to_solar_with_policy(
        2021,
        4,
        8,
        True,
        leap_month_policy="regular_month",
    ) == lunar_to_solar(2021, 4, 8, False)


def test_missing_lunar_day_policy_is_explicit() -> None:
    # 2020's leap fourth month has 29 days.
    assert lunar_to_solar_with_policy(
        2020,
        4,
        30,
        True,
        missing_day_policy="skip",
    ) is None
    assert lunar_to_solar_with_policy(
        2020,
        4,
        30,
        True,
        missing_day_policy="last_day",
    ) == lunar_to_solar(2020, 4, 29, True)


def test_recurring_lunar_candidates_search_past_skipped_years() -> None:
    reminder = recurring_lunar_reminder()
    candidates = candidate_target_dates(reminder, 2020, years_ahead=2)
    assert len(candidates) == 3
    assert candidates[0] == lunar_to_solar(2020, 4, 8, True)
    assert candidates == sorted(candidates)


def test_next_lunar_date_uses_the_lunar_year_at_shanghai_new_year_boundary() -> None:
    reminder = recurring_lunar_reminder(month=11, day=20, is_leap_month=False)
    today = date(2026, 1, 1)
    assert lunar_year_for_solar_date(today) == 2025
    assert next_upcoming_date(reminder, today=today) == date(2026, 1, 8)


def test_lunar_twelfth_month_is_not_skipped_before_spring_festival() -> None:
    reminder = recurring_lunar_reminder(month=12, day=20, is_leap_month=False)
    assert next_upcoming_date(reminder, today=date(2026, 1, 1)) == date(2026, 2, 7)


def test_one_off_lunar_reminder_does_not_apply_recurrence_policies() -> None:
    reminder = recurring_lunar_reminder(
        event_year=2021,
        is_recurring=False,
        leap_month_policy="regular_month",
    )
    assert candidate_target_dates(reminder, 2021) == []


def test_recurring_solar_february_29_uses_explicit_missing_day_policy() -> None:
    last_day = Reminder(
        title="闰日",
        calendar_type="solar",
        month=2,
        day=29,
        is_recurring=True,
        enabled=True,
        missing_day_policy="last_day",
    )
    skipped = Reminder(
        title="闰日",
        calendar_type="solar",
        month=2,
        day=29,
        is_recurring=True,
        enabled=True,
        missing_day_policy="skip",
    )
    assert candidate_target_dates(last_day, 2025, years_ahead=0) == [date(2025, 2, 28)]
    assert candidate_target_dates(skipped, 2025, years_ahead=0) == [date(2028, 2, 29)]
