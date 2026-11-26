"""Unicode confusable skeleton (UTS #39) plus small-capital folding."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path


def _read_table(path: Path, table: dict[str, str]) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        source, target, *_rest = [part.strip() for part in line.split(";")]
        if not source or not target:
            continue
        key = "".join(chr(int(piece, 16)) for piece in source.split())
        value = "".join(chr(int(piece, 16)) for piece in target.split())
        table[key] = value


def _load() -> dict[str, str]:
    table: dict[str, str] = {}
    data = Path(__file__).with_name("data")
    _read_table(data / "confusables.txt", table)
    _read_table(data / "local-confusables.txt", table)
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
    folded = unicodedata.normalize("NFKC", text).casefold()
    table = _table()
    mapped: list[str] = []
    for char in folded:
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


def _without_marks(text: str, table: dict[str, str] | None) -> str:
    """Copy ASCII runs in one slice. Non-ASCII characters still map one by one."""
    if text.isascii():
        return text
    parts: list[str] = []
    pos = 0
    for match in re.finditer(r"[^\x00-\x7f]", text):
        if match.start() > pos:
            parts.append(text[pos : match.start()])
        char = match.group()
        if unicodedata.category(char) not in {"Mn", "Cf"}:
            parts.append(table.get(char, char) if table is not None else char)
        pos = match.end()
    if pos < len(text):
        parts.append(text[pos:])
    return "".join(parts)


def fold_confusable(text: str) -> str:
    """NFKC, drop marks and format characters, map non-ASCII confusables, casefold."""
    folded = unicodedata.normalize("NFKC", text)
    if folded.isascii():
        return folded.casefold()
    flattened = unicodedata.normalize("NFD", _without_marks(folded, _table()))
    if flattened.isascii():
        return flattened.casefold()
    return _without_marks(flattened, None).casefold()
