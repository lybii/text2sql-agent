import pytest

from app.semantic.registry import get_registry
from app.sql.guard import check_sql, is_aggregate_query

SCHEMA = get_registry().schema_mapping("sales")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(sale_price) FROM analytics.v_transactions WHERE status = 'Hoàn tất'",
        "SELECT city, COUNT(*) AS n FROM v_transactions GROUP BY city ORDER BY n DESC",
        "WITH x AS (SELECT city, sale_price FROM analytics.v_transactions) SELECT city, AVG(sale_price) FROM x GROUP BY city",
        "SELECT t.city FROM analytics.v_transactions AS t WHERE t.completed_date >= DATE '2025-01-01'",
        "SELECT DATE_TRUNC('month', completed_date)::date AS m, SUM(sale_price) FROM analytics.v_transactions GROUP BY 1",
        "SELECT city, rev FROM (SELECT city, SUM(sale_price) AS rev FROM analytics.v_transactions GROUP BY city) s",
        "SELECT TO_CHAR(created_date, 'YYYY-MM') AS ym, COUNT(*) FROM analytics.v_transactions GROUP BY 1;",
    ],
)
def test_accepts_safe_queries(sql: str) -> None:
    result = check_sql(sql, SCHEMA, max_rows=100)
    assert result.ok, result.errors
    assert result.sql and "LIMIT 100" in result.sql


@pytest.mark.parametrize(
    ("sql", "fragment"),
    [
        ("DELETE FROM analytics.v_transactions", "SELECT"),
        ("DROP TABLE analytics.v_transactions", "SELECT"),
        ("UPDATE analytics.v_transactions SET sale_price = 0", "SELECT"),
        ("SELECT 1; DROP TABLE app.users", "một câu lệnh"),
        ("SELECT * FROM app.users", "Bảng không nằm"),
        ("SELECT * FROM source.customers", "Bảng không nằm"),
        ("SELECT * FROM analytics.v_agent_monthly", "Bảng không nằm"),  # other dataset: not allowed here
        ("SELECT * FROM pg_catalog.pg_roles", "Bảng không nằm"),
        ("SELECT table_name FROM information_schema.tables", "Bảng không nằm"),
        ("SELECT pg_sleep(10)", "Hàm không được phép"),
        ("SELECT pg_read_file('/etc/passwd')", "Hàm không được phép"),
        ("SELECT set_config('statement_timeout', '0', false)", "Hàm không được phép"),
        ("SELECT * FROM dblink('host=x', 'select 1') AS t(a int)", "Hàm không được phép"),
        ("SELECT customer_phone FROM analytics.v_transactions", "Cột không hợp lệ"),
        ("SELECT * INTO app.stolen FROM analytics.v_transactions", "thao tác bị cấm"),
        ("SELECT city FROM analytics.v_transactions FOR UPDATE", "thao tác bị cấm"),
        ("SELECT city FROM otherdb.analytics.v_transactions", "database khác"),
        ("SELEC city FROM", "parse"),
        ("", "rỗng"),
    ],
)
def test_rejects_unsafe_queries(sql: str, fragment: str) -> None:
    result = check_sql(sql, SCHEMA, max_rows=100)
    assert not result.ok
    assert any(fragment in e for e in result.errors), result.errors


def test_limit_is_capped_not_raised() -> None:
    assert "LIMIT 5" in (check_sql("SELECT city FROM v_transactions LIMIT 5", SCHEMA, max_rows=100).sql or "")
    capped = check_sql("SELECT city FROM v_transactions LIMIT 100000", SCHEMA, max_rows=100)
    assert capped.ok and capped.limit_applied and "LIMIT 100" in (capped.sql or "")


def test_every_semantic_example_passes_the_guard() -> None:
    registry = get_registry()
    for dataset in registry.all():
        for example in dataset.examples:
            result = check_sql(example.sql, registry.schema_mapping(dataset.code), max_rows=500)
            assert result.ok, (dataset.code, example.question, result.errors)


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT SUM(sale_price) FROM analytics.v_transactions", True),
        ("SELECT city, SUM(sale_price) FROM analytics.v_transactions GROUP BY city", True),
        ("SELECT property_code, sale_price FROM analytics.v_transactions", False),
    ],
)
def test_aggregate_detection(sql: str, expected: bool) -> None:
    assert is_aggregate_query(sql) is expected
