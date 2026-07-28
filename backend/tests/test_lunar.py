from __future__ import annotations

from datetime import date

import pytest

from app.services.lunar import lunar_to_solar


def test_lunar_new_year_conversion() -> None:
    assert lunar_to_solar(2026, 1, 1, False) == date(2026, 2, 17)


def test_lunar_mid_autumn_conversion() -> None:
    assert lunar_to_solar(2026, 8, 15, False) == date(2026, 9, 25)


def test_invalid_lunar_day_is_not_silently_reduced() -> None:
    with pytest.raises(ValueError, match="day out of range"):
        lunar_to_solar(2026, 2, 30, False)
