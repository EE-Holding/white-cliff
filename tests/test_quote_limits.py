import pytest

from white_cliff.quotes import QuoteError, review_quotes

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
