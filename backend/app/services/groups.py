from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Group, utc_now

CODE_RE = re.compile(r"^[A-Z0-9-]{6,16}$")


class GroupError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_group_code(raw: str) -> str:
    code = (raw or "").strip().upper()
    if not CODE_RE.match(code):
        raise GroupError("group_code_invalid", "群组码格式不正确")
    return code


def mask_group_code(code: str) -> str:
    code = (code or "").strip().upper()
    if len(code) <= 4:
        return "*" * len(code)
    return f"{code[:2]}{'*' * max(2, len(code) - 4)}{code[-2:]}"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def code_version(group: Group) -> int:
    return int(_as_utc(group.code_updated_at).timestamp())


def get_active_group_by_code(db: Session, code: str) -> Group | None:
    normalized = normalize_group_code(code)
    group = db.scalar(select(Group).where(Group.code == normalized))
    if not group or group.status != "active":
        return None
    return group


def get_group_by_id(db: Session, group_id: int) -> Group | None:
    return db.get(Group, group_id)


def create_group(
    db: Session,
    *,
    name: str,
    code: str,
    push_topic_code: str,
    description: str | None = None,
    default_remind_time=None,
) -> Group:
    from datetime import time as time_cls

    normalized = normalize_group_code(code)
    exists = db.scalar(select(Group.id).where(Group.code == normalized))
    if exists:
        raise GroupError("group_code_exists", "群组码已存在")
    topic = (push_topic_code or "").strip()
    if not topic:
        raise GroupError("topic_required", "请填写 PushPlus 群编码")
    now = utc_now()
    group = Group(
        name=name.strip(),
        code=normalized,
        description=(description or "").strip() or None,
        push_topic_code=topic,
        default_remind_time=default_remind_time or time_cls(9, 0),
        code_updated_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def reset_group_code(db: Session, group: Group, new_code: str) -> Group:
    from datetime import timedelta

    normalized = normalize_group_code(new_code)
    exists = db.scalar(select(Group.id).where(Group.code == normalized, Group.id != group.id))
    if exists:
        raise GroupError("group_code_exists", "群组码已存在")
    group.code = normalized
    now = utc_now()
    # SQLite may truncate sub-second precision; always bump at least +1s for code_ver.
    if group.code_updated_at is not None:
        prev = _as_utc(group.code_updated_at)
        if now <= prev + timedelta(seconds=1):
            now = prev + timedelta(seconds=1)
    group.code_updated_at = now
    db.commit()
    db.refresh(group)
    return group


def to_public_group(group: Group) -> dict:
    return {
        "id": group.id,
        "name": group.name,
        "code_masked": mask_group_code(group.code),
        "description": group.description,
        "default_remind_time": group.default_remind_time,
        "timezone": group.timezone,
    }
