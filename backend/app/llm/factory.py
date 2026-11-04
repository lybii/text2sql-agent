from functools import lru_cache

from app.core.config import get_settings
from app.llm.base import LLMProvider
from app.llm.demo.provider import DemoProvider
from app.llm.gateway import ChaosProvider, LLMGateway
from app.semantic.registry import get_registry


@lru_cache
def get_gateway() -> LLMGateway:
    settings = get_settings()
    demo = DemoProvider(get_registry())
    primary: LLMProvider | None = None
    fallback: LLMProvider | None = None
    if settings.llm_provider == "openai":
        from app.llm.openai_provider import OpenAIProvider

        primary = OpenAIProvider(settings)
        if settings.llm_fallback_model:
            fallback = OpenAIProvider(settings, model=settings.llm_fallback_model)
    if settings.llm_chaos_failure_rate > 0:
        # Chaos applies to the first rung so the fallback path can be exercised, even in demo mode.
        primary = ChaosProvider(primary or DemoProvider(get_registry()), settings.llm_chaos_failure_rate)
    return LLMGateway(
        demo,
        primary,
        fallback,
        failure_threshold=settings.breaker_failure_threshold,
        reset_seconds=settings.breaker_reset_seconds,
        prices=settings.llm_prices,
    )
