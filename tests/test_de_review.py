"""The German review file is generated from the code and lists every shown string."""

import ast
import csv
import importlib.util
import re
from pathlib import Path

from white_cliff.german import MONTHS, _SCALE
from white_cliff.lexicon import STRINGS

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "docs" / "de-review.csv"
SCRIPT = ROOT / "scripts" / "export_de_review.py"
_UMLAUT = re.compile(r"[äöüÄÖÜß]")


def _rows():
    spec = importlib.util.spec_from_file_location("export_de_review", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.review_rows()


def _on_disk():
    with EXPORT.open(encoding="utf-8-sig", newline="") as handle:
        return [tuple(row) for row in csv.reader(handle)]


def test_the_review_file_lists_every_german_string():
    assert EXPORT.is_file()
    header, *found = _on_disk()
    assert header == ("key", "english", "german", "where")
    rows = _rows()
    assert found == rows
    listed = {key: (english, german) for key, english, german, _where in found}
    for key, (english, german) in STRINGS.items():
        assert listed[key] == (english, german)
    for month in MONTHS:
        assert any(german == month for _key, _english, german, _where in found)
    for german in _SCALE.values():
        assert any(cell == german for _key, _english, cell, _where in found)


def test_a_shown_german_fragment_cannot_skip_the_export():
    covered = "\n".join(german for _key, _english, german, _where in _rows())
    for rel in ("src/white_cliff/wording.py", "src/white_cliff/present.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            text = node.value.strip()
            if not text or _UMLAUT.search(text) is None:
                continue
            assert text in covered, f"{rel}:{node.lineno}"
    present = (ROOT / "src/white_cliff/present.py").read_text(encoding="utf-8")
    assert 'segment("de", "Deutsch")' in present
    assert "Deutsch" in covered
    assert "Sprache" in covered
