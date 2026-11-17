"""Market-price metrics are refused, not explained."""

from __future__ import annotations

import re

from white_cliff.skeleton import fold_confusable

_PATTERNS = (
    re.compile(r"\bp\s*/\s*e\b", re.I),
    re.compile(r"\bpe\s+multiple\b", re.I),
    re.compile(r"\bpe ratio\b", re.I),
    re.compile(r"\bprice[\s-]*(?:to|/)?[\s-]*(?:earnings|book|sales)\b", re.I),
    re.compile(r"\btimes\s+(?:earnings|sales|book|ebitda)\b", re.I),
    re.compile(r"\bcapitali[sz]ation\b", re.I),
    re.compile(r"\bcapitalizacion\b", re.I),
    re.compile(r"\bmarktkapitalisierung\b", re.I),
    re.compile(r"\bkapitalisierung\b", re.I),
    re.compile(r"\bearnings\s+yield\b", re.I),
    re.compile(r"\bev\s+(?:to|/)\s*ebitda\b", re.I),
    re.compile(r"\b(?:share|stock)[\s-]+price\b", re.I),
    re.compile(r"\btrades?\s+at\b", re.I),
    re.compile(r"\bprice\s*/\s*earnings\b", re.I),
    re.compile(r"\bprice\s*-?\s*to\s*-?\s*earnings\b", re.I),
    re.compile(r"\bev\s*/\s*ebitda\b", re.I),
    re.compile(r"\benterprise value\b", re.I),
    re.compile(r"\bmarket[\s-]*cap\b", re.I),
    re.compile(r"\bmarket capitalization\b", re.I),
    re.compile(r"\bdividend[\s-]+yield\b", re.I),
    re.compile(r"\bp\s*/\s*b\b", re.I),
    re.compile(r"\bprice\s*-?\s*to\s*-?\s*book\b", re.I),
    re.compile(r"\bprice\s*/\s*book\b", re.I),
    re.compile(r"\bprice\s*/\s*sales\b", re.I),
    re.compile(r"\bev\s*/\s*sales\b", re.I),
    re.compile(r"\bpeg ratio\b", re.I),
    re.compile(r"\bpeg\b", re.I),
    re.compile(r"\bp\s+e\s+ratio\b", re.I),
    re.compile(r"\bmarket value of the equity\b", re.I),
    re.compile(r"\bprice of the shares\b", re.I),
    re.compile(r"\bearnings multiple\b", re.I),
    re.compile(r"\bmultiple of earnings\b", re.I),
    re.compile(r"\bvaluation multiple\b", re.I),
    re.compile(r"\b(?:priced|valued) at a premium\b", re.I),
    re.compile(r"\btrades? for a premium\b", re.I),
    re.compile(r"\bprice to free cash flow\b", re.I),
    re.compile(r"\bev\s*(?:/|to)\s*ebit\b", re.I),
    re.compile(r"\bev\s*(?:/|to)\s*revenue\b", re.I),
    re.compile(r"\bkgv\b", re.I),
    re.compile(r"市盈率"),
)

_PER = re.compile(r"\bPER\b(?!\s+SHARES?\b)")


def _prepare(text: str) -> str:
    return fold_confusable(text)


def is_price_text(text: str) -> bool:
    if not text:
        return False
    if _PER.search(text) or "市盈率" in text:
        return True
    prepared = _prepare(text)
    return any(pattern.search(prepared) for pattern in _PATTERNS)


def price_metric_reason(text: str) -> str | None:
    if is_price_text(text):
        return "price metric"
    return None
