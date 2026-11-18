"""Digits, number words, and the absence of a free-text path."""

import re
import sys
from pathlib import Path

import pytest

from white_cliff import cli
from white_cliff.disclaimer import DISCLAIMER
from white_cliff.numbers import number_words
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.review import bare_digits, review_text
from tests.support import MINI_XML, write_filing

ROOT = Path(__file__).resolve().parents[1]

FIGURES = [
    "424242",
    "1,000",
    "99.5",
    "5%",
    "$3",
    "５",
    "①",
    "²",
    "½",
    "1e6",
    "1 000",
    "1\u200b000",
    "{fact:abc1}",
]

NUMBER_WORDS = (
    "Revenue was twelve million dollars [section:Income statement].",
    "Demand roughly doubled [section:Income statement].",
    "That is a dozen times net income [section:Income statement].",
    "The figure is XII billion [section:Income statement].",
    "The change is one hundred per cent [section:Income statement].",
    "The result is half of the prior year [section:Income statement].",
    "The scale is ten to the sixth [section:Income statement].",
    "[twelve billion USD](https://www.sec.gov/) [section:Income statement].",
    '<img src="x" onerror="alert(1)"> [section:Notes].',
    "The gain was twofold [section:Income statement].",
    "The gain was tenfold [section:Income statement].",
    "The gain was hundredfold [section:Income statement].",
    "The gain was several-fold [section:Income statement].",
    "The figure is tens of billions [section:Income statement].",
    "The figure is in the billions [section:Income statement].",
    "The figure is millions [section:Income statement].",
    "The figure was halved [section:Income statement].",
    "This is the eleventh time [section:Income statement].",
    "This is the twentieth time [section:Income statement].",
    "This is the thousandth time [section:Income statement].",
    "This is the millionth time [section:Income statement].",
    "There were a couple of items [section:Income statement].",
    "There were a score of items [section:Income statement].",
    "Revenue grew by a quarter [section:Income statement].",
    "The balance was nil [section:Income statement].",
    "Der Betrag ist zwölf Millionen [section:Income statement].",
    "Der Betrag ist zwölf Milliarden [section:Income statement].",
    "Le montant est douze millions [section:Income statement].",
    "El importe es dos mil millones [section:Income statement].",
)

_OPENINGS = (
    "This explanation covers ",
    "This filing was not retrieved from EDGAR",
    "Revenue for the ",
    "Gross profit for the ",
    "Operating income for the ",
    "Revenue from contracts with customers for the ",
    "Net income attributable to the company for the ",
    "Operating cash flow for the ",
    "The basic average share count ",
    "Common shares outstanding at the period end was",
    "The share count is tagged but White Cliff can't use it",
    "Long-term debt, including current maturities was",
    "Long-term debt, excluding current portion was",
    "Long-term debt and finance lease obligations, excluding current portion was",
    "Long-term debt and finance lease obligations, including current maturities was",
    "Long-term debt, including current maturities minus cash and cash equivalents was",
    "Long-term debt, excluding current portion minus cash and cash equivalents was",
    "Long-term debt and finance lease obligations, excluding current portion minus cash and cash equivalents was",
    "Long-term debt and finance lease obligations, including current maturities minus cash and cash equivalents was",
    "Cash and cash equivalents was",
    "The gross margin ",
    "The operating margin ",
    "The net margin ",
    "The year over year change in revenue ",
    "A price metric quoted in the filing was omitted",
    "A confidential omission is shown as filed:",
    "A personal data span was omitted from the explanation",
    "This section was omitted because it failed the ",
)


def test_every_injected_figure_is_caught(tmp_path):
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/mini.xml"
    directory = write_filing(tmp_path / "mini", "mini.xml", MINI_XML, url)
    filing = load_directory(directory)
    explained = explain_filing(filing)
    for figure in FIGURES:
        text = f"The figure is {figure} [section:Income statement]."
        assert bare_digits(text) or review_text(text, filing.store), figure
        assert figure not in explained.markdown
        assert figure not in explained.html


def test_number_words_are_refused_and_absent_from_output(tmp_path):
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/mini.xml"
    directory = write_filing(tmp_path / "mini", "mini.xml", MINI_XML, url)
    filing = load_directory(directory)
    explained = explain_filing(filing)
    rendered = explained.markdown + explained.html
    for text in NUMBER_WORDS:
        assert number_words(text) or review_text(text, filing.store), text
        assert "onerror" not in rendered.lower()
        assert "<img" not in rendered
        assert "](https://www.sec.gov/)" not in rendered
    assert number_words("Revenue for the quarter was {fact:abcdefghijklmnop}.") is False
    assert "twelve" not in rendered.lower()


def test_model_option_and_env_cannot_inject_text(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as rejected:
        cli.main(["explain", str(tmp_path), "--model-text", "buy the stock"])
    assert rejected.value.code == 2
    script = tmp_path / "stub.py"
    script.write_text('print("SHOULD_NOT_APPEAR")\n', encoding="utf-8")
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/mini.xml"
    directory = write_filing(tmp_path / "mini", "mini.xml", MINI_XML, url)
    monkeypatch.setenv("WHITE_CLIFF_MODEL_CMD", f"{sys.executable} {script}")
    filing = load_directory(directory)
    explained = explain_filing(filing)
    monkeypatch.delenv("WHITE_CLIFF_MODEL_CMD", raising=False)
    assert explained.markdown == explain_filing(filing).markdown
    assert "SHOULD_NOT_APPEAR" not in explained.markdown
    with pytest.raises(SystemExit) as helped:
        cli.main(["--help"])
    assert helped.value.code == 0
    assert "model" not in capsys.readouterr().out.lower()


def test_package_does_not_launch_a_command():
    root = ROOT / "src" / "white_cliff"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "subprocess" not in text, path
        assert "os.system" not in text, path
        assert "os.exec" not in text, path
        assert "Popen" not in text, path
    assert not (root / "model.py").exists()


def test_every_rendered_sentence_is_a_template(tmp_path):
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/mini.xml"
    directory = write_filing(tmp_path / "mini", "mini.xml", MINI_XML, url)
    explained = explain_filing(load_directory(directory))
    body = explained.markdown.replace(DISCLAIMER, " ")
    body = re.sub(r"\[Report an error\]\([^)]*\)\.?", " ", body)
    body = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", body)
    body = re.sub(r"Section: [A-Za-z ]+", " ", body)
    body = re.sub(r"Report an error:.*", " ", body, flags=re.S)
    for sentence in re.split(r"(?<=[.])\s+", body):
        sentence = " ".join(sentence.split())
        if not sentence:
            continue
        assert any(sentence.startswith(opening) for opening in _OPENINGS), sentence
