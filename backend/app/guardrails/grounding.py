"""Output rail for the natural-language explanation: every number it states must be traceable.

A number in the explanation is *grounded* if it matches a number in the result rows, the row count,
the question/interpretation, or a simple aggregate of a result column (sum, mean, range, % change, share).
Units are scaled ("1,25 tỷ" → 1.25e9), the tolerance follows the displayed precision ("1,2 tỷ" accepts
anything that rounds to it), and both Vietnamese (1.234,5) and English (1,234.5) separators are accepted.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

_UNITS = {
    "nghìn tỷ": 1e12,
    "ngàn tỷ": 1e12,
    "nghin ty": 1e12,
    "tỷ": 1e9,
    "ty": 1e9,
    "triệu": 1e6,
    "trieu": 1e6,
    "nghìn": 1e3,
    "ngàn": 1e3,
    "nghin": 1e3,
}
_NUMBER = re.compile(
    r"(?<![\w])(\d+(?:[.,]\d+)*)\s*(nghìn tỷ|ngàn tỷ|nghin ty|tỷ|ty|triệu|trieu|nghìn|ngàn|nghin)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Number:
    raw: str
    candidates: tuple[tuple[float, float], ...]  # (value, tolerance) for each plausible reading


def _readings(raw: str) -> list[tuple[float, int]]:
    """Plausible (value, decimals) readings of a number token with ambiguous separators."""
    seps = re.findall(r"[.,]", raw)
    if not seps:
        return [(float(raw), 0)]
    if len(set(seps)) == 2:  # both used: the last one is the decimal separator
        dec = seps[-1]
        thousands = "," if dec == "." else "."
        whole, frac = raw.replace(thousands, "").split(dec)
        return [(float(f"{whole}.{frac}"), len(frac))]
    sep = seps[0]
    parts = raw.split(sep)
    if len(parts) > 2:  # repeated separator: thousands grouping
        return [(float("".join(parts)), 0)]
    readings = [(float(f"{parts[0]}.{parts[1]}"), len(parts[1]))]
    if len(parts[1]) == 3:
        readings.append((float(parts[0] + parts[1]), 0))
    return readings


def extract_numbers(text: str) -> list[Number]:
    out = []
    for m in _NUMBER.finditer(text):
        scale = _UNITS.get((m.group(2) or "").lower(), 1.0)
        out.append(
            Number(
                m.group(0),
                tuple(
                    (value * scale, 0.5 * 10**-decimals * scale) for value, decimals in _readings(m.group(1))
                ),
            )
        )
    return out


def _reference_values(rows: list[list[Any]], extra: Iterable[float]) -> list[float]:
    refs = list(extra)
    columns: dict[int, list[float]] = {}
    for row in rows:
        for i, v in enumerate(row):
            if isinstance(v, bool):
                continue
            if isinstance(v, int | float):
                refs.append(float(v))
                columns.setdefault(i, []).append(float(v))
            elif isinstance(v, str):
                refs.extend(value for n in extract_numbers(v) for value, _ in n.candidates)
    for values in columns.values():
        refs += [sum(values), sum(values) / len(values), max(values) - min(values)]
    return refs


def ungrounded_numbers(
    explanation: str, *, rows: list[list[Any]], row_count: int, context: str = ""
) -> list[str]:
    """Number tokens in `explanation` that cannot be traced to the result or the question context."""
    context_values = [value for n in extract_numbers(context) for value, _ in n.candidates]
    refs = _reference_values(rows, [float(row_count), *context_values])
    sample = refs[:100]
    derived = [abs(b - a) / abs(a) * 100 for a in sample for b in sample if a]
    derived += [a / b * 100 for a in sample for b in sample if b and 0 < a <= b]

    def grounded(n: Number) -> bool:
        for value, tol in n.candidates:
            if value <= 12 and value.is_integer():
                return True  # small counts, months, ranks ("top 3", "tháng 5")
            if any(abs(value - r) <= max(tol, abs(r) * 0.005) for r in refs):
                return True
            if any(abs(value - p) <= max(tol, 0.05) for p in derived):
                return True
        return False

    return [n.raw for n in extract_numbers(explanation) if not grounded(n)]
