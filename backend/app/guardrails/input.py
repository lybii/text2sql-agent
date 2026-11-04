"""Input rails: cheap deterministic checks before any LLM call.

Pattern matching will not stop a determined attacker — that is not its job. It filters the obvious
attempts cheaply; the real guarantees come from the SQL guard, the read-only role and human approval.
"""

import re
from dataclasses import dataclass

from app.core.text import normalize

# Matched against normalized text (lowercase, no Vietnamese diacritics).
_INJECTION_PATTERNS = [
    r"ignore (all |any )?(the )?(previous|above|prior) (instructions|prompts?|rules)",
    r"disregard (all |the )?(previous|above|prior)",
    r"(reveal|show|print|repeat) (me )?(your|the) (system )?(prompt|instructions)",
    r"system prompt",
    r"you are now\b",
    r"\bjailbreak\b|\bdan mode\b|developer mode",
    r"bo qua (moi|tat ca|toan bo|cac) (huong dan|chi dan|quy tac|lenh)",
    r"(tiet lo|cho xem|in ra) (system prompt|prompt|chi dan he thong|huong dan he thong)",
    r"gia vo (ban|minh) la",
    r"\b(drop|truncate|alter|grant|revoke)\s+(table|schema|database|role|user)\b",
    r"\b(delete\s+from|insert\s+into|update\s+\w+\s+set)\b",
    r"(xoa|sua|cap nhat|chen) (du lieu|bang|ban ghi)",
    r"pg_sleep|pg_read_file|information_schema|pg_catalog|\bdblink\b|\bcopy\s+\w+\s+(to|from)\b",
    r"(mat khau|password|api[ _]?key|secret|token) (cua|of|trong|in)",
]
_INJECTION_RE = [re.compile(p) for p in _INJECTION_PATTERNS]


@dataclass(frozen=True)
class InputVerdict:
    ok: bool
    reason: str | None = None
    message: str | None = None


def check_input(question: str, *, max_chars: int) -> InputVerdict:
    stripped = question.strip()
    if not stripped:
        return InputVerdict(False, "empty", "Bạn chưa nhập câu hỏi.")
    if len(stripped) > max_chars:
        return InputVerdict(
            False, "too_long", f"Câu hỏi quá dài (tối đa {max_chars} ký tự). Hãy hỏi ngắn gọn hơn."
        )
    text = normalize(stripped)
    for pattern in _INJECTION_RE:
        if pattern.search(text):
            return InputVerdict(
                False,
                "prompt_injection",
                "Mình chỉ có thể trả lời câu hỏi phân tích dữ liệu bán hàng và không thể thực hiện yêu cầu này.",
            )
    return InputVerdict(True)
