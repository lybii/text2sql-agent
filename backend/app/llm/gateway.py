"""LLM gateway: circuit breaker + fallback ladder + cost accounting in front of the task providers.

    primary model ──(error / circuit open)──▶ fallback model ──▶ DemoProvider (deterministic)

The gateway implements `LLMProvider` itself, so the agent never knows which rung answered;
`Usage.route` records it for metrics and evaluation.
"""

import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypeVar

from app.llm.base import (
    AnalyzeInput,
    ExplainInput,
    Explanation,
    LLMProvider,
    LLMResult,
    QuestionAnalysis,
    SqlDraft,
    SqlInput,
    Usage,
)
from app.observability import metrics

log = logging.getLogger(__name__)
T = TypeVar("T")
State = Literal["closed", "open", "half_open"]
_STATE_VALUE = {"closed": 0, "open": 1, "half_open": 2}


class CircuitOpenError(RuntimeError):
    pass


class CircuitBreaker:
    """CLOSED → (N consecutive failures) → OPEN → (reset timeout) → HALF_OPEN → (probe ok) → CLOSED."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        reset_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at = 0.0
        self._state: State = "closed"
        self._publish()

    @property
    def state(self) -> State:
        if self._state == "open" and self._clock() - self._opened_at >= self.reset_seconds:
            self._state = "half_open"
            self._publish()
        return self._state

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        if self.state == "open":
            raise CircuitOpenError(f"circuit {self.name} is open")
        try:
            result = await fn()
        except Exception:
            self._record_failure()
            raise
        self._record_success()
        return result

    def _record_success(self) -> None:
        self._failures = 0
        if self._state != "closed":
            log.info("circuit closed", extra={"fields": {"provider": self.name}})
        self._state = "closed"
        self._publish()

    def _record_failure(self) -> None:
        self._failures += 1
        if self._state == "half_open" or self._failures >= self.failure_threshold:
            if self._state != "open":
                log.warning("circuit opened", extra={"fields": {"provider": self.name}})
            self._state = "open"
            self._opened_at = self._clock()
            self._publish()

    def _publish(self) -> None:
        metrics.CIRCUIT_STATE.labels(self.name).set(_STATE_VALUE[self._state])


class ChaosProvider:
    """Wraps a provider and fails a fraction of calls. Used by `make chaos` and tests only."""

    def __init__(self, inner: LLMProvider, failure_rate: float, rng: random.Random | None = None) -> None:
        self.name = f"chaos({inner.name})"
        self._inner = inner
        self._rate = failure_rate
        self._rng = rng or random.Random(7)

    def _maybe_fail(self) -> None:
        if self._rng.random() < self._rate:
            raise TimeoutError("chaos: injected provider failure")

    async def analyze_question(self, inp: AnalyzeInput) -> LLMResult[QuestionAnalysis]:
        self._maybe_fail()
        return await self._inner.analyze_question(inp)

    async def generate_sql(self, inp: SqlInput) -> LLMResult[SqlDraft]:
        self._maybe_fail()
        return await self._inner.generate_sql(inp)

    async def explain_result(
        self, inp: ExplainInput, *, callbacks: list[Any] | None = None
    ) -> LLMResult[Explanation]:
        self._maybe_fail()
        return await self._inner.explain_result(inp, callbacks=callbacks)


def estimate_cost(usage: Usage, prices: dict[str, list[float]]) -> float:
    price = prices.get(usage.model)
    if not price:
        return 0.0
    return (usage.prompt_tokens * price[0] + usage.completion_tokens * price[1]) / 1_000_000


class LLMGateway:
    name = "gateway"

    def __init__(
        self,
        demo: LLMProvider,
        primary: LLMProvider | None = None,
        fallback: LLMProvider | None = None,
        *,
        failure_threshold: int = 3,
        reset_seconds: float = 30.0,
        prices: dict[str, list[float]] | None = None,
    ) -> None:
        self._prices = prices or {}
        self._ladder: list[
            tuple[Literal["primary", "fallback", "demo"], LLMProvider, CircuitBreaker | None]
        ] = []
        if primary is not None:
            self._ladder.append(
                ("primary", primary, CircuitBreaker(primary.name, failure_threshold, reset_seconds))
            )
        if fallback is not None:
            self._ladder.append(
                ("fallback", fallback, CircuitBreaker(fallback.name, failure_threshold, reset_seconds))
            )
        self._ladder.append(("demo", demo, None))  # last rung: deterministic, no breaker

    @property
    def breakers(self) -> list[CircuitBreaker]:
        return [b for _, _, b in self._ladder if b is not None]

    async def _run(self, task: str, call: Callable[[LLMProvider], Awaitable[LLMResult[T]]]) -> LLMResult[T]:
        last_error: Exception | None = None
        for route, provider, breaker in self._ladder:
            started = time.perf_counter()
            try:
                if breaker is None:
                    result = await call(provider)
                else:
                    result = await breaker.call(lambda p=provider: call(p))  # type: ignore[misc]
            except CircuitOpenError as exc:
                metrics.LLM_CALLS.labels(task, route, "circuit_open").inc()
                last_error = exc
                continue
            except Exception as exc:
                metrics.LLM_CALLS.labels(task, route, "error").inc()
                log.warning(
                    "llm call failed",
                    extra={"fields": {"task": task, "route": route, "error": repr(exc)[:200]}},
                )
                last_error = exc
                continue
            metrics.LLM_CALLS.labels(task, route, "ok").inc()
            metrics.LLM_LATENCY.labels(task, route).observe(time.perf_counter() - started)
            usage = result.usage.model_copy(update={"route": route, "task": task})
            self._account(usage)
            return LLMResult(result.value, usage)
        raise RuntimeError(f"All LLM routes failed for {task}") from last_error

    def _account(self, usage: Usage) -> None:
        metrics.LLM_TOKENS.labels(usage.model, "input").inc(usage.prompt_tokens)
        metrics.LLM_TOKENS.labels(usage.model, "output").inc(usage.completion_tokens)
        metrics.LLM_COST.labels(usage.model).inc(estimate_cost(usage, self._prices))

    def cost(self, usage: Usage) -> float:
        return estimate_cost(usage, self._prices)

    async def analyze_question(self, inp: AnalyzeInput) -> LLMResult[QuestionAnalysis]:
        return await self._run("analyze_question", lambda p: p.analyze_question(inp))

    async def generate_sql(self, inp: SqlInput) -> LLMResult[SqlDraft]:
        return await self._run("generate_sql", lambda p: p.generate_sql(inp))

    async def explain_result(
        self, inp: ExplainInput, *, callbacks: list[Any] | None = None
    ) -> LLMResult[Explanation]:
        return await self._run("explain_result", lambda p: p.explain_result(inp, callbacks=callbacks))
