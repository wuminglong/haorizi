from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import client_ip, session_expires_at
from app.schemas import JoinGroupRequest, JoinGroupResponse
from app.security import create_group_session_token
from app.services.groups import GroupError, code_version, get_active_group_by_code, to_public_group
from app.services.pushplus import PushPlusClient, PushPlusSendError
from app.services.rate_limit import limiter

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/groups/join", response_model=JoinGroupResponse)
def join_group(
    payload: JoinGroupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> JoinGroupResponse:
    settings = get_settings()
    ip = client_ip(request)
    rate_key = f"join:ip:{ip}"
    err_key = f"join:err:{ip}"

    rate = limiter.hit_many(
        rate_key,
        [
            (settings.join_rate_limit_per_minute, 60),
            (settings.join_rate_limit_per_10_minutes, 600),
        ],
    )
    if not rate.allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=rate.detail)

    try:
        group = get_active_group_by_code(db, payload.group_code)
    except GroupError as exc:
        limiter.record_error(
            err_key,
            threshold=settings.join_error_cooldown_threshold,
            cooldown_seconds=settings.join_error_cooldown_seconds,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc

    if group is None:
        cool = limiter.record_error(
            err_key,
            threshold=settings.join_error_cooldown_threshold,
            cooldown_seconds=settings.join_error_cooldown_seconds,
        )
        if not cool.allowed:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=cool.detail)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="群组码无效")

    limiter.clear_errors(err_key)

    qr_url = None
    try:
        client = PushPlusClient()
        qr = client.get_topic_qrcode_by_code(group.push_topic_code)
        qr_url = qr.get("qr_code_img_url")
    except PushPlusSendError:
        qr_url = None
    except Exception:
        qr_url = None

    token = create_group_session_token(group.id, code_version(group))
    expires_at = session_expires_at()
    response.set_cookie(
        key=settings.group_session_cookie_name,
        value=token,
        max_age=settings.group_session_days * 24 * 3600,
        httponly=True,
        secure=settings.public_base_url.startswith("https://"),
        samesite="lax",
    )

    return JoinGroupResponse(
        group=to_public_group(group),  # type: ignore[arg-type]
        join_push={
            "channel": "pushplus",
            "topic_code": group.push_topic_code,
            "qr_code_img_url": qr_url,
            "expires_in_seconds": settings.pushplus_qr_seconds,
        },
        session={
            "expires_at": expires_at,
        },
    )
