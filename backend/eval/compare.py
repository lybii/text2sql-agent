"""Paired comparison of two eval reports on the same golden set.

    python -m eval.compare eval/reports/A.json eval/reports/B.json

Compares case-by-case (not two averages): lists flips, per-slice deltas, and an exact McNemar test on the
discordant pairs. A small p-value means B's change in pass rate is unlikely to be noise.
"""

import json
import sys
from math import comb
from pathlib import Path
from typing import Any


def _passed(row: dict[str, Any]) -> bool:
    return bool(row["outcome_ok"] and row.get("exec_ok", True))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value; b = A pass/B fail, c = A fail/B pass."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(comb(n, i) for i in range(0, min(b, c) + 1)) / 2**n
    return min(1.0, 2 * tail)


def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    a_rows = {r["id"]: r for r in a["golden"]}
    b_rows = {r["id"]: r for r in b["golden"]}
    shared = sorted(a_rows.keys() & b_rows.keys())
    regressions = [i for i in shared if _passed(a_rows[i]) and not _passed(b_rows[i])]
    fixes = [i for i in shared if not _passed(a_rows[i]) and _passed(b_rows[i])]
    slices: dict[str, list[int]] = {}
    for i in shared:
        s = slices.setdefault(a_rows[i]["slice"], [0, 0, 0])
        s[0] += 1
        s[1] += _passed(a_rows[i])
        s[2] += _passed(b_rows[i])
    return {
        "a": a["meta"],
        "b": b["meta"],
        "paired_cases": len(shared),
        "pass_a": sum(_passed(a_rows[i]) for i in shared),
        "pass_b": sum(_passed(b_rows[i]) for i in shared),
        "fixes": fixes,
        "regressions": regressions,
        "mcnemar_p": round(mcnemar_exact(len(regressions), len(fixes)), 4),
        "by_slice": {
            k: {"n": n, "a": pa, "b": pb, "delta": pb - pa} for k, (n, pa, pb) in sorted(slices.items())
        },
        "latency_p95": (
            a["summary"]["golden"]["latency_ms"]["p95"],
            b["summary"]["golden"]["latency_ms"]["p95"],
        ),
        "cost_per_case": (
            a["summary"]["golden"]["cost_per_case_usd"],
            b["summary"]["golden"]["cost_per_case_usd"],
        ),
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python -m eval.compare A.json B.json")
    reports = [json.loads(Path(p).read_text(encoding="utf8")) for p in sys.argv[1:]]
    print(json.dumps(compare(*reports), ensure_ascii=False, indent=2))
