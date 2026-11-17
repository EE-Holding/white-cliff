import pytest

from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.quotes import QuoteError, review_quotes
from tests.support import write_filing

FILING = (
    "The company expects demand to remain steady in the next year. "
    "A second sentence stays in the filing. "
    "A third sentence is also present. "
    "A fourth sentence is also present."
)
URL = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/filing.htm"


def test_valid_quote_links_to_sec():
    text = '"The company expects demand to remain steady in the next year."'
    quotes = review_quotes(text, FILING, URL)
    assert len(quotes) == 1
    assert quotes[0].url.startswith("https://www.sec.gov/")
    assert "quote=" in quotes[0].url


def test_quote_limits():
    long_quote = " ".join(["word"] * 51)
    with pytest.raises(QuoteError):
        review_quotes(f'"{long_quote}"', long_quote, URL)
    with pytest.raises(QuoteError):
        review_quotes('"Alpha one. Beta two."', "Alpha one. Beta two.", URL)
    three = (
        '"The company expects demand to remain steady in the next year." '
        '"A second sentence stays in the filing." '
        '"A third sentence is also present."'
    )
    assert len(review_quotes(three, FILING, URL)) == 3
    four = three + ' "A fourth sentence is also present."'
    with pytest.raises(QuoteError):
        review_quotes(four, FILING, URL)
    with pytest.raises(QuoteError):
        review_quotes('"Not in the filing at all."', FILING, URL)
    with pytest.raises(QuoteError):
        review_quotes('"The company expects demand to remain steady in the next year."', FILING, "file:///tmp/filing.htm")


def test_other_quote_marks_and_abbreviations():
    sentence = "The company expects demand to remain steady in the next year."
    for opener, closer in (("‘", "’"), ("«", "»"), ("„", "“"), ("‹", "›")):
        quotes = review_quotes(f"{opener}{sentence}{closer}", FILING, URL)
        assert len(quotes) == 1
        assert quotes[0].url.startswith("https://www.sec.gov/")
    filing = "Apple Inc. kept its U.S. stores open during the reported period."
    quotes = review_quotes(f'"{filing}"', filing, URL)
    assert len(quotes) == 1


def test_unquoted_overlap_is_a_quote_and_rendered_output_links_it(tmp_path):
    sentence = "The company expects demand to remain steady in the next year."
    html = f"<p>{sentence} A second sentence stays in the filing.</p>"
    directory = write_filing(tmp_path / "q", "filing.htm", html, URL, form="8-K")
    filing = load_directory(directory)
    copied = "The company expects demand to remain steady in the annual report."
    # Eight or more words copied from the filing, without quote marks.
    overlap = "The company expects demand to remain steady in [section:Notes]."
    explained = explain_filing(filing, model_text=overlap)
    assert "#quote=" in explained.markdown
    assert "https://www.sec.gov/" in explained.markdown
    assert explained.markdown.count("#quote=") >= 1
    linked = explain_filing(filing, model_text=f'"{sentence}" [section:Notes].')
    assert f"#quote=" in linked.markdown
    assert sentence in linked.markdown
    long_copy = (
        '"The company expects demand to remain steady in the next year [section:Notes]. '
        'Another line stays in the filing [section:Notes]."'
    )
    refused = explain_filing(filing, model_text=long_copy)
    assert "quote" in refused.markdown
    assert "A second sentence stays in the filing." not in refused.markdown
    del copied
