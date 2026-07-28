from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.dialects import mysql, sqlite

from app.models import UTCDateTime


def test_utc_datetime_mysql_bind_and_result_are_explicit_utc() -> None:
    value = datetime(2026, 7, 28, 9, 0, tzinfo=timezone(timedelta(hours=8)))
    column_type = UTCDateTime()
    stored = column_type.process_bind_param(value, mysql.dialect())
    assert stored == datetime(2026, 7, 28, 1, 0)
    assert stored.tzinfo is None

    loaded = column_type.process_result_value(stored, mysql.dialect())
    assert loaded == datetime(2026, 7, 28, 1, 0, tzinfo=timezone.utc)


def test_utc_datetime_sqlite_roundtrip_normalizes_aware_values() -> None:
    column_type = UTCDateTime()
    stored = column_type.process_bind_param(
        datetime(2026, 7, 28, 1, 0, tzinfo=timezone.utc),
        sqlite.dialect(),
    )
    assert column_type.process_result_value(stored, sqlite.dialect()).tzinfo == timezone.utc
