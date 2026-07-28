from __future__ import annotations

from datetime import date, datetime, time, timezone

from app.models import Group, Reminder, ReminderRule
from app.services.plans import (
    build_plan_drafts,
    regenerate_all_enabled_plans,
    regenerate_reminder_plans,
)


def test_build_plan_drafts_advance_and_on_day() -> None:
    rule = ReminderRule(remind_time=time(9, 0), advance_days=7, include_on_day=True)
    drafts = build_plan_drafts(date(2026, 5, 24), rule, "Asia/Shanghai")
    assert [d.kind for d in drafts] == ["advance", "on_day"]
    assert [d.due_at for d in drafts] == [
        datetime(2026, 5, 17, 1, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 24, 1, 0, tzinfo=timezone.utc),
    ]


def test_only_on_day() -> None:
    rule = ReminderRule(remind_time=time(9, 0), advance_days=0, include_on_day=True)
    drafts = build_plan_drafts(date(2026, 5, 24), rule, "Asia/Shanghai")
    assert len(drafts) == 1
    assert drafts[0].kind == "on_day"


def test_regenerate_creates_pending_plans(db_session) -> None:
    group = Group(name="g", code="FAMILY01", push_topic_code="family001", code_updated_at=datetime.now(timezone.utc))
    reminder = Reminder(
        group=group,
        title="妈妈生日",
        calendar_type="solar",
        event_year=2026,
        month=12,
        day=31,
        is_recurring=False,
        enabled=True,
    )
    reminder.rule = ReminderRule(remind_time=time(9, 0), advance_days=7, include_on_day=True)
    db_session.add(reminder)
    db_session.flush()

    plans = regenerate_reminder_plans(
        db_session,
        reminder,
        now=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
    )
    assert len(plans) == 2
    assert {p.kind for p in plans} == {"advance", "on_day"}

    db_session.commit()
    assert regenerate_all_enabled_plans(
        db_session,
        now=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
    ) == 0
