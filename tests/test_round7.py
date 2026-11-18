"""XBRL-only figures and the untagged-filing page."""

from white_cliff.disclaimer import DISCLAIMER
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.review import audit_rendered
from tests.support import write_filing

URL = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/plain.htm"
SENTENCE = "This filing has no tagged figures that White Cliff can explain."


def test_untagged_filing_page_is_exact(tmp_path) -> None:
    html = "<html><body><p>Total net sales were 5,000.</p></body></html>"
    directory = write_filing(tmp_path / "plain", "plain.htm", html, URL, form="8-K")
    explained = explain_filing(load_directory(directory))
    assert explained.markdown == f"{DISCLAIMER}\n\n{SENTENCE} [the filing]({URL})\n"
    assert explained.html == (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        "<title>Filing explanation</title>\n"
        "</head>\n"
        "<body>\n"
        f'<p class="disclaimer">{DISCLAIMER}</p>\n'
        f"<p>{SENTENCE} "
        f'<a href="{URL}">the filing</a></p>\n'
        "</body>\n"
        "</html>\n"
    )
    assert audit_rendered(explained.markdown) is None
    assert audit_rendered(explained.html) is None
    assert "5,000" not in explained.markdown
    assert "5,000" not in explained.html
