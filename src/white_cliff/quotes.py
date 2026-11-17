"""Quotes must be verbatim, linked, and short."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from white_cliff.omissions import find_omissions
from white_cliff.skeleton import _small_capital, _table

_PAIRS = (
    ('"', '"'),
    ("“", "”"),
    ("‘", "’"),
    ("«", "»"),
    ("„", "“"),
    ("‹", "›"),
)
_WORD = re.compile(r"[0-9a-z]+(?:'[0-9a-z]+)?")
_ABBREV = {"inc", "u.s", "u.k", "mr", "mrs", "ms", "dr", "no", "fig"}


class QuoteError(ValueError):
    """A quote is not a short verbatim span of the filing."""


@dataclass(frozen=True)
class Quote:
    text: str
    url: str
    start: int
    text_start: int = 0
    text_end: int = 0


def _fold_with_map(text: str) -> tuple[str, list[int]]:
    table = _table()
    chars: list[str] = []
    origins: list[int] = []
    for index, char in enumerate(text):
        if ord(char) < 128:
            if "A" <= char <= "Z":
                char = char.lower()
            mapped = table.get(char)
            if mapped is None:
                chars.append(char)
                origins.append(index)
                continue
            for unit in mapped:
                chars.append(unit)
                origins.append(index)
            continue
        if unicodedata.category(char) == "Cf":
            continue
        for piece in unicodedata.normalize("NFKC", char).casefold():
            if unicodedata.category(piece) in {"Mn", "Cf"}:
                continue
            mapped = table.get(piece, piece)
            for unit in unicodedata.normalize("NFD", mapped):
                if unicodedata.category(unit) in {"Mn", "Cf"}:
                    continue
                chars.append(_small_capital(unit))
                origins.append(index)
    return "".join(chars), origins


@lru_cache(maxsize=2)
def _filing_words(text: str) -> tuple[tuple[tuple[str, int, int], ...], tuple[str, ...], tuple[tuple[int, ...], ...]]:
    words = tuple(_words(text))
    folded = tuple(word for word, _start, _end in words)
    starts: dict[str, list[int]] = {}
    for index, word in enumerate(folded):
        starts.setdefault(word, []).append(index)
    packed = tuple(tuple(indexes) for indexes in starts.values())
    keys = tuple(starts)
    return words, folded, tuple(zip(keys, packed))


def _words(text: str) -> list[tuple[str, int, int]]:
    folded, origins = _fold_with_map(text)
    found: list[tuple[str, int, int]] = []
    for match in _WORD.finditer(folded):
        start = origins[match.start()]
        end = origins[match.end() - 1] + 1
        found.append((match.group(0), start, end))
    return found


def _sentences(text: str) -> list[str]:
    cleaned = "".join(char for char in text if unicodedata.category(char) != "Cf")
    parts = re.split(r"(?<=[.!?])\s+", cleaned.strip())
    merged: list[str] = []
    for part in parts:
        if not part:
            continue
        if merged:
            tail = merged[-1].rstrip(".").split()[-1].lower() if merged[-1].split() else ""
            if tail.rstrip(".") in _ABBREV or len(tail.rstrip(".")) <= 1:
                merged[-1] = f"{merged[-1]} {part}"
                continue
        merged.append(part)
    return merged


def _filing_url(filing_url: str, start: int) -> str:
    if not filing_url.startswith("https://www.sec.gov/"):
        raise QuoteError("a quote needs the filing's sec.gov url")
    base = filing_url.split("#", 1)[0]
    return f"{base}#quote={start}"


def _straight_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        if text[index] != "'":
            index += 1
            continue
        if index > 0 and (text[index - 1].isalnum() or text[index - 1] == "'"):
            index += 1
            continue
        end = text.find("'", index + 1)
        if end < 0:
            break
        inner = text[index + 1 : end]
        if " " in inner and "\n" not in inner:
            spans.append((index + 1, end))
            index = end + 1
            continue
        index += 1
    return spans


def _marked_spans(text: str) -> list[tuple[int, int]]:
    spans = list(_straight_spans(text))
    for opener, closer in _PAIRS:
        start = 0
        while True:
            begin = text.find(opener, start)
            if begin < 0:
                break
            end = text.find(closer, begin + len(opener))
            if end < 0:
                break
            inner_start = begin + len(opener)
            if end > inner_start and "\n" not in text[inner_start:end]:
                spans.append((inner_start, end))
            start = end + len(closer)
    spans.sort()
    kept: list[tuple[int, int]] = []
    occupied = -1
    for start, end in spans:
        if start < occupied:
            continue
        kept.append((start, end))
        occupied = end
    return kept


def _sequence_at(
    quote_words: list[str],
    filing_words: list[tuple[str, int, int]],
    folded: tuple[str, ...] | list[str],
    starts: dict[str, tuple[int, ...]],
) -> tuple[int, int] | None:
    if not quote_words:
        return None
    width = len(quote_words)
    if width > len(folded):
        return None
    for index in starts.get(quote_words[0], ()):
        if index + width > len(folded):
            continue
        if list(folded[index : index + width]) == quote_words:
            return filing_words[index][1], filing_words[index + width - 1][2]
    return None


def review_quotes(text: str, filing_text: str, filing_url: str) -> list[Quote]:
    """Accept only one-sentence, 50-word, verbatim quotes with a sec.gov link."""
    spans = _marked_spans(text)
    if len(spans) > 3:
        raise QuoteError("more than three quotes")
    filing_words, filing_folded, packed_starts = _filing_words(filing_text)
    filing_words = list(filing_words)
    starts = dict(packed_starts)
    quotes: list[Quote] = []
    if spans:
        for start, end in spans:
            quotes.append(
                _verbatim(text[start:end], filing_words, filing_folded, starts, filing_url, start, end)
            )
        return quotes
    source_words = _words(text)
    folded = [word for word, _start, _end in source_words]
    for index in range(0, len(source_words) - 7):
        found = _sequence_at(folded[index : index + 8], filing_words, filing_folded, starts)
        if found is None:
            continue
        text_start = source_words[index][1]
        text_end = source_words[index + 7][2]
        snippet = text[text_start:text_end]
        quotes.append(
            Quote(snippet, _filing_url(filing_url, found[0]), found[0], text_start, text_end)
        )
        if len(quotes) > 3:
            raise QuoteError("more than three quotes")
    return quotes


def _verbatim(
    snippet: str,
    filing_words: list[tuple[str, int, int]],
    filing_folded: tuple[str, ...] | list[str],
    starts: dict[str, tuple[int, ...]],
    filing_url: str,
    text_start: int,
    text_end: int,
) -> Quote:
    if find_omissions(snippet):
        raise QuoteError("a quote contains an omission marker")
    sentences = _sentences(snippet)
    if len(sentences) != 1:
        raise QuoteError("a quote must be one sentence")
    words = _words(snippet)
    if len(words) > 50:
        raise QuoteError("a quote must be 50 words or fewer")
    found = _sequence_at(
        [word for word, _start, _end in words],
        filing_words,
        filing_folded,
        starts,
    )
    if found is None:
        raise QuoteError("a quote is not verbatim from the filing")
    return Quote(snippet, _filing_url(filing_url, found[0]), found[0], text_start, text_end)
