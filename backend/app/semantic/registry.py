import hashlib
from functools import lru_cache
from pathlib import Path

import yaml

from app.core.config import get_settings
from app.semantic.models import Dataset

# SQLGlot schema mapping: {schema: {table: {column: type}}}
SchemaMapping = dict[str, dict[str, dict[str, str]]]

_SQL_TYPES = {"text": "text", "int": "int", "numeric": "numeric", "date": "date", "bool": "boolean"}


class SemanticRegistry:
    def __init__(self, datasets: list[Dataset]) -> None:
        codes = [d.code for d in datasets]
        if len(codes) != len(set(codes)):
            raise ValueError("Duplicate dataset codes in semantic layer")
        self._datasets = {d.code: d for d in datasets}
        payload = "".join(d.model_dump_json() for d in sorted(datasets, key=lambda d: d.code))
        self.fingerprint = hashlib.sha256(payload.encode()).hexdigest()[:12]

    @classmethod
    def from_directory(cls, directory: Path) -> "SemanticRegistry":
        files = sorted(directory.glob("*.yaml"))
        if not files:
            raise FileNotFoundError(f"No semantic YAML found in {directory}")
        return cls([Dataset.model_validate(yaml.safe_load(f.read_text(encoding="utf-8"))) for f in files])

    def all(self) -> list[Dataset]:
        return list(self._datasets.values())

    def get(self, code: str) -> Dataset | None:
        return self._datasets.get(code)

    def require(self, code: str) -> Dataset:
        dataset = self._datasets.get(code)
        if dataset is None:
            raise KeyError(code)
        return dataset

    def schema_mapping(self, code: str) -> SchemaMapping:
        """Allowlist for the SQL guard: only the tables/columns of this dataset."""
        mapping: SchemaMapping = {}
        for table in self.require(code).tables:
            schema, name = table.name.split(".", 1)
            mapping.setdefault(schema, {})[name] = {c.name: _SQL_TYPES[c.type] for c in table.columns}
        return mapping

    def catalog_summary(self) -> str:
        """Compact description of every dataset used for routing (no column-level detail)."""
        lines = []
        for d in self.all():
            metrics = ", ".join(m.name for m in d.metrics)
            lines.append(f"- {d.code}: {d.name} — {d.description} Chỉ số: {metrics}.")
        return "\n".join(lines)

    def prompt_context(self, code: str) -> str:
        """Column-level context for SQL generation. Only called after the access check passed."""
        d = self.require(code)
        parts = [f"Dataset `{d.code}` — {d.name}: {d.description}", "", "## Bảng/View được phép"]
        for t in d.tables:
            parts.append(f"### {t.name}\n{t.description}")
            for c in t.columns:
                values = f" Giá trị hợp lệ: {', '.join(repr(v) for v in c.values)}." if c.values else ""
                parts.append(f"- {c.name} ({c.type}): {c.description}{values}")
        if d.metrics:
            parts.append("\n## Chỉ số chuẩn (PHẢI dùng đúng biểu thức và bộ lọc)")
            for m in d.metrics:
                filters = " AND ".join(m.filters) or "(không)"
                time = f"; cột thời gian: {m.time_column}" if m.time_column else ""
                parts.append(
                    f"- {m.name} [{m.code}]: {m.expression} trên {m.table}; lọc: {filters}{time}. "
                    f"Từ đồng nghĩa: {', '.join(m.aliases)}"
                )
        if d.examples:
            parts.append("\n## Ví dụ đã kiểm chứng")
            for ex in d.examples:
                parts.append(f"Hỏi: {ex.question}\nSQL: {ex.sql.strip()}")
        return "\n".join(parts)


@lru_cache
def get_registry() -> SemanticRegistry:
    return SemanticRegistry.from_directory(get_settings().semantic_dir)
