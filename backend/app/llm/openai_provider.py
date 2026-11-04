import json
import time
from typing import Any, TypeVar

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.core.config import Settings
from app.llm import prompts
from app.llm.base import (
    AnalyzeInput,
    ExplainInput,
    Explanation,
    LLMResult,
    QuestionAnalysis,
    SqlDraft,
    SqlInput,
    Usage,
)

M = TypeVar("M", bound=BaseModel)


class LLMOutputError(RuntimeError):
    pass


class OpenAIProvider:
    """Structured-output calls via LangChain; usage is read from the raw AIMessage."""

    name = "openai"

    def __init__(self, settings: Settings, model: str | None = None) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        self._model = model or settings.llm_model
        self.name = f"openai:{self._model}"
        self._chat = ChatOpenAI(
            model=self._model,
            api_key=settings.openai_api_key,  # type: ignore[arg-type]
            base_url=settings.openai_base_url,
            timeout=settings.llm_timeout_seconds,
            temperature=0,
            max_retries=1,  # retries beyond this are the circuit breaker's / fallback's job
        )

    async def _structured(
        self, schema: type[M], messages: list[BaseMessage], run_name: str, callbacks: list[Any] | None = None
    ) -> LLMResult[M]:
        runnable = self._chat.with_structured_output(schema, method="function_calling", include_raw=True)
        config: RunnableConfig = {"run_name": run_name}
        if callbacks:
            config["callbacks"] = callbacks
        started = time.perf_counter()
        out: dict[str, Any] = await runnable.ainvoke(messages, config=config)  # type: ignore[assignment]
        latency = round((time.perf_counter() - started) * 1000)
        parsed = out.get("parsed")
        if parsed is None:
            raise LLMOutputError(f"{run_name}: model output did not match schema: {out.get('parsing_error')}")
        raw: AIMessage = out["raw"]
        meta: dict[str, Any] = dict(raw.usage_metadata or {})
        usage = Usage(
            task=run_name,
            model=self._model,
            prompt_tokens=meta.get("input_tokens", 0),
            completion_tokens=meta.get("output_tokens", 0),
            latency_ms=latency,
        )
        return LLMResult(parsed, usage)

    async def analyze_question(self, inp: AnalyzeInput) -> LLMResult[QuestionAnalysis]:
        messages: list[BaseMessage] = [
            SystemMessage(
                prompts.ANALYZE_SYSTEM.format(catalog=inp.catalog_summary, today=inp.today.isoformat())
            )
        ]
        for turn in inp.history:
            if turn.role == "user":
                messages.append(HumanMessage(prompts.spotlight(turn.content)))
            else:
                messages.append(AIMessage(turn.content))
        messages.append(HumanMessage(prompts.spotlight(inp.question)))
        return await self._structured(QuestionAnalysis, messages, "analyze_question")

    async def generate_sql(self, inp: SqlInput) -> LLMResult[SqlDraft]:
        system = prompts.SQL_SYSTEM.format(
            context=inp.dataset_context, today=inp.today.isoformat(), max_rows=inp.max_rows
        )
        messages: list[BaseMessage] = [SystemMessage(system), HumanMessage(prompts.spotlight(inp.question))]
        if inp.previous_sql and inp.errors:
            messages.append(
                HumanMessage(
                    prompts.SQL_REPAIR.format(
                        sql=inp.previous_sql, errors="\n".join(f"- {e}" for e in inp.errors)
                    )
                )
            )
        return await self._structured(SqlDraft, messages, "generate_sql")

    async def explain_result(
        self, inp: ExplainInput, *, callbacks: list[Any] | None = None
    ) -> LLMResult[Explanation]:
        payload = {
            "question": inp.question,
            "interpretation": inp.interpretation,
            "columns": [c["name"] for c in inp.columns],
            "rows": inp.rows[:30],
            "row_count": inp.row_count,
            "truncated": inp.truncated,
        }
        messages: list[BaseMessage] = [
            SystemMessage(prompts.EXPLAIN_SYSTEM),
            HumanMessage(json.dumps(payload, ensure_ascii=False, default=str)),
        ]
        return await self._structured(Explanation, messages, "explain_result", callbacks)
