from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_env: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # Two connections with different PostgreSQL roles: least privilege by construction.
    database_url: str = "postgresql+asyncpg://app_backend:app_backend@127.0.0.1:5444/text2sql?ssl=disable"
    analytics_database_url: str = (
        "postgresql+asyncpg://analytics_reader:analytics_reader@127.0.0.1:5444/text2sql?ssl=disable"
    )

    jwt_secret: str = "change-me-in-production-please-32b"
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 480

    # ---- LLM gateway ----
    llm_provider: Literal["demo", "openai"] = "demo"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    llm_model: str = "gpt-4o-mini"
    llm_fallback_model: str | None = None  # second rung of the fallback ladder (same API)
    llm_timeout_seconds: float = 30.0
    breaker_failure_threshold: int = 3
    breaker_reset_seconds: float = 30.0
    plan_cache_ttl_seconds: int = 3600
    plan_cache_size: int = 512
    # USD per 1M tokens: {"model": [input, output]}
    llm_prices: dict[str, list[float]] = Field(
        default_factory=lambda: {
            "gpt-4o-mini": [0.15, 0.60],
            "gpt-4o": [2.50, 10.0],
            "gpt-4.1-mini": [0.40, 1.60],
        }
    )
    llm_chaos_failure_rate: float = 0.0  # dev/chaos testing only: inject primary-provider failures

    # ---- Observability ----
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None

    # ---- Agent / guardrails / HITL ----
    semantic_dir: Path = BACKEND_DIR / "semantic"
    sql_max_attempts: int = 2
    query_max_rows: int = 500
    query_timeout_ms: int = 10_000
    history_window: int = 6
    input_max_chars: int = 500
    rate_limit_per_minute: int = 20
    approval_mode: Literal["always", "risk_based"] = "always"
    approval_ttl_minutes: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
