"""Unicode confusable skeleton (UTS #39) plus small-capital folding."""

from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path


def _load() -> dict[str, str]:
    table: dict[str, str] = {}
    path = Path(__file__).with_name("data") / "confusables.txt"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        source, target, *_rest = [part.strip() for part in line.split(";")]
        if not source or not target:
            continue
        key = "".join(chr(int(piece, 16)) for piece in source.split())
        value = "".join(chr(int(piece, 16)) for piece in target.split())
        table[key] = value
    return table


@lru_cache(maxsize=1)
def _table() -> dict[str, str]:
    return _load()


def _small_capital(char: str) -> str:
    name = unicodedata.name(char, "")
    if "SMALL CAPITAL" not in name:
        return char
    letter = name.split()[-1]
    if len(letter) == 1 and letter.isalpha():
        return letter.lower()
    return char


def skeleton(text: str) -> str:
    """Map confusable characters onto a comparable prototype string."""
    folded = unicodedata.normalize("NFKC", text).lower()
    table = _table()
    mapped: list[str] = []
    for char in unicodedata.normalize("NFD", folded):
        if unicodedata.category(char) in {"Mn", "Cf"}:
            continue
        mapped.append(table.get(char, char))
    flattened = unicodedata.normalize("NFD", "".join(mapped))
    kept = []
    for char in flattened:
        if unicodedata.category(char) in {"Mn", "Cf"}:
            continue
        kept.append(_small_capital(char))
    return "".join(kept)
