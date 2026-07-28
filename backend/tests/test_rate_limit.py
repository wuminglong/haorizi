from __future__ import annotations

from datetime import datetime, timedelta, timezone

import app.services.rate_limit as rate_limit
from app.services.rate_limit import MemoryRateLimiter


def test_rate_limit_blocks_after_threshold() -> None:
    limiter = MemoryRateLimiter()
    key = "ip:1"
    for _ in range(3):
        assert limiter.hit(key, limit=3, window_seconds=60).allowed
    assert not limiter.hit(key, limit=3, window_seconds=60).allowed


def test_error_cooldown() -> None:
    limiter = MemoryRateLimiter()
    key = "err:1"
    for _ in range(2):
        assert limiter.record_error(key, threshold=3, cooldown_seconds=60).allowed
    blocked = limiter.record_error(key, threshold=3, cooldown_seconds=60)
    assert not blocked.allowed


def test_multiple_windows_keep_long_window_history(monkeypatch) -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(rate_limit, "_now", lambda: now)
    limiter = MemoryRateLimiter()

    for _ in range(3):
        assert limiter.hit_many("join:ip", [(10, 60), (3, 600)]).allowed
        now += timedelta(seconds=70)

    assert not limiter.hit_many("join:ip", [(10, 60), (3, 600)]).allowed
