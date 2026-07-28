from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.config import get_settings


def _upgrade(database_path: Path, monkeypatch) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(config, "head")


def test_pre_group_table_name_collision_is_archived_before_bootstrap(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE reminders (id INTEGER PRIMARY KEY, title VARCHAR(100), month INTEGER, day INTEGER)"
        )
        connection.execute("INSERT INTO reminders (id, title, month, day) VALUES (1, '旧提醒', 8, 15)")

    _upgrade(database_path, monkeypatch)

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {
            "groups",
            "reminders",
            "reminder_rules",
            "reminder_plans",
            "send_logs",
            "legacy_pre_group_20260728_reminders",
        } <= tables

        current_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(reminders)")
        }
        assert {"group_id", "calendar_type", "leap_month_policy", "missing_day_policy"} <= current_columns

        archived = connection.execute(
            "SELECT id, title, month, day FROM legacy_pre_group_20260728_reminders"
        ).fetchone()
        assert archived == (1, "旧提醒", 8, 15)


def test_unknown_partial_group_schema_fails_before_alembic_stamp(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "unknown.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE groups (id INTEGER PRIMARY KEY, name VARCHAR(100))")

    with pytest.raises(RuntimeError, match="incomplete group-reminder schema"):
        _upgrade(database_path, monkeypatch)

    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        assert revision is None
