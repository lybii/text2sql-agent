"""Read-only execution against the `analytics` schema with the `analytics_reader` role."""

import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine


class QueryExecutionError(Exception):
    pass


@dataclass(frozen=True)
class QueryResult:
    columns: list[dict[str, str]]
    rows: list[list[Any]]
    elapsed_ms: int


def _to_json(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def _column_type(values: list[Any]) -> str:
    sample = next((v for v in values if v is not None), None)
    if isinstance(sample, bool):
        return "bool"
    if isinstance(sample, int | float | Decimal):
        return "number"
    if isinstance(sample, datetime | date):
        return "date"
    return "text"


async def execute_readonly(engine: AsyncEngine, sql: str, *, timeout_ms: int) -> QueryResult:
    started = time.perf_counter()
    try:
        async with engine.connect() as conn, conn.begin():
            await conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            await conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
            result = await conn.exec_driver_sql(sql)
            names = list(result.keys())
            raw_rows = [list(r) for r in result.fetchall()]
    except DBAPIError as exc:
        message = str(exc.orig) if exc.orig is not None else str(exc)
        if "statement timeout" in message or "canceling statement" in message:
            raise QueryExecutionError("Truy vấn vượt quá thời gian cho phép") from exc
        if "permission denied" in message:
            raise QueryExecutionError("Truy vấn bị cơ sở dữ liệu từ chối (thiếu quyền)") from exc
        raise QueryExecutionError("Cơ sở dữ liệu không thực thi được truy vấn") from exc

    columns = [
        {"name": name, "type": _column_type([row[i] for row in raw_rows])} for i, name in enumerate(names)
    ]
    rows = [[_to_json(v) for v in row] for row in raw_rows]
    return QueryResult(columns=columns, rows=rows, elapsed_ms=round((time.perf_counter() - started) * 1000))
