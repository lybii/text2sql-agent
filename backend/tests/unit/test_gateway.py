from datetime import date
from typing import Any

import pytest

from app.llm.base import (
    AnalyzeInput,
    ExplainInput,
    Explanation,
    LLMResult,
    QuestionAnalysis,
    SqlDraft,
    SqlInput,
    Usage,
)
from app.llm.demo.provider import DemoProvider
from app.llm.gateway import CircuitBreaker, CircuitOpenError, LLMGateway, estimate_cost
from app.semantic.registry import get_registry

INP = AnalyzeInput(question="Doanh thu năm 2025", history=[], catalog_summary="", today=date(2026, 1, 1))


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class Flaky:
    name = "flaky"

    def __init__(self, fail: bool = True) -> None:
        self.fail = fail
        self.calls = 0

    async def analyze_question(self, inp: AnalyzeInput) -> LLMResult[QuestionAnalysis]:
        self.calls += 1
        if self.fail:
            raise TimeoutError("boom")
        return LLMResult(
            QuestionAnalysis(
                intent="chitchat", standalone_question="x", needs_clarification=False, reply="ok"
            ),
            Usage(model="gpt-4o-mini", prompt_tokens=1000, completion_tokens=100),
        )

    async def generate_sql(self, inp: SqlInput) -> LLMResult[SqlDraft]:
        raise NotImplementedError

    async def explain_result(
        self, inp: ExplainInput, *, callbacks: list[Any] | None = None
    ) -> LLMResult[Explanation]:
        raise NotImplementedError


async def _ok() -> str:
    return "ok"


async def _boom() -> str:
    raise RuntimeError("x")


async def test_breaker_opens_then_half_opens_then_closes() -> None:
    clock = Clock()
    breaker = CircuitBreaker("p", failure_threshold=2, reset_seconds=10, clock=clock)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await breaker.call(_boom)
    assert breaker.state == "open"
    with pytest.raises(CircuitOpenError):
        await breaker.call(_ok)
    clock.t = 11
    assert breaker.state == "half_open"
    assert await breaker.call(_ok) == "ok"
    assert breaker.state == "closed"


async def test_half_open_failure_reopens_immediately() -> None:
    clock = Clock()
    breaker = CircuitBreaker("p", failure_threshold=3, reset_seconds=10, clock=clock)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await breaker.call(_boom)
    clock.t = 11
    with pytest.raises(RuntimeError):
        await breaker.call(_boom)
    assert breaker.state == "open"


async def test_fallback_ladder_reaches_demo_and_stops_calling_dead_primary() -> None:
    primary = Flaky(fail=True)
    gateway = LLMGateway(DemoProvider(get_registry()), primary, failure_threshold=2)
    for _ in range(4):
        result = await gateway.analyze_question(INP)
        assert result.usage.route == "demo"
    assert primary.calls == 2  # circuit open after 2 failures: later calls fail fast


async def test_primary_route_and_cost_accounting() -> None:
    gateway = LLMGateway(
        DemoProvider(get_registry()), Flaky(fail=False), prices={"gpt-4o-mini": [0.15, 0.60]}
    )
    result = await gateway.analyze_question(INP)
    assert result.usage.route == "primary" and result.usage.task == "analyze_question"
    assert gateway.cost(result.usage) == pytest.approx((1000 * 0.15 + 100 * 0.60) / 1e6)


def test_unknown_model_costs_nothing() -> None:
    assert estimate_cost(Usage(model="local", prompt_tokens=10), {"gpt-4o": [1, 1]}) == 0.0
