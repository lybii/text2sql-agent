import re
import unicodedata


def normalize(text: str) -> str:
    """Lowercase, strip Vietnamese diacritics, collapse whitespace: 'Doanh Thu Hà Nội' -> 'doanh thu ha noi'."""
    text = text.lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[?!,;:\"“”()]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def contains_phrase(haystack: str, phrase: str) -> bool:
    """Whole-phrase match on normalized text (so 'quan 1' does not match 'quan 10')."""
    return re.search(rf"(?<![\w.]){re.escape(phrase)}(?![\w])", haystack) is not None
