"""Planning graph: question → (guard | clarify | access check | SQL draft ⇄ guard) → awaiting_approval.

LLM nodes: analyze_question, generate_sql. Everything else is deterministic code (Plan-Then-Execute).
The graph never touches the database: entitlements come in through the state, so it is unit-testable.
"""

import logging
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.cache import PlanCache
from app.agent.state import STATE_VERSION, PlanState, RiskLevel
from app.core.text import contains_phrase, normalize
from app.guardrails.input import check_input
from app.llm.base import AnalyzeInput, LLMProvider, SqlDraft, SqlInput
from app.observability import metrics
from app.semantic.registry import SemanticRegistry
from app.sql.guard import check_sql, is_aggregate_query

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentDeps:
    llm: LLMProvider
    registry: SemanticRegistry
    cache: PlanCache | None = None
    max_rows: int = 500
    max_attempts: int = 2
    input_max_chars: int = 500


def build_planning_graph(deps: AgentDeps) -> CompiledStateGraph[Any, Any, Any, Any]:
    registry, llm, cache = deps.registry, deps.llm, deps.cache

    # ---------------------------------------------------------------- input rails
    async def input_guard(state: PlanState) -> PlanState:
        verdict = check_input(state["question"], max_chars=deps.input_max_chars)
        if verdict.ok:
            return {"state_version": STATE_VERSION}
        metrics.INPUT_BLOCKS.labels(verdict.reason or "unknown").inc()
        return {
            "state_version": STATE_VERSION,
            "outcome": "blocked",
            "block_reason": verdict.reason,
            "reply": verdict.message or "Yêu cầu bị từ chối.",
        }

    def route_after_input(state: PlanState) -> str:
        return "end" if state.get("outcome") == "blocked" else "analyze_question"

    # ---------------------------------------------------------------- understanding
    async def analyze_question(state: PlanState) -> PlanState:
        result = await llm.analyze_question(
            AnalyzeInput(
                question=state["question"],
                history=state.get("history", []),
                catalog_summary=registry.catalog_summary(),
                today=state["today"],
            )
        )
        a = result.value
        return {
            "intent": a.intent,
            "standalone_question": a.standalone_question or state["question"],
            "needs_clarification": a.needs_clarification,
            "clarification_question": a.clarification_question,
            "dataset_candidates": a.dataset_candidates,
            "direct_reply": a.reply,
            "usage": [result.usage],
        }

    def route_after_analyze(state: PlanState) -> str:
        if state["intent"] != "data_query":
            return "respond"
        return "clarify" if state["needs_clarification"] else "select_dataset"

    async def respond(state: PlanState) -> PlanState:
        reply = state.get("direct_reply") or "Mình chỉ hỗ trợ câu hỏi về dữ liệu bán hàng."
        return {"outcome": "answered", "reply": reply}

    async def clarify(state: PlanState) -> PlanState:
        reply = (
            state.get("clarification_question")
            or state.get("reply")
            or ("Bạn có thể nói rõ hơn chỉ số và khoảng thời gian cần xem không?")
        )
        return {"outcome": "clarification", "reply": reply}

    # ---------------------------------------------------------------- routing & access (deterministic)
    async def select_dataset(state: PlanState) -> PlanState:
        known = [c for c in state.get("dataset_candidates", []) if registry.get(c)]
        if not known:  # LLM gave nothing usable: keyword overlap against the catalog
            text = normalize(state["standalone_question"])
            scored = [
                (sum(contains_phrase(text, normalize(k)) for k in d.keywords), d.code) for d in registry.all()
            ]
            known = [code for score, code in sorted(scored, reverse=True) if score > 0][:1]
        if not known:
            return {
                "dataset_code": None,
                "reply": "Mình chưa xác định được dữ liệu phù hợp. Bạn muốn xem chỉ số nào "
                "(doanh thu, tồn kho, khách hàng mới, …)?",
            }
        accessible = set(state.get("accessible_datasets", []))
        return {"dataset_code": next((c for c in known if c in accessible), known[0])}

    def route_after_select(state: PlanState) -> str:
        return "check_access" if state.get("dataset_code") else "clarify"

    async def check_access(state: PlanState) -> PlanState:
        code = state["dataset_code"]
        assert code is not None
        if code in state.get("accessible_datasets", []):
            return {}
        return {
            "outcome": "access_required",
            "reply": f"Câu hỏi cần dữ liệu “{registry.require(code).name}” nhưng bạn chưa được cấp quyền. "
            "Bạn có thể gửi yêu cầu truy cập để quản trị viên xét duyệt.",
        }

    def route_after_access(state: PlanState) -> str:
        return "end" if state.get("outcome") == "access_required" else "generate_sql"

    # ---------------------------------------------------------------- SQL drafting
    async def generate_sql(state: PlanState) -> PlanState:
        code = state["dataset_code"]
        assert code is not None
        attempts = state.get("attempts", 0) + 1
        question = state["standalone_question"]
        if attempts == 1 and cache is not None and (hit := cache.get(question, code)):
            return {
                "attempts": attempts,
                "from_cache": True,
                "draft_sql": hit.sql,
                "interpretation": hit.interpretation,
                "assumptions": hit.assumptions,
            }
        try:
            result = await llm.generate_sql(
                SqlInput(
                    question=question,
                    dataset_code=code,
                    dataset_context=registry.prompt_context(code),  # only the authorized dataset
                    today=state["today"],
                    max_rows=deps.max_rows,
                    previous_sql=state.get("draft_sql"),
                    errors=state.get("validation_errors", []),
                )
            )
        except Exception as exc:
            log.warning("generate_sql failed: %r", exc)
            return {
                "attempts": attempts,
                "draft_sql": None,
                "validation_errors": [f"Không sinh được SQL: {exc}"],
            }
        d = result.value
        return {
            "attempts": attempts,
            "from_cache": False,
            "draft_sql": d.sql,
            "interpretation": d.interpretation,
            "assumptions": d.assumptions,
            "usage": [result.usage],
        }

    async def validate_sql(state: PlanState) -> PlanState:
        draft = state.get("draft_sql")
        if not draft:
            return {"sql": None}
        code = state["dataset_code"]
        assert code is not None
        verdict = check_sql(draft, registry.schema_mapping(code), max_rows=deps.max_rows)
        if not verdict.ok:
            metrics.GUARD_REJECTIONS.labels("plan").inc()
        return {"sql": verdict.sql, "validation_errors": verdict.errors}

    def route_after_validate(state: PlanState) -> str:
        if state.get("sql"):
            return "assess_risk"
        return "generate_sql" if state.get("attempts", 0) < deps.max_attempts else "reject"

    async def assess_risk(state: PlanState) -> PlanState:
        code, sql = state["dataset_code"], state["sql"]
        assert code is not None and sql is not None
        confidential = registry.require(code).sensitivity == "confidential"
        risk: RiskLevel = "high" if confidential or not is_aggregate_query(sql) else "low"
        if cache is not None and not state.get("from_cache"):
            cache.put(
                state["standalone_question"],
                code,
                SqlDraft(
                    sql=state["draft_sql"] or sql,
                    interpretation=state.get("interpretation") or "",
                    assumptions=state.get("assumptions", []),
                ),
            )
        return {
            "risk_level": risk,
            "outcome": "awaiting_approval",
            "reply": state.get("interpretation") or "Đã lập truy vấn, vui lòng kiểm tra trước khi chạy.",
        }

    async def reject(state: PlanState) -> PlanState:
        return {
            "outcome": "rejected",
            "reply": "Mình chưa tạo được truy vấn an toàn cho câu hỏi này. "
            "Bạn thử diễn đạt cụ thể hơn (chỉ số, phạm vi, thời gian) nhé.",
        }

    # ---------------------------------------------------------------- wiring
    g = StateGraph(PlanState)
    for name, fn in [
        ("input_guard", input_guard),
        ("analyze_question", analyze_question),
        ("respond", respond),
        ("clarify", clarify),
        ("select_dataset", select_dataset),
        ("check_access", check_access),
        ("generate_sql", generate_sql),
        ("validate_sql", validate_sql),
        ("assess_risk", assess_risk),
        ("reject", reject),
    ]:
        g.add_node(name, fn)  # type: ignore[call-overload]

    g.add_edge(START, "input_guard")
    g.add_conditional_edges(
        "input_guard", route_after_input, {"end": END, "analyze_question": "analyze_question"}
    )
    g.add_conditional_edges("analyze_question", route_after_analyze, ["respond", "clarify", "select_dataset"])
    g.add_conditional_edges("select_dataset", route_after_select, ["check_access", "clarify"])
    g.add_conditional_edges("check_access", route_after_access, {"end": END, "generate_sql": "generate_sql"})
    g.add_edge("generate_sql", "validate_sql")
    g.add_conditional_edges("validate_sql", route_after_validate, ["assess_risk", "generate_sql", "reject"])
    for terminal in ("respond", "clarify", "assess_risk", "reject"):
        g.add_edge(terminal, END)
    return g.compile()
