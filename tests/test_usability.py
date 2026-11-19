"""A first visit: the result stays put, and the page is readable."""

import re
from pathlib import Path

import pytest

from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.present import choices_page, result_page, shown_amount
from white_cliff.desktop_copy import SEVERAL
from tests.test_desktop_app import DOC, _Transport, _app

_ANCHOR = re.compile(r"<a\b[^>]*>", re.I)
PINNED = Path(__file__).resolve().parents[1] / "pinned" / "filings"


class _Named:
    def __init__(self, title: str, ticker: str, cik: str) -> None:
        self.title = title
        self.ticker = ticker
        self.cik = cik


@pytest.fixture(scope="module")
def nvidia_page() -> str:
    filing = load_directory(PINNED / "0001045810-26-000075")
    explained = explain_filing(filing)
    return result_page(
        explained,
        form=filing.form,
        period=filing.period_end or "",
        filed="2026-01-01",
        url=filing.url,
        company=filing.filer,
        focus=filing.focus,
        fiscal_year_end=filing.fiscal_year_end,
    )


def test_sec_links_open_beside_the_page_and_back_reloads_the_result(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path, _Transport())
    app.handle("POST", "/identity", {"name": "Example Person", "email": "person@example.com"})
    shown = app.handle("POST", "/explain", {"query": "AAPL"})
    assert shown.status == 200
    assert "$478,834 million" in shown.body
    for tag in _ANCHOR.findall(shown.body):
        if "sec.gov" not in tag:
            assert "target=" not in tag
            continue
        assert 'target="_blank"' in tag
        assert 'rel="noopener"' in tag
    assert 'history.pushState(null, "", "/result")' in shown.body
    home = app.handle("GET", "/", {})
    assert 'name="query"' in home.body
    assert "$478,834 million" not in home.body
    stray = app.handle("GET", "/favicon.ico", {})
    assert stray.status == 404
    restored = app.handle("GET", "/result", {})
    assert restored.status == 200
    assert restored.body == shown.body
    assert DOC in restored.body


def test_company_choices_are_clear_rows_with_the_closest_first():
    page = choices_page(
        SEVERAL,
        [
            _Named("Zebra Apps Inc", "ZAPP", "0000000002"),
            _Named("Aperture Inc", "APTR", "0000000003"),
            _Named("Apple Inc.", "AAPL", "0000320193"),
        ],
        "t",
        "Apple",
    )
    assert page.index("Apple Inc. AAPL") < page.index("Aperture Inc APTR")
    assert page.index("Aperture Inc APTR") < page.index("Zebra Apps Inc ZAPP")
    card = page.split('<div class="card choices">', 1)[1].split("</div>", 1)[0]
    assert SEVERAL in card
    assert "min-height: 60px" in page
    assert "border: 1px solid #c7c7cc" in page
    assert "border-radius: 12px" in page
    rule = page.split("button.choice {", 1)[1].split("}", 1)[0]
    assert "font-size: 22px" in rule
    assert "font-weight: 600" in rule
    assert 'class="choice-mark"' in page
    assert "stroke: #0a4b8f" in page or "stroke:#0a4b8f" in page


def test_each_statement_has_one_heading_and_one_id(nvidia_page):
    headings = re.findall(r"<h2[^>]*>([^<]+)</h2>", nvidia_page)
    assert headings.count("Income statement") == 1
    assert headings.count("Balance sheet") == 1
    ids = re.findall(r'id="(section-[^"]+)"', nvidia_page)
    assert ids
    assert len(ids) == len(set(ids))
    assert "<h2><button" not in nvidia_page
    assert "<h3><button" not in nvidia_page
    check = nvidia_page.split('data-check="C1"', 1)[1].split("</section>", 1)[0]
    assert 'class="explain tap"' in check
    assert 'aria-controls="formula-c1"' in check
    assert "<h3>Profit and operating cash flow</h3>" in check


def test_revenue_keeps_the_year_over_year_explain_and_margins_show_the_change(nvidia_page):
    assert ">Revenue year over year</h3>" not in nvidia_page
    revenue = nvidia_page.split(">Revenue</h3>", 1)[1].split("</article>", 1)[0]
    assert "the change in revenue from the same period a year earlier" in revenue
    gross = nvidia_page.split(">The gross margin", 1)[1].split("</article>", 1)[0]
    assert "percentage points" in gross
    assert 'class="cmp"' in gross


def test_negatives_use_a_minus_sign_and_the_zero_tick_is_labelled():
    assert shown_amount("-4767 USD millions") == "\u2212$4,767 million"
    css_page = choices_page(SEVERAL, [], "t", "")
    # The zero label is on result charts. The stylesheet is shared.
    assert 'content: "0"' in css_page
    assert ".bar-track::after" in css_page
    rule = css_page.split(".bar-track::after {", 1)[1].split("}", 1)[0]
    assert "font-size: 18px" in rule
    assert "#555559" in rule


def test_cash_flow_check_leads_with_the_period(nvidia_page):
    check = nvidia_page.split('data-check="C1"', 1)[1].split("</section>", 1)[0]
    lead = re.search(r'<p class="period">([^<]+)</p>', check)
    assert lead is not None
    assert lead.group(1).startswith("Six months ended ")
    assert check.index('class="period"') < check.index("Operating cash flow was")


def test_explain_paragraphs_are_one_size():
    page = choices_page(SEVERAL, [], "t", "")
    rule = page.split(".detail-inner p, .explain p {", 1)[1].split("}", 1)[0]
    assert "font-size: 20px" in rule
    assert "line-height: 30px" in rule
    assert "#3a3a3c" in rule
    assert "12px" in rule


def test_the_result_page_searches_from_the_top_bar(nvidia_page):
    top = nvidia_page.split('<div class="top">', 1)[1].split('<div class="column">', 1)[0]
    assert 'action="/explain"' in top
    assert "Company name or ticker" in top
    assert ">Explain<" in top
    assert "width: 360px" in nvidia_page
    assert "min-height: 48px" in nvidia_page
    below = nvidia_page.split("@media (max-width: 899px)", 1)[1]
    assert "width: 100%" in below
