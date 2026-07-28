from __future__ import annotations

from datetime import date, datetime, time, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator[datetime]):
    """Persist UTC as naive DATETIME and always return an aware UTC value.

    MySQL DATETIME has no timezone metadata even when SQLAlchemy is configured
    with ``timezone=True``.  Normalizing at the type boundary keeps SQLite and
    PyMySQL round-trips identical for worker comparisons.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class Group(TimestampMixin, Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    push_topic_code: Mapped[str] = mapped_column(String(64), nullable=False)
    default_remind_time: Mapped[time] = mapped_column(Time, default=time(9, 0), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai", nullable=False)
    code_updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)

    reminders: Mapped[list[Reminder]] = relationship(back_populates="group", cascade="all, delete-orphan")


class Reminder(TimestampMixin, Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    person_name: Mapped[str | None] = mapped_column(String(100))
    calendar_type: Mapped[str] = mapped_column(String(12), nullable=False)
    event_year: Mapped[int | None] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    day: Mapped[int] = mapped_column(Integer, nullable=False)
    is_leap_month: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    leap_month_policy: Mapped[str] = mapped_column(String(20), default="skip", nullable=False)
    missing_day_policy: Mapped[str] = mapped_column(String(20), default="last_day", nullable=False)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remark: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    group: Mapped[Group] = relationship(back_populates="reminders")
    rule: Mapped[ReminderRule] = relationship(
        back_populates="reminder",
        cascade="all, delete-orphan",
        uselist=False,
    )
    plans: Mapped[list[ReminderPlan]] = relationship(
        back_populates="reminder",
        cascade="all, delete-orphan",
    )
    logs: Mapped[list[SendLog]] = relationship(
        back_populates="reminder",
        cascade="all, delete-orphan",
    )


class ReminderRule(TimestampMixin, Base):
    __tablename__ = "reminder_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reminder_id: Mapped[int] = mapped_column(
        ForeignKey("reminders.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    remind_time: Mapped[time] = mapped_column(Time, default=time(9, 0), nullable=False)
    advance_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    include_on_day: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reminder: Mapped[Reminder] = relationship(back_populates="rule")


class ReminderPlan(TimestampMixin, Base):
    __tablename__ = "reminder_plans"
    __table_args__ = (
        UniqueConstraint("reminder_id", "target_date", "kind", name="uq_reminder_plan_target_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True, nullable=False)
    reminder_id: Mapped[int] = mapped_column(
        ForeignKey("reminders.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    target_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    due_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    processing_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(String(512))

    reminder: Mapped[Reminder] = relationship(back_populates="plans")
    group: Mapped[Group] = relationship()
    logs: Mapped[list[SendLog]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class SendLog(TimestampMixin, Base):
    __tablename__ = "send_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True, nullable=False)
    reminder_id: Mapped[int] = mapped_column(
        ForeignKey("reminders.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("reminder_plans.id", ondelete="SET NULL"), index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    request_payload: Mapped[dict | None] = mapped_column(JSON)
    response_payload: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(512))

    reminder: Mapped[Reminder] = relationship(back_populates="logs")
    plan: Mapped[ReminderPlan | None] = relationship(back_populates="logs")
