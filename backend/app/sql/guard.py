"""Deterministic SQL guardrail. The LLM output is untrusted input; this is the gate.

Layer 1 of defense in depth (the read-only DB role and READ ONLY transaction are layers 2-3).
"""

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify

from app.semantic.registry import SchemaMapping

_FORBIDDEN_NODE_NAMES = (
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "TruncateTable",
    "Command", "Into", "Set", "Copy", "Grant", "Lock", "Transaction", "Commit", "Rollback",
)  # fmt: skip
_FORBIDDEN_NODES = tuple(getattr(exp, name) for name in _FORBIDDEN_NODE_NAMES if hasattr(exp, name))

# Functions sqlglot does not model natively arrive as `exp.Anonymous`. Only these are allowed;
# everything else (pg_sleep, pg_read_file, dblink, set_config, current_setting, ...) is rejected.
_SAFE_ANONYMOUS_FUNCTIONS = frozenset({"date_part", "to_char", "initcap", "make_date", "justify_interval"})


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    sql: str | None = None
    errors: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    limit_applied: bool = False


def check_sql(sql: str, schema: SchemaMapping, *, max_rows: int) -> GuardResult:
    if not sql or not sql.strip():
        return GuardResult(False, errors=["SQL rỗng"])
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except ParseError as exc:
        return GuardResult(False, errors=[f"SQL không parse được: {str(exc).splitlines()[0]}"])
    if len(statements) != 1:
        return GuardResult(False, errors=["Chỉ cho phép đúng một câu lệnh"])
    tree = statements[0]

    if not isinstance(tree, exp.Query):
        return GuardResult(False, errors=["Chỉ cho phép truy vấn SELECT"])
    forbidden = sorted({type(n).__name__ for n in tree.walk() if isinstance(n, _FORBIDDEN_NODES)})
    if forbidden:
        return GuardResult(False, errors=[f"Câu lệnh chứa thao tác bị cấm: {', '.join(forbidden)}"])

    errors: list[str] = []
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    allowed = {f"{s}.{t}" for s, tables in schema.items() for t in tables}
    referenced: set[str] = set()
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if not table.db and name in cte_names:
            continue
        if table.catalog:
            errors.append(f"Không cho phép tham chiếu database khác: {table.sql()}")
            continue
        qualified = f"{(table.db or 'analytics').lower()}.{name}"
        if qualified not in allowed:
            errors.append(f"Bảng không nằm trong dataset được phép: {table.sql(dialect='postgres')}")
        else:
            referenced.add(qualified)

    unsafe = sorted({f.name.lower() for f in tree.find_all(exp.Anonymous)} - _SAFE_ANONYMOUS_FUNCTIONS)
    if unsafe:
        errors.append(f"Hàm không được phép: {', '.join(unsafe)}")
    if errors:
        return GuardResult(False, errors=errors, tables=sorted(referenced))

    try:
        # Validation only: resolves aliases/CTEs/subqueries and fails on unknown columns.
        qualify(
            tree.copy(),
            schema=schema,
            db="analytics",
            dialect="postgres",
            validate_qualify_columns=True,
            quote_identifiers=False,
        )
    except OptimizeError as exc:
        return GuardResult(False, errors=[f"Cột không hợp lệ: {exc}"], tables=sorted(referenced))

    limited, limit_applied = _enforce_limit(tree, max_rows)
    if limited is None:
        return GuardResult(False, errors=["LIMIT phải là số nguyên không âm"], tables=sorted(referenced))
    return GuardResult(
        True,
        sql=limited.sql(dialect="postgres", pretty=True),
        tables=sorted(referenced),
        limit_applied=limit_applied,
    )


def is_aggregate_query(sql: str) -> bool:
    """True if the outermost query aggregates (GROUP BY or only aggregate projections)."""
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except ParseError:
        return False
    select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
    if select is None:
        return False
    if select.args.get("group"):
        return True
    projections = select.expressions
    return bool(projections) and all(p.find(exp.AggFunc) is not None for p in projections)


def _enforce_limit(tree: exp.Query, max_rows: int) -> tuple[exp.Query | None, bool]:
    limit = tree.args.get("limit")
    if limit is None:
        return tree.limit(max_rows, copy=True), True
    value = limit.expression
    if not (isinstance(value, exp.Literal) and value.is_int) or int(value.this) < 0:
        return None, False
    if int(value.this) > max_rows:
        return tree.limit(max_rows, copy=True), True
    return tree, False
