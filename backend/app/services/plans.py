from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload

from app.models import Reminder, ReminderPlan, ReminderRule
from app.services.lunar import candidate_target_dates, lunar_year_for_solar_date


@dataclass(frozen=True)
class PlanDraft:
    target_date: date
    due_at: datetime
    kind: str


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def combine_local(day: date, remind_time: time, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name or "Asia/Shanghai")
    local_dt = datetime.combine(day, remind_time, tzinfo=tz)
    return local_dt.astimezone(timezone.utc)


def group_local_date(now: datetime, tz_name: str) -> date:
    tz = ZoneInfo(tz_name or "Asia/Shanghai")
    return normalize_datetime(now).astimezone(tz).date()


def build_plan_drafts(target_date: date, rule: ReminderRule, tz_name: str) -> list[PlanDraft]:
    drafts: list[PlanDraft] = []
    if rule.advance_days > 0:
        due_day = target_date - timedelta(days=rule.advance_days)
        drafts.append(
            PlanDraft(
                target_date=target_date,
                due_at=combine_local(due_day, rule.remind_time, tz_name),
                kind="advance",
            )
        )
    if rule.include_on_day:
        drafts.append(
            PlanDraft(
                target_date=target_date,
                due_at=combine_local(target_date, rule.remind_time, tz_name),
                kind="on_day",
            )
        )
    # de-dupe identical due points preferring on_day
    by_due: dict[datetime, PlanDraft] = {}
    for draft in drafts:
        existing = by_due.get(draft.due_at)
        if existing is None or draft.kind == "on_day":
            by_due[draft.due_at] = draft
    return sorted(by_due.values(), key=lambda item: item.due_at)


def cancel_unsent_plans(db: Session, reminder_id: int) -> None:
    db.execute(
        update(ReminderPlan)
        .where(ReminderPlan.reminder_id == reminder_id)
        .where(ReminderPlan.status.in_(["pending", "failed"]))
        .values(status="cancelled")
    )


def load_existing_plans(
    db: Session,
    reminder_id: int,
) -> dict[tuple[date, str], ReminderPlan]:
    rows = db.scalars(
        select(ReminderPlan).where(
            ReminderPlan.reminder_id == reminder_id,
        )
    ).all()
    return {(row.target_date, row.kind): row for row in rows}


def regenerate_reminder_plans(
    db: Session,
    reminder: Reminder,
    now: datetime | None = None,
    *,
    cancel_existing: bool = True,
) -> list[ReminderPlan]:
    from app.config import get_settings

    now = normalize_datetime(now or datetime.now(timezone.utc))
    if cancel_existing:
        cancel_unsent_plans(db, reminder.id)

    if not reminder.enabled or reminder.deleted_at is not None or not reminder.rule:
        db.flush()
        return []

    group = reminder.group
    tz_name = group.timezone if group else "Asia/Shanghai"
    today = group_local_date(now, tz_name)
    existing_plans = load_existing_plans(db, reminder.id)
    created: list[ReminderPlan] = []

    from_year = (
        lunar_year_for_solar_date(today)
        if reminder.calendar_type == "lunar" and reminder.is_recurring
        else today.year
    )
    for target in candidate_target_dates(
        reminder,
        from_year,
        years_ahead=2,
        not_before=today,
    ):
        for draft in build_plan_drafts(target, reminder.rule, tz_name):
            due_at = draft.due_at
            if due_at < now and draft.target_date >= today:
                due_at = now
            existing = existing_plans.get((draft.target_date, draft.kind))
            if existing is not None:
                # The database keeps one plan per target/kind across every
                # status.  On an edit, reuse a cancelled/failed plan instead
                # of inserting a duplicate; sent plans remain immutable.
                if not cancel_existing or existing.status == "sent":
                    continue
                existing.due_at = due_at
                existing.status = "pending"
                existing.attempt_count = 0
                existing.max_attempts = get_settings().reminder_max_attempts
                existing.sent_at = None
                existing.processing_started_at = None
                existing.last_error_code = None
                existing.last_error_message = None
                created.append(existing)
                continue
            plan = ReminderPlan(
                group_id=reminder.group_id,
                reminder_id=reminder.id,
                target_date=draft.target_date,
                due_at=due_at,
                kind=draft.kind,
                status="pending",
                max_attempts=get_settings().reminder_max_attempts,
            )
            db.add(plan)
            created.append(plan)
    db.flush()
    return created


def regenerate_all_enabled_plans(db: Session, now: datetime | None = None) -> int:
    reminders = db.scalars(
        select(Reminder)
        .options(
            joinedload(Reminder.rule),
            joinedload(Reminder.group),
        )
        .where(Reminder.deleted_at.is_(None))
        .where(Reminder.enabled.is_(True))
    ).unique().all()
    count = 0
    for reminder in reminders:
        count += len(
            regenerate_reminder_plans(
                db,
                reminder,
                now=now,
                cancel_existing=False,
            )
        )
    db.commit()
    return count
