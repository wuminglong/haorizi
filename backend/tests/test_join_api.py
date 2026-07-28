from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import create_app
from app.services.rate_limit import limiter


def _client_with_db():
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
    # prevent static mount side effects issues by keeping as is
    client = TestClient(app)
    return client


def test_admin_create_and_join_flow() -> None:
    limiter.reset()
    client = _client_with_db()
    # create group via admin
    resp = client.post(
        "/api/admin/groups",
        headers={"X-Admin-Token": "test-admin-token"},
        json={
            "name": "吴家提醒群",
            "code": "FAMILY01",
            "push_topic_code": "family001",
            "description": "demo",
            "default_remind_time": "09:00:00",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "FAMILY01"

    join = client.post("/api/public/groups/join", json={"group_code": "family01"})
    assert join.status_code == 200, join.text
    data = join.json()
    assert data["group"]["name"] == "吴家提醒群"
    assert data["session"]["token"]
    token = data["session"]["token"]

    cookie_me = client.get("/api/group/me")
    assert cookie_me.status_code == 200

    me = client.get("/api/group/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["group"]["code_masked"].startswith("FA")

    created = client.post(
        "/api/group/reminders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "妈妈生日",
            "person_name": "妈妈",
            "calendar_type": "solar",
            "event_year": 2026,
            "month": 12,
            "day": 20,
            "is_leap_month": False,
            "is_recurring": False,
            "enabled": True,
            "remark": "cake",
            "rule": {"remind_time": "09:00:00", "advance_days": 7, "include_on_day": True},
        },
    )
    assert created.status_code == 201, created.text
    reminder = created.json()
    assert reminder["title"] == "妈妈生日"
    assert "提前7天" in reminder["rule_text"]

    plans = client.get("/api/group/plans?status=pending", headers={"Authorization": f"Bearer {token}"})
    assert plans.status_code == 200
    assert len(plans.json()) >= 1

    preview = client.post(
        "/api/group/reminders/preview",
        json={
            "calendar_type": "lunar",
            "month": 4,
            "day": 30,
            "is_leap_month": True,
            "is_recurring": True,
            "leap_month_policy": "skip",
            "missing_day_policy": "last_day",
        },
    )
    assert preview.status_code == 200, preview.text
    assert len(preview.json()["occurrences"]) == 3
    assert "没有对应闰月的农历年将跳过" in preview.json()["warnings"]


def test_join_invalid_code() -> None:
    limiter.reset()
    client = _client_with_db()
    resp = client.post("/api/public/groups/join", json={"group_code": "NOTEXIST1"})
    assert resp.status_code == 404


def test_reminder_update_delete_and_session_reset() -> None:
    client = _client_with_db()
    admin_headers = {"X-Admin-Token": "test-admin-token"}
    created_group = client.post(
        "/api/admin/groups",
        headers=admin_headers,
        json={
            "name": "家庭群",
            "code": "FAMILY01",
            "push_topic_code": "family001",
            "default_remind_time": "09:00:00",
        },
    )
    assert created_group.status_code == 201
    group_id = created_group.json()["id"]

    joined = client.post("/api/public/groups/join", json={"group_code": "FAMILY01"})
    token = joined.json()["session"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        "/api/group/reminders",
        headers=headers,
        json={
            "title": "生日",
            "calendar_type": "solar",
            "month": 12,
            "day": 20,
            "is_recurring": True,
            "enabled": True,
            "rule": {"remind_time": "09:00:00", "advance_days": 7, "include_on_day": True},
        },
    )
    assert created.status_code == 201
    reminder_id = created.json()["id"]

    updated = client.put(
        f"/api/group/reminders/{reminder_id}",
        headers=headers,
        json={
            "title": "生日（已修改）",
            "calendar_type": "solar",
            "month": 12,
            "day": 20,
            "is_recurring": True,
            "enabled": True,
            "rule": {"remind_time": "10:00:00", "advance_days": 3, "include_on_day": False},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["rule_text"] == "提前3天 10:00"

    deleted = client.delete(f"/api/group/reminders/{reminder_id}", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/api/group/reminders", headers=headers).json() == []

    reset = client.post(
        f"/api/admin/groups/{group_id}/reset-code",
        headers=admin_headers,
        json={"code": "FAMILY99"},
    )
    assert reset.status_code == 200
    assert client.get("/api/group/me", headers=headers).status_code == 401


def test_invalid_empty_reminder_rule_is_rejected() -> None:
    client = _client_with_db()
    client.post(
        "/api/admin/groups",
        headers={"X-Admin-Token": "test-admin-token"},
        json={
            "name": "家庭群",
            "code": "FAMILY01",
            "push_topic_code": "family001",
            "default_remind_time": "09:00:00",
        },
    )
    joined = client.post("/api/public/groups/join", json={"group_code": "FAMILY01"})
    headers = {"Authorization": f"Bearer {joined.json()['session']['token']}"}
    response = client.post(
        "/api/group/reminders",
        headers=headers,
        json={
            "title": "无效提醒",
            "calendar_type": "solar",
            "month": 1,
            "day": 1,
            "is_recurring": True,
            "enabled": True,
            "rule": {"remind_time": "09:00:00", "advance_days": 0, "include_on_day": False},
        },
    )
    assert response.status_code == 422
