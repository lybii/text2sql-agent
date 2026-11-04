"""Exact-match plan cache (ADR-11). Stores only drafts that already passed the SQL guard."""

import hashlib
import time
from collections import OrderedDict
from collections.abc import Callable

from app.core.text import normalize
from app.llm.base import SqlDraft
from app.observability import metrics


class PlanCache:
    def __init__(
        self, *, ttl_seconds: int, max_size: int, namespace: str, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_size
        self._namespace = namespace  # prompt version + semantic fingerprint: changes invalidate everything
        self._clock = clock
        self._items: OrderedDict[str, tuple[float, SqlDraft]] = OrderedDict()

    def key(self, question: str, dataset_code: str) -> str:
        raw = f"{self._namespace}|{dataset_code}|{normalize(question)}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, question: str, dataset_code: str) -> SqlDraft | None:
        if self._ttl <= 0:
            return None
        k = self.key(question, dataset_code)
        item = self._items.get(k)
        if item is None or self._clock() - item[0] > self._ttl:
            self._items.pop(k, None)
            metrics.PLAN_CACHE.labels("miss").inc()
            return None
        self._items.move_to_end(k)
        metrics.PLAN_CACHE.labels("hit").inc()
        return item[1]

    def put(self, question: str, dataset_code: str, draft: SqlDraft) -> None:
        if self._ttl <= 0:
            return
        self._items[self.key(question, dataset_code)] = (self._clock(), draft)
        self._items.move_to_end(self.key(question, dataset_code))
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()
