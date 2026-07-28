from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Reminder, ReminderPlan, ReminderRule, SendLog, utc_now
from app.schemas import ReminderDatePreviewRequest, ReminderUpsertRequest
from app.services.lunar import candidate_target_dates, lunar_year_for_solar_date
from app.services.plans import group_local_date, normalize_datetime, regenerate_reminder_plans
from app.services.pushplus import PushPlusClient, PushPlusSendError


LUNAR_MONTHS = ["正", "二", "三", "四", "五", "六", "七", "八", "九", "十", "冬", "腊"]
LUNAR_DAYS = [
    "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
    "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十",
]


def lunar_day_text(day: int) -> str:
    if 1 <= day <= 30:
        return LUNAR_DAYS[day - 1]
    return str(day)


def build_date_text(reminder: Reminder) -> str:
    if reminder.calendar_type == "lunar":
        month_name = LUNAR_MONTHS[reminder.month - 1] if 1 <= reminder.month <= 12 else str(reminder.month)
        leap = "闰" if reminder.is_leap_month else ""
        core = f"农历{leap}{month_name}月{lunar_day_text(reminder.day)}"
    else:
        if reminder.is_recurring:
            core = f"阳历 {reminder.month:02d}-{reminder.day:02d}"
        else:
            year = reminder.event_year or "????"
            core = f"阳历 {year}-{reminder.month:02d}-{reminder.day:02d}"
    suffix = "每年" if reminder.is_recurring else "一次"
    return f"{core} · {suffix}"


def build_rule_text(rule: ReminderRule) -> str:
    hhmm = rule.remind_time.strftime("%H:%M")
    if rule.advance_days > 0 and rule.include_on_day:
        return f"提前{rule.advance_days}天，含当天 {hhmm}"
    if rule.advance_days > 0:
        return f"提前{rule.advance_days}天 {hhmm}"
    return f"仅当天 {hhmm}"


def upcoming_dates(reminder: Reminder, today: date | None = None) -> list[date]:
    if today is None:
        group = reminder.group
        tz_name = group.timezone if group else "Asia/Shanghai"
        today = group_local_date(datetime.now(timezone.utc), tz_name)

    if reminder.calendar_type == "lunar" and reminder.is_recurring:
        from_year = lunar_year_for_solar_date(today)
    else:
        from_year = today.year
    return candidate_target_dates(
        reminder,
        from_year,
        years_ahead=2,
        not_before=today,
    )


def next_upcoming_date(reminder: Reminder, today: date | None = None) -> date | None:
    return next(iter(upcoming_dates(reminder, today=today)), None)


def preview_reminder_dates(
    payload: ReminderDatePreviewRequest,
    *,
    timezone_name: str = "Asia/Shanghai",
    now: datetime | None = None,
) -> dict:
    from lunardate import LunarDate

    today = group_local_date(now or datetime.now(timezone.utc), timezone_name)
    reminder = Reminder(
        title="preview",
        calendar_type=payload.calendar_type,
        event_year=payload.event_year,
        month=payload.month,
        day=payload.day,
        is_leap_month=payload.is_leap_month,
        leap_month_policy=payload.leap_month_policy,
        missing_day_policy=payload.missing_day_policy,
        is_recurring=payload.is_recurring,
        enabled=True,
    )
    dates = upcoming_dates(reminder, today=today)
    occurrences = []
    for target in dates:
        adjustment = "none"
        if payload.calendar_type == "lunar":
            lunar = LunarDate.fromSolarDate(target.year, target.month, target.day)
            source_year = lunar.year
            if payload.is_leap_month and not bool(lunar.isLeapMonth):
                adjustment = "regular_month"
            elif lunar.day != payload.day:
                adjustment = "last_day"
        else:
            source_year = target.year
            if target.day != payload.day:
                adjustment = "last_day"
        occurrences.append(
            {
                "target_date": target,
                "source_year": source_year,
                "adjustment": adjustment,
            }
        )

    warnings: list[str] = []
    if payload.calendar_type == "lunar" and payload.is_leap_month:
        if payload.leap_month_policy == "skip":
            warnings.append("没有对应闰月的农历年将跳过")
        else:
            warnings.append("没有对应闰月的农历年将按普通同月提醒")
    if payload.missing_day_policy == "last_day":
        if payload.calendar_type == "lunar" and payload.day == 30:
            warnings.append("小月没有三十时按该月最后一天提醒")
        if payload.calendar_type == "solar" and payload.month == 2 and payload.day == 29:
            warnings.append("非闰年按二月最后一天提醒")
    elif (payload.calendar_type == "lunar" and payload.day == 30) or (
        payload.calendar_type == "solar" and payload.month == 2 and payload.day == 29
    ):
        warnings.append("目标日期不存在的年份将跳过")
    return {"occurrences": occurrences, "warnings": warnings}


def reminder_query(group_id: int):
    return (
        select(Reminder)
        .options(joinedload(Reminder.rule), joinedload(Reminder.group))
        .where(Reminder.group_id == group_id)
        .where(Reminder.deleted_at.is_(None))
    )


def get_reminder_or_none(db: Session, group_id: int, reminder_id: int) -> Reminder | None:
    return db.scalar(reminder_query(group_id).where(Reminder.id == reminder_id))


def apply_reminder_payload(reminder: Reminder, payload: ReminderUpsertRequest) -> None:
    reminder.title = payload.title.strip()
    reminder.person_name = payload.person_name
    reminder.calendar_type = payload.calendar_type
    reminder.event_year = payload.event_year
    reminder.month = payload.month
    reminder.day = payload.day
    reminder.is_leap_month = payload.is_leap_month
    reminder.leap_month_policy = getattr(payload, "leap_month_policy", "skip")
    reminder.missing_day_policy = getattr(payload, "missing_day_policy", "last_day")
    reminder.is_recurring = payload.is_recurring
    reminder.enabled = payload.enabled
    reminder.remark = payload.remark
    if reminder.rule is None:
        reminder.rule = ReminderRule()
    reminder.rule.remind_time = payload.rule.remind_time
    reminder.rule.advance_days = payload.rule.advance_days
    reminder.rule.include_on_day = payload.rule.include_on_day


def to_reminder_out(reminder: Reminder, today: date | None = None) -> dict:
    rule = reminder.rule
    assert rule is not None
    return {
        "id": reminder.id,
        "title": reminder.title,
        "person_name": reminder.person_name,
        "calendar_type": reminder.calendar_type,
        "event_year": reminder.event_year,
        "month": reminder.month,
        "day": reminder.day,
        "is_leap_month": reminder.is_leap_month,
        "leap_month_policy": getattr(reminder, "leap_month_policy", "skip"),
        "missing_day_policy": getattr(reminder, "missing_day_policy", "last_day"),
        "is_recurring": reminder.is_recurring,
        "enabled": reminder.enabled,
        "remark": reminder.remark,
        "upcoming_date": next_upcoming_date(reminder, today=today),
        "upcoming_dates": upcoming_dates(reminder, today=today),
        "date_text": build_date_text(reminder),
        "rule": {
            "remind_time": rule.remind_time,
            "advance_days": rule.advance_days,
            "include_on_day": rule.include_on_day,
        },
        "rule_text": build_rule_text(rule),
        "updated_at": reminder.updated_at,
    }


def list_reminders(db: Session, group_id: int) -> list[dict]:
    items = db.scalars(reminder_query(group_id).order_by(Reminder.id.desc())).unique().all()
    tz_name = items[0].group.timezone if items and items[0].group else "Asia/Shanghai"
    today = group_local_date(datetime.now(timezone.utc), tz_name)
    payload = [to_reminder_out(item, today=today) for item in items]
    payload.sort(
        key=lambda item: (
            0 if item["enabled"] else 1,
            item["upcoming_date"] or date(9999, 12, 31),
            -item["id"],
        )
    )
    return payload


def create_reminder(db: Session, group_id: int, payload: ReminderUpsertRequest) -> Reminder:
    reminder = Reminder(group_id=group_id)
    apply_reminder_payload(reminder, payload)
    db.add(reminder)
    db.flush()
    regenerate_reminder_plans(db, reminder)
    db.commit()
    db.refresh(reminder)
    return get_reminder_or_none(db, group_id, reminder.id)  # type: ignore[return-value]


def update_reminder(db: Session, reminder: Reminder, payload: ReminderUpsertRequest) -> Reminder:
    apply_reminder_payload(reminder, payload)
    regenerate_reminder_plans(db, reminder)
    db.commit()
    return get_reminder_or_none(db, reminder.group_id, reminder.id)  # type: ignore[return-value]


def delete_reminder(db: Session, reminder: Reminder) -> None:
    reminder.deleted_at = utc_now()
    reminder.enabled = False
    regenerate_reminder_plans(db, reminder)
    db.commit()


def list_plans(db: Session, group_id: int, status: str = "pending", limit: int = 50) -> list[dict]:
    rows = db.scalars(
        select(ReminderPlan)
        .options(joinedload(ReminderPlan.reminder))
        .where(ReminderPlan.group_id == group_id)
        .where(ReminderPlan.status == status)
        .order_by(ReminderPlan.due_at.asc())
        .limit(limit)
    ).unique().all()
    result = []
    for row in rows:
        title = row.reminder.title if row.reminder else ""
        result.append(
            {
                "id": row.id,
                "reminder_id": row.reminder_id,
                "reminder_title": title,
                "target_date": row.target_date,
                "due_at": row.due_at,
                "kind": row.kind,
                "status": row.status,
            }
        )
    return result


def log_send_result(
    db: Session,
    plan: ReminderPlan,
    *,
    status: str,
    request_payload: dict | None,
    response_payload: dict | None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> SendLog:
    log = SendLog(
        group_id=plan.group_id,
        reminder_id=plan.reminder_id,
        plan_id=plan.id,
        channel="pushplus",
        status=status,
        request_payload=request_payload,
        response_payload=response_payload,
        error_code=error_code,
        error_message=error_message,
    )
    db.add(log)
    return log


def run_due_reminders_once(db: Session, now: datetime | None = None) -> int:
    from app.config import get_settings

    settings = get_settings()
    now = normalize_datetime(now or datetime.now(timezone.utc))
    stale_before = now - timedelta(seconds=settings.reminder_processing_timeout_seconds)
    db.query(ReminderPlan).filter(
        ReminderPlan.status == "processing",
        ReminderPlan.processing_started_at.is_not(None),
        ReminderPlan.processing_started_at <= stale_before,
    ).update(
        {
            ReminderPlan.status: "pending",
            ReminderPlan.processing_started_at: None,
        },
        synchronize_session=False,
    )

    claimed = db.scalars(
        select(ReminderPlan)
        .where(ReminderPlan.status == "pending")
        .where(ReminderPlan.due_at <= now)
        .order_by(ReminderPlan.due_at.asc())
        .limit(settings.reminder_batch_size)
        .with_for_update(skip_locked=True)
    ).all()
    plan_ids = [plan.id for plan in claimed]
    for plan in claimed:
        plan.status = "processing"
        plan.processing_started_at = now
    db.commit()

    client = PushPlusClient()
    sent_count = 0
    for plan_id in plan_ids:
        plan = db.scalar(
            select(ReminderPlan)
            .options(
                joinedload(ReminderPlan.reminder).joinedload(Reminder.rule),
                joinedload(ReminderPlan.group),
            )
            .where(ReminderPlan.id == plan_id)
            .where(ReminderPlan.status == "processing")
        )
        if plan is None:
            continue
        reminder = plan.reminder
        group = plan.group
        if (
            not reminder
            or not group
            or reminder.deleted_at is not None
            or not reminder.enabled
            or group.status != "active"
        ):
            plan.status = "cancelled"
            plan.processing_started_at = None
            db.commit()
            continue
        try:
            request_payload, response_payload = client.send_group_reminder(group, reminder, plan)
        except PushPlusSendError as exc:
            plan.attempt_count += 1
            plan.last_error_code = exc.error_code
            plan.last_error_message = exc.message
            if plan.attempt_count >= plan.max_attempts:
                plan.status = "failed"
            else:
                plan.status = "pending"
                plan.due_at = now + timedelta(seconds=settings.reminder_retry_delay_seconds)
            plan.processing_started_at = None
            log_send_result(
                db,
                plan,
                status="failed",
                request_payload=exc.request_payload,
                response_payload=exc.response_payload,
                error_code=exc.error_code,
                error_message=exc.message,
            )
            db.commit()
            continue
        except Exception as exc:  # isolate one unexpected provider failure from the batch
            plan.attempt_count += 1
            plan.last_error_code = "unexpected_send_error"
            plan.last_error_message = "发送服务发生未预期错误"
            plan.status = "failed" if plan.attempt_count >= plan.max_attempts else "pending"
            if plan.status == "pending":
                plan.due_at = now + timedelta(seconds=settings.reminder_retry_delay_seconds)
            plan.processing_started_at = None
            log_send_result(
                db,
                plan,
                status="failed",
                request_payload=None,
                response_payload=None,
                error_code="unexpected_send_error",
                error_message=str(exc)[:512],
            )
            db.commit()
            continue

        plan.status = "sent"
        plan.sent_at = now
        plan.processing_started_at = None
        plan.last_error_code = None
        plan.last_error_message = None
        log_send_result(
            db,
            plan,
            status="sent",
            request_payload=request_payload,
            response_payload=response_payload,
        )
        sent_count += 1
        db.commit()

    return sent_count
