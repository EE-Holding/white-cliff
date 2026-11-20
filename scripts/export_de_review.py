"""Write docs/de-review.csv from the German strings the program shows.

The file is for a native reviewer. This script does not rewrite any German.
"""

from __future__ import annotations

import ast
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "docs" / "de-review.csv"
_UMLAUT = re.compile(r"[äöüÄÖÜß]")
_MONTHS_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
# German assembled beside its English in code, not stored under a string id.
_ENGLISH_FOR = {
    "Der Wert blieb unverändert gegenüber": "It was unchanged from",
}


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _where(key: str, files: list[tuple[str, str]]) -> str:
    hits = [
        rel
        for rel, text in files
        if not rel.endswith("/lexicon.py") and (f"'{key}'" in text or f'"{key}"' in text)
    ]
    return "; ".join(hits or ["src/white_cliff/lexicon.py"])


def _fragments(covered: str) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    for rel in ("src/white_cliff/wording.py", "src/white_cliff/present.py"):
        tree = ast.parse(_read(rel))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            text = node.value.strip()
            if not text or _UMLAUT.search(text) is None or text in covered:
                continue
            rows.append(
                (
                    f"{rel}:{node.lineno}",
                    _ENGLISH_FOR.get(text, ""),
                    node.value if node.value == text else text,
                    f"{rel}:{node.lineno}",
                )
            )
            covered += "\n" + text
    return rows


def review_rows() -> list[tuple[str, str, str, str]]:
    """key, English source, German text, where it appears."""
    sys.path.insert(0, str(ROOT / "src"))
    from white_cliff.german import MONTHS, _SCALE
    from white_cliff.lexicon import STRINGS

    files = [
        (path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted((ROOT / "src").rglob("*.py"))
    ]
    rows = []
    for key, (english, german) in STRINGS.items():
        where = _where(key, files)
        shown = [
            rel
            for rel, text in files
            if not rel.endswith("/lexicon.py")
            and german
            and (f'"{german}"' in text or f"'{german}'" in text)
            and rel not in where
        ]
        if shown:
            where = "; ".join([where, *shown]) if where else "; ".join(shown)
        rows.append((key, english, german, where))
    where_format = "src/white_cliff/german.py"
    for index, german in enumerate(MONTHS):
        rows.append((f"DE.month.{index + 1:02d}", _MONTHS_EN[index], german, where_format))
    for english, german in _SCALE.items():
        rows.append((f"DE.scale.{english}", english, german, where_format))
    german_py = _read("src/white_cliff/german.py")
    for key, english, german in (
        ("DE.unit.percent", "percent", "Prozent"),
        ("DE.unit.percentage_points", "percentage points", "Prozentpunkte"),
        ("DE.unit.per_share", "per share", "je Aktie"),
        ("DE.unit.shares", "shares", "Aktien"),
    ):
        if f'"{german}"' not in german_py:
            raise RuntimeError(f"{german} is not a shown unit word")
        rows.append((key, english, german, where_format))
    covered = "\n".join(german for _key, _english, german, _where in rows)
    rows.extend(_fragments(covered))
    return rows


def write_export(path: Path = EXPORT) -> int:
    rows = review_rows()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("key", "english", "german", "where"))
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    count = write_export()
    print(f"{EXPORT.relative_to(ROOT)} {count}")


if __name__ == "__main__":
    main()
