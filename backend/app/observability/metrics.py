"""Prometheus metrics. Label sets are small and bounded (no user ids, no questions)."""

from prometheus_client import Counter, Gauge, Histogram

_LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30)

HTTP_LATENCY = Histogram(
    "t2s_http_request_seconds",
    "HTTP request latency",
    ["method", "route", "status"],
    buckets=_LATENCY_BUCKETS,
)
PLAN_LATENCY = Histogram("t2s_plan_seconds", "End-to-end planning latency", buckets=_LATENCY_BUCKETS)
PLAN_OUTCOMES = Counter("t2s_plan_outcomes_total", "Planning outcomes", ["outcome"])

LLM_LATENCY = Histogram("t2s_llm_seconds", "LLM call latency", ["task", "route"], buckets=_LATENCY_BUCKETS)
LLM_CALLS = Counter("t2s_llm_calls_total", "LLM calls", ["task", "route", "status"])
LLM_TOKENS = Counter("t2s_llm_tokens_total", "LLM tokens", ["model", "direction"])
LLM_COST = Counter("t2s_llm_cost_usd_total", "Estimated LLM cost in USD", ["model"])
CIRCUIT_STATE = Gauge("t2s_circuit_state", "Circuit state: 0 closed, 1 open, 2 half-open", ["provider"])
PLAN_CACHE = Counter("t2s_plan_cache_total", "Plan cache lookups", ["result"])

INPUT_BLOCKS = Counter("t2s_input_blocked_total", "Questions blocked by input rails", ["reason"])
GUARD_REJECTIONS = Counter("t2s_sql_guard_rejections_total", "SQL rejected by the guard", ["stage"])
GROUNDING = Counter("t2s_explanation_grounding_total", "Explanation grounding check", ["result"])

HITL_DECISIONS = Counter("t2s_hitl_decisions_total", "Human-in-the-loop decisions", ["decision"])
QUERY_EXEC_LATENCY = Histogram(
    "t2s_query_execution_seconds", "SQL execution latency", ["status"], buckets=_LATENCY_BUCKETS
)
