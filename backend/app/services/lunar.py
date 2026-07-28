from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Literal

from lunardate import LunarDate

from app.models import Reminder


MIN_LUNAR_YEAR = 1901
MAX_LUNAR_YEAR = 2099
LeapMonthPolicy = Literal["skip", "regular_month"]
MissingDayPolicy = Literal["last_day", "skip"]


def _safe_solar_date(year: int, month: int, day: int) -> date:
    last_day = monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _validate_lunar_year(year: int) -> None:
    if not MIN_LUNAR_YEAR <= year <= MAX_LUNAR_YEAR:
        raise ValueError(
            f"Lunar year must be between {MIN_LUNAR_YEAR} and {MAX_LUNAR_YEAR}: {year}"
        )


def lunar_to_solar(year: int, month: int, day: int, is_leap_month: bool) -> date:
    """Strictly convert a lunar date without changing its day or month."""
    _validate_lunar_year(year)
    if not 1 <= month <= 12:
        raise ValueError(f"Invalid lunar month: {month}")
    if not 1 <= day <= 30:
        raise ValueError(f"Invalid lunar day: {day}")
    return LunarDate(year, month, day, isLeapMonth=is_leap_month).toSolarDate()


def lunar_year_for_solar_date(day: date) -> int:
    """Return the lunar year containing a supported solar date."""
    lunar_day = LunarDate.fromSolarDate(day.year, day.month, day.day)
    _validate_lunar_year(lunar_day.year)
    return lunar_day.year


def _lunar_month_exists(year: int, month: int, is_leap_month: bool) -> bool:
    try:
        lunar_to_solar(year, month, 1, is_leap_month)
    except ValueError:
        return False
    return True


def _last_day_of_lunar_month(year: int, month: int, is_leap_month: bool) -> date:
    """Resolve the last day only when the caller explicitly chose last_day."""
    for candidate_day in range(30, 0, -1):
        try:
            return lunar_to_solar(year, month, candidate_day, is_leap_month)
        except ValueError:
            continue
    raise ValueError(f"Invalid lunar month: {year}-{month}, leap={is_leap_month}")


def lunar_to_solar_with_policy(
    year: int,
    month: int,
    day: int,
    is_leap_month: bool,
    *,
    leap_month_policy: LeapMonthPolicy = "skip",
    missing_day_policy: MissingDayPolicy = "last_day",
) -> date | None:
    """Resolve a recurring lunar date using its explicit, persisted policies.

    ``None`` means this lunar year has no occurrence.  The strict converter is
    always attempted first: a fallback is only applied for the corresponding
    policy, never implicitly.
    """
    if leap_month_policy not in ("skip", "regular_month"):
        raise ValueError(f"Unsupported leap_month_policy: {leap_month_policy}")
    if missing_day_policy not in ("last_day", "skip"):
        raise ValueError(f"Unsupported missing_day_policy: {missing_day_policy}")

    _validate_lunar_year(year)
    if not 1 <= month <= 12:
        raise ValueError(f"Invalid lunar month: {month}")

    selected_is_leap = is_leap_month
    if is_leap_month and not _lunar_month_exists(year, month, True):
        if leap_month_policy == "skip":
            return None
        selected_is_leap = False

    try:
        return lunar_to_solar(year, month, day, selected_is_leap)
    except ValueError:
        if missing_day_policy == "skip":
            return None
        return _last_day_of_lunar_month(year, month, selected_is_leap)


def _recurring_lunar_policies(reminder: Reminder) -> tuple[LeapMonthPolicy, MissingDayPolicy]:
    # Defaults preserve the persisted model defaults for callers that construct
    # lightweight Reminder-like objects in tests or migration tooling.
    return (
        getattr(reminder, "leap_month_policy", "skip"),
        getattr(reminder, "missing_day_policy", "last_day"),
    )


def target_date_for_year(reminder: Reminder, year: int) -> date:
    if reminder.calendar_type == "solar":
        try:
            return date(year, reminder.month, reminder.day)
        except ValueError:
            if not reminder.is_recurring or getattr(reminder, "missing_day_policy", "last_day") == "skip":
                raise
            return _safe_solar_date(year, reminder.month, reminder.day)
    if reminder.calendar_type != "lunar":
        raise ValueError(f"Unsupported calendar_type: {reminder.calendar_type}")

    # One-off reminders are intentionally strict: policies only describe how a
    # recurring reminder should behave in a different lunar year.
    if not reminder.is_recurring:
        return lunar_to_solar(year, reminder.month, reminder.day, reminder.is_leap_month)

    leap_month_policy, missing_day_policy = _recurring_lunar_policies(reminder)
    target = lunar_to_solar_with_policy(
        year,
        reminder.month,
        reminder.day,
        reminder.is_leap_month,
        leap_month_policy=leap_month_policy,
        missing_day_policy=missing_day_policy,
    )
    if target is None:
        raise ValueError(f"No lunar occurrence for {year}-{reminder.month}-{reminder.day}")
    return target


def candidate_target_dates(
    reminder: Reminder,
    from_year: int,
    years_ahead: int = 2,
    *,
    not_before: date | None = None,
) -> list[date]:
    """Return upcoming recurrence candidates.

    For lunar reminders ``from_year`` is a lunar year.  We scan through 2099
    until the requested number of *valid future* occurrences is found, so a
    skipped leap month does not shorten the planning horizon.
    """
    if not reminder.is_recurring:
        if reminder.event_year is None:
            return []
        try:
            target = target_date_for_year(reminder, reminder.event_year)
            if not_before is not None and target < not_before:
                return []
            return [target]
        except ValueError:
            return []

    valid_dates: list[date] = []
    desired_count = years_ahead + 1
    for year in range(max(from_year, MIN_LUNAR_YEAR), MAX_LUNAR_YEAR + 1):
        try:
            target = target_date_for_year(reminder, year)
        except ValueError:
            continue
        if not_before is not None and target < not_before:
            continue
        valid_dates.append(target)
        if len(valid_dates) >= desired_count:
            break
    return valid_dates
