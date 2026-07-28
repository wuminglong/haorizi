from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.admin_schemas import AdminReminderCreate, AdminReminderPayload, AdminSessionRequest
from app.config import get_settings
from app.db import get_db
from app.deps import client_ip, require_admin
from app.models import Group, ReminderPlan
from app.schemas import (
    AdminCreateGroupRequest,
    AdminGroupOut,
    AdminPatchGroupRequest,
    AdminResetCodeRequest,
    OkResponse,
)
from app.security import admin_token_valid, create_admin_session_token
from app.services.admin import (
    create_admin_reminder,
    dashboard,
    delete_admin_reminder,
    get_admin_reminder,
    list_admin_groups,
    list_admin_reminders,
    list_send_logs,
    retry_failed_plan,
    restore_admin_reminder,
    serialize_reminder,
    update_admin_reminder,
)
from app.services.groups import GroupError, create_group, get_group_by_id, reset_group_code
from app.services.rate_limit import limiter


router = APIRouter(prefix="/api/admin", tags=["admin"])


def _set_admin_cookie(response: Response) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.admin_session_cookie_name,
        value=create_admin_session_token(),
        max_age=settings.admin_session_hours * 3600,
        httponly=True,
        secure=settings.public_base_url.startswith("https://"),
        samesite="lax",
    )


@router.post("/session", status_code=status.HTTP_204_NO_CONTENT)
def create_admin_session(payload: AdminSessionRequest, request: Request, response: Response) -> Response:
    settings = get_settings()
    ip = client_ip(request)
    rate = limiter.hit(
        f"admin-login:ip:{ip}",
        limit=settings.admin_login_rate_limit_per_minute,
        window_seconds=60,
    )
    if not rate.allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=rate.detail)
    if not admin_token_valid(payload.password):
        cooldown = limiter.record_error(
            f"admin-login-error:ip:{ip}",
            threshold=settings.admin_login_error_cooldown_threshold,
            cooldown_seconds=settings.admin_login_error_cooldown_seconds,
        )
        if not cooldown.allowed:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=cooldown.detail)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="建群口令无效")
    limiter.clear_errors(f"admin-login-error:ip:{ip}")
    _set_admin_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/session/me", dependencies=[Depends(require_admin)])
def get_admin_session() -> dict[str, bool]:
    return {"authenticated": True}


@router.get("/session", dependencies=[Depends(require_admin)], include_in_schema=False)
def get_admin_session_compat() -> dict[str, bool]:
    return {"authenticated": True}


@router.delete("/session", response_model=OkResponse, dependencies=[Depends(require_admin)])
def delete_admin_session(response: Response) -> OkResponse:
    settings = get_settings()
    response.delete_cookie(
        settings.admin_session_cookie_name,
        secure=settings.public_base_url.startswith("https://"),
        httponly=True,
        samesite="lax",
    )
    return OkResponse(ok=True)


@router.get("/dashboard", dependencies=[Depends(require_admin)])
def admin_dashboard(db: Session = Depends(get_db)) -> dict:
    return dashboard(db)


@router.get("/groups", dependencies=[Depends(require_admin)])
def admin_list_groups(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    q: str | None = Query(default=None, max_length=100),
    status_filter: str | None = Query(default=None, alias="status", max_length=20),
    db: Session = Depends(get_db),
) -> dict:
    return list_admin_groups(db, page=page, page_size=page_size, query=q, status=status_filter)


@router.post("/groups", response_model=AdminGroupOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def admin_create_group(
    payload: AdminCreateGroupRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> Group:
    settings = get_settings()
    ip = client_ip(request)
    rate = limiter.hit_many(
        f"create:ip:{ip}",
        [
            (settings.create_group_rate_limit_per_minute, 60),
            (settings.create_group_rate_limit_per_hour, 3600),
        ],
    )
    if not rate.allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=rate.detail)

    try:
        return create_group(
            db,
            name=payload.name,
            code=payload.code,
            description=payload.description,
            push_topic_code=payload.push_topic_code,
            default_remind_time=payload.default_remind_time,
        )
    except GroupError as exc:
        status_code = status.HTTP_400_BAD_REQUEST
        if exc.code == "group_code_exists":
            status_code = status.HTTP_409_CONFLICT
        raise HTTPException(status_code=status_code, detail=exc.message) from exc


@router.patch("/groups/{group_id}", response_model=AdminGroupOut, dependencies=[Depends(require_admin)])
def admin_patch_group(
    group_id: int,
    payload: AdminPatchGroupRequest,
    db: Session = Depends(get_db),
) -> Group:
    group = get_group_by_id(db, group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="群组不存在")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(group, key, value)
    db.commit()
    db.refresh(group)
    return group


@router.post("/groups/{group_id}/reset-code", response_model=AdminGroupOut, dependencies=[Depends(require_admin)])
def admin_reset_code(
    group_id: int,
    payload: AdminResetCodeRequest,
    db: Session = Depends(get_db),
) -> Group:
    group = get_group_by_id(db, group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="群组不存在")
    try:
        return reset_group_code(db, group, payload.code)
    except GroupError as exc:
        status_code = status.HTTP_400_BAD_REQUEST
        if exc.code == "group_code_exists":
            status_code = status.HTTP_409_CONFLICT
        raise HTTPException(status_code=status_code, detail=exc.message) from exc


@router.get("/reminders", dependencies=[Depends(require_admin)])
def admin_list_reminders(
    group_id: int | None = Query(default=None, gt=0),
    q: str | None = Query(default=None, max_length=100),
    enabled: bool | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    return list_admin_reminders(
        db,
        page=page,
        page_size=page_size,
        group_id=group_id,
        query=q,
        enabled=enabled,
        include_deleted=include_deleted,
    )


@router.post("/reminders", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def admin_create_reminder(payload: AdminReminderCreate, db: Session = Depends(get_db)) -> dict:
    reminder = create_admin_reminder(db, payload)
    if not reminder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="群组不存在")
    return serialize_reminder(reminder)


@router.put("/reminders/{reminder_id}", dependencies=[Depends(require_admin)])
def admin_update_reminder(
    reminder_id: int,
    payload: AdminReminderPayload,
    db: Session = Depends(get_db),
) -> dict:
    reminder = get_admin_reminder(db, reminder_id)
    if not reminder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提醒不存在")
    updated = update_admin_reminder(db, reminder, payload)
    assert updated is not None
    return serialize_reminder(updated)


@router.delete("/reminders/{reminder_id}", response_model=OkResponse, dependencies=[Depends(require_admin)])
def admin_delete_reminder(reminder_id: int, db: Session = Depends(get_db)) -> OkResponse:
    reminder = get_admin_reminder(db, reminder_id)
    if not reminder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提醒不存在")
    delete_admin_reminder(db, reminder)
    return OkResponse(ok=True)


@router.post("/reminders/{reminder_id}/restore", dependencies=[Depends(require_admin)])
def admin_restore_reminder(reminder_id: int, db: Session = Depends(get_db)) -> dict:
    reminder = get_admin_reminder(db, reminder_id, include_deleted=True)
    if not reminder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提醒不存在")
    if reminder.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="提醒未删除，无需恢复")
    restored = restore_admin_reminder(db, reminder)
    assert restored is not None
    return serialize_reminder(restored)


@router.get("/groups/{group_id}/reminders", dependencies=[Depends(require_admin)])
def admin_list_group_reminders(
    group_id: int,
    include_deleted: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    if not get_group_by_id(db, group_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="群组不存在")
    return list_admin_reminders(
        db, page=page, page_size=page_size, group_id=group_id, include_deleted=include_deleted
    )


@router.get("/send-logs", dependencies=[Depends(require_admin)])
def admin_list_send_logs(
    group_id: int | None = Query(default=None, gt=0),
    status_filter: str | None = Query(default=None, alias="status", max_length=20),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    return list_send_logs(db, page=page, page_size=page_size, group_id=group_id, status=status_filter)


@router.post("/plans/{plan_id}/retry", dependencies=[Depends(require_admin)])
def admin_retry_failed_plan(plan_id: int, db: Session = Depends(get_db)) -> dict:
    plan = db.get(ReminderPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="发送计划不存在")
    if plan.status != "failed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="仅失败计划可重试")
    retried = retry_failed_plan(db, plan_id)
    assert retried is not None
    return {
        "id": retried.id,
        "status": retried.status,
        "attempt_count": retried.attempt_count,
        "due_at": retried.due_at,
    }


@router.get("/members", dependencies=[Depends(require_admin)])
def admin_list_members() -> dict:
    # Membership has intentionally not been modelled in Phase 1.
    return {"enabled": False, "items": [], "message": "成员管理尚未启用"}


@router.get("/groups/{group_id}/members", dependencies=[Depends(require_admin)])
def admin_list_group_members(group_id: int, db: Session = Depends(get_db)) -> dict:
    if not get_group_by_id(db, group_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="群组不存在")
    return {"enabled": False, "items": [], "message": "成员管理尚未启用"}
