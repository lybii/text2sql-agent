import re
import time
from typing import Any

from app.core.text import contains_phrase, normalize
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
from app.llm.demo.compiler import Intent, compile_sql, extract_intent, find_metric
from app.semantic.registry import SemanticRegistry

MODEL = "demo-rules"
_GREETING = re.compile(r"^(xin chao|chao|hello|hi|alo|ban la ai|ban lam duoc gi|huong dan|help)\b")
_TIME_HINT = "Ví dụ: năm 2025, quý 2/2025, tháng 3/2025 hoặc “toàn bộ thời gian”."


def _usage(started: float, task: str) -> Usage:
    return Usage(
        task=task, model=MODEL, route="demo", latency_ms=round((time.perf_counter() - started) * 1000)
    )


def format_number(value: float) -> str:
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1e9:
        return f"{sign}{v / 1e9:,.2f} tỷ".replace(",", "X").replace(".", ",").replace("X", ".")
    if v >= 1e6:
        return f"{sign}{v / 1e6:,.1f} triệu".replace(",", "X").replace(".", ",").replace("X", ".")
    if float(v).is_integer():
        return f"{sign}{int(v):,}".replace(",", ".")
    return f"{sign}{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class DemoProvider:
    """Offline, deterministic provider built on the semantic layer (see compiler.py)."""

    name = "demo"

    def __init__(self, registry: SemanticRegistry) -> None:
        self._registry = registry

    def _capabilities(self) -> str:
        return "; ".join(
            f"{d.name} ({', '.join(m.name.lower() for m in d.metrics[:3])})" for d in self._registry.all()
        )

    async def analyze_question(self, inp: AnalyzeInput) -> LLMResult[QuestionAnalysis]:
        started = time.perf_counter()
        text = normalize(inp.question)
        if _GREETING.search(text):
            reply = (
                "Chào bạn! Mình có thể trả lời câu hỏi về dữ liệu bán hàng bất động sản: "
                f"{self._capabilities()}. Thử hỏi: “Doanh thu theo thành phố năm 2025”."
            )
            return LLMResult(
                QuestionAnalysis(
                    intent="chitchat",
                    standalone_question=inp.question,
                    needs_clarification=False,
                    reply=reply,
                ),
                _usage(started, "analyze_question"),
            )

        standalone = inp.question
        intent = extract_intent(self._registry, text, inp.today)
        previous = next((t.content for t in reversed(inp.history) if t.role == "user"), None)
        if previous and intent is None:
            # A fragment without a metric ("quý 3/2025") answers the previous clarification: merge.
            # A full question that merely lacks a time range is NOT merged — it gets its own clarification.
            combined = f"{previous} {inp.question}"
            merged = extract_intent(self._registry, normalize(combined), inp.today)
            if merged and not merged.missing_time:
                intent, standalone = merged, combined

        if intent is None:
            return LLMResult(self._no_metric(inp.question, text), _usage(started, "analyze_question"))
        if intent.missing_time:
            return LLMResult(
                QuestionAnalysis(
                    intent="data_query",
                    standalone_question=standalone,
                    needs_clarification=True,
                    clarification_question=f"Bạn muốn xem {intent.metric.name.lower()} trong khoảng thời gian nào? "
                    + _TIME_HINT,
                    dataset_candidates=[intent.dataset.code],
                ),
                _usage(started, "analyze_question"),
            )
        return LLMResult(
            QuestionAnalysis(
                intent="data_query",
                standalone_question=standalone,
                needs_clarification=False,
                dataset_candidates=[intent.dataset.code],
            ),
            _usage(started, "analyze_question"),
        )

    def _no_metric(self, question: str, text: str) -> QuestionAnalysis:
        for dataset in self._registry.all():
            if any(contains_phrase(text, normalize(k)) for k in dataset.keywords):
                metrics = ", ".join(m.name.lower() for m in dataset.metrics)
                return QuestionAnalysis(
                    intent="data_query",
                    standalone_question=question,
                    needs_clarification=True,
                    clarification_question=f"Bạn muốn xem chỉ số nào của {dataset.name.lower()}? Ví dụ: {metrics}.",
                    dataset_candidates=[dataset.code],
                )
        return QuestionAnalysis(
            intent="out_of_scope",
            standalone_question=question,
            needs_clarification=False,
            reply=f"Câu hỏi này nằm ngoài phạm vi dữ liệu mình được phép truy cập. Mình hỗ trợ: {self._capabilities()}.",
        )

    async def generate_sql(self, inp: SqlInput) -> LLMResult[SqlDraft]:
        started = time.perf_counter()
        dataset = self._registry.require(inp.dataset_code)
        text = normalize(inp.question)
        found = find_metric(self._registry, text)
        intent: Intent | None = None
        if found and found[0].code == dataset.code:
            intent = extract_intent(self._registry, text, inp.today, found)
        if intent is None:
            raise ValueError("Demo provider could not map the question to a metric of this dataset")
        sql, interpretation, assumptions = compile_sql(intent, inp.max_rows)
        return LLMResult(
            SqlDraft(sql=sql, interpretation=interpretation, assumptions=assumptions),
            _usage(started, "generate_sql"),
        )

    async def explain_result(
        self, inp: ExplainInput, *, callbacks: list[Any] | None = None
    ) -> LLMResult[Explanation]:
        started = time.perf_counter()
        return LLMResult(explain_deterministic(inp), _usage(started, "explain_result"))


def explain_deterministic(inp: ExplainInput) -> Explanation:
    if inp.row_count == 0:
        return Explanation(summary="Không có dữ liệu phù hợp với điều kiện truy vấn.")
    numeric = [i for i, c in enumerate(inp.columns) if c["type"] == "number"]
    if not numeric:
        return Explanation(summary=f"Truy vấn trả về {inp.row_count} dòng.")
    value_idx = numeric[-1]
    value_name = inp.columns[value_idx]["name"]
    if inp.row_count == 1 and len(inp.columns) == 1:
        value = inp.rows[0][value_idx]
        text = "không có giá trị" if value is None else format_number(float(value))
        return Explanation(summary=f"{inp.interpretation.rstrip('.')}: {text}.")

    label_idx = next((i for i in range(len(inp.columns)) if i != value_idx), 0)
    valid = [r for r in inp.rows if r[value_idx] is not None]
    if not valid:
        return Explanation(
            summary=f"Truy vấn trả về {inp.row_count} dòng nhưng không có giá trị {value_name}."
        )

    def label(row: list[Any]) -> str:
        return " · ".join(str(row[i]) for i in range(len(row)) if i not in numeric) or str(row[label_idx])

    top = max(valid, key=lambda r: r[value_idx])
    bottom = min(valid, key=lambda r: r[value_idx])
    highlights = [
        f"Cao nhất: {label(top)} — {format_number(float(top[value_idx]))}",
        f"Thấp nhất: {label(bottom)} — {format_number(float(bottom[value_idx]))}",
    ]
    if inp.truncated:
        highlights.append("Kết quả đã bị giới hạn số dòng; hãy thu hẹp điều kiện để xem đầy đủ.")
    return Explanation(summary=f"Kết quả gồm {inp.row_count} dòng ({value_name}).", highlights=highlights)
