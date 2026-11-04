from datetime import date

import pytest

from app.analysis.chart import recommend_chart
from app.core.text import normalize
from app.llm.demo.compiler import compile_sql, extract_intent
from app.llm.demo.timeparse import parse_grain, parse_time_scope
from app.semantic.registry import get_registry

TODAY = date(2026, 11, 4)


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("doanh thu nam 2025", date(2025, 1, 1), date(2026, 1, 1)),
        ("thang 3/2025", date(2025, 3, 1), date(2025, 4, 1)),
        ("thang 12 nam 2024", date(2024, 12, 1), date(2025, 1, 1)),
        ("quy 2 nam 2025", date(2025, 4, 1), date(2025, 7, 1)),
        ("q4/2024", date(2024, 10, 1), date(2025, 1, 1)),
        ("quy iii 2025", date(2025, 7, 1), date(2025, 10, 1)),
        ("tu 2023 den 2024", date(2023, 1, 1), date(2025, 1, 1)),
        ("nam nay", date(2026, 1, 1), date(2027, 1, 1)),
        ("nam ngoai", date(2025, 1, 1), date(2026, 1, 1)),
        ("thang truoc", date(2026, 10, 1), date(2026, 11, 1)),
        ("quy truoc", date(2026, 7, 1), date(2026, 10, 1)),
    ],
)
def test_time_scope(text: str, start: date, end: date) -> None:
    scope = parse_time_scope(text, TODAY)
    assert scope is not None and (scope.start, scope.end) == (start, end)


def test_time_scope_all_and_none() -> None:
    assert parse_time_scope("toan bo thoi gian", TODAY).kind == "all"  # type: ignore[union-attr]
    assert parse_time_scope("doanh thu la bao nhieu", TODAY) is None
    assert parse_grain("doanh thu theo thang") == "month"
    assert parse_grain("xu huong doanh thu") == "month"


def test_normalize_vietnamese() -> None:
    assert normalize("  Doanh Thu Đà Nẵng?? ") == "doanh thu da nang"


def test_compiler_filters_grouping_and_ranking() -> None:
    reg = get_registry()
    intent = extract_intent(
        reg, normalize("Top 3 dự án có doanh thu căn hộ cao nhất tại Sài Gòn quý 2/2025"), TODAY
    )
    assert intent is not None
    sql, interpretation, _ = compile_sql(intent, 500)
    assert "project_name" in sql and "LIMIT 3" in sql and "DESC" in sql
    assert "city = 'TP.HCM'" in sql and "property_type = 'Căn hộ'" in sql
    assert "quý 2/2025" in interpretation


def test_compiler_year_month_metric() -> None:
    intent = extract_intent(get_registry(), normalize("tỷ lệ hoàn thành chỉ tiêu quý 1/2025"), TODAY)
    assert intent is not None
    sql, _, _ = compile_sql(intent, 500)
    assert "year = 2025 AND month BETWEEN 1 AND 3" in sql


def test_registry_is_consistent() -> None:
    reg = get_registry()
    assert {d.code for d in reg.all()} == {"sales", "inventory", "customers", "staff_performance"}
    assert reg.require("staff_performance").access == "restricted"
    assert set(reg.schema_mapping("sales")["analytics"]) == {"v_transactions"}
    assert len(reg.fingerprint) == 12


@pytest.mark.parametrize(
    ("columns", "rows", "kind"),
    [
        ([{"name": "revenue", "type": "number"}], [[1]], "kpi"),
        (
            [{"name": "city", "type": "text"}, {"name": "revenue", "type": "number"}],
            [["a", 1], ["b", 2]],
            "bar",
        ),
        (
            [{"name": "month", "type": "date"}, {"name": "revenue", "type": "number"}],
            [["2025-01-01", 1], ["2025-02-01", 2]],
            "line",
        ),
        (
            [
                {"name": "year", "type": "number"},
                {"name": "month", "type": "number"},
                {"name": "r", "type": "number"},
            ],
            [[2025, 1, 1], [2025, 2, 2]],
            "line",
        ),
    ],
)
def test_chart_recommendation(columns: list[dict[str, str]], rows: list[list[object]], kind: str) -> None:
    spec = recommend_chart(columns, rows)
    assert spec is not None and spec["type"] == kind


def test_no_chart_for_text_only() -> None:
    assert recommend_chart([{"name": "code", "type": "text"}], [["a"], ["b"]]) is None
