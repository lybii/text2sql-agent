"""Optional Langfuse tracing. Enabled only when keys are configured; never breaks a request.

One query run == one Langfuse trace: planning (LangGraph + LLM calls), execution and the
explanation are attached to the same `trace_id`, which is stored on `app.query_runs`.
User feedback is pushed back as a score on that trace.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from functools import lru_cache
from typing import Any

from app.core.config import get_settings

log = logging.getLogger(__name__)


class Tracer:
    def __init__(self) -> None:
        self._client: Any = None
        settings = get_settings()
        if not (settings.langfuse_public_key and settings.langfuse_secret_key):
            return
        try:
            from langfuse import Langfuse

            self._client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
                environment=settings.app_env,
            )
            log.info("Langfuse tracing enabled")
        except Exception:
            log.warning("Langfuse init failed; tracing disabled", exc_info=True)
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def new_trace_id(self) -> str | None:
        if not self.enabled:
            return None
        from langfuse import Langfuse

        return Langfuse.create_trace_id()

    def langchain_callbacks(self, trace_id: str | None) -> list[Any]:
        if not (self.enabled and trace_id):
            return []
        try:
            from langfuse.langchain import CallbackHandler

            return [CallbackHandler(trace_context={"trace_id": trace_id})]
        except Exception:
            log.warning("Langfuse callback unavailable", exc_info=True)
            return []

    @contextmanager
    def span(
        self, name: str, trace_id: str | None, *, input: Any = None, metadata: dict[str, Any] | None = None
    ) -> Iterator[Any]:
        """Open a span on the trace; yields the span (or None). Errors inside the body propagate."""
        if not (self.enabled and trace_id):
            yield None
            return
        try:
            cm = self._client.start_as_current_observation(
                trace_context={"trace_id": trace_id},
                name=name,
                as_type="span",
                input=input,
                metadata=metadata,
            )
            span = cm.__enter__()
        except Exception:
            log.warning("Langfuse span start failed", exc_info=True)
            yield None
            return
        try:
            yield span
        finally:
            with suppress(Exception):
                cm.__exit__(None, None, None)

    def score(self, trace_id: str | None, name: str, value: float, comment: str | None = None) -> None:
        if not (self.enabled and trace_id):
            return
        try:
            self._client.create_score(trace_id=trace_id, name=name, value=value, comment=comment)
        except Exception:
            log.warning("Langfuse score failed", exc_info=True)

    def trace_url(self, trace_id: str | None) -> str | None:
        if not (self.enabled and trace_id):
            return None
        try:
            return self._client.get_trace_url(trace_id=trace_id)  # type: ignore[no-any-return]
        except Exception:
            return None

    def flush(self) -> None:
        if self.enabled:
            with suppress(Exception):
                self._client.flush()


def set_span_output(span: Any, output: Any) -> None:
    if span is not None:
        with suppress(Exception):
            span.update(output=output)


@lru_cache
def get_tracer() -> Tracer:
    return Tracer()
