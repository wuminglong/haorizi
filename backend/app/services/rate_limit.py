from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RateLimitResult:
    allowed: bool
    detail: str = ""


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[datetime]] = defaultdict(deque)
        self._errors: dict[str, int] = defaultdict(int)
        self._cooldown_until: dict[str, datetime] = {}
        self._lock = Lock()

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._errors.clear()
            self._cooldown_until.clear()

    def _prune(self, key: str, window: timedelta, now: datetime) -> None:
        q = self._events[key]
        threshold = now - window
        while q and q[0] < threshold:
            q.popleft()

    def hit(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult:
        now = _now()
        with self._lock:
            cooldown = self._cooldown_until.get(key)
            if cooldown and now < cooldown:
                return RateLimitResult(False, "操作太频繁，请稍后再试")
            self._prune(key, timedelta(seconds=window_seconds), now)
            q = self._events[key]
            if len(q) >= limit:
                return RateLimitResult(False, "操作太频繁，请稍后再试")
            q.append(now)
            return RateLimitResult(True)

    def hit_many(self, key: str, checks: list[tuple[int, int]]) -> RateLimitResult:
        """checks: list of (limit, window_seconds). Counts one event against all windows."""
        if not checks:
            return RateLimitResult(True)
        now = _now()
        with self._lock:
            cooldown = self._cooldown_until.get(key)
            if cooldown and now < cooldown:
                return RateLimitResult(False, "操作太频繁，请稍后再试")
            if cooldown:
                self._cooldown_until.pop(key, None)

            queue = self._events[key]
            max_window = max(window_seconds for _, window_seconds in checks)
            self._prune(key, timedelta(seconds=max_window), now)
            for limit, window_seconds in checks:
                threshold = now - timedelta(seconds=window_seconds)
                count = sum(event >= threshold for event in queue)
                if count >= limit:
                    return RateLimitResult(False, "操作太频繁，请稍后再试")
            queue.append(now)
            return RateLimitResult(True)

    def record_error(self, key: str, *, threshold: int, cooldown_seconds: int) -> RateLimitResult:
        now = _now()
        with self._lock:
            self._errors[key] += 1
            if self._errors[key] >= threshold:
                self._cooldown_until[key] = now + timedelta(seconds=cooldown_seconds)
                self._errors[key] = 0
                return RateLimitResult(False, "尝试次数过多，请稍后再试")
            return RateLimitResult(True)

    def clear_errors(self, key: str) -> None:
        with self._lock:
            self._errors.pop(key, None)
            self._cooldown_until.pop(key, None)


limiter = MemoryRateLimiter()
