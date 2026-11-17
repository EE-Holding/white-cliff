"""Verbatim quotes stay short and point at sec.gov."""

from __future__ import annotations

import re
from dataclasses import dataclass

_QUOTE = re.compile(
    r'"([^"]+)"'
    r"|“([^”]+)”"
    r"|‘([^’]+)’"
    r"|«([^»]+)»"
    r"|„([^“]+)“"
    r"|‹([^›]+)›"
)
_ABBREV = re.compile(r"\b(?:Inc|U\.S|Mr|Mrs|Ms|Dr|Jr|Sr|Co|Ltd|Corp)\.")
_WORD = re.compile(r"[A-Za-z0-9']+")


class QuoteError(Exception):
    pass


@dataclass(frozen=True)
class Quote:
    text: str
    url: str
    start: int


def _sentences(text: str) -> int:
    protected = _ABBREV.sub(lambda match: match.group(0).replace(".", "\u0001"), text)
    parts = [part for part in re.split(r"[.!?]+", protected) if part.strip()]
    return len(parts) if parts else 0


def _words(text: str) -> list[str]:
    return _WORD.findall(text)


def extract_quote_texts(text: str) -> list[str]:
    found: list[str] = []
    for match in _QUOTE.finditer(text):
        found.append(next(group for group in match.groups() if group is not None))
    return found


def _sequences(filing_text: str) -> set[tuple[str, ...]]:
    filing_words = [word.lower() for word in _words(filing_text)]
    return {
        tuple(filing_words[index : index + 8])
        for index in range(max(len(filing_words) - 7, 0))
    }


def _sentence_parts(text: str) -> list[str]:
    protected = _ABBREV.sub(lambda match: match.group(0).replace(".", "\u0001"), text)
    parts = re.split(r"[.!?]+", protected)
    return [part.replace("\u0001", ".").strip() for part in parts if part.strip()]


def _locate_words(words: list[str], filing_text: str) -> str | None:
    if not words:
        return None
    pattern = r"\b" + r"\W+".join(re.escape(word) for word in words) + r"\b"
    match = re.search(pattern, filing_text, re.I)
    if match is None:
        return None
    return match.group(0)


def _ngram_quotes(text: str, filing_text: str) -> list[str]:
    """Any run of eight or more words copied from one filing sentence is a quote."""
    found: list[str] = []
    for part in _sentence_parts(text):
        words = _words(part)
        index = 0
        while index <= len(words) - 8:
            if _locate_words(words[index : index + 8], filing_text) is None:
                index += 1
                continue
            end = index + 8
            while end < len(words) and _locate_words(words[index : end + 1], filing_text) is not None:
                end += 1
            located = _locate_words(words[index:end], filing_text)
            if located:
                found.append(located)
            index = end
    return found


def _accept(quote: str, filing_text: str, filing_url: str) -> Quote:
    cleaned = quote.strip()
    if _sentences(cleaned) > 1:
        raise QuoteError("quote sentence limit")
    if len(_words(cleaned)) > 50:
        raise QuoteError("quote word limit")
    if len(_words(cleaned)) == 0:
        raise QuoteError("empty quote")
    start = filing_text.find(cleaned)
    if start < 0:
        lowered = filing_text.lower()
        start = lowered.find(cleaned.lower())
    if start < 0:
        raise QuoteError("quote is not verbatim")
    if not filing_url.startswith("https://www.sec.gov/"):
        raise QuoteError("missing sec.gov link")
    return Quote(text=cleaned, url=f"{filing_url}#quote={start}", start=start)


def review_quotes(text: str, filing_text: str, filing_url: str) -> list[Quote]:
    """Accept up to three verbatim, single-sentence quotes of at most 50 words."""
    explicit = extract_quote_texts(text)
    copied = [
        item
        for item in _ngram_quotes(text, filing_text)
        if not any(item.lower() in prior.lower() for prior in explicit)
    ]
    quotes = explicit + copied
    if len(quotes) > 3:
        raise QuoteError("too many quotes")
    if not filing_url.startswith("https://www.sec.gov/"):
        if quotes:
            raise QuoteError("missing sec.gov link")
        return []
    return [_accept(quote, filing_text, filing_url) for quote in quotes]
