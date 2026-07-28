from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

if load_dotenv:
    load_dotenv()


def _get_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)


def _get_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str
    database_url: str
    session_secret: str
    group_session_cookie_name: str
    group_session_days: int
    admin_session_cookie_name: str
    admin_session_hours: int
    admin_token: str
    public_base_url: str
    cors_origins: list[str]
    trusted_proxy_ips: list[str]
    auto_create_tables: bool
    pushplus_token: str
    pushplus_enabled: bool
    pushplus_secret_key: str
    pushplus_qr_seconds: int
    pushplus_qr_scan_count: int
    join_rate_limit_per_minute: int
    join_rate_limit_per_10_minutes: int
    join_error_cooldown_threshold: int
    join_error_cooldown_seconds: int
    create_group_rate_limit_per_minute: int
    create_group_rate_limit_per_hour: int
    admin_login_rate_limit_per_minute: int
    admin_login_error_cooldown_threshold: int
    admin_login_error_cooldown_seconds: int
    write_rate_limit_per_minute: int
    reminder_scan_interval_seconds: int
    reminder_retry_delay_seconds: int
    reminder_batch_size: int
    reminder_max_attempts: int
    reminder_processing_timeout_seconds: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    public_base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    default_database_url = f"sqlite:///{Path(__file__).resolve().parents[1] / 'haorizi_dev.db'}"
    return Settings(
        app_name=os.getenv("APP_NAME", "HaoRiZi"),
        database_url=os.getenv("DATABASE_URL", default_database_url),
        session_secret=os.getenv("SESSION_SECRET", "dev-only-change-me"),
        group_session_cookie_name=os.getenv("GROUP_SESSION_COOKIE_NAME", "haorizi_group_session"),
        group_session_days=_get_int("GROUP_SESSION_DAYS", 30),
        admin_session_cookie_name=os.getenv("ADMIN_SESSION_COOKIE_NAME", "haorizi_admin_session"),
        admin_session_hours=_get_int("ADMIN_SESSION_HOURS", 12),
        admin_token=os.getenv("ADMIN_TOKEN", "dev-admin-token"),
        public_base_url=public_base_url,
        cors_origins=_get_list(
            "CORS_ORIGINS",
            "http://localhost:8000,http://localhost:5173,http://127.0.0.1:8000",
        ),
        trusted_proxy_ips=_get_list("TRUSTED_PROXY_IPS", "127.0.0.1,::1"),
        auto_create_tables=_get_bool("AUTO_CREATE_TABLES", False),
        pushplus_token=os.getenv("PUSHPLUS_TOKEN", ""),
        pushplus_enabled=_get_bool("PUSHPLUS_ENABLED", False),
        pushplus_secret_key=os.getenv("PUSHPLUS_SECRET_KEY", ""),
        pushplus_qr_seconds=_get_int("PUSHPLUS_QR_SECONDS", 60 * 60 * 24 * 7),
        pushplus_qr_scan_count=_get_int("PUSHPLUS_QR_SCAN_COUNT", -1),
        join_rate_limit_per_minute=_get_int("JOIN_RATE_LIMIT_PER_MINUTE", 10),
        join_rate_limit_per_10_minutes=_get_int("JOIN_RATE_LIMIT_PER_10_MINUTES", 30),
        join_error_cooldown_threshold=_get_int("JOIN_ERROR_COOLDOWN_THRESHOLD", 8),
        join_error_cooldown_seconds=_get_int("JOIN_ERROR_COOLDOWN_SECONDS", 900),
        create_group_rate_limit_per_minute=_get_int("CREATE_GROUP_RATE_LIMIT_PER_MINUTE", 5),
        create_group_rate_limit_per_hour=_get_int("CREATE_GROUP_RATE_LIMIT_PER_HOUR", 20),
        admin_login_rate_limit_per_minute=_get_int("ADMIN_LOGIN_RATE_LIMIT_PER_MINUTE", 5),
        admin_login_error_cooldown_threshold=_get_int("ADMIN_LOGIN_ERROR_COOLDOWN_THRESHOLD", 5),
        admin_login_error_cooldown_seconds=_get_int("ADMIN_LOGIN_ERROR_COOLDOWN_SECONDS", 900),
        write_rate_limit_per_minute=_get_int("WRITE_RATE_LIMIT_PER_MINUTE", 30),
        reminder_scan_interval_seconds=_get_int("REMINDER_SCAN_INTERVAL_SECONDS", 60),
        reminder_retry_delay_seconds=_get_int("REMINDER_RETRY_DELAY_SECONDS", 300),
        reminder_batch_size=_get_int("REMINDER_BATCH_SIZE", 50),
        reminder_max_attempts=_get_int("REMINDER_MAX_ATTEMPTS", 3),
        reminder_processing_timeout_seconds=_get_int("REMINDER_PROCESSING_TIMEOUT_SECONDS", 900),
    )
