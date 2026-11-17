"""Number words the prose must not write. The renderer fills digits from the store."""

from __future__ import annotations

import re
import unicodedata

_CARDINALS = {
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
    "hundred",
    "thousand",
    "million",
    "millions",
    "billion",
    "billions",
    "trillion",
    "dozen",
    "half",
    "halved",
    "nil",
    "double",
    "triple",
    "quadruple",
    "zwolf",
    "douze",
    "millones",
    "milliarden",
    "millionen",
}
_ORDINALS = {
    "first",
    "second",
    "third",
    "fourth",
    "fifth",
    "sixth",
    "seventh",
    "eighth",
    "ninth",
    "tenth",
    "eleventh",
    "twelfth",
    "twentieth",
    "hundredth",
    "thousandth",
    "millionth",
}
_PHRASES = (
    "several-fold",
    "several fold",
    "tens of billions",
    "in the billions",
    "a couple of",
    "a score of",
    "by a quarter",
    "a quarter",
    "zwolf millionen",
    "zwolf milliarden",
    "douze millions",
    "dos mil millones",
)
_MULTIPLIERS = ("doubl", "tripl", "quadrupl")
_ROMAN = re.compile(
    r"^(?=.)M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$",
    re.I,
)


def _plain(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Cf")
    decomposed = unicodedata.normalize("NFKD", normalized)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return stripped.lower()


def number_words(text: str) -> bool:
    """True when the text names a quantity instead of using a placeholder."""
    lowered = _plain(text)
    if "per cent" in lowered or "percent" in lowered:
        return True
    for phrase in _PHRASES:
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            return True
    for token in re.findall(r"[a-z]+", lowered):
        if token in _CARDINALS or token in _ORDINALS:
            return True
        if token.endswith("fold") and len(token) > 4:
            return True
        if any(token.startswith(prefix) for prefix in _MULTIPLIERS):
            return True
        if len(token) >= 2 and _ROMAN.fullmatch(token):
            return True
    return False
