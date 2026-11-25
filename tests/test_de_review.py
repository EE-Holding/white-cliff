"""The German review file is generated from the code and lists every shown string."""

import ast
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


def test_the_review_file_lists_every_german_string():
    assert not EXPORT.is_file()
    found = _rows()
    listed = {key: (english, phrase) for key, english, phrase, _where in found}
    for key, (english, phrase) in STRINGS.items():
        assert listed[key] == (english, phrase)
    for month in MONTHS:
        assert any(phrase == month for _key, _english, phrase, _where in found)
    for phrase in _SCALE.values():
        assert any(cell == phrase for _key, _english, cell, _where in found)


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
