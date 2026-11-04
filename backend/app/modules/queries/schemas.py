from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.db.models import QueryRun
from app.observability.tracing import get_tracer
from app.semantic.registry import get_registry


class ApproveIn(BaseModel):
    sql_hash: str = Field(min_length=64, max_length=64)


class EditIn(BaseModel):
    sql: str = Field(min_length=10, max_length=5000)


class FeedbackIn(BaseModel):
    rating: Literal[-1, 1]
    comment: str | None = Field(default=None, max_length=1000)


class RunMetrics(BaseModel):
    prompt_version: str | None
    llm_model: str | None
    llm_route: str | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    sql_attempts: int
    planning_ms: int | None
    execution_ms: int | None
    explain_ms: int | None


class QueryRunOut(BaseModel):
    id: int
    conversation_id: int
    status: str
    question: str
    standalone_question: str | None
    dataset_code: str | None
    dataset_name: str | None
    sql: str | None
    sql_hash: str | None
    interpretation: str | None
    assumptions: list[str]
    validation_errors: list[str]
    risk_level: str | None
    edited: bool
    auto_executed: bool
    expires_at: datetime | None
    columns: list[dict[str, Any]] | None
    rows: list[list[Any]] | None
    row_count: int | None
    truncated: bool
    chart: dict[str, Any] | None
    explanation: dict[str, Any] | None
    explanation_grounded: bool | None
    error_message: str | None
    metrics: RunMetrics
    feedback: int | None = None
    trace_url: str | None = None
    created_at: datetime
    approved_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def build(cls, run: QueryRun, feedback: int | None = None) -> "QueryRunOut":
        dataset = get_registry().get(run.dataset_code) if run.dataset_code else None
        return cls(
            id=run.id,
            conversation_id=run.conversation_id,
            status=run.status,
            question=run.question,
            standalone_question=run.standalone_question,
            dataset_code=run.dataset_code,
            dataset_name=dataset.name if dataset else None,
            sql=run.sql,
            sql_hash=run.sql_hash,
            interpretation=run.interpretation,
            assumptions=run.assumptions or [],
            validation_errors=run.validation_errors or [],
            risk_level=run.risk_level,
            edited=run.edited,
            auto_executed=run.auto_executed,
            expires_at=run.expires_at,
            columns=run.columns,
            rows=run.rows,
            row_count=run.row_count,
            truncated=run.truncated,
            chart=run.chart,
            explanation=run.explanation,
            explanation_grounded=run.explanation_grounded,
            error_message=run.error_message,
            metrics=RunMetrics(
                prompt_version=run.prompt_version,
                llm_model=run.llm_model,
                llm_route=run.llm_route,
                prompt_tokens=run.prompt_tokens,
                completion_tokens=run.completion_tokens,
                cost_usd=round(run.cost_usd, 6),
                sql_attempts=run.sql_attempts,
                planning_ms=run.planning_ms,
                execution_ms=run.execution_ms,
                explain_ms=run.explain_ms,
            ),
            feedback=feedback,
            trace_url=get_tracer().trace_url(run.trace_id),
            created_at=run.created_at,
            approved_at=run.approved_at,
            finished_at=run.finished_at,
        )
