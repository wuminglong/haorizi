from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CalendarType = Literal["solar", "lunar"]
LeapMonthPolicy = Literal["skip", "regular_month"]
MissingDayPolicy = Literal["last_day", "skip"]
PlanStatus = Literal["pending", "processing", "sent", "failed", "cancelled"]
PlanKind = Literal["advance", "on_day"]


class JoinGroupRequest(BaseModel):
    group_code: str = Field(min_length=1, max_length=32)


class GroupPublic(BaseModel):
    id: int
    name: str
    code_masked: str
    description: str | None = None
    default_remind_time: time
    timezone: str


class JoinPushInfo(BaseModel):
    channel: str = "pushplus"
    topic_code: str
    qr_code_img_url: str | None = None
    expires_in_seconds: int


class SessionInfo(BaseModel):
    token: str
    expires_at: datetime


class JoinGroupResponse(BaseModel):
    group: GroupPublic
    join_push: JoinPushInfo
    session: SessionInfo


class GroupMeResponse(BaseModel):
    group: GroupPublic


class ReminderRuleIn(BaseModel):
    remind_time: time = Field(default=time(9, 0))
    advance_days: int = Field(default=7, ge=0, le=365)
    include_on_day: bool = True

    @model_validator(mode="after")
    def validate_rule(self) -> ReminderRuleIn:
        if self.advance_days <= 0 and not self.include_on_day:
            raise ValueError("请至少开启提前提醒或当天提醒")
        return self


class ReminderRuleOut(BaseModel):
    remind_time: time
    advance_days: int
    include_on_day: bool


class ReminderUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=100)
    person_name: str | None = Field(default=None, max_length=100)
    calendar_type: CalendarType
    event_year: int | None = Field(default=None, ge=1901, le=2099)
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)
    is_leap_month: bool = False
    leap_month_policy: LeapMonthPolicy = "skip"
    missing_day_policy: MissingDayPolicy = "last_day"
    is_recurring: bool = True
    enabled: bool = True
    remark: str | None = Field(default=None, max_length=500)
    rule: ReminderRuleIn = Field(default_factory=ReminderRuleIn)

    @field_validator("person_name", "remark")
    @classmethod
    def empty_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_reminder(self) -> ReminderUpsertRequest:
        if self.calendar_type == "solar" and self.is_leap_month:
            raise ValueError("阳历日期不能设置为闰月")
        if not self.is_recurring and self.event_year is None:
            raise ValueError("一次性提醒请填写年份")
        if self.calendar_type == "solar":
            # 2000 is a leap year, so recurring 02-29 remains a valid pattern.
            check_year = self.event_year if not self.is_recurring else 2000
            try:
                date(check_year or 2000, self.month, self.day)
            except ValueError as exc:
                raise ValueError("阳历日期无效") from exc
        elif self.day > 30:
            raise ValueError("农历日期最多为三十")
        elif not self.is_recurring:
            from app.services.lunar import lunar_to_solar

            try:
                lunar_to_solar(self.event_year or 0, self.month, self.day, self.is_leap_month)
            except ValueError as exc:
                raise ValueError("农历日期在所选农历年中不存在") from exc
        return self


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    person_name: str | None
    calendar_type: str
    event_year: int | None
    month: int
    day: int
    is_leap_month: bool
    leap_month_policy: LeapMonthPolicy
    missing_day_policy: MissingDayPolicy
    is_recurring: bool
    enabled: bool
    remark: str | None
    upcoming_date: date | None
    upcoming_dates: list[date]
    date_text: str
    rule: ReminderRuleOut
    rule_text: str
    updated_at: datetime


class ReminderPlanOut(BaseModel):
    id: int
    reminder_id: int
    reminder_title: str
    target_date: date
    due_at: datetime
    kind: PlanKind
    status: PlanStatus


class ReminderDatePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calendar_type: CalendarType
    event_year: int | None = Field(default=None, ge=1901, le=2099)
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)
    is_leap_month: bool = False
    leap_month_policy: LeapMonthPolicy = "skip"
    missing_day_policy: MissingDayPolicy = "last_day"
    is_recurring: bool = True

    @model_validator(mode="after")
    def validate_date(self) -> ReminderDatePreviewRequest:
        if self.calendar_type == "solar" and self.is_leap_month:
            raise ValueError("阳历日期不能设置为闰月")
        if not self.is_recurring and self.event_year is None:
            raise ValueError("一次性提醒请填写年份")
        if self.calendar_type == "solar":
            check_year = self.event_year if not self.is_recurring else 2000
            try:
                date(check_year or 2000, self.month, self.day)
            except ValueError as exc:
                raise ValueError("阳历日期无效") from exc
        elif self.day > 30:
            raise ValueError("农历日期最多为三十")
        elif not self.is_recurring:
            from app.services.lunar import lunar_to_solar

            try:
                lunar_to_solar(self.event_year or 0, self.month, self.day, self.is_leap_month)
            except ValueError as exc:
                raise ValueError("农历日期在所选农历年中不存在") from exc
        return self


class ReminderDateOccurrence(BaseModel):
    target_date: date
    source_year: int
    adjustment: Literal["none", "regular_month", "last_day"] = "none"


class ReminderDatePreviewResponse(BaseModel):
    occurrences: list[ReminderDateOccurrence]
    warnings: list[str] = Field(default_factory=list)


class OkResponse(BaseModel):
    ok: bool = True


class AdminCreateGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=6, max_length=16)
    description: str | None = Field(default=None, max_length=500)
    push_topic_code: str = Field(min_length=1, max_length=64)
    default_remind_time: time = Field(default=time(9, 0))


class AdminPatchGroupRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    status: Literal["active", "disabled"] | None = None
    push_topic_code: str | None = Field(default=None, min_length=1, max_length=64)
    default_remind_time: time | None = None


class AdminResetCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=16)


class AdminGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    status: str
    description: str | None
    push_topic_code: str
    default_remind_time: time
    timezone: str
    code_updated_at: datetime
