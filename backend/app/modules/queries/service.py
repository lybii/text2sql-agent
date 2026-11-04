"""Query lifecycle: plan (graph) → [edit] → approve → execute → explain. `app.query_runs` is the source of truth."""

import hashlib
import logging
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.factory import get_planning_graph
from app.agent.state import PlanState
from app.analysis.chart import recommend_chart
from app.core.config import get_settings
from app.core.errors import AppError, Conflict, NotFound
from app.core.logging import redact
from app.db.models import Conversation, Feedback, Message, QueryRun, User
from app.db.session import analytics_engine
from app.guardrails.grounding import ungrounded_numbers
from app.llm.base import ChatTurn, ExplainInput
from app.llm.demo.provider import explain_deterministic
from app.llm.factory import get_gateway
from app.llm.prompts import PROMPT_VERSION
from app.modules.access.service import accessible_datasets, can_access
from app.observability import metrics
from app.observability.audit import audit
from app.observability.tracing import get_tracer, set_span_output
from app.semantic.registry import get_registry
from app.sql.executor import QueryExecutionError, execute_readonly
from app.sql.guard import check_sql, is_aggregate_query

log = logging.getLogger(__name__)

DEFAULT_TITLE = "Cuộc trò chuyện mới"


def compute_sql_hash(sql: str, dataset_code: str) -> str:
    return hashlib.sha256(f"{dataset_code}\n{sql}".encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


# ================================================================================================ plan


async def _history(session: AsyncSession, conversation_id: int, window: int) -> list[ChatTurn]:
    rows = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(window)
    )
    return [ChatTurn(role=m.role, content=m.content) for m in reversed(list(rows))]  # type: ignore[arg-type]


async def plan_question(
    session: AsyncSession, user: User, conversation: Conversation, question: str
) -> tuple[Message, Message, QueryRun]:
    settings = get_settings()
    registry = get_registry()
    gateway = get_gateway()
    tracer = get_tracer()

    # A new question supersedes anything still waiting for approval in this conversation.
    superseded = await session.scalars(
        update(QueryRun)
        .where(QueryRun.conversation_id == conversation.id, QueryRun.status == "awaiting_approval")
        .values(status="superseded", finished_at=_now())
        .returning(QueryRun.id)
    )
    for run_id in superseded:
        audit(session, actor_id=user.id, action="query.superseded", entity="query_run", entity_id=run_id)

    history = await _history(session, conversation.id, settings.history_window)
    accessible = await accessible_datasets(session, user, registry)
    trace_id = tracer.new_trace_id()

    started = time.perf_counter()
    initial: PlanState = {
        "question": question,
        "history": history,
        "accessible_datasets": accessible,
        "today": date.today(),
    }
    with tracer.span("plan_query", trace_id, input={"question": redact(question)}) as span:
        state = cast(
            PlanState,
            await get_planning_graph().ainvoke(
                initial,
                config={"callbacks": tracer.langchain_callbacks(trace_id), "run_name": "planning_graph"},
            ),
        )
        set_span_output(span, {"outcome": state.get("outcome"), "sql": state.get("sql")})
    planning_ms = round((time.perf_counter() - started) * 1000)
    outcome = state["outcome"]
    metrics.PLAN_LATENCY.observe(planning_ms / 1000)
    metrics.PLAN_OUTCOMES.labels(outcome).inc()

    usage = state.get("usage", [])
    sql = state.get("sql")
    dataset_code = state.get("dataset_code")
    llm_usage = [u for u in usage if u.route != "demo"] or usage
    run = QueryRun(
        user_id=user.id,
        conversation_id=conversation.id,
        question=question,
        standalone_question=state.get("standalone_question"),
        dataset_code=dataset_code,
        status=outcome,
        sql=sql,
        sql_hash=compute_sql_hash(sql, dataset_code) if sql and dataset_code else None,
        interpretation=state.get("interpretation") if outcome in ("awaiting_approval", "rejected") else None,
        assumptions=state.get("assumptions", []) if sql else [],
        validation_errors=state.get("validation_errors", []) if outcome == "rejected" else [],
        sql_attempts=state.get("attempts", 0),
        risk_level=state.get("risk_level"),
        expires_at=_now() + timedelta(minutes=settings.approval_ttl_minutes)
        if outcome == "awaiting_approval"
        else None,
        trace_id=trace_id,
        prompt_version=PROMPT_VERSION,
        llm_model=llm_usage[-1].model if llm_usage else None,
        llm_route="cache" if state.get("from_cache") else (llm_usage[-1].route if llm_usage else None),
        prompt_tokens=sum(u.prompt_tokens for u in usage),
        completion_tokens=sum(u.completion_tokens for u in usage),
        cost_usd=sum(gateway.cost(u) for u in usage),
        planning_ms=planning_ms,
    )
    session.add(run)
    await session.flush()

    user_msg = Message(conversation_id=conversation.id, role="user", content=question, query_run_id=run.id)
    assistant_msg = Message(
        conversation_id=conversation.id, role="assistant", content=state["reply"], query_run_id=run.id
    )
    session.add_all([user_msg, assistant_msg])
    conversation.updated_at = _now()
    if conversation.title == DEFAULT_TITLE:
        conversation.title = question.strip()[:80]
    audit(
        session,
        actor_id=user.id,
        action="query.planned",
        entity="query_run",
        entity_id=run.id,
        outcome=outcome,
        dataset=dataset_code,
        risk=run.risk_level,
        sql_hash=run.sql_hash,
        block_reason=state.get("block_reason"),
    )
    await session.commit()
    log.info(
        "query planned",
        extra={"fields": {"run_id": run.id, "outcome": outcome, "ms": planning_ms, "route": run.llm_route}},
    )

    if outcome == "awaiting_approval" and settings.approval_mode == "risk_based" and run.risk_level == "low":
        await _start_execution(session, run, user, decision="auto_executed")
    return user_msg, assistant_msg, run


# ================================================================================================ HITL


async def get_owned_run(session: AsyncSession, user: User, run_id: int) -> QueryRun:
    run = await session.get(QueryRun, run_id)
    if run is None or run.user_id != user.id:
        raise NotFound("Không tìm thấy truy vấn")
    return run


async def _expire_if_due(session: AsyncSession, run: QueryRun) -> None:
    if run.status == "awaiting_approval" and run.expires_at and run.expires_at <= _now():
        run.status = "expired"
        run.finished_at = _now()
        audit(session, actor_id=None, action="query.expired", entity="query_run", entity_id=run.id)
        metrics.HITL_DECISIONS.labels("expired").inc()
        await session.commit()


async def approve(session: AsyncSession, user: User, run_id: int, sql_hash: str) -> QueryRun:
    run = await get_owned_run(session, user, run_id)
    await _expire_if_due(session, run)
    if run.status in ("running", "succeeded") and run.sql_hash == sql_hash:
        return run  # idempotent retry / double click
    if run.status != "awaiting_approval":
        raise Conflict(f"Truy vấn không còn chờ duyệt (trạng thái: {run.status})")
    if run.sql_hash != sql_hash:
        raise Conflict("SQL đã thay đổi so với bản bạn xem. Hãy tải lại trước khi duyệt.", code="sql_changed")
    await _start_execution(session, run, user, decision="approved")
    return run


async def _start_execution(session: AsyncSession, run: QueryRun, user: User, *, decision: str) -> None:
    # Atomic transition: only one caller can move this run to `running`, and only for the hash shown.
    claimed = await session.scalar(
        update(QueryRun)
        .where(
            QueryRun.id == run.id,
            QueryRun.status == "awaiting_approval",
            QueryRun.sql_hash == run.sql_hash,
            QueryRun.expires_at > _now(),
        )
        .values(status="running", approved_at=_now(), auto_executed=decision == "auto_executed")
        .returning(QueryRun.id)
    )
    if claimed is None:
        await session.rollback()
        raise Conflict("Truy vấn đã được xử lý hoặc đã hết hạn")
    audit(session, actor_id=user.id, action=f"query.{decision}", entity="query_run", entity_id=run.id,
          sql_hash=run.sql_hash, risk=run.risk_level, edited=run.edited)  # fmt: skip
    metrics.HITL_DECISIONS.labels(decision).inc()
    await session.commit()
    await session.refresh(run)
    await _execute(session, run, user)


async def _fail(session: AsyncSession, run: QueryRun, user: User, message: str, **detail: Any) -> None:
    run.status = "failed"
    run.error_message = message
    run.finished_at = _now()
    audit(session, actor_id=user.id, action="query.failed", entity="query_run", entity_id=run.id,
          error=message, **detail)  # fmt: skip
    await session.commit()


async def _execute(session: AsyncSession, run: QueryRun, user: User) -> None:
    settings = get_settings()
    registry = get_registry()
    tracer = get_tracer()
    assert run.sql and run.dataset_code

    # Re-check at execution time: access may have been revoked while the run waited for approval.
    if not await can_access(session, user, registry, run.dataset_code):
        await _fail(session, run, user, "Quyền truy cập dataset đã bị thu hồi.", reason="access_revoked")
        return
    verdict = check_sql(run.sql, registry.schema_mapping(run.dataset_code), max_rows=settings.query_max_rows)
    if not verdict.ok or verdict.sql is None:
        metrics.GUARD_REJECTIONS.labels("execute").inc()
        await _fail(session, run, user, "SQL không còn hợp lệ: " + "; ".join(verdict.errors), reason="guard")
        return

    started = time.perf_counter()
    with tracer.span("execute_sql", run.trace_id, input={"sql": verdict.sql}) as span:
        try:
            result = await execute_readonly(
                analytics_engine(), verdict.sql, timeout_ms=settings.query_timeout_ms
            )
        except QueryExecutionError as exc:
            metrics.QUERY_EXEC_LATENCY.labels("error").observe(time.perf_counter() - started)
            run.execution_ms = round((time.perf_counter() - started) * 1000)
            await _fail(session, run, user, str(exc), reason="execution")
            return
        set_span_output(span, {"row_count": len(result.rows), "ms": result.elapsed_ms})
    metrics.QUERY_EXEC_LATENCY.labels("ok").observe(result.elapsed_ms / 1000)

    run.columns = result.columns
    run.rows = result.rows
    run.row_count = len(result.rows)
    run.truncated = verdict.limit_applied and len(result.rows) >= settings.query_max_rows
    run.execution_ms = result.elapsed_ms
    run.chart = dict(recommend_chart(result.columns, result.rows) or {}) or None
    await _explain(run)
    run.status = "succeeded"
    run.finished_at = _now()
    audit(session, actor_id=user.id, action="query.executed", entity="query_run", entity_id=run.id,
          row_count=run.row_count, ms=run.execution_ms)  # fmt: skip
    await session.commit()


async def _explain(run: QueryRun) -> None:
    """LLM explanation + grounding check; ungrounded numbers → deterministic explanation."""
    gateway, tracer = get_gateway(), get_tracer()
    inp = ExplainInput(
        question=run.standalone_question or run.question,
        interpretation=run.interpretation or "",
        columns=run.columns or [],
        rows=(run.rows or [])[:50],
        row_count=run.row_count or 0,
        truncated=run.truncated,
    )
    started = time.perf_counter()
    try:
        result = await gateway.explain_result(inp, callbacks=tracer.langchain_callbacks(run.trace_id))
        explanation = result.value
        run.prompt_tokens += result.usage.prompt_tokens
        run.completion_tokens += result.usage.completion_tokens
        run.cost_usd += gateway.cost(result.usage)
    except Exception:
        log.warning("explanation failed; using deterministic summary", exc_info=True)
        explanation = explain_deterministic(inp)
    text = " ".join([explanation.summary, *explanation.highlights])
    context = f"{run.question} {run.standalone_question or ''} {run.interpretation or ''} {run.sql or ''}"
    bad = ungrounded_numbers(text, rows=run.rows or [], row_count=run.row_count or 0, context=context)
    run.explanation_grounded = not bad
    metrics.GROUNDING.labels("grounded" if not bad else "ungrounded").inc()
    if bad:
        log.warning(
            "ungrounded numbers in explanation", extra={"fields": {"run_id": run.id, "numbers": bad[:5]}}
        )
        explanation = explain_deterministic(inp)
    run.explanation = explanation.model_dump()
    run.explain_ms = round((time.perf_counter() - started) * 1000)


async def edit(session: AsyncSession, user: User, run_id: int, sql: str) -> QueryRun:
    settings = get_settings()
    registry = get_registry()
    run = await get_owned_run(session, user, run_id)
    await _expire_if_due(session, run)
    if run.status != "awaiting_approval" or not run.dataset_code:
        raise Conflict("Chỉ sửa được truy vấn đang chờ duyệt")
    verdict = check_sql(sql, registry.schema_mapping(run.dataset_code), max_rows=settings.query_max_rows)
    if not verdict.ok or verdict.sql is None:
        metrics.GUARD_REJECTIONS.labels("edit").inc()
        raise AppError("SQL không hợp lệ: " + "; ".join(verdict.errors), code="sql_rejected")
    old_hash = run.sql_hash
    run.sql = verdict.sql
    run.sql_hash = compute_sql_hash(verdict.sql, run.dataset_code)
    run.edited = True
    confidential = registry.require(run.dataset_code).sensitivity == "confidential"
    run.risk_level = "high" if confidential or not is_aggregate_query(verdict.sql) else "low"
    audit(session, actor_id=user.id, action="query.edited", entity="query_run", entity_id=run.id,
          old_hash=old_hash, new_hash=run.sql_hash)  # fmt: skip
    metrics.HITL_DECISIONS.labels("edited").inc()
    await session.commit()
    return run


async def cancel(session: AsyncSession, user: User, run_id: int) -> QueryRun:
    run = await get_owned_run(session, user, run_id)
    if run.status != "awaiting_approval":
        raise Conflict("Chỉ hủy được truy vấn đang chờ duyệt")
    run.status = "cancelled"
    run.finished_at = _now()
    audit(session, actor_id=user.id, action="query.cancelled", entity="query_run", entity_id=run.id)
    metrics.HITL_DECISIONS.labels("cancelled").inc()
    await session.commit()
    return run


async def give_feedback(
    session: AsyncSession, user: User, run_id: int, rating: int, comment: str | None
) -> None:
    run = await get_owned_run(session, user, run_id)
    if run.status != "succeeded":
        raise Conflict("Chỉ đánh giá được truy vấn đã chạy thành công")
    existing = await session.scalar(
        select(Feedback).where(Feedback.query_run_id == run.id, Feedback.user_id == user.id)
    )
    if existing:
        existing.rating, existing.comment = rating, comment
    else:
        session.add(Feedback(query_run_id=run.id, user_id=user.id, rating=rating, comment=comment))
    await session.commit()
    get_tracer().score(run.trace_id, "user_feedback", float(rating), comment)


async def feedback_map(session: AsyncSession, user_id: int, run_ids: list[int]) -> dict[int, int]:
    if not run_ids:
        return {}
    rows = await session.execute(
        select(Feedback.query_run_id, Feedback.rating).where(
            Feedback.user_id == user_id, Feedback.query_run_id.in_(run_ids)
        )
    )
    return {rid: rating for rid, rating in rows.all()}
