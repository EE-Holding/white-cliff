"""Check model and template text before any number is filled in."""

from __future__ import annotations

import re
import unicodedata

from white_cliff.advice import advice_reason
from white_cliff.facts import FactStore
from white_cliff.prices import price_metric_reason
from white_cliff.quotes import QuoteError, review_quotes

_PLACEHOLDER = re.compile(r"\{(fact|calc):([a-z]+)\}")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def bare_digits(text: str) -> bool:
    """True when a digit or numeric character sits outside a placeholder."""
    stripped = _PLACEHOLDER.sub("", text)
    normalized = unicodedata.normalize("NFKC", stripped)
    for char in normalized:
        if char.isdecimal() or unicodedata.category(char).startswith("N"):
            return True
    for char in stripped:
        if unicodedata.category(char).startswith("N"):
            return True
    return False


def unresolved_placeholders(text: str, store: FactStore) -> bool:
    for kind, identifier in _PLACEHOLDER.findall(text):
        if kind == "fact" and not store.has_fact(identifier):
            return True
        if kind == "calc" and not store.has_calc(identifier):
            return True
    # A brace that looks like a placeholder but contains a digit is not valid.
    if re.search(r"\{(?:fact|calc):[^}]*\d[^}]*\}", text):
        return True
    return False


def missing_section_citation(text: str) -> bool:
    parts = [part.strip() for part in _SENTENCE.split(text.strip()) if part.strip()]
    if not parts:
        return True
    return any("[section:" not in part for part in parts)


def review_text(
    text: str,
    store: FactStore,
    filing_text: str = "",
    filing_url: str = "",
) -> str | None:
    """Return a refusal reason, or None when the text may be rendered."""
    if bare_digits(text):
        return "bare digit"
    if unresolved_placeholders(text, store):
        return "unresolved placeholder"
    advice = advice_reason(text)
    if advice:
        return advice
    price = price_metric_reason(text)
    if price:
        return price
    if missing_section_citation(text):
        return "missing section citation"
    try:
        review_quotes(text, filing_text, filing_url)
    except QuoteError as exc:
        return str(exc)
    return None
