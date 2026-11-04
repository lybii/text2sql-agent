"""Task-level LLM contract. Providers implement three tasks; the rest of the app is provider-agnostic."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class Usage(BaseModel):
    task: str = ""
    model: str
    route: Literal["primary", "fallback", "demo", "cache"] = "primary"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0


@dataclass(frozen=True)
class LLMResult(Generic[T]):
    value: T
    usage: Usage


class QuestionAnalysis(BaseModel):
    intent: Literal["data_query", "chitchat", "out_of_scope"] = Field(
        description="data_query: cần số liệu từ dữ liệu bán hàng; chitchat: chào hỏi/hỏi cách dùng; "
        "out_of_scope: ngoài phạm vi dữ liệu"
    )
    standalone_question: str = Field(
        description="Câu hỏi đầy đủ, độc lập, đã hợp nhất ngữ cảnh từ lịch sử hội thoại"
    )
    needs_clarification: bool = Field(description="True nếu thiếu thông tin bắt buộc để trả lời chính xác")
    clarification_question: str | None = Field(default=None, description="Câu hỏi làm rõ, ngắn gọn")
    dataset_candidates: list[str] = Field(
        default_factory=list, description="Mã dataset phù hợp, xếp theo mức phù hợp giảm dần"
    )
    reply: str | None = Field(default=None, description="Câu trả lời trực tiếp khi intent khác data_query")


class SqlDraft(BaseModel):
    sql: str = Field(description="Đúng một câu PostgreSQL SELECT (hoặc WITH ... SELECT)")
    interpretation: str = Field(description="Diễn giải nghiệp vụ bằng tiếng Việt: hệ thống sẽ tính gì")
    assumptions: list[str] = Field(default_factory=list, description="Giả định đã áp dụng")


class Explanation(BaseModel):
    summary: str = Field(description="Tóm tắt 1-3 câu, chỉ dùng số liệu có trong kết quả")
    highlights: list[str] = Field(default_factory=list, description="Tối đa 3 điểm đáng chú ý")


@dataclass(frozen=True)
class AnalyzeInput:
    question: str
    history: list[ChatTurn]
    catalog_summary: str
    today: date


@dataclass(frozen=True)
class SqlInput:
    question: str
    dataset_code: str
    dataset_context: str
    today: date
    max_rows: int
    previous_sql: str | None = None
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExplainInput:
    question: str
    interpretation: str
    columns: list[dict[str, str]]
    rows: list[list[Any]]
    row_count: int
    truncated: bool


class LLMProvider(Protocol):
    name: str

    async def analyze_question(self, inp: AnalyzeInput) -> LLMResult[QuestionAnalysis]: ...

    async def generate_sql(self, inp: SqlInput) -> LLMResult[SqlDraft]: ...

    async def explain_result(
        self, inp: ExplainInput, *, callbacks: list[Any] | None = None
    ) -> LLMResult[Explanation]: ...
