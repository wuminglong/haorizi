from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import enforce_write_rate_limit, get_current_group
from app.models import Group
from app.schemas import (
    GroupMeResponse,
    OkResponse,
    ReminderOut,
    ReminderDatePreviewRequest,
    ReminderDatePreviewResponse,
    ReminderPlanOut,
    ReminderUpsertRequest,
)
from app.services.groups import to_public_group
from app.services.pushplus import PushPlusClient, PushPlusSendError
from app.services.reminders import (
    create_reminder,
    delete_reminder,
    get_reminder_or_none,
    list_plans,
    list_reminders,
    preview_reminder_dates,
    to_reminder_out,
    update_reminder,
)

router = APIRouter(prefix="/api/group", tags=["group"])


@router.get("/me", response_model=GroupMeResponse)
def group_me(group: Group = Depends(get_current_group)) -> GroupMeResponse:
    return GroupMeResponse(group=to_public_group(group))  # type: ignore[arg-type]


@router.get("/join-qrcode")
def join_qrcode(group: Group = Depends(get_current_group)) -> dict:
    settings = get_settings()
    client = PushPlusClient()
    try:
        qr = client.get_topic_qrcode_by_code(group.push_topic_code)
        return {
            "channel": "pushplus",
            "topic_code": group.push_topic_code,
            "qr_code_img_url": qr.get("qr_code_img_url"),
            "expires_in_seconds": settings.pushplus_qr_seconds,
        }
    except PushPlusSendError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc


@router.get("/reminders", response_model=list[ReminderOut])
def get_reminders(
    group: Group = Depends(get_current_group),
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_reminders(db, group.id)


@router.post("/reminders/preview", response_model=ReminderDatePreviewResponse)
def preview_reminder(
    payload: ReminderDatePreviewRequest,
    group: Group = Depends(get_current_group),
) -> dict:
    return preview_reminder_dates(payload, timezone_name=group.timezone)


@router.post("/reminders", response_model=ReminderOut, status_code=status.HTTP_201_CREATED)
def post_reminder(
    payload: ReminderUpsertRequest,
    request: Request,
    group: Group = Depends(get_current_group),
    db: Session = Depends(get_db),
) -> dict:
    enforce_write_rate_limit(request)
    reminder = create_reminder(db, group.id, payload)
    return to_reminder_out(reminder)


@router.put("/reminders/{reminder_id}", response_model=ReminderOut)
def put_reminder(
    reminder_id: int,
    payload: ReminderUpsertRequest,
    request: Request,
    group: Group = Depends(get_current_group),
    db: Session = Depends(get_db),
) -> dict:
    enforce_write_rate_limit(request)
    reminder = get_reminder_or_none(db, group.id, reminder_id)
    if not reminder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提醒不存在")
    reminder = update_reminder(db, reminder, payload)
    return to_reminder_out(reminder)


@router.delete("/reminders/{reminder_id}", response_model=OkResponse)
def remove_reminder(
    reminder_id: int,
    request: Request,
    group: Group = Depends(get_current_group),
    db: Session = Depends(get_db),
) -> OkResponse:
    enforce_write_rate_limit(request)
    reminder = get_reminder_or_none(db, group.id, reminder_id)
    if not reminder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提醒不存在")
    delete_reminder(db, reminder)
    return OkResponse(ok=True)


@router.get("/plans", response_model=list[ReminderPlanOut])
def get_plans(
    status_filter: str = Query(default="pending", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    group: Group = Depends(get_current_group),
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_plans(db, group.id, status=status_filter, limit=limit)


@router.post("/logout", response_model=OkResponse)
def logout(response: Response) -> OkResponse:
    settings = get_settings()
    response.delete_cookie(settings.group_session_cookie_name)
    return OkResponse(ok=True)
