"""Advice gate: a phrase list plus a second, deterministic classifier."""

from __future__ import annotations

import re
import unicodedata

_CONFUSABLES = str.maketrans(
    {
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "у": "y",
        "х": "x",
        "і": "i",
        "ѕ": "s",
        "ј": "j",
        "һ": "h",
        "ԁ": "d",
        "ɡ": "g",
        "в": "b",
        "м": "m",
        "н": "h",
        "к": "k",
        "т": "t",
        "α": "a",
        "ο": "o",
        "ν": "v",
        "τ": "t",
        "ρ": "p",
    }
)

_ADVICE_WORDS = {
    "buy",
    "sell",
    "hold",
    "cheap",
    "expensive",
    "undervalued",
    "overvalued",
    "forecast",
    "forecasts",
    "comprar",
    "vender",
    "mantener",
    "acheter",
    "vendre",
    "kaufen",
    "verkaufen",
    "halten",
    "acquire",
}

_SQUASHED = {
    "pricetarget",
    "fairvalue",
    "youshould",
    "youought",
    "strongbuy",
    "strongsell",
    "deberiascomprar",
    "ilfautacheter",
}

_PHRASES = (
    "you should",
    "you ought",
    "price target",
    "fair value",
    "strong buy",
    "strong sell",
    "over valued",
    "under valued",
    "deberias comprar",
    "debes comprar",
    "recomiendo vender",
    "il faut acheter",
    "vous devriez",
    "sie sollten",
    "ought to acquire",
    "建议买入",
    "应该买入",
    "应该持有",
    "建议持有",
)

_FORECAST_DIRECTION = {
    "rise",
    "rises",
    "increase",
    "increases",
    "fall",
    "falls",
    "grow",
    "grows",
    "decline",
    "declines",
    "drop",
    "drops",
    "outperform",
    "underperform",
    "soar",
    "plunge",
}


def _strip_marks(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _join_tokens(tokens: list[str]) -> list[str]:
    joined: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if len(token) == 1 and token.isalpha():
            end = index
            while (
                end < len(tokens)
                and len(tokens[end]) == 1
                and tokens[end].isalpha()
            ):
                end += 1
            word = "".join(tokens[index:end])
            if word in _ADVICE_WORDS or word in _SQUASHED:
                joined.append(word)
            else:
                joined.extend(tokens[index:end])
            index = end
            continue
        joined.append(token)
        index += 1
    changed = True
    current = joined
    while changed:
        changed = False
        nxt: list[str] = []
        index = 0
        while index < len(current):
            if (
                index + 1 < len(current)
                and current[index].isalpha()
                and current[index + 1].isalpha()
                and len(current[index]) <= 3
                and len(current[index + 1]) <= 3
            ):
                glued = current[index] + current[index + 1]
                if glued in _ADVICE_WORDS or glued in _SQUASHED:
                    nxt.append(glued)
                    index += 2
                    changed = True
                    continue
            nxt.append(current[index])
            index += 1
        current = nxt
    return current


def normalize(text: str) -> str:
    """Fold homoglyphs, spacing tricks, and accents into comparable text."""
    folded = unicodedata.normalize("NFKC", text)
    folded = "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")
    folded = folded.replace("\u00ad", "")
    folded = _strip_marks(folded).lower()
    folded = folded.translate(_CONFUSABLES)
    folded = folded.replace("-", " ")
    folded = re.sub(r"[^\w\s/']+", " ", folded, flags=re.UNICODE)
    folded = re.sub(r"\b(over|under)\s+valued\b", r"\1valued", folded)
    folded = re.sub(r"\s+", " ", folded).strip()
    tokens = _join_tokens(folded.split()) if folded else []
    return " ".join(tokens)


def rule_list_reason(text: str) -> str | None:
    """Phrase and word list. Returns a reason, or None when the text is clear."""
    if not text:
        return None
    normalized = normalize(text)
    if not normalized:
        return None
    squashed = normalized.replace(" ", "")
    for phrase in _PHRASES:
        if phrase in normalized or phrase.replace(" ", "") in squashed:
            return "advice phrase"
    for phrase in _SQUASHED:
        if phrase in squashed:
            return "advice phrase"
    tokens = set(normalized.split())
    if tokens & _ADVICE_WORDS:
        return "advice word"
    if "peer" in tokens or "peers" in tokens:
        if tokens & {"cheap", "expensive", "price", "valuation", "undervalued", "overvalued"}:
            return "advice peer comparison"
    return None


def classifier_reason(text: str) -> str | None:
    """Second check. Independent feature rules, not the phrase table."""
    if not text:
        return None
    normalized = normalize(text)
    tokens = normalized.split()
    if not tokens:
        return None
    token_set = set(tokens)
    features: set[str] = set()
    if token_set & {"buy", "sell", "hold", "acquire", "comprar", "vender", "acheter", "vendre", "kaufen", "verkaufen"}:
        features.add("transaction")
    if token_set & {"undervalued", "overvalued", "cheap", "expensive"}:
        features.add("valuation")
    if "target" in token_set and "price" in token_set:
        features.add("target")
    if "pricetarget" in token_set:
        features.add("target")
    if token_set & {"forecast", "forecasts"}:
        features.add("forecast")
    for index, token in enumerate(tokens):
        if token == "will":
            window = set(tokens[index : index + 5])
            if window & _FORECAST_DIRECTION:
                features.add("forecast")
    if "price" in token_set and "will" in token_set:
        features.add("forecast")
    if {"you", "should"} <= token_set or {"you", "ought"} <= token_set:
        features.add("modal")
    if "youshould" in token_set or "youought" in token_set:
        features.add("modal")
    if features & {"transaction", "valuation", "target", "forecast", "modal"}:
        return "advice classifier:" + ",".join(sorted(features))
    return None


def advice_reason(text: str) -> str | None:
    """Block when either the rule list or the classifier matches."""
    return rule_list_reason(text) or classifier_reason(text)
