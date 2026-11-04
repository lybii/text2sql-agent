import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, request_context_middleware
from app.db.session import app_engine, dispose_engines
from app.llm.factory import get_gateway
from app.modules.access.router import router as access_router
from app.modules.admin.router import router as admin_router
from app.modules.auth.router import router as auth_router
from app.modules.catalog.router import router as catalog_router
from app.modules.conversations.router import router as conversations_router
from app.modules.queries.router import router as queries_router
from app.observability import metrics
from app.observability.tracing import get_tracer
from app.semantic.registry import get_registry

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    registry = get_registry()  # fail fast on invalid semantic YAML
    get_gateway()
    log.info(
        "startup",
        extra={
            "fields": {
                "env": settings.app_env,
                "llm_provider": settings.llm_provider,
                "datasets": [d.code for d in registry.all()],
                "approval_mode": settings.approval_mode,
                "tracing": get_tracer().enabled,
            }
        },
    )
    yield
    get_tracer().flush()
    await dispose_engines()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="Text2SQL Agent", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _metrics(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")  # template, not raw path: bounded cardinality
        metrics.HTTP_LATENCY.labels(request.method, path, str(response.status_code)).observe(
            time.perf_counter() - started
        )
        return response

    app.middleware("http")(request_context_middleware)
    register_error_handlers(app)

    for router in (
        auth_router,
        catalog_router,
        conversations_router,
        queries_router,
        access_router,
        admin_router,
    ):
        app.include_router(router, prefix="/api/v1")

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        async with app_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.get("/metrics", tags=["ops"], include_in_schema=False)
    async def prometheus_metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
