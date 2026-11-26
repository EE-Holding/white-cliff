import pytest

from white_cliff.pipeline import load_directory
from white_cliff.quotes import QuoteError, review_quotes
from tests.support import render_quote_page
from tests.support import write_filing

FILING = (
    "The company expects demand to remain steady in the next year. "
    "A second sentence stays in the filing. "
    "A third sentence is also present. "
    "A fourth sentence is also present."
)
URL = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/filing.htm"


def test_a_repeated_phrase_links_the_earlier_copy():
    phrase = "The company expects demand to remain steady in the next year."
    filing = phrase + " Extra words stay here. " + phrase
    quotes = review_quotes(f'"{phrase}"', filing, URL)
    assert quotes[0].url.endswith("#quote=0")


def test_valid_quote_links_to_sec():
    text = '"The company expects demand to remain steady in the next year."'
    quotes = review_quotes(text, FILING, URL)
    assert len(quotes) == 1
    assert quotes[0].url.startswith("https://www.sec.gov/")
    assert "quote=" in quotes[0].url


def test_quote_limits(tmp_path):
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

    body = (
        "The company expects demand to remain steady in the next year. "
        "Operations continued without interruption during the reported period. "
        "Customers renewed agreements throughout the reported period. "
        "Suppliers delivered components throughout the reported period."
    )
    html = f"<p>{body}</p>"
    directory = write_filing(tmp_path / "limits", "filing.htm", html, URL, form="8-K")
    filing = load_directory(directory)
    linked, linked_html = render_quote_page(
        '"The company expects demand to remain steady in the next year." [section:Notes].',
        filing.text,
        URL,
    )
    assert "#quote=" in linked
    assert "https://www.sec.gov/" in linked
    assert linked.count("#quote=") == 1
    assert "#quote=" in linked_html
    long_dir = write_filing(
        tmp_path / "long",
        "filing.htm",
        f"<p>{long_quote}</p>",
        URL,
        form="8-K",
    )
    refused_long, refused_html = render_quote_page(
        f'"{long_quote}" [section:Notes].',
        load_directory(long_dir).text,
        URL,
    )
    assert long_quote not in refused_long
    assert long_quote not in refused_html
    assert "quote" in refused_long
    two, _two_html = render_quote_page(
        (
            '[section:Notes] "The company expects demand to remain steady in the next year. '
            'Operations continued without interruption during the reported period." [section:Notes].'
        ),
        filing.text,
        URL,
    )
    assert "quote" in two
    assert "Operations continued without interruption during the reported period." not in two
    cited = " [section:Notes]. "
    accepted, _accepted_html = render_quote_page(
        cited.join(
            (
                '"The company expects demand to remain steady in the next year."',
                '"Operations continued without interruption during the reported period."',
                '"Customers renewed agreements throughout the reported period." [section:Notes].',
            )
        ),
        filing.text,
        URL,
    )
    assert accepted.count("#quote=") == 3
    overflow, _overflow_html = render_quote_page(
        cited.join(
            (
                '"The company expects demand to remain steady in the next year."',
                '"Operations continued without interruption during the reported period."',
                '"Customers renewed agreements throughout the reported period."',
                '"Suppliers delivered components throughout the reported period." [section:Notes].',
            )
        ),
        filing.text,
        URL,
    )
    assert "quote" in overflow
    assert "Suppliers delivered components throughout the reported period." not in overflow
    assert overflow.count("#quote=") == 0


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
    overlap = "The company expects demand to remain steady in [section:Notes]."
    explained, _html = render_quote_page(overlap, filing.text, URL)
    assert "#quote=" in explained
    assert "https://www.sec.gov/" in explained
    assert explained.count("#quote=") >= 1
    linked, _linked_html = render_quote_page(f'"{sentence}" [section:Notes].', filing.text, URL)
    assert "#quote=" in linked
    assert sentence in linked
    long_copy = (
        '"The company expects demand to remain steady in the next year [section:Notes]. '
        'Another line stays in the filing [section:Notes]."'
    )
    refused, _refused_html = render_quote_page(long_copy, filing.text, URL)
    assert "quote" in refused
    assert "A second sentence stays in the filing." not in refused


def test_rendered_quotes_fold_before_match_and_keep_the_link():
    sentence = "The company expects demand to remain steady in the next year."
    amped = "The company expects demand to remain steady in R&D programs."
    filing = f"{sentence} {amped}"
    _markdown, html = render_quote_page(f'"{amped}"', filing, URL)
    assert 'href="https://www.sec.gov/' in html
    assert "#quote=" in html
    assert "R&amp;D" in html
    cased, _cased_html = render_quote_page(f'"{sentence.upper()}"', filing, URL)
    assert "#quote=" in cased
    assert "https://www.sec.gov/" in cased
    punct = sentence.replace("steady in", "steady, in")
    _punct_md, punct_html = render_quote_page(f'"{punct}"', filing, URL)
    assert "#quote=" in punct_html
    assert "https://www.sec.gov/" in punct_html
    zwsp = sentence.replace("company", "com\u200bpany")
    _zwsp_md, zwsp_html = render_quote_page(f'"{zwsp}"', filing, URL)
    assert "#quote=" in zwsp_html
    words = ["alpha"] * 59
    words[10] = "al\u200bpha"
    long = " ".join(words) + "."
    plain = long.replace("\u200b", "")
    with pytest.raises(QuoteError):
        review_quotes(f'"{long}"', plain, URL)
    refused, refused_html = render_quote_page(f'"{long}"', plain, URL)
    assert "#quote=" not in refused
    assert "#quote=" not in refused_html
    assert "quote" in refused
    one = "'The company expects demand to remain steady in the next year.'"
    four, four_html = render_quote_page(" ".join([one] * 4), filing, URL)
    assert four.count("#quote=") == 0
    assert four_html.count("#quote=") == 0
    with pytest.raises(QuoteError):
        review_quotes(
            '"The company expects [***] demand to remain steady in the next year."',
            FILING,
            URL,
        )
