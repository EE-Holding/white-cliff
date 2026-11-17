"""Check model and template text before any number is filled in."""

from __future__ import annotations

import re
import unicodedata

from white_cliff.advice import advice_reason
from white_cliff.facts import FactStore
from white_cliff.numbers import number_words
from white_cliff.prices import price_metric_reason
from white_cliff.quotes import QuoteError, review_quotes
from white_cliff.redact import contains_personal

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


def forbidden_markup(text: str) -> bool:
    """Model text may cite a section. It may not build a link or a tag."""
    cleaned = re.sub(r"\[section:[^\]]+\]", "", text)
    cleaned = re.sub(r"\[\*+(?:\s*\*)*\]", "", cleaned)
    cleaned = re.sub(r"\[(?i:redacted|omitted)\]", "", cleaned)
    return "<" in cleaned or "](" in cleaned or "[" in cleaned or "![" in cleaned


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
    if number_words(text):
        return "number word"
    if forbidden_markup(text):
        return "markup"
    if contains_personal(text):
        return "personal data"
    if unresolved_placeholders(text, store):
        return "unresolved placeholder"
    advice = advice_reason(text, filing_text)
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


def audit_rendered(text: str) -> str | None:
    """Re-check prose after chips and the disclaimer are removed."""
    from white_cliff.disclaimer import DISCLAIMER

    body = text.replace(DISCLAIMER, " ", 1)
    body = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", body)
    body = re.sub(r"<data\b[^>]*>.*?</data>", " ", body, flags=re.I | re.S)
    body = re.sub(r"<a\b[^>]*>.*?</a>", " ", body, flags=re.I | re.S)
    body = re.sub(r"<[^>]+>", " ", body)
    if bare_digits(body):
        return "bare digit"
    if number_words(body):
        return "number word"
    if advice_reason(body):
        return "advice"
    if price_metric_reason(body):
        return "price metric"
    return None
