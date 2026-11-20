"""One centred column, a collapsed section note, and the print margins."""

import re
import time
from pathlib import Path

import pytest

from white_cliff.i18n import using
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.present import result_page, search_page

PINNED = Path(__file__).resolve().parents[1] / "pinned" / "filings"
NVIDIA = "0001045810-26-000075"

# The section sentences as they read today. The collapse wraps them; it does not rewrite them.
SECTION_EN = (
    "This section shows Revenue, Gross profit, Operating income, Net income attributable to the company, "
    "Gross margin: gross profit as a percent of revenue, Operating margin: operating income as a percent of revenue, "
    "Net margin: net income attributable to the company as a percent of revenue from the Income statement in "
    "NVIDIA CORP&#x27;s quarterly report for "
    '<a href="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm" '
    'target="_blank" rel="noopener">the quarter ended July\xa026,\xa02026</a>.',
    "This section shows Operating cash flow from the Cash flows in NVIDIA CORP&#x27;s quarterly report for "
    '<a href="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm" '
    'target="_blank" rel="noopener">the six months ended July\xa026,\xa02026</a>.',
    "This section shows Long-term debt, including current maturities, Cash and cash equivalents, Net debt "
    "from the Balance sheet in NVIDIA CORP&#x27;s quarterly report for "
    '<a href="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm" '
    'target="_blank" rel="noopener">the period ended July\xa026,\xa02026</a>.',
    "This section shows The basic average share count from the Equity in NVIDIA CORP&#x27;s quarterly report for "
    '<a href="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm" '
    'target="_blank" rel="noopener">the quarter ended July\xa026,\xa02026</a>.',
)
SECTION_DE = (
    "Dieser Abschnitt zeigt Umsatz, Bruttoergebnis, Betriebsergebnis, Auf das Unternehmen entfallendes "
    "Nettoergebnis, Bruttomarge: Bruttoergebnis in Prozent des Umsatzes, Operative Marge: Betriebsergebnis "
    "in Prozent des Umsatzes, Nettomarge: auf das Unternehmen entfallendes Nettoergebnis in Prozent des "
    "Umsatzes im "
    '<a href="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm" '
    'target="_blank" rel="noopener">Quartal zum 26.\xa0Juli\xa02026</a>, entnommen aus der Gewinn- und '
    "Verlustrechnung im Bericht (Quartalsbericht) von NVIDIA CORP.",
    "Dieser Abschnitt zeigt Operativer Cashflow im "
    '<a href="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm" '
    'target="_blank" rel="noopener">Sechsmonatszeitraum zum 26.\xa0Juli\xa02026</a>, entnommen aus der '
    "Kapitalflussrechnung im Bericht (Quartalsbericht) von NVIDIA CORP.",
    "Dieser Abschnitt zeigt Langfristige Finanzschulden einschließlich kurzfristig fälliger Anteile, "
    "Zahlungsmittel und Zahlungsmitteläquivalente, Langfristige Finanzschulden einschließlich kurzfristig "
    "fälliger Anteile abzüglich Zahlungsmittel und Zahlungsmitteläquivalente im "
    '<a href="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm" '
    'target="_blank" rel="noopener">Zeitraum zum 26.\xa0Juli\xa02026</a>, entnommen aus der Bilanz im '
    "Bericht (Quartalsbericht) von NVIDIA CORP.",
    "Dieser Abschnitt zeigt Durchschnittliche Anzahl der Aktien (unverwässert) im "
    '<a href="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm" '
    'target="_blank" rel="noopener">Quartal zum 26.\xa0Juli\xa02026</a>, entnommen aus der '
    "Eigenkapitalveränderungsrechnung im Bericht (Quartalsbericht) von NVIDIA CORP.",
)


def _style() -> str:
    return search_page("t").split("</style>", 1)[0]


def _page(language: str) -> str:
    filing = load_directory(PINNED / NVIDIA)
    explained = explain_filing(filing)
    with using(language):
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


def test_the_result_sheet_stays_in_the_centred_column():
    screen = _style().split("@media print", 1)[0]
    rule = screen.split("table.print-sheet {", 1)[1].split("}", 1)[0]
    assert "margin-left: auto" in rule
    assert "margin-right: auto" in rule
    assert "margin: 0" not in rule
    grid = screen.split(".grid {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: 1fr 1fr" in grid
    assert "680px" not in grid


def test_section_notes_are_collapsed_and_the_words_stay():
    for language, expected in (("en", SECTION_EN), ("de", SECTION_DE)):
        page = _page(language)
        notes = re.findall(
            r'<p\b(?P<tag>[^>]*\bdata-template="SECTION"[^>]*)>(?P<body>.*?)</p>',
            page,
            re.S,
        )
        assert [body for _tag, body in notes] == list(expected)
        for tag, _body in notes:
            assert " hidden" in f" {tag} "
            control = re.search(r'id="([^"]+)"', tag)
            assert control is not None
            button = re.search(
                rf'<button type="button" class="tap" aria-expanded="false" '
                rf'aria-controls="{re.escape(control.group(1))}">([^<]+)</button>',
                page,
            )
            assert button is not None
        if language == "en":
            assert ">Income statement</button>" in page
    rule = _style().split('p[data-template="SECTION"] {', 1)[1].split("}", 1)[0]
    assert "font-size: 18px" in rule


def test_section_headings_keep_the_strong_size_and_spacing():
    style = _style()
    heading = style.split("h2 {", 1)[1].split("}", 1)[0]
    assert "font-size: 22px" in heading
    assert "font-weight: 600" in heading
    assert "margin: 48px 0 16px" in heading
    tap = style.split("h2 button.tap {", 1)[1].split("}", 1)[0]
    assert "font-size: 22px" in tap
    assert "font-weight: 600" in tap
    group = style.split(".explain, .quality, .marker", 1)[1].split("{", 1)[0]
    assert "h2" not in group


def test_the_zero_tick_has_no_numeral():
    screen = _style().split("@media print", 1)[0]
    assert 'content: "0"' not in screen
    assert ".bar-track::after" not in screen


def test_print_has_side_margins_and_space_under_the_disclaimer():
    style = _style()
    printed = style.split("@media print", 1)[1]
    disclaimer = printed.split(".print-head .disclaimer {", 1)[1].split("}", 1)[0]
    assert "padding-bottom: 24px" in disclaimer
    sheet = printed.split("table.print-sheet.column {", 1)[1].split("}", 1)[0]
    assert "padding-left: 48px" in sheet
    assert "padding-right: 48px" in sheet


def test_the_header_search_input_is_at_least_360():
    style = _style()
    rule = style.split("body.result form.search input {", 1)[1].split("}", 1)[0]
    assert "min-width: 360px" in rule
    assert "flex: 1 0 100%" in style.split("body.result form.search {", 1)[1].split("}", 1)[0]


def test_left_edges_match_and_the_search_is_wide(tmp_path):
    from tests.test_desktop_app import _chrome_binary, _chrome_page, _eval

    binary = _chrome_binary()
    if binary is None:
        pytest.skip("chrome is not installed")
    html_path = tmp_path / "result.html"
    html_path.write_text(_page("en"), encoding="utf-8")
    chrome, stderr_file, page = _chrome_page(binary, tmp_path / "profile", tmp_path / "chrome.txt")
    try:
        page.call("Page.enable")
        page.call("Runtime.enable")
        page.call("Page.navigate", {"url": html_path.as_uri()})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            ready = _eval(page, "document.querySelector('article.card') !== null")
            if ready:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("the result page did not paint")
        expression = """(() => {
          const disclaimer = document.querySelector(".disclaimer");
          const box = disclaimer.getBoundingClientRect();
          const style = getComputedStyle(disclaimer);
          const contentLeft = box.left + parseFloat(style.paddingLeft);
          const contentRight = box.right - parseFloat(style.paddingRight);
          const range = document.createRange();
          range.selectNodeContents(disclaimer);
          const textLeft = range.getBoundingClientRect().left;
          const card = document.querySelector("article.card").getBoundingClientRect();
          const last = document.querySelectorAll("article.card")[1].getBoundingClientRect();
          const sheet = document.querySelector("table.print-sheet").getBoundingClientRect();
          const top = document.querySelector(".top").getBoundingClientRect();
          const input = document.querySelector("#query").getBoundingClientRect();
          const button = document.querySelector("body.result form.search button").getBoundingClientRect();
          const section = getComputedStyle(document.querySelector('p[data-template="SECTION"]'));
          const heading = getComputedStyle(document.querySelector("h2 button.tap"));
          return {
            contentLeft, contentRight, textLeft,
            cardLeft: card.left,
            cardRight: last.right,
            sheetLeft: sheet.left,
            disclaimerLeft: box.left,
            topLeft: top.left,
            inputWidth: input.width,
            inputTop: input.top,
            buttonTop: button.top,
            sectionSize: section.fontSize,
            headingSize: heading.fontSize,
            headingWeight: heading.fontWeight,
          };
        })()"""
        for width in (1100, 1280):
            page.call(
                "Emulation.setDeviceMetricsOverride",
                {"width": width, "height": 1400, "deviceScaleFactor": 1, "mobile": False},
            )
            measured = _eval(page, expression)
            assert abs(measured["textLeft"] - measured["contentLeft"]) <= 1
            assert abs(measured["cardLeft"] - measured["contentLeft"]) <= 1
            assert abs(measured["cardRight"] - measured["contentRight"]) <= 1
            assert abs(measured["sheetLeft"] - measured["disclaimerLeft"]) <= 1
            assert abs(measured["topLeft"] - measured["disclaimerLeft"]) <= 1
            assert measured["inputWidth"] >= 360
            assert abs(measured["inputTop"] - measured["buttonTop"]) <= 1
            assert measured["sectionSize"] == "18px"
            assert measured["headingSize"] == "22px"
            assert measured["headingWeight"] == "600"
    finally:
        page.close()
        chrome.kill()
        chrome.wait(timeout=5)
        if not stderr_file.closed:
            stderr_file.close()
