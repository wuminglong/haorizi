from __future__ import annotations

from app.security import create_group_session_token, parse_group_session_token
from app.services.groups import code_version, create_group, reset_group_code


def test_session_roundtrip_and_reset_invalidates(db_session) -> None:
    group = create_group(
        db_session,
        name="测试群",
        code="FAMILY01",
        push_topic_code="family001",
    )
    token = create_group_session_token(group.id, code_version(group))
    payload = parse_group_session_token(token)
    assert payload is not None
    assert payload["gid"] == group.id

    reset_group_code(db_session, group, "FAMILY99")
    # Token signature remains valid, but the dependency rejects the stale code version.
    old = parse_group_session_token(token)
    assert old is not None
    assert old["code_ver"] != code_version(group)
