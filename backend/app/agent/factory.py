from functools import lru_cache
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from app.agent.cache import PlanCache
from app.agent.graph import AgentDeps, build_planning_graph
from app.core.config import get_settings
from app.llm.factory import get_gateway
from app.llm.prompts import PROMPT_VERSION
from app.semantic.registry import get_registry


@lru_cache
def get_plan_cache() -> PlanCache:
    settings = get_settings()
    return PlanCache(
        ttl_seconds=settings.plan_cache_ttl_seconds,
        max_size=settings.plan_cache_size,
        namespace=f"{PROMPT_VERSION}:{get_registry().fingerprint}:{settings.llm_model}",
    )


@lru_cache
def get_planning_graph() -> CompiledStateGraph[Any, Any, Any, Any]:
    settings = get_settings()
    return build_planning_graph(
        AgentDeps(
            llm=get_gateway(),
            registry=get_registry(),
            cache=get_plan_cache(),
            max_rows=settings.query_max_rows,
            max_attempts=settings.sql_max_attempts,
            input_max_chars=settings.input_max_chars,
        )
    )
