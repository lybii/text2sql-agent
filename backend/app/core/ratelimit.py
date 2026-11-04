"""Per-user sliding-window rate limit (in-process; use Redis when running several replicas)."""

import time
from collections import defaultdict, deque
from collections.abc import Callable

from app.core.errors import AppError


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class RateLimiter:
    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._limit = per_minute
        self._clock = clock
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def check(self, user_id: int) -> None:
        if self._limit <= 0:
            return
        now = self._clock()
        hits = self._hits[user_id]
        while hits and now - hits[0] > 60:
            hits.popleft()
        if len(hits) >= self._limit:
            raise RateLimited("Bạn gửi câu hỏi quá nhanh. Vui lòng thử lại sau ít phút.")
        hits.append(now)
