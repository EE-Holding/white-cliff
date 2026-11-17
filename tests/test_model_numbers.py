import sys

from white_cliff.model import model_prompt, model_text_from_env
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.review import bare_digits, review_text
from tests.support import MINI_XML, write_filing

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


def test_every_model_figure_is_caught(tmp_path):
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/mini.xml"
    directory = write_filing(tmp_path / "mini", "mini.xml", MINI_XML, url)
    filing = load_directory(directory)
    for figure in FIGURES:
        text = f"The figure is {figure} [section:Income statement]."
        assert bare_digits(text) or review_text(text, filing.store), figure
        explained = explain_filing(filing, model_text=text)
        assert "bare digit" in explained.markdown or "placeholder" in explained.markdown
        if figure.isascii() and any(char.isdigit() for char in figure):
            assert figure not in explained.markdown
            assert figure not in explained.html


def test_model_command_gets_no_values_and_digits_are_dropped(tmp_path, monkeypatch):
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/mini.xml"
    directory = write_filing(tmp_path / "mini", "mini.xml", MINI_XML, url)
    filing = load_directory(directory)
    prompt = model_prompt(filing)
    for value in ("5000", "4000", "800", "300", "100", "50"):
        assert value not in prompt
    script = tmp_path / "model.py"
    script.write_text(
        'print("Revenue was 424242 [section:Income statement].")\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("WHITE_CLIFF_MODEL_CMD", f"{sys.executable} {script}")
    text = model_text_from_env(filing)
    explained = explain_filing(filing, model_text=text)
    assert "424242" not in explained.markdown
