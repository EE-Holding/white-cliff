"""Market-price metrics are refused, not explained."""

from __future__ import annotations

import re
import unicodedata

_PATTERNS = (
    re.compile(r"\bp\s*/\s*e\b", re.I),
    re.compile(r"\bpe\s+multiple\b", re.I),
    re.compile(r"\bpe ratio\b", re.I),
    re.compile(r"\bprice[\s-]*(?:to|/)?[\s-]*(?:earnings|book|sales)\b", re.I),
    re.compile(r"\btimes\s+(?:earnings|sales|book|ebitda)\b", re.I),
    re.compile(r"\bcapitali[sz]ation\b", re.I),
    re.compile(r"\bearnings\s+yield\b", re.I),
    re.compile(r"\bev\s+(?:to|/)\s*ebitda\b", re.I),
    re.compile(r"\b(?:share|stock)\s+price\b", re.I),
    re.compile(r"\btrades?\s+at\b", re.I),
    re.compile(r"\bprice\s*/\s*earnings\b", re.I),
    re.compile(r"\bprice\s*-?\s*to\s*-?\s*earnings\b", re.I),
    re.compile(r"\bev\s*/\s*ebitda\b", re.I),
    re.compile(r"\benterprise value\b", re.I),
    re.compile(r"\bmarket cap\b", re.I),
    re.compile(r"\bmarket capitalization\b", re.I),
    re.compile(r"\bdividend yield\b", re.I),
    re.compile(r"\bp\s*/\s*b\b", re.I),
    re.compile(r"\bprice\s*-?\s*to\s*-?\s*book\b", re.I),
    re.compile(r"\bprice\s*/\s*book\b", re.I),
    re.compile(r"\bprice\s*/\s*sales\b", re.I),
    re.compile(r"\bev\s*/\s*sales\b", re.I),
    re.compile(r"\bpeg ratio\b", re.I),
)


def _prepare(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(
        ch for ch in normalized if unicodedata.category(ch) != "Cf"
    )
    return normalized.lower()


def is_price_text(text: str) -> bool:
    if not text:
        return False
    prepared = _prepare(text)
    return any(pattern.search(prepared) for pattern in _PATTERNS)


def price_metric_reason(text: str) -> str | None:
    if is_price_text(text):
        return "price metric"
    return None
