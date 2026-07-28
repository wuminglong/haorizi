from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.admin_schemas import AdminReminderCreate, AdminReminderPayload
from app.models import Group, Reminder, ReminderPlan, ReminderRule, SendLog, utc_now
from app.services.plans import regenerate_reminder_plans
from app.services.reminders import build_date_text, build_rule_text, next_upcoming_date


def _page(page: int, page_size: int, total: int, items: list[dict]) -> dict:
    return {"items": items, "page": page, "page_size": page_size, "total": total}


def _reminder_options():
    return (joinedload(Reminder.group), joinedload(Reminder.rule))


def get_admin_reminder(db: Session, reminder_id: int, *, include_deleted: bool = False) -> Reminder | None:
    stmt = select(Reminder).options(*_reminder_options()).where(Reminder.id == reminder_id)
    if not include_deleted:
        stmt = stmt.where(Reminder.deleted_at.is_(None))
    return db.scalar(stmt)


def serialize_reminder(reminder: Reminder) -> dict:
    rule = reminder.rule
    assert rule is not None
    return {
        "id": reminder.id,
        "group_id": reminder.group_id,
        "group_name": reminder.group.name if reminder.group else "",
        "title": reminder.title,
        "person_name": reminder.person_name,
        "calendar_type": reminder.calendar_type,
        "event_year": reminder.event_year,
        "month": reminder.month,
        "day": reminder.day,
        "is_leap_month": reminder.is_leap_month,
        "leap_month_policy": reminder.leap_month_policy,
        "missing_day_policy": reminder.missing_day_policy,
        "is_recurring": reminder.is_recurring,
        "enabled": reminder.enabled,
        "remark": reminder.remark,
        "deleted_at": reminder.deleted_at,
        "upcoming_date": next_upcoming_date(reminder),
        "date_text": build_date_text(reminder),
        "rule": {
            "remind_time": rule.remind_time,
            "advance_days": rule.advance_days,
            "include_on_day": rule.include_on_day,
        },
        "rule_text": build_rule_text(rule),
        "created_at": reminder.created_at,
        "updated_at": reminder.updated_at,
    }


def list_admin_reminders(
    db: Session,
    *,
    page: int,
    page_size: int,
    group_id: int | None = None,
    query: str | None = None,
    enabled: bool | None = None,
    include_deleted: bool = False,
) -> dict:
    filters = []
    if group_id is not None:
        filters.append(Reminder.group_id == group_id)
    if not include_deleted:
        filters.append(Reminder.deleted_at.is_(None))
    if enabled is not None:
        filters.append(Reminder.enabled.is_(enabled))
    if query and query.strip():
        keyword = f"%{query.strip()}%"
        filters.append(or_(Reminder.title.ilike(keyword), Reminder.person_name.ilike(keyword)))
    total = db.scalar(select(func.count(Reminder.id)).where(*filters)) or 0
    rows = db.scalars(
        select(Reminder)
        .options(*_reminder_options())
        .where(*filters)
        .order_by(Reminder.updated_at.desc(), Reminder.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).unique().all()
    return _page(page, page_size, total, [serialize_reminder(row) for row in rows])


def _apply_reminder_payload(reminder: Reminder, payload: AdminReminderPayload) -> None:
    reminder.title = payload.title.strip()
    reminder.person_name = payload.person_name
    reminder.calendar_type = payload.calendar_type
    reminder.event_year = payload.event_year
    reminder.month = payload.month
    reminder.day = payload.day
    reminder.is_leap_month = payload.is_leap_month
    reminder.leap_month_policy = payload.leap_month_policy
    reminder.missing_day_policy = payload.missing_day_policy
    reminder.is_recurring = payload.is_recurring
    reminder.enabled = payload.enabled
    reminder.remark = payload.remark
    if reminder.rule is None:
        reminder.rule = ReminderRule()
    reminder.rule.remind_time = payload.rule.remind_time
    reminder.rule.advance_days = payload.rule.advance_days
    reminder.rule.include_on_day = payload.rule.include_on_day


def create_admin_reminder(db: Session, payload: AdminReminderCreate) -> Reminder | None:
    group = db.get(Group, payload.group_id)
    if not group:
        return None
    reminder = Reminder(group=group)
    _apply_reminder_payload(reminder, payload)
    db.add(reminder)
    db.flush()
    regenerate_reminder_plans(db, reminder)
    db.commit()
    return get_admin_reminder(db, reminder.id)


def update_admin_reminder(db: Session, reminder: Reminder, payload: AdminReminderPayload) -> Reminder | None:
    _apply_reminder_payload(reminder, payload)
    regenerate_reminder_plans(db, reminder)
    db.commit()
    return get_admin_reminder(db, reminder.id)


def delete_admin_reminder(db: Session, reminder: Reminder) -> None:
    reminder.deleted_at = utc_now()
    reminder.enabled = False
    regenerate_reminder_plans(db, reminder)
    db.commit()


def restore_admin_reminder(db: Session, reminder: Reminder) -> Reminder | None:
    reminder.deleted_at = None
    reminder.enabled = True
    regenerate_reminder_plans(db, reminder)
    db.commit()
    return get_admin_reminder(db, reminder.id)


def dashboard(db: Session) -> dict:
    plan_rows = db.scalars(
        select(ReminderPlan)
        .options(joinedload(ReminderPlan.group), joinedload(ReminderPlan.reminder))
        .where(ReminderPlan.status.in_(["pending", "processing", "failed"]))
        .order_by(ReminderPlan.due_at.asc(), ReminderPlan.id.asc())
        .limit(50)
    ).unique().all()
    plans = [
        {
            "id": plan.id,
            "group_id": plan.group_id,
            "group_name": plan.group.name if plan.group else "",
            "reminder_id": plan.reminder_id,
            "reminder_title": plan.reminder.title if plan.reminder else "",
            "target_date": plan.target_date,
            "due_at": plan.due_at,
            "kind": plan.kind,
            "status": plan.status,
            "attempt_count": plan.attempt_count,
            "last_error_message": plan.last_error_message,
        }
        for plan in plan_rows
    ]
    return {
        "groups": db.scalar(select(func.count(Group.id))) or 0,
        "active_groups": db.scalar(select(func.count(Group.id)).where(Group.status == "active")) or 0,
        "reminders": db.scalar(select(func.count(Reminder.id)).where(Reminder.deleted_at.is_(None))) or 0,
        "enabled_reminders": db.scalar(
            select(func.count(Reminder.id)).where(
                Reminder.deleted_at.is_(None),
                Reminder.enabled.is_(True),
            )
        )
        or 0,
        "pending_plans": db.scalar(select(func.count(ReminderPlan.id)).where(ReminderPlan.status == "pending")) or 0,
        "failed_plans": db.scalar(select(func.count(ReminderPlan.id)).where(ReminderPlan.status == "failed")) or 0,
        "send_logs": db.scalar(select(func.count(SendLog.id))) or 0,
        "plans": plans,
    }


def list_admin_groups(db: Session, *, page: int, page_size: int, query: str | None, status: str | None) -> dict:
    filters = []
    if status:
        filters.append(Group.status == status)
    if query and query.strip():
        keyword = f"%{query.strip()}%"
        filters.append(or_(Group.name.ilike(keyword), Group.code.ilike(keyword)))
    total = db.scalar(select(func.count(Group.id)).where(*filters)) or 0
    reminder_count = func.count(Reminder.id).label("reminder_count")
    rows = db.execute(
        select(Group, reminder_count)
        .outerjoin(Reminder, (Reminder.group_id == Group.id) & Reminder.deleted_at.is_(None))
        .where(*filters)
        .group_by(Group.id)
        .order_by(Group.created_at.desc(), Group.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = []
    for group, count in rows:
        items.append({
            "id": group.id, "name": group.name, "code": group.code, "status": group.status,
            "description": group.description, "push_topic_code": group.push_topic_code,
            "default_remind_time": group.default_remind_time, "timezone": group.timezone,
            "code_updated_at": group.code_updated_at, "created_at": group.created_at,
            "updated_at": group.updated_at, "reminder_count": count,
        })
    return _page(page, page_size, total, items)


def list_send_logs(
    db: Session,
    *,
    page: int,
    page_size: int,
    group_id: int | None = None,
    status: str | None = None,
) -> dict:
    filters = []
    if group_id is not None:
        filters.append(SendLog.group_id == group_id)
    if status:
        filters.append(SendLog.status == status)
    total = db.scalar(select(func.count(SendLog.id)).where(*filters)) or 0
    rows = db.execute(
        select(SendLog, Group.name, Reminder.title)
        .join(Group, SendLog.group_id == Group.id)
        .outerjoin(Reminder, SendLog.reminder_id == Reminder.id)
        .where(*filters)
        .order_by(SendLog.created_at.desc(), SendLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = []
    for log, group_name, reminder_title in rows:
        items.append({
            "id": log.id, "group_id": log.group_id, "group_name": group_name,
            "reminder_id": log.reminder_id, "reminder_title": reminder_title or "",
            "plan_id": log.plan_id, "channel": log.channel, "status": log.status,
            "request_payload": log.request_payload, "response_payload": log.response_payload,
            "error_code": log.error_code, "error_message": log.error_message,
            "created_at": log.created_at,
        })
    return _page(page, page_size, total, items)


def retry_failed_plan(db: Session, plan_id: int) -> ReminderPlan | None:
    plan = db.get(ReminderPlan, plan_id)
    if not plan or plan.status != "failed":
        return None
    plan.status = "pending"
    plan.attempt_count = 0
    plan.due_at = datetime.now(timezone.utc)
    plan.processing_started_at = None
    db.commit()
    db.refresh(plan)
    return plan
