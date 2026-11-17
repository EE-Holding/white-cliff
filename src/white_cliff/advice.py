"""Advice gate: a phrase list plus a second, deterministic classifier."""

from __future__ import annotations

import re
import unicodedata

from white_cliff.skeleton import skeleton

def _folded(items):
    return {skeleton(item) for item in items}


def _folded_seq(items):
    return tuple(skeleton(item) for item in items)


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
    "underpriced",
    "overpriced",
    "mispriced",
    "steal",
    "inexpensive",
    "barata",
    "kopen",
    "koop",
    "günstig",
    "überbewertet",
    "gunstig",
    "uberbewertet",
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
    "golong",
    "takeprofit",
    "sousevalue",
    "kaufempfehlung",
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
    "go long",
    "take profit",
    "建议买入",
    "应该买入",
    "应该持有",
    "建议持有",
    "a good investment",
    "a compelling investment",
    "a must-own name",
    "must own",
    "own the stock",
    "dump the stock",
    "exit the position",
    "load up",
    "snap up",
    "pick up shares",
    "we upgrade",
    "we downgrade",
    "top pick",
    "recommendation is positive",
    "positive rating",
    "add to their positions",
    "add exposure",
    "add to your position",
    "stay away",
    "intrinsic value",
    "looks rich",
    "die aktie ist",
    "koop het aandeel",
    "покупайте акции",
    "acquistate le azioni",
    "株を買うべき",
    "买入该股票",
    "kupuj akcje",
    "satın al",
    "satin al",
    "projected to grow",
    "set to grow",
    "set to rise",
    "poised to rise",
    "poised to jump",
    "going to grow",
    "on track to expand",
    "predicted to increase",
    "bound to rise",
    "may increase",
    "revenue grows",
    "guided to grow",
    "projected to climb",
    "predict higher",
)

_PREFIXES = (
    "buy",
    "sell",
    "accumulat",
    "overweight",
    "underweight",
    "outperform",
    "underperform",
    "upside",
    "downside",
    "bargain",
    "attractiv",
    "trim",
    "avoid",
    "opportun",
    "purchas",
    "kauf",
    "verkauf",
    "achet",
    "unterbewert",
    "infravalor",
    "sobrevalor",
)

_MODAL = {"should", "ought", "consider", "recommends", "recommend", "recommended", "considering"}
_FUTURE = {"will", "shall", "likely", "outlook"}
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
    "expand",
    "expands",
    "rally",
    "improve",
    "improves",
}


_ADVICE_WORDS = _folded(_ADVICE_WORDS)
_SQUASHED = _folded(_SQUASHED)
_PHRASES = _folded_seq(_PHRASES)
_PREFIXES = _folded_seq(_PREFIXES)
_MODAL = _folded(_MODAL)
_FUTURE = _folded(_FUTURE)
_FORECAST_DIRECTION = _folded(_FORECAST_DIRECTION)


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
            while end < len(tokens) and len(tokens[end]) == 1 and tokens[end].isalpha():
                end += 1
            word = "".join(tokens[index:end])
            if word in _ADVICE_WORDS or word in _SQUASHED or _stem(word):
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
                if glued in _ADVICE_WORDS or glued in _SQUASHED or _stem(glued):
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
    folded = skeleton(text)
    folded = _strip_marks(folded)
    folded = folded.replace("-", " ").replace("_", " ").replace("/", " ")
    folded = re.sub(r"[^\w\s/']+", " ", folded, flags=re.UNICODE)
    folded = re.sub(r"\b(over|under)\s+valued\b", r"\1valued", folded)
    folded = re.sub(r"\s+", " ", folded).strip()
    tokens = _join_tokens(folded.split()) if folded else []
    return " ".join(tokens)


_COMPR = skeleton("compr")
_COMPREHENS = skeleton("comprehens")


def _stem(token: str) -> bool:
    if token in {"withhold", "withholding", "withheld", "withholds"}:
        return False
    if token.startswith("hold") and token not in {"holder", "holders"}:
        return True
    if token.startswith("vend") and not token.startswith(("vendor", "vending")):
        return True
    if token.startswith(_COMPR) and not token.startswith(_COMPREHENS):
        return True
    if token in {"short", "shorts"}:
        return True
    return any(token.startswith(prefix) for prefix in _PREFIXES)


def _future_token(token: str) -> bool:
    if token in _FUTURE:
        return True
    return token.startswith("expect") or token.startswith("anticipat")


def _sentences(text: str) -> list[str]:
    protected = re.sub(r"\b(?:Inc|U\.S|Mr|Mrs|Ms|Dr|Jr|Sr|Co|Ltd|Corp)\.", lambda m: m.group(0).replace(".", "\u0001"), text)
    parts = re.split(r"(?<=[.!?])\s+", protected)
    return [part.replace("\u0001", ".").strip() for part in parts if part.strip()]


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
    tokens = normalized.split()
    token_set = set(tokens)
    if token_set & _ADVICE_WORDS:
        return "advice word"
    if any(_stem(token) for token in tokens):
        return "advice word"
    if "peer" in token_set or "peers" in token_set:
        if token_set & {"cheap", "expensive", "price", "valuation", "undervalued", "overvalued"}:
            return "advice peer comparison"
    for index, token in enumerate(tokens[:-1]):
        if token == "take" and tokens[index + 1].startswith("profit"):
            return "advice phrase"
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
    if any(_stem(token) for token in tokens):
        features.add("transaction")
    if token_set & {"undervalued", "overvalued", "cheap", "expensive"}:
        features.add("valuation")
    if "target" in token_set and "price" in token_set:
        features.add("target")
    if "pricetarget" in token_set:
        features.add("target")
    if token_set & {"forecast", "forecasts"}:
        features.add("forecast")
    if any(_future_token(token) for token in tokens):
        features.add("forecast")
    for index, token in enumerate(tokens):
        if token == "will":
            window = set(tokens[index : index + 5])
            if window & _FORECAST_DIRECTION:
                features.add("forecast")
    if "price" in token_set and "will" in token_set:
        features.add("forecast")
    if token_set & _MODAL or "youshould" in token_set or "youought" in token_set:
        features.add("modal")
    if {"you", "should"} <= token_set or {"you", "ought"} <= token_set:
        features.add("modal")
    if features & {"transaction", "valuation", "target", "forecast", "modal"}:
        return "advice classifier:" + ",".join(sorted(features))
    return None


def _verbatim(sentence: str, filing_text: str) -> bool:
    if not filing_text:
        return False
    folded = re.sub(r"\s+", " ", skeleton(sentence)).strip(" .!?\"'")
    source = re.sub(r"\s+", " ", skeleton(filing_text))
    return bool(folded) and folded in source


def _forecast_only(reason: str | None) -> bool:
    if not reason or not reason.startswith("advice classifier:"):
        return False
    features = set(reason.split(":", 1)[1].split(","))
    return features <= {"forecast"}


def advice_reason(text: str, filing_text: str = "") -> str | None:
    """Block when either the rule list or the classifier matches."""
    listed = rule_list_reason(text)
    classified = classifier_reason(text)
    if listed:
        return listed
    if classified and not _forecast_only(classified):
        return classified
    for sentence in _sentences(text):
        tokens = set(normalize(sentence).split())
        if not any(_future_token(token) for token in tokens):
            continue
        bare = re.sub(r"\[section:[^\]]+\]", "", sentence)
        bare = bare.strip(" \"'“”‘’«»„‹›")
        if _verbatim(bare, filing_text):
            continue
        return classified or "advice forecast"
    return None
