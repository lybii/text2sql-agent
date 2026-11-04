"""Deterministic question → intent → SQL compiler driven by the semantic layer.

Not meant to compete with an LLM: it covers the common "metric [by dimension] [filter] [time]"
shape so the whole product can run offline, in tests and in CI with reproducible results.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from app.core.text import contains_phrase, normalize
from app.llm.demo.timeparse import Grain, TimeScope, parse_grain, parse_time_scope
from app.semantic.models import Column, Dataset, Dimension, Metric
from app.semantic.registry import SemanticRegistry

VALUE_SYNONYMS = {
    "TP.HCM": ["tp.hcm", "tphcm", "tp hcm", "hcm", "ho chi minh", "sai gon", "thanh pho ho chi minh"],
}
_DESC_WORDS = r"cao nhat|nhieu nhat|lon nhat|tot nhat|dan dau|manh nhat"
_ASC_WORDS = r"thap nhat|it nhat|kem nhat|nho nhat"
_GRAIN_LABEL = {"month": "tháng", "quarter": "quý", "year": "năm"}


@dataclass
class Intent:
    dataset: Dataset
    metric: Metric
    time: TimeScope | None
    grain: Grain | None
    group_by: list[Dimension] = field(default_factory=list)
    filters: list[tuple[Column, str]] = field(default_factory=list)
    top_n: int | None = None
    descending: bool = True

    @property
    def missing_time(self) -> bool:
        return self.metric.requires_time and self.time is None


def find_metric(registry: SemanticRegistry, text: str) -> tuple[Dataset, Metric] | None:
    best: tuple[int, Dataset, Metric] | None = None
    for dataset in registry.all():
        for metric in dataset.metrics:
            for alias in [metric.name, *metric.aliases]:
                phrase = normalize(alias)
                if contains_phrase(text, phrase) and (best is None or len(phrase) > best[0]):
                    best = (len(phrase), dataset, metric)
    return (best[1], best[2]) if best else None


def extract_intent(
    registry: SemanticRegistry, text: str, today: date, prefer: tuple[Dataset, Metric] | None = None
) -> Intent | None:
    found = prefer or find_metric(registry, text)
    if found is None:
        return None
    dataset, metric = found
    table = dataset.table(metric.table)
    intent = Intent(dataset, metric, parse_time_scope(text, today), parse_grain(text))

    dims = [d for d in dataset.dimensions if d.table == metric.table]
    for dim in dims:
        for alias in sorted((normalize(a) for a in dim.aliases), key=len, reverse=True):
            a = re.escape(alias)
            if re.search(rf"\b(theo|tung|moi|cac|giua cac|top \d+|\d+) {a}\b|\b{a} nao\b", text):
                intent.group_by.append(dim)
                break

    filtered_cols = " ".join(metric.filters)
    for col in table.columns:
        if not col.values or col.name in filtered_cols:
            continue
        for value in col.values:
            phrases = [normalize(value), *VALUE_SYNONYMS.get(value, [])]
            if any(contains_phrase(text, p) for p in phrases):
                intent.filters.append((col, value))
                break

    ranking_desc = re.search(rf"\b({_DESC_WORDS})\b", text)
    ranking_asc = re.search(rf"\b({_ASC_WORDS})\b", text)
    if m := re.search(r"\btop (\d{1,3})\b", text):
        intent.top_n = int(m.group(1))
    elif (ranking_desc or ranking_asc) and intent.group_by:
        aliases = "|".join(re.escape(normalize(a)) for d in intent.group_by for a in d.aliases)
        m = re.search(rf"\b(\d{{1,2}}) ({aliases})\b", text)
        intent.top_n = int(m.group(1)) if m else 1
    intent.descending = not (ranking_asc and not ranking_desc)
    return intent


def _time_select(metric: Metric, grain: Grain) -> list[tuple[str, str]]:
    """(select expression, output alias) pairs for the requested time grain."""
    col = metric.time_column
    if metric.time_kind == "year_month":
        return {
            "year": [("year", "year")],
            "quarter": [("year", "year"), ("(month + 2) / 3", "quarter")],
            "month": [("year", "year"), ("month", "month")],
        }[grain]
    return {
        "year": [(f"EXTRACT(YEAR FROM {col})::int", "year")],
        "quarter": [
            (f"EXTRACT(YEAR FROM {col})::int", "year"),
            (f"EXTRACT(QUARTER FROM {col})::int", "quarter"),
        ],
        "month": [(f"DATE_TRUNC('month', {col})::date", "month")],
    }[grain]


def _time_where(metric: Metric, scope: TimeScope) -> str | None:
    if scope.start is None or scope.end is None or metric.time_column is None:
        return None
    if metric.time_kind == "date":
        col = metric.time_column
        return f"{col} >= DATE '{scope.start.isoformat()}' AND {col} < DATE '{scope.end.isoformat()}'"
    y, m = scope.start.year, scope.start.month
    if scope.kind == "month":
        return f"year = {y} AND month = {m}"
    if scope.kind == "quarter":
        return f"year = {y} AND month BETWEEN {m} AND {m + 2}"
    return f"year BETWEEN {y} AND {scope.end.year - 1}"


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def compile_sql(intent: Intent, max_rows: int) -> tuple[str, str, list[str]]:
    metric = intent.metric
    select: list[str] = []
    assumptions: list[str] = []
    time_parts: list[tuple[str, str]] = []

    grain = intent.grain if metric.time_column else None
    if grain:
        time_parts = _time_select(metric, grain)
        select += [expr if expr == alias else f"{expr} AS {alias}" for expr, alias in time_parts]
    select += [d.column for d in intent.group_by]
    select.append(f"{metric.expression} AS {metric.code}")

    where = list(metric.filters)
    where += [f"{col.name} = {_quote(value)}" for col, value in intent.filters]
    if intent.time:
        if metric.time_column is None:
            assumptions.append(f"Chỉ số “{metric.name}” là số liệu hiện tại, không lọc theo thời gian.")
        elif clause := _time_where(metric, intent.time):
            where.append(clause)
            assumptions.append(f"Thời gian tính theo cột `{metric.time_column}`.")

    sql = f"SELECT {', '.join(select)}\nFROM {metric.table}"
    if where:
        sql += "\nWHERE " + "\n  AND ".join(where)
    n_group = len(time_parts) + len(intent.group_by)
    if n_group:
        sql += "\nGROUP BY " + ", ".join(str(i) for i in range(1, n_group + 1))
    if intent.top_n and intent.group_by:
        sql += f"\nORDER BY {metric.code} {'DESC' if intent.descending else 'ASC'}\nLIMIT {intent.top_n}"
    elif time_parts:
        sql += "\nORDER BY " + ", ".join(str(i) for i in range(1, len(time_parts) + 1))
    elif intent.group_by:
        sql += f"\nORDER BY {metric.code} DESC"

    parts = [f"Tính {metric.name.lower()} ({metric.description.rstrip('.').lower()})"]
    by = [_GRAIN_LABEL[grain]] if grain else []
    by += [d.name.lower() for d in intent.group_by]
    if by:
        parts.append("theo " + ", ".join(by))
    if intent.filters:
        parts.append("với " + ", ".join(f"{c.description.lower()} = {v}" for c, v in intent.filters))
    if intent.time and metric.time_column:
        parts.append(f"trong {intent.time.label}")
    if intent.top_n and intent.group_by:
        parts.append(f"lấy {intent.top_n} {'cao' if intent.descending else 'thấp'} nhất")
    assumptions.append(f"Hiển thị tối đa {max_rows} dòng.")
    return sql, ", ".join(parts) + ".", assumptions
