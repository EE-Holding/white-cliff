"""The page shows the explain output, the disclaimer, and plain failures."""

import html
import re
from pathlib import Path
from urllib.parse import urlsplit

from white_cliff.advice import advice_reason
from white_cliff.desktop_copy import (
    BUSY,
    CANNOT_EXPLAIN,
    CLOSE_INTRO,
    DISCLAIMER,
    ENTER_BOTH,
    NO_10KQ,
    NO_INTERNET,
    NO_MATCH,
    SEC_ODD,
    SEC_WHY,
    SEVERAL,
)
from white_cliff.disclaimer import ensure_safe_output
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.present import error_page, plain_report, result_page, search_page, shown_amount
from white_cliff.render import markdown_figure_ids

ROOT = Path(__file__).resolve().parents[1]
PINNED = ROOT / "pinned" / "filings"
EXACT_WHY = (
    "The SEC asks programs that download filings from sec.gov to include a name "
    "and email with each request. White Cliff keeps yours only on this computer "
    "and sends them only to sec.gov, with each request. We never see them. "
    "You can change or erase them at any time."
)
PLAIN = (
    NO_INTERNET,
    NO_MATCH,
    NO_10KQ,
    BUSY,
    CANNOT_EXPLAIN,
    ENTER_BOTH,
    SEC_ODD,
    CLOSE_INTRO,
    SEVERAL,
)


def _visible(page: str) -> str:
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", page, flags=re.I | re.S)
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return text.replace(DISCLAIMER, " ", 1)


def _figures(markdown: str) -> list[tuple[str, str]]:
    pairs = []
    for label, url, _title in markdown_figure_ids(markdown):
        if "#fact=" in url or "#calc=" in url:
            pairs.append((label, url))
    return pairs


def _page_figures(page: str) -> list[tuple[str, str]]:
    pairs = []
    for match in re.finditer(r'<a class="figure" href="([^"]*)">(.*?)</a>', page, flags=re.S):
        pairs.append((html.unescape(match.group(2)), html.unescape(match.group(1))))
    return pairs


def test_why_sentence_is_exact():
    assert SEC_WHY == EXACT_WHY


def test_failure_sentences_have_no_traceback_and_no_advice():
    for sentence in PLAIN:
        assert "Traceback" not in sentence
        assert "File \"" not in sentence
        assert advice_reason(sentence) is None


def test_pinned_explanations_match_and_keep_the_guard():
    for path in sorted(PINNED.iterdir()):
        if not path.is_dir():
            continue
        filing = load_directory(path)
        explained = explain_filing(filing)
        page = result_page(
            explained,
            form=filing.form or "10-K",
            period=filing.period_end or "",
            filed="2026-10-31",
            url=filing.url,
        )
        ensure_safe_output(page)
        assert page.find(DISCLAIMER) < page.find("font-size")
        assert "font-size: 21px" in page
        assert "font-size: 24px" in page
        assert "#1d1d1f" in page
        assert "#ffffff" in page
        assert [href for _text, href in _page_figures(page)] == [
            href for _label, href in _figures(explained.markdown)
        ]
        shown = [html.unescape(item) for item in re.findall(r"<data[^>]*>(.*?)</data>", explained.html)]
        assert [text for text, _href in _page_figures(page)] == [shown_amount(item) for item in shown]
        assert advice_reason(_visible(page), filing.text) is None
        assert "github.com" not in page
        assert "Traceback" not in page
        for href in re.findall(r'href="([^"]+)"', page):
            target = html.unescape(href)
            if target.startswith("/"):
                continue
            assert urlsplit(target).hostname in {"www.sec.gov", "data.sec.gov"}
        if filing.form in {"10-K", "10-Q"} and filing.url.startswith("https://www.sec.gov/"):
            line = plain_report(filing.form, filing.period_end or "")
            assert line in page
            assert filing.form not in page
            assert filing.url in page or html.escape(filing.url, quote=True) in page


def test_how_to_open_says_the_first_lookup_is_live():
    text = (ROOT / "docs" / "how-to-open.md").read_text(encoding="utf-8")
    source = (ROOT / "src" / "white_cliff" / "data" / "how-to-open.md").read_text(encoding="utf-8")
    assert text == source
    assert text.startswith(DISCLAIMER)
    live = "The first lookup is the first live one; the app was tested with saved filings."
    assert live in text
    rest = text.replace(live, "")
    assert re.search(r"\b(I|we|our|ours|me|my|myself)\b", rest) is None
    assert "from here" not in text


def test_error_page_is_the_sentence():
    page = error_page(CANNOT_EXPLAIN, token="abc", query="NVDA")
    ensure_safe_output(page)
    assert CANNOT_EXPLAIN in page
    assert 'class="failure"' in page
    assert 'value="NVDA"' in page
    assert 'class="next"' not in page
    assert "Traceback" not in page
    assert advice_reason(_visible(page)) is None
    fresh = search_page(token="abc")
    assert 'class="failure"' not in fresh
    assert ".submit(" not in page
    assert "requestSubmit" not in page
