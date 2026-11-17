from pathlib import Path

from white_cliff.omissions import preserves_omissions
from white_cliff.pipeline import explain_filing, load_directory

ROOT = Path(__file__).resolve().parents[1]


def test_confidential_omission_is_shown_as_filed():
    filing = load_directory(ROOT / "tests" / "fixtures" / "omissions")
    explained = explain_filing(filing)
    assert "[***]" in explained.markdown
    assert "[***]" in explained.html
    assert preserves_omissions(filing.text, explained.markdown)
    assert "royalty rate is 5" not in explained.markdown
    assert "royalty rate is 10" not in explained.markdown


def test_model_does_not_fill_an_omission(tmp_path):
    from tests.support import MINI_XML, write_filing

    source = MINI_XML.replace(
        "</xbrl>",
        "<us-gaap:Revenues contextRef=\"c-year\" unitRef=\"usd\">[***]</us-gaap:Revenues></xbrl>",
    )
    # The marker is not a numeric fact. Explain a normal mini filing with a model
    # that tries to replace an omission with a number.
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/mini.xml"
    directory = write_filing(tmp_path / "mini", "mini.xml", MINI_XML, url)
    filing = load_directory(directory)
    explained = explain_filing(
        filing,
        model_text="The omitted rate is 12 [section:Notes].",
    )
    assert "12" not in explained.markdown
    assert "bare digit" in explained.markdown
    del source
