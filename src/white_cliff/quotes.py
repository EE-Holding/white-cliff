"""Verbatim quotes stay short and point at sec.gov."""

from __future__ import annotations

import re
from dataclasses import dataclass

_QUOTE = re.compile(r'"([^"]+)"|“([^”]+)”')


class QuoteError(Exception):
    pass


@dataclass(frozen=True)
class Quote:
    text: str
    url: str
    start: int


def _sentences(text: str) -> int:
    parts = [part for part in re.split(r"[.!?]+", text) if part.strip()]
    return len(parts) if parts else 0


def _words(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text, flags=re.UNICODE))


def extract_quote_texts(text: str) -> list[str]:
    found: list[str] = []
    for match in _QUOTE.finditer(text):
        found.append(match.group(1) if match.group(1) is not None else match.group(2))
    return found


def review_quotes(text: str, filing_text: str, filing_url: str) -> list[Quote]:
    """Accept up to three verbatim, single-sentence quotes of at most 50 words."""
    quotes = extract_quote_texts(text)
    if len(quotes) > 3:
        raise QuoteError("too many quotes")
    if not filing_url.startswith("https://www.sec.gov/"):
        if quotes:
            raise QuoteError("missing sec.gov link")
        return []
    accepted: list[Quote] = []
    for quote in quotes:
        cleaned = quote.strip()
        if _sentences(cleaned) > 1:
            raise QuoteError("quote sentence limit")
        if _words(cleaned) > 50:
            raise QuoteError("quote word limit")
        if _words(cleaned) == 0:
            raise QuoteError("empty quote")
        start = filing_text.find(cleaned)
        if start < 0:
            raise QuoteError("quote is not verbatim")
        url = f"{filing_url}#quote={start}"
        accepted.append(Quote(text=cleaned, url=url, start=start))
    return accepted
