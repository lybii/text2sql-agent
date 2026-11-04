"""Deterministic chart recommendation. The frontend renders the spec with Recharts."""

from typing import Any, Literal, TypedDict

_TIME_NAMES = {"month", "quarter", "year", "date", "week", "day", "thang", "quy", "nam"}


class ChartSpec(TypedDict):
    type: Literal["kpi", "line", "bar"]
    x: str | None
    y: list[str]


def _is_time(column: dict[str, str]) -> bool:
    name = column["name"].lower()
    return column["type"] == "date" or name in _TIME_NAMES or name.endswith(("_date", "_month", "_year"))


def recommend_chart(columns: list[dict[str, str]], rows: list[list[Any]]) -> ChartSpec | None:
    if not rows or not columns:
        return None
    numeric = [c["name"] for c in columns if c["type"] == "number" and not _is_time(c)]
    dims = [c for c in columns if c["name"] not in numeric]
    if not numeric:
        return None
    if len(rows) == 1 and not dims:
        return {"type": "kpi", "x": None, "y": numeric[:1]}
    if len(dims) != 1 or len(rows) < 2:
        # Multi-dimension results (e.g. year + month) read better as a table, except year/month pairs.
        names = {d["name"] for d in dims}
        if names == {"year", "month"} or names == {"year", "quarter"}:
            return {"type": "line", "x": None, "y": numeric[:3]}  # frontend joins year+period as label
        return None
    x = dims[0]
    if _is_time(x):
        return {"type": "line", "x": x["name"], "y": numeric[:3]}
    if len(rows) <= 30:
        return {"type": "bar", "x": x["name"], "y": numeric[:2]}
    return None
