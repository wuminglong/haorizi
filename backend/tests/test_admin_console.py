from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import create_app
from app.models import ReminderPlan, SendLog


def _client_with_db() -> tuple[TestClient, sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), SessionLocal


def _create_group(client: TestClient) -> int:
    response = client.post(
        "/api/admin/groups",
        headers={"X-Admin-Token": "test-admin-token"},
        json={
            "name": "管理员测试群",
            "code": "ADMIN001",
            "push_topic_code": "admin001",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _reminder_payload(group_id: int) -> dict:
    return {
        "group_id": group_id,
        "title": "妈妈生日",
        "person_name": "妈妈",
        "calendar_type": "solar",
        "month": 12,
        "day": 20,
        "is_recurring": True,
        "leap_month_policy": "skip",
        "missing_day_policy": "last_day",
        "rule": {"remind_time": "09:00:00", "advance_days": 7, "include_on_day": True},
    }


def test_admin_password_session_cookie_and_legacy_header() -> None:
    client, _ = _client_with_db()
    assert client.get("/api/admin/session/me").status_code == 401

    bad = client.post("/api/admin/session", json={"password": "wrong"})
    assert bad.status_code == 401

    login = client.post("/api/admin/session", json={"password": "test-admin-token"})
    assert login.status_code == 204
    set_cookie = login.headers["set-cookie"].lower()
    assert "haorizi_admin_session=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert client.get("/api/admin/session/me").json() == {"authenticated": True}

    # X-Admin-Token remains usable by legacy tools without a browser cookie.
    legacy = TestClient(client.app)
    assert legacy.get("/api/admin/dashboard", headers={"X-Admin-Token": "test-admin-token"}).status_code == 200

    logout = client.delete("/api/admin/session")
    assert logout.status_code == 200
    assert client.get("/api/admin/session/me").status_code == 401


def test_admin_login_is_rate_limited() -> None:
    client, _ = _client_with_db()
    statuses = [client.post("/api/admin/session", json={"password": "wrong"}).status_code for _ in range(5)]
    assert statuses[:4] == [401, 401, 401, 401]
    assert statuses[4] == 429


def test_admin_cookie_write_rejects_untrusted_origin() -> None:
    client, _ = _client_with_db()
    assert client.post("/api/admin/session", json={"password": "test-admin-token"}).status_code == 204
    response = client.post(
        "/api/admin/groups",
        headers={"Origin": "https://evil.example"},
        json={"name": "跨站群", "code": "CROSS001", "push_topic_code": "cross001"},
    )
    assert response.status_code == 403


def test_admin_session_cookie_is_secure_for_https_public_base(monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test/haorizi")
    client, _ = _client_with_db()
    login = client.post("/api/admin/session", json={"admin_token": "test-admin-token"})
    assert login.status_code == 204
    assert "secure" in login.headers["set-cookie"].lower()


def test_admin_cross_group_reminder_restore_logs_and_failed_retry() -> None:
    client, SessionLocal = _client_with_db()
    headers = {"X-Admin-Token": "test-admin-token"}
    group_id = _create_group(client)

    created = client.post("/api/admin/reminders", headers=headers, json=_reminder_payload(group_id))
    assert created.status_code == 201, created.text
    reminder_id = created.json()["id"]

    listed = client.get(f"/api/admin/reminders?group_id={group_id}", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["group_id"] == group_id

    deleted = client.delete(f"/api/admin/reminders/{reminder_id}", headers=headers)
    assert deleted.status_code == 200
    assert client.get(f"/api/admin/reminders?group_id={group_id}", headers=headers).json()["total"] == 0

    restored = client.post(f"/api/admin/reminders/{reminder_id}/restore", headers=headers)
    assert restored.status_code == 200, restored.text
    assert restored.json()["enabled"] is True

    with SessionLocal() as db:
        plan = ReminderPlan(
            group_id=group_id,
            reminder_id=reminder_id,
            target_date=date(2030, 1, 1),
            due_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            kind="on_day",
            status="failed",
            attempt_count=3,
        )
        db.add(plan)
        db.flush()
        plan_id = plan.id
        db.add(
            SendLog(
                group_id=group_id,
                reminder_id=reminder_id,
                plan_id=plan_id,
                channel="pushplus",
                status="failed",
                error_code="network",
                error_message="timeout",
            )
        )
        db.commit()

    retried = client.post(f"/api/admin/plans/{plan_id}/retry", headers=headers)
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "pending"
    assert retried.json()["attempt_count"] == 0
    assert client.post(f"/api/admin/plans/{plan_id}/retry", headers=headers).status_code == 409

    logs = client.get(f"/api/admin/send-logs?group_id={group_id}&status=failed", headers=headers)
    assert logs.status_code == 200
    assert logs.json()["total"] == 1
    assert logs.json()["items"][0]["error_code"] == "network"

    summary = client.get("/api/admin/dashboard", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["groups"] == 1
    assert summary.json()["send_logs"] == 1
