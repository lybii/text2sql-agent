"""Vietnamese time-expression parsing for the deterministic demo provider."""

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

Grain = Literal["month", "quarter", "year"]

_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4}


@dataclass(frozen=True)
class TimeScope:
    start: date | None  # None = all available time
    end: date | None  # exclusive
    label: str
    kind: Literal["month", "quarter", "year", "range", "all"]


def _month(year: int, month: int) -> TimeScope:
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return TimeScope(date(year, month, 1), end, f"tháng {month}/{year}", "month")


def _quarter(year: int, q: int) -> TimeScope:
    start = date(year, 3 * (q - 1) + 1, 1)
    end = date(year + 1, 1, 1) if q == 4 else date(year, 3 * q + 1, 1)
    return TimeScope(start, end, f"quý {q}/{year}", "quarter")


def _year(year: int) -> TimeScope:
    return TimeScope(date(year, 1, 1), date(year + 1, 1, 1), f"năm {year}", "year")


def parse_time_scope(text: str, today: date) -> TimeScope | None:
    """`text` must be normalized (no diacritics, lowercase)."""
    if m := re.search(r"\bthang (\d{1,2})\s*(?:/|-|nam)?\s*(\d{4})", text):
        month, year = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12:
            return _month(year, month)
    if m := re.search(r"\b(?:quy|q)\s*(iv|iii|ii|i|[1-4])\s*(?:/|-|nam)?\s*(\d{4})", text):
        raw = m.group(1)
        return _quarter(int(m.group(2)), _ROMAN.get(raw) or int(raw))
    if m := re.search(r"(?:tu )?(?:nam )?(20\d{2})\s*(?:-|den|toi)\s*(?:nam )?(20\d{2})", text):
        y1, y2 = sorted((int(m.group(1)), int(m.group(2))))
        return TimeScope(date(y1, 1, 1), date(y2 + 1, 1, 1), f"{y1}–{y2}", "range")
    if m := re.search(r"\b(20\d{2})\b", text):
        return _year(int(m.group(1)))

    if re.search(r"\bnam nay\b", text):
        return _year(today.year)
    if re.search(r"\bnam (ngoai|truoc|roi)\b", text):
        return _year(today.year - 1)
    if re.search(r"\bthang nay\b", text):
        return _month(today.year, today.month)
    if re.search(r"\bthang (truoc|roi)\b", text):
        return _month(today.year - 1, 12) if today.month == 1 else _month(today.year, today.month - 1)
    current_q = (today.month - 1) // 3 + 1
    if re.search(r"\bquy nay\b", text):
        return _quarter(today.year, current_q)
    if re.search(r"\bquy (truoc|roi)\b", text):
        return _quarter(today.year - 1, 4) if current_q == 1 else _quarter(today.year, current_q - 1)
    if re.search(r"\b(tat ca|toan bo|tu truoc den nay|tu dau|moi thoi diem|all time)\b", text):
        return TimeScope(None, None, "toàn bộ thời gian", "all")
    return None


def parse_grain(text: str) -> Grain | None:
    # "moi" is deliberately absent: without diacritics "mỗi năm" (each year) equals "mới năm" as in
    # "khách hàng mới năm 2025" (new customers in 2025). "theo/từng/hàng/các" are unambiguous.
    if re.search(r"\b(theo|tung|hang|cac) thang\b|xu huong", text):
        return "month"
    if re.search(r"\b(theo|tung|hang|cac) quy\b", text):
        return "quarter"
    if re.search(r"\b(theo|tung|hang|cac) nam\b", text):
        return "year"
    return None
