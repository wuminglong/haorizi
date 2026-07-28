from __future__ import annotations

import pytest

from app.services.groups import GroupError, mask_group_code, normalize_group_code


def test_normalize_group_code_ok() -> None:
    assert normalize_group_code(" family01 ") == "FAMILY01"


def test_normalize_group_code_invalid() -> None:
    with pytest.raises(GroupError):
        normalize_group_code("ab")


def test_mask_group_code() -> None:
    assert mask_group_code("FAMILY01") == "FA****01"
