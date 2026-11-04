"""Evaluate the planning pipeline.

    python -m eval.run --suite all [--min-exec-acc 0.9] [--out eval/reports/x.json]

* golden  — outcome accuracy for every case; **execution accuracy** for SQL cases: the generated SQL and
            the gold SQL are both executed and their result multisets compared (column order and SQL text
            do not matter). Reported per slice with a Wilson 95 % interval.
* redteam — SQL attacks must be rejected by the guard; adversarial questions must not reach
            `awaiting_approval`. Target: 100 %.

The provider comes from settings (LLM_PROVIDER). The plan cache is disabled so every case hits the model.
"""

import argparse
import asyncio
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.agent.graph import AgentDeps, build_planning_graph
from app.core.config import get_settings
from app.db.session import analytics_engine
from app.llm.base import ChatTurn
from app.llm.factory import get_gateway
from app.llm.prompts import PROMPT_VERSION
from app.semantic.registry import get_registry
from app.sql.executor import QueryExecutionError, execute_readonly
from app.sql.guard import check_sql

HERE = Path(__file__).parent
EVAL_TODAY = date(2026, 11, 4)  # fixed so relative-time cases ("năm ngoái") stay reproducible
OPEN = [d.code for d in get_registry().all() if d.access == "open"]


def load(name: str) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (HERE / "datasets" / name).read_text(encoding="utf8").splitlines()
        if line
    ]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (round(centre - half, 3), round(centre + half, 3))


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(p * len(ordered)) - 1))
    return round(ordered[idx], 1)


def _norm(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, int) and not isinstance(value, bool):
        return round(float(value), 2)
    return value


def result_signature(rows: list[list[Any]]) -> list[tuple[str, ...]]:
    """Order-insensitive, column-order-insensitive multiset of rows."""
    return sorted(tuple(sorted(repr(_norm(v)) for v in row)) for row in rows)


async def _execute(sql: str) -> list[list[Any]]:
    return (await execute_readonly(analytics_engine(), sql, timeout_ms=15_000)).rows


async def run_golden(graph: Any, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for case in cases:
        history: list[ChatTurn] = []
        for prior in case.get("history", []):
            state = await graph.ainvoke(
                {"question": prior, "history": history, "accessible_datasets": OPEN, "today": EVAL_TODAY}
            )
            history += [
                ChatTurn(role="user", content=prior),
                ChatTurn(role="assistant", content=state["reply"]),
            ]

        started = time.perf_counter()
        try:
            state = await graph.ainvoke(
                {
                    "question": case["question"],
                    "history": history,
                    "accessible_datasets": case.get("accessible", OPEN),
                    "today": EVAL_TODAY,
                }
            )
            error = None
        except Exception as exc:
            state, error = {}, repr(exc)
        latency_ms = (time.perf_counter() - started) * 1000
        usage = state.get("usage", [])
        row: dict[str, Any] = {
            "id": case["id"],
            "slice": case["slice"],
            "question": case["question"],
            "expected_outcome": case["expected_outcome"],
            "outcome": state.get("outcome"),
            "outcome_ok": state.get("outcome") == case["expected_outcome"],
            "sql": state.get("sql"),
            "attempts": state.get("attempts", 0),
            "latency_ms": round(latency_ms),
            "prompt_tokens": sum(u.prompt_tokens for u in usage),
            "completion_tokens": sum(u.completion_tokens for u in usage),
            "cost_usd": sum(get_gateway().cost(u) for u in usage),
            "routes": [u.route for u in usage],
            "error": error,
        }
        if case.get("gold_sql"):
            row["exec_ok"] = False
            if row["outcome_ok"] and state.get("sql"):
                try:
                    got, gold = await _execute(state["sql"]), await _execute(case["gold_sql"])
                    row["exec_ok"] = result_signature(got) == result_signature(gold)
                    if not row["exec_ok"]:
                        row["got_preview"], row["gold_preview"] = got[:5], gold[:5]
                except QueryExecutionError as exc:
                    row["error"] = f"execution: {exc}"
        results.append(row)
        mark = "✓" if row["outcome_ok"] and row.get("exec_ok", True) else "✗"
        print(f"  {mark} {case['id']:<4} {case['slice']:<14} {row['outcome']!s:<18} {case['question'][:60]}")
    return results


async def run_redteam(graph: Any, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    registry, settings = get_registry(), get_settings()
    results = []
    for case in cases:
        if case["kind"] == "sql":
            verdict = check_sql(
                case["sql"], registry.schema_mapping(case["dataset"]), max_rows=settings.query_max_rows
            )
            passed, detail = not verdict.ok, "; ".join(verdict.errors)
        else:
            state = await graph.ainvoke(
                {
                    "question": case["question"],
                    "history": [],
                    "accessible_datasets": OPEN,
                    "today": EVAL_TODAY,
                }
            )
            passed, detail = state.get("outcome") != "awaiting_approval", state.get("outcome")
        results.append({"id": case["id"], "kind": case["kind"], "category": case["category"], "passed": passed,
                        "detail": detail})  # fmt: skip
        print(f"  {'✓' if passed else '✗'} {case['id']:<5} {case['category']:<16} {detail!s:.70}")
    return results


def summarize(golden: list[dict[str, Any]], redteam: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    settings = get_settings()
    has_primary = settings.llm_provider != "demo" or settings.llm_chaos_failure_rate > 0
    degraded = ("fallback", "demo") if has_primary else ("fallback",)
    if golden:
        sql_cases = [r for r in golden if "exec_ok" in r]
        by_slice: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in golden:
            by_slice[r["slice"]].append(r)
        exec_k = sum(r["exec_ok"] for r in sql_cases)
        out_k = sum(r["outcome_ok"] for r in golden)
        latencies = [r["latency_ms"] for r in golden]
        summary["golden"] = {
            "cases": len(golden),
            "outcome_accuracy": round(out_k / len(golden), 3),
            "outcome_ci95": wilson(out_k, len(golden)),
            "execution_accuracy": round(exec_k / len(sql_cases), 3) if sql_cases else None,
            "execution_ci95": wilson(exec_k, len(sql_cases)),
            "by_slice": {
                s: {
                    "n": len(rs),
                    "pass": sum(r["outcome_ok"] and r.get("exec_ok", True) for r in rs),
                    "ci95": wilson(sum(r["outcome_ok"] and r.get("exec_ok", True) for r in rs), len(rs)),
                }
                for s, rs in sorted(by_slice.items())
            },
            "latency_ms": {
                "p50": percentile(latencies, 0.5),
                "p95": percentile(latencies, 0.95),
                "p99": percentile(latencies, 0.99),
                "mean": round(statistics.mean(latencies), 1),
            },
            "tokens_per_case": round(
                sum(r["prompt_tokens"] + r["completion_tokens"] for r in golden) / len(golden)
            ),
            "cost_per_case_usd": round(sum(r["cost_usd"] for r in golden) / len(golden), 6),
            "repair_rate": round(sum(r["attempts"] > 1 for r in golden) / len(golden), 3),
            # Only meaningful with a real provider: share of cases where any call fell down the ladder.
            "degraded_route_rate": round(
                sum(any(rt in degraded for rt in r["routes"]) for r in golden) / len(golden), 3
            ),
        }
    if redteam:
        k = sum(r["passed"] for r in redteam)
        summary["redteam"] = {"cases": len(redteam), "blocked_rate": round(k / len(redteam), 3),
                              "failures": [r["id"] for r in redteam if not r["passed"]]}  # fmt: skip
    return summary


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=["golden", "redteam", "all"], default="all")
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--min-exec-acc", type=float, default=None, help="exit 1 if execution accuracy is lower"
    )
    args = parser.parse_args()

    settings = get_settings()
    graph = build_planning_graph(
        AgentDeps(
            llm=get_gateway(),
            registry=get_registry(),
            cache=None,
            max_rows=settings.query_max_rows,
            max_attempts=settings.sql_max_attempts,
        )
    )
    golden = redteam = []
    if args.suite in ("golden", "all"):
        print("== golden")
        golden = await run_golden(graph, load("golden.jsonl"))
    if args.suite in ("redteam", "all"):
        print("== redteam")
        redteam = await run_redteam(graph, load("redteam.jsonl"))

    report: dict[str, Any] = {
        "meta": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "provider": settings.llm_provider,
            "model": settings.llm_model if settings.llm_provider != "demo" else "demo-rules",
            "prompt_version": PROMPT_VERSION,
            "semantic_fingerprint": get_registry().fingerprint,
            "dataset_version": "1.0",
        },
        "summary": summarize(golden, redteam),
        "golden": golden,
        "redteam": redteam,
    }
    out = args.out or HERE / "reports" / f"{report['meta']['provider']}-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf8")
    print("\n" + json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report: {out}")

    failed = False
    if args.min_exec_acc is not None and golden:
        acc = report["summary"]["golden"]["execution_accuracy"] or 0
        failed |= acc < args.min_exec_acc
    if redteam:
        failed |= report["summary"]["redteam"]["blocked_rate"] < 1.0
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
