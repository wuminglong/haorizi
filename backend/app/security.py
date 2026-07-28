from __future__ import annotations

from datetime import datetime, timezone
from secrets import compare_digest
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt="haorizi-group-session")


def _admin_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt="haorizi-admin-session")


def create_group_session_token(group_id: int, code_ver: int, max_age_seconds: int | None = None) -> str:
    settings = get_settings()
    max_age = max_age_seconds if max_age_seconds is not None else settings.group_session_days * 24 * 3600
    now = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "gid": group_id,
        "code_ver": int(code_ver),
        "exp": now + max_age,
    }
    return _serializer().dumps(payload)


def parse_group_session_token(token: str) -> dict[str, Any] | None:
    settings = get_settings()
    max_age = settings.group_session_days * 24 * 3600
    try:
        payload = _serializer().loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict):
        return None
    if "gid" not in payload or "code_ver" not in payload or "exp" not in payload:
        return None
    now = int(datetime.now(timezone.utc).timestamp())
    if int(payload["exp"]) < now:
        return None
    return {
        "gid": int(payload["gid"]),
        "code_ver": int(payload["code_ver"]),
        "exp": int(payload["exp"]),
    }


def admin_token_valid(token: str | None) -> bool:
    settings = get_settings()
    if not token or not settings.admin_token:
        return False
    return compare_digest(token.strip(), settings.admin_token)


def create_admin_session_token(max_age_seconds: int | None = None) -> str:
    """Create a signed, revocable-by-secret admin browser session token.

    The ADMIN_TOKEN itself never leaves the login request after this point.
    Rotating SESSION_SECRET invalidates all outstanding browser sessions.
    """
    settings = get_settings()
    max_age = max_age_seconds if max_age_seconds is not None else settings.admin_session_hours * 3600
    now = int(datetime.now(timezone.utc).timestamp())
    return _admin_serializer().dumps({"scope": "admin", "exp": now + max_age})


def parse_admin_session_token(token: str | None) -> bool:
    if not token:
        return False
    settings = get_settings()
    try:
        payload = _admin_serializer().loads(token, max_age=settings.admin_session_hours * 3600)
    except (BadSignature, SignatureExpired):
        return False
    if not isinstance(payload, dict) or payload.get("scope") != "admin" or "exp" not in payload:
        return False
    try:
        return int(payload["exp"]) >= int(datetime.now(timezone.utc).timestamp())
    except (TypeError, ValueError):
        return False
