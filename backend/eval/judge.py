"""LLM-as-judge for explanation faithfulness — binary PASS/FAIL, usable only after calibration.

    # 1) label a sample by hand (eval/datasets/judge_labels.jsonl, field human_label = PASS|FAIL)
    python -m eval.judge calibrate eval/datasets/judge_labels.jsonl    # → TPR / TNR of the judge
    # 2) only if TPR and TNR are acceptable, use it to compare two versions (never as an absolute score)
    python -m eval.judge score eval/datasets/judge_labels.jsonl

Each line: {"id", "question", "columns", "rows", "explanation", "human_label"?}. Requires LLM_PROVIDER=openai.
TPR = share of human-FAIL cases the judge also fails (catches real errors);
TNR = share of human-PASS cases the judge passes (does not cry wolf).
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.core.config import get_settings

JUDGE_PROMPT = """Bạn là người chấm độ trung thực (faithfulness) của phần diễn giải kết quả truy vấn.
FAIL nếu diễn giải có BẤT KỲ điều nào sau: nêu con số không suy ra được từ bảng kết quả; nhận định sai
(ví dụ gọi sai giá trị cao nhất/thấp nhất); khẳng định nguyên nhân/xu hướng mà dữ liệu không thể hiện.
Ngược lại là PASS. Chỉ chấm trung thực, không chấm văn phong."""


class Verdict(BaseModel):
    reasoning: str = Field(description="Lý do ngắn gọn, nêu claim sai nếu có")
    label: Literal["PASS", "FAIL"]


async def judge_one(chat: Any, case: dict[str, Any]) -> str:
    payload = {k: case[k] for k in ("question", "columns", "rows", "explanation")}
    out: Verdict = await chat.ainvoke(
        [SystemMessage(JUDGE_PROMPT), HumanMessage(json.dumps(payload, ensure_ascii=False, default=str))]
    )
    return out.label


async def main(mode: str, cases: list[dict[str, Any]]) -> None:
    settings = get_settings()
    if not settings.openai_api_key:
        sys.exit("judge requires OPENAI_API_KEY")
    chat = ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key, temperature=0)  # type: ignore[arg-type]
    structured = chat.with_structured_output(Verdict, method="function_calling")
    labels = [await judge_one(structured, c) for c in cases]
    if mode == "score":
        print(json.dumps({"n": len(cases), "pass_rate": round(labels.count("PASS") / max(len(cases), 1), 3)}))
        return
    pairs = [(c["human_label"], j) for c, j in zip(cases, labels, strict=True) if c.get("human_label")]
    fails = [j for h, j in pairs if h == "FAIL"]
    passes = [j for h, j in pairs if h == "PASS"]
    print(
        json.dumps(
            {
                "labelled": len(pairs),
                "TPR": round(fails.count("FAIL") / len(fails), 3) if fails else None,
                "TNR": round(passes.count("PASS") / len(passes), 3) if passes else None,
                "note": "Raw agreement hides class imbalance — read TPR and TNR separately.",
            }
        )
    )


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("calibrate", "score"):
        sys.exit("usage: python -m eval.judge calibrate|score FILE.jsonl")
    lines = Path(sys.argv[2]).read_text(encoding="utf8").splitlines()
    asyncio.run(main(sys.argv[1], [json.loads(line) for line in lines if line.strip()]))
