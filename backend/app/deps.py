from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Group
from app.security import admin_token_valid, parse_admin_session_token, parse_group_session_token
from app.services.groups import code_version, get_group_by_id
from app.services.rate_limit import limiter


def client_ip(request: Request) -> str:
    settings = get_settings()
    peer_ip = request.client.host if request.client and request.client.host else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and peer_ip in settings.trusted_proxy_ips:
        return forwarded.split(",")[0].strip() or "unknown"
    return peer_ip


def enforce_trusted_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    settings = get_settings()
    public = urlsplit(settings.public_base_url)
    allowed = set(settings.cors_origins)
    if public.scheme and public.netloc:
        allowed.add(f"{public.scheme}://{public.netloc}")
    if origin.rstrip("/") not in {item.rstrip("/") for item in allowed}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请求来源不受信任")


def require_admin(
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    # Keep X-Admin-Token available for scripts and the legacy create-group page.
    cookie_name = get_settings().admin_session_cookie_name
    header_valid = admin_token_valid(x_admin_token)
    cookie_valid = parse_admin_session_token(request.cookies.get(cookie_name))
    if not header_valid and not cookie_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="建群口令无效")
    if cookie_valid and not header_valid and request.method not in {"GET", "HEAD", "OPTIONS"}:
        enforce_trusted_origin(request)


def get_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def get_current_group(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Group:
    settings = get_settings()
    token = get_bearer_token(authorization) or request.cookies.get(settings.group_session_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效，请重新输入群组码")

    payload = parse_group_session_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效，请重新输入群组码")

    group = get_group_by_id(db, payload["gid"])
    if not group or group.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效，请重新输入群组码")
    if payload["code_ver"] != code_version(group):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效，请重新输入群组码")

    request.state.group_session_token = token
    return group


def enforce_write_rate_limit(request: Request) -> None:
    settings = get_settings()
    enforce_trusted_origin(request)
    token = getattr(request.state, "group_session_token", None) or client_ip(request)
    result = limiter.hit(
        f"write:{token}",
        limit=settings.write_rate_limit_per_minute,
        window_seconds=60,
    )
    if not result.allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=result.detail)


def session_expires_at() -> datetime:
    settings = get_settings()
    return datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=settings.group_session_days)
