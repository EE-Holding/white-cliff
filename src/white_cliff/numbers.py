"""Number words a model must not write. The renderer fills digits from the store."""

from __future__ import annotations

import re

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
    "billion",
    "trillion",
    "dozen",
    "half",
    "double",
    "triple",
    "quadruple",
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
    "twelfth",
    "hundredth",
}
_MULTIPLIERS = ("doubl", "tripl", "quadrupl")
_ROMAN = re.compile(
    r"^(?=.)M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$",
    re.I,
)


def number_words(text: str) -> bool:
    """True when the text names a quantity instead of using a placeholder."""
    lowered = text.lower()
    if "per cent" in lowered or "percent" in lowered:
        return True
    for token in re.findall(r"[A-Za-z]+", text):
        word = token.lower()
        if word in _CARDINALS or word in _ORDINALS:
            return True
        if any(word.startswith(prefix) for prefix in _MULTIPLIERS):
            return True
        if len(word) >= 2 and _ROMAN.fullmatch(word):
            return True
    return False
