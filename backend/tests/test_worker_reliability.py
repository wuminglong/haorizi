from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select

from app.models import Group, Reminder, ReminderPlan, ReminderRule, SendLog
from app.services.pushplus import PushPlusClient, PushPlusSendError
from app.services.reminders import run_due_reminders_once


def _due_plan(db_session, *, title: str, status: str = "pending", started_at=None) -> int:
    group = Group(name=f"{title}群", code=f"CODE{title}", push_topic_code=f"topic-{title}")
    reminder = Reminder(
        group=group,
        title=title,
        calendar_type="solar",
        month=12,
        day=31,
        is_recurring=True,
        enabled=True,
    )
    reminder.rule = ReminderRule(remind_time=time(9), advance_days=0, include_on_day=True)
    plan = ReminderPlan(
        group=group,
        reminder=reminder,
        target_date=date(2026, 12, 31),
        due_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        kind="on_day",
        status=status,
        processing_started_at=started_at,
    )
    db_session.add(plan)
    db_session.commit()
    return plan.id


def test_due_worker_claims_and_sends_with_redacted_log(db_session) -> None:
    plan_id = _due_plan(db_session, title="成功")
    sent = run_due_reminders_once(db_session, now=datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert sent == 1
    plan = db_session.get(ReminderPlan, plan_id)
    assert plan is not None and plan.status == "sent"
    assert plan.processing_started_at is None
    log = db_session.scalar(select(SendLog).where(SendLog.plan_id == plan_id))
    assert log is not None
    assert log.request_payload["token"] == "***"


def test_one_provider_failure_does_not_rollback_the_batch(db_session, monkeypatch) -> None:
    failed_id = _due_plan(db_session, title="失败")
    sent_id = _due_plan(db_session, title="继续")

    def fake_send(self, group, reminder, plan):
        if reminder.title == "失败":
            raise PushPlusSendError("timeout", "连接超时", request_payload={"token": "***"})
        return {"token": "***"}, {"code": 200}

    monkeypatch.setattr(PushPlusClient, "send_group_reminder", fake_send)
    sent = run_due_reminders_once(db_session, now=datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert sent == 1
    failed = db_session.get(ReminderPlan, failed_id)
    success = db_session.get(ReminderPlan, sent_id)
    assert failed is not None and failed.status == "pending" and failed.attempt_count == 1
    assert success is not None and success.status == "sent"
    assert db_session.scalar(select(SendLog).where(SendLog.plan_id == failed_id)) is not None


def test_stale_processing_plan_is_recovered(db_session) -> None:
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    plan_id = _due_plan(
        db_session,
        title="恢复",
        status="processing",
        started_at=now - timedelta(hours=1),
    )
    assert run_due_reminders_once(db_session, now=now) == 1
    plan = db_session.get(ReminderPlan, plan_id)
    assert plan is not None and plan.status == "sent" and plan.processing_started_at is None
