"""Quality & HITL dashboard data for admins. Aggregates only — no question text, no result rows."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import and_, case, func, select

from app.db.models import AuditEvent, Feedback, QueryRun, User
from app.modules.auth.deps import AdminUser, SessionDep

router = APIRouter(prefix="/admin", tags=["admin"])

_DECIDED = ("succeeded", "failed", "running", "cancelled", "expired", "superseded")


class StatsOut(BaseModel):
    days: int
    totals: dict[str, int]
    rates: dict[str, float | None]
    latency_ms: dict[str, float | None]
    llm: dict[str, Any]
    hitl: dict[str, Any]
    feedback: dict[str, int]
    by_prompt_version: list[dict[str, Any]]


class AuditOut(BaseModel):
    id: int
    created_at: datetime
    actor: str | None
    action: str
    entity: str
    entity_id: int | None
    detail: dict[str, Any]


def _pct(col: Any, p: float) -> Any:
    return func.percentile_cont(p).within_group(col)


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


@router.get("/stats")
async def stats(_: AdminUser, session: SessionDep, days: int = Query(30, ge=1, le=365)) -> StatsOut:
    since = datetime.now(UTC) - timedelta(days=days)
    in_window = QueryRun.created_at >= since

    status_rows = await session.execute(
        select(QueryRun.status, func.count()).where(in_window).group_by(QueryRun.status)
    )
    totals = {s: n for s, n in status_rows.all()}
    total = sum(totals.values())

    lat = (
        await session.execute(
            select(
                _pct(QueryRun.planning_ms, 0.5),
                _pct(QueryRun.planning_ms, 0.95),
                _pct(QueryRun.planning_ms, 0.99),
                _pct(QueryRun.execution_ms, 0.5),
                _pct(QueryRun.execution_ms, 0.95),
            ).where(in_window)
        )
    ).one()

    llm = (
        await session.execute(
            select(
                func.coalesce(func.sum(QueryRun.prompt_tokens), 0),
                func.coalesce(func.sum(QueryRun.completion_tokens), 0),
                func.coalesce(func.sum(QueryRun.cost_usd), 0.0),
                func.count().filter(QueryRun.llm_route == "cache"),
                func.count().filter(QueryRun.llm_route.in_(("fallback", "demo"))),
                func.count().filter(QueryRun.sql.is_not(None)),
                func.count().filter(QueryRun.explanation_grounded.is_(False)),
                func.count().filter(QueryRun.explanation_grounded.is_not(None)),
            ).where(in_window)
        )
    ).one()
    tokens_in, tokens_out, cost, cache_hits, degraded, with_sql, ungrounded, explained = llm

    hitl = (
        await session.execute(
            select(
                func.count().filter(QueryRun.approved_at.is_not(None), QueryRun.auto_executed.is_(False)),
                func.count().filter(QueryRun.auto_executed.is_(True)),
                func.count().filter(QueryRun.edited.is_(True), QueryRun.status.in_(_DECIDED)),
                func.count().filter(QueryRun.status.in_(_DECIDED), QueryRun.sql.is_not(None)),
                _pct(func.extract("epoch", QueryRun.approved_at - QueryRun.created_at), 0.5).filter(
                    and_(QueryRun.approved_at.is_not(None), QueryRun.auto_executed.is_(False))
                ),
            ).where(in_window)
        )
    ).one()
    approved, auto_exec, edited, decided, median_wait = hitl

    fb_rows = await session.execute(
        select(Feedback.rating, func.count())
        .join(QueryRun, QueryRun.id == Feedback.query_run_id)
        .where(in_window)
        .group_by(Feedback.rating)
    )
    fb = {("up" if r == 1 else "down"): n for r, n in fb_rows.all()}

    pv_rows = await session.execute(
        select(
            QueryRun.prompt_version,
            func.count(),
            func.avg(case((QueryRun.status == "succeeded", 1.0), else_=0.0)),
            func.avg(QueryRun.planning_ms),
            func.avg(QueryRun.cost_usd),
        )
        .where(in_window)
        .group_by(QueryRun.prompt_version)
    )

    succeeded, failed = totals.get("succeeded", 0), totals.get("failed", 0)
    return StatsOut(
        days=days,
        totals={"runs": total, **totals},
        rates={
            "execution_success": _ratio(succeeded, succeeded + failed),
            "clarification": _ratio(totals.get("clarification", 0), total),
            "guard_rejected": _ratio(totals.get("rejected", 0), total),
            "input_blocked": _ratio(totals.get("blocked", 0), total),
            "access_required": _ratio(totals.get("access_required", 0), total),
        },
        latency_ms={
            "planning_p50": lat[0],
            "planning_p95": lat[1],
            "planning_p99": lat[2],
            "execution_p50": lat[3],
            "execution_p95": lat[4],
        },
        llm={
            "prompt_tokens": int(tokens_in),
            "completion_tokens": int(tokens_out),
            "cost_usd": round(float(cost), 4),
            "cost_per_run_usd": round(float(cost) / total, 6) if total else None,
            "plan_cache_hit_rate": _ratio(cache_hits, with_sql),
            "degraded_route_rate": _ratio(degraded, total),
            "ungrounded_explanation_rate": _ratio(ungrounded, explained),
        },
        hitl={
            "approved": approved,
            "auto_executed": auto_exec,
            "cancelled": totals.get("cancelled", 0),
            "expired": totals.get("expired", 0),
            "superseded": totals.get("superseded", 0),
            "approval_rate": _ratio(approved + auto_exec, decided),
            "edit_rate": _ratio(edited, decided),
            "median_seconds_to_approve": round(median_wait, 1) if median_wait is not None else None,
        },
        feedback={"up": fb.get("up", 0), "down": fb.get("down", 0)},
        by_prompt_version=[
            {
                "prompt_version": pv,
                "runs": n,
                "success_share": round(float(s or 0), 4),
                "avg_planning_ms": round(float(ms or 0)),
                "avg_cost_usd": round(float(c or 0), 6),
            }
            for pv, n, s, ms, c in pv_rows.all()
        ],
    )


@router.get("/audit")
async def audit_log(
    _: AdminUser, session: SessionDep, limit: int = Query(100, ge=1, le=500), action: str | None = None
) -> list[AuditOut]:
    query = (
        select(AuditEvent, User.email)
        .outerjoin(User, User.id == AuditEvent.actor_id)
        .order_by(AuditEvent.id.desc())
        .limit(limit)
    )
    if action:
        query = query.where(AuditEvent.action.like(f"{action}%"))
    rows = await session.execute(query)
    return [
        AuditOut(
            id=e.id,
            created_at=e.created_at,
            actor=email or ("system" if e.actor_id is None else None),
            action=e.action,
            entity=e.entity,
            entity_id=e.entity_id,
            detail=e.detail,
        )
        for e, email in rows.all()
    ]
