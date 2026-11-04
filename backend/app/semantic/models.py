"""Typed contract for semantic YAML files. Invalid YAML fails fast at startup and in CI."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

ColumnType = Literal["text", "int", "numeric", "date", "bool"]
Unit = Literal["vnd", "count", "percent", "m2", "number"]


class Column(BaseModel):
    name: str
    type: ColumnType
    description: str
    values: list[str] = Field(default_factory=list, description="Enumerated values usable as filters")


class Table(BaseModel):
    name: str = Field(pattern=r"^analytics\.[a-z_][a-z0-9_]*$")
    description: str
    columns: list[Column]

    @property
    def short_name(self) -> str:
        return self.name.split(".", 1)[1]

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name == name), None)


class Metric(BaseModel):
    code: str
    name: str
    description: str
    expression: str
    table: str
    time_column: str | None = None
    time_kind: Literal["date", "year_month"] = "date"
    filters: list[str] = Field(default_factory=list)
    requires_time: bool = False
    unit: Unit = "number"
    aliases: list[str] = Field(default_factory=list)


class Dimension(BaseModel):
    column: str
    table: str
    name: str
    aliases: list[str] = Field(default_factory=list)


class Example(BaseModel):
    question: str
    sql: str


class Dataset(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    description: str
    access: Literal["open", "restricted"]
    sensitivity: Literal["internal", "confidential"] = "internal"
    owner: str
    keywords: list[str] = Field(default_factory=list)
    tables: list[Table]
    metrics: list[Metric] = Field(default_factory=list)
    dimensions: list[Dimension] = Field(default_factory=list)
    examples: list[Example] = Field(default_factory=list)
    sample_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references_exist(self) -> "Dataset":
        tables = {t.name: t for t in self.tables}
        for metric in self.metrics:
            table = tables.get(metric.table)
            if table is None:
                raise ValueError(f"metric {metric.code}: unknown table {metric.table}")
            if metric.time_column and metric.time_kind == "date" and table.column(metric.time_column) is None:
                raise ValueError(f"metric {metric.code}: unknown time column {metric.time_column}")
        for dim in self.dimensions:
            table = tables.get(dim.table)
            if table is None or table.column(dim.column) is None:
                raise ValueError(f"dimension {dim.column}: unknown column on {dim.table}")
        return self

    def table(self, name: str) -> Table:
        return next(t for t in self.tables if t.name == name)
