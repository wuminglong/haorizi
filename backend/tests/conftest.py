from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db import Base
from app import models  # noqa: F401
from app.services.pushplus import PushPlusClient
from app.services.rate_limit import limiter


@pytest.fixture(autouse=True)
def isolate_runtime_settings(monkeypatch) -> Generator[None, None, None]:
    monkeypatch.setenv("PUSHPLUS_ENABLED", "false")
    monkeypatch.setenv("PUSHPLUS_TOKEN", "")
    monkeypatch.setenv("PUSHPLUS_SECRET_KEY", "")
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("AUTO_CREATE_TABLES", "false")
    get_settings.cache_clear()
    PushPlusClient._access_key = None
    PushPlusClient._access_key_expire_at = None
    limiter.reset()
    yield
    get_settings.cache_clear()
    PushPlusClient._access_key = None
    PushPlusClient._access_key_expire_at = None
    limiter.reset()


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with SessionLocal() as session:
        yield session
