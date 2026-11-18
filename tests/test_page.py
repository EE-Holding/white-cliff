"""The single page a person opens from disk."""

import json
import os
import re
import socket
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from white_cliff.advice import advice_reason
from white_cliff.disclaimer import DISCLAIMER, OutputRefused
from white_cliff.facts import format_decimal
from white_cliff.pipeline import explain_filing, load_directory

ROOT = Path(__file__).resolve().parents[1]
PINNED = ROOT / "pinned"
SAVED_LINE = (
    "This page uses saved copies of 9 filings from sec.gov, "
    "saved on November 17, 2026 and November 18, 2026. "
    "It does not look up new filings."
)
APPLE_10K = "0000320193-26-000026"
APPLE_10Q = "0000320193-26-000020"
APPLE_8K = "0000320193-26-000024"
ALPHABET = "0001652044-26-000084"
_FIGURE = re.compile(
    r'<data data-kind="(?P<kind>fact|calc)" data-id="(?P<id>[^"]+)">(?P<label>[^<]*)</data>\s*'
    r'<a class="source-chip" data-id="(?P=id)" href="(?P<href>[^"]+)">'
)
_PAGE_FIGURE = re.compile(
    r'<a class="figure" data-kind="(?P<kind>fact|calc)" data-id="(?P<id>[^"]+)" '
    r'href="(?P<href>[^"]+)">(?P<label>[^<]*)</a>'
)
_FORBIDDEN = (
    "XMLHttpRequest",
    "sendBeacon",
    "WebSocket",
    "<script src",
    "<link href",
    "<img src",
    "@import",
    "url(",
    "localStorage",
    "sessionStorage",
    "document.cookie",
)


def _save_days() -> set[str]:
    manifest = json.loads((PINNED / "manifest.json").read_text(encoding="utf-8"))
    days: set[str] = set()
    for entry in manifest["filings"]:
        provenance = json.loads(
            (PINNED / "filings" / entry["accession"] / "provenance.json").read_text(encoding="utf-8")
        )
        for item in provenance["files"]:
            days.add(str(item["retrieved_at"])[:10])
    return days


def _figure_filings() -> list[str]:
    manifest = json.loads((PINNED / "manifest.json").read_text(encoding="utf-8"))
    found = []
    for entry in manifest["filings"]:
        expected = json.loads(
            (PINNED / "filings" / entry["accession"] / "expected.json").read_text(encoding="utf-8")
        )
        if expected["facts"]:
            found.append(entry["accession"])
    return found


@pytest.fixture(scope="module")
def page_text(tmp_path_factory):
    from white_cliff import cli

    saved_agent = os.environ.pop("WHITE_CLIFF_USER_AGENT", None)
    original_connect = socket.socket.connect
    original_create = socket.create_connection

    def fail(*_args, **_kwargs):
        raise AssertionError("socket connection")

    socket.socket.connect = fail
    socket.create_connection = fail
    dest = tmp_path_factory.mktemp("page") / "white-cliff.html"
    try:
        code = cli.main(["page", "--out", str(dest), "--pinned", str(PINNED)])
    finally:
        socket.socket.connect = original_connect
        socket.create_connection = original_create
        if saved_agent is not None:
            os.environ["WHITE_CLIFF_USER_AGENT"] = saved_agent
    assert code == 0
    assert dest.is_file()
    return dest.read_text(encoding="utf-8")


def test_matching_is_forgiving_and_does_not_guess():
    from white_cliff.page import Company, match_query, normalize

    assert normalize("Apple, Inc.") == "apple"
    assert normalize("COCA COLA CO") == "coca cola"
    assert normalize("coca-cola") == "coca cola"
    assert normalize("JOHNSON & JOHNSON") == "johnson johnson"
    assert normalize("MICROSOFT CORPORATION") == "microsoft"
    assert normalize("BRK.B") == "brk b"
    assert normalize("  aapl ") == "aapl"

    companies = (
        Company("Apple Inc.", ("aapl", "apple"), APPLE_10K),
        Company("COCA COLA CO", ("coca cola", "ko"), "0001628280-26-010047"),
        Company("Johnson & Johnson", ("jnj", "johnson johnson"), "0000200406-26-000016"),
    )
    assert match_query("AAPL", companies).filing == APPLE_10K
    assert match_query("aapl", companies).filing == APPLE_10K
    assert match_query("Apple, Inc.", companies).filing == APPLE_10K
    assert match_query("coca-cola", companies).filing == "0001628280-26-010047"
    assert match_query("JOHNSON & JOHNSON", companies).name == "Johnson & Johnson"
    assert match_query("no such company", companies) is None
    assert match_query("", companies) is None
    assert match_query("app", companies) is None
    tied = (
        Company("One Inc.", ("one", "aaa"), "0000000001-26-000001"),
        Company("Two Inc.", ("one", "bbb"), "0000000002-26-000001"),
    )
    assert match_query("one", tied) is None
    assert match_query("aaa", tied).name == "One Inc."


def test_cover_comes_from_the_filing_and_refuses_a_gap():
    from white_cliff.page import CoverError, read_cover

    apple = (PINNED / "filings" / APPLE_10K / "aapl-20260926.htm").read_text(encoding="utf-8")
    cover = read_cover(apple)
    assert cover.name == "Apple Inc."
    assert "AAPL" in cover.symbols

    exxon = (PINNED / "filings" / "0000034088-26-000045" / "xom-20251231.htm").read_text(
        encoding="utf-8"
    )
    exxon_cover = read_cover(exxon)
    assert exxon_cover.name == "Exxon Mobil Corporation"
    assert "XOM" in exxon_cover.symbols

    named = (
        '<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body>'
        '<ix:nonNumeric name="dei:EntityRegistrantName">Example Co</ix:nonNumeric>'
        "</body></html>"
    )
    with pytest.raises(CoverError):
        read_cover(named)
    ticked = (
        '<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body>'
        '<ix:nonNumeric name="dei:TradingSymbol">EX</ix:nonNumeric>'
        "</body></html>"
    )
    with pytest.raises(CoverError):
        read_cover(ticked)


def test_saved_line_uses_the_provenance_count_and_dates(page_text):
    manifest = json.loads((PINNED / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["filings"]) == 9
    assert _save_days() == {"2026-11-17", "2026-11-18"}
    assert page_text.find(DISCLAIMER) < page_text.find(SAVED_LINE)
    assert SAVED_LINE in page_text
    assert page_text.find(SAVED_LINE) < page_text.find('id="company"')


def test_page_lists_every_saved_filing_that_has_figures(page_text):
    accessions = _figure_filings()
    assert APPLE_8K not in accessions
    assert APPLE_10K in accessions
    assert APPLE_10Q in accessions
    sections = re.findall(r'<section\b[^>]*data-accession="([^"]+)"', page_text)
    assert sections == accessions
    assert "Company name or ticker" in page_text
    assert ">Explain</button>" in page_text
    data = json.loads(
        re.search(
            r'<script type="application/json" id="saved-companies">(.*?)</script>',
            page_text,
            re.S,
        ).group(1)
    )
    apple = next(item for item in data if "aapl" in item["keys"])
    assert apple["filing"] == APPLE_10K
    assert "apple" in apple["keys"]
    alphabet = next(item for item in data if "googl" in item["keys"])
    assert alphabet["filing"] == ALPHABET
    assert "goog" in alphabet["keys"]
    assert "googl" in alphabet["keys"]
    buttons = re.findall(r'<button type="button" data-filing="([^"]+)">', page_text)
    assert APPLE_10K in buttons
    assert APPLE_10Q not in buttons
    assert len(buttons) == len(data)


def test_embedded_keys_agree_with_the_python_matcher(page_text):
    from white_cliff.page import SUFFIXES, companies_for, normalize

    data = json.loads(
        re.search(
            r'<script type="application/json" id="saved-companies">(.*?)</script>',
            page_text,
            re.S,
        ).group(1)
    )
    fresh = [
        {"name": company.name, "keys": list(company.keys), "filing": company.filing}
        for company in companies_for(PINNED)
    ]
    assert data == fresh
    for item in data:
        for key in item["keys"]:
            assert key == normalize(key)
    script = re.search(r"<script>\n(.*?)\n</script>", page_text, re.S).group(1)
    for suffix in SUFFIXES:
        assert f'"{suffix}":1' in script
    assert "fetch" not in script
    assert "node" not in script.split()


def test_figures_match_the_explain_output_and_expected_json(page_text):
    for accession in _figure_filings():
        directory = PINNED / "filings" / accession
        expected = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
        filing = load_directory(directory)
        explained = explain_filing(filing)
        explain_figures = {
            (match.group("kind"), match.group("id"), match.group("href"), match.group("label"))
            for match in _FIGURE.finditer(explained.html)
        }
        assert explain_figures
        section = re.search(
            rf'<section\b[^>]*data-accession="{re.escape(accession)}"[^>]*>.*?</section>',
            page_text,
            re.S,
        )
        assert section is not None
        page_figures = {
            (match.group("kind"), match.group("id"), match.group("href"), match.group("label"))
            for match in _PAGE_FIGURE.finditer(section.group(0))
        }
        assert page_figures == explain_figures
        shown_facts = []
        for kind, identifier, href, label in page_figures:
            assert href.startswith("https://www.sec.gov/")
            if kind != "fact":
                continue
            fact = filing.store.get(identifier)
            assert label.startswith(format_decimal(fact.value) + " ")
            shown_facts.append((fact, href, label))
            fragment = urlsplit(href.replace("&amp;", "&")).fragment
            assert fragment.startswith(f"fact={identifier}")
        assert shown_facts
        for fact, _href, label in shown_facts:
            matched = False
            for item in expected["facts"]:
                if Decimal(item["value"]) != fact.value or item["unit"] != fact.unit:
                    continue
                if item.get("match") == "table":
                    matched = item["row"].lower() in fact.label.lower()
                else:
                    matched = (
                        fact.concept == item["concept"]
                        and fact.period.kind == item["kind"]
                        and fact.period.end == item["end"]
                        and (item["start"] is None or fact.period.start == item["start"])
                    )
                if matched:
                    break
            assert matched, (accession, fact.concept, label)
            assert str(fact.value) in label or format(fact.value, "f") in label
        first_figure = page_text.find('<a class="figure"')
        assert page_text.find(DISCLAIMER) < first_figure


def test_page_makes_no_network_request(page_text):
    lowered = page_text.lower()
    for token in _FORBIDDEN:
        assert token.lower() not in lowered
    assert re.search(r"\bfetch\b", page_text) is None
    for href in re.findall(r'href="([^"]*)"', page_text):
        assert href.startswith("https://www.sec.gov/"), href
    for url in re.findall(r"https?://[^\s\"'<>]+", page_text):
        assert url.startswith("https://www.sec.gov/"), url
    assert "src=" not in lowered
    style = re.search(r"<style>(.*?)</style>", page_text, re.S).group(1)
    assert "font-size: 20px" in style
    assert "font-size: 32px" in style
    assert "text-decoration: underline" in style
    assert "width: 100%" in style
    assert "max-width: 40rem" in style


def test_page_text_passes_the_advice_guard(page_text):
    prose = re.sub(r"<script\b[^>]*>.*?</script>", " ", page_text, flags=re.S | re.I)
    prose = re.sub(r"<style\b[^>]*>.*?</style>", " ", prose, flags=re.S | re.I)
    prose = prose.replace(DISCLAIMER, " ", 1)
    prose = re.sub(r"<[^>]+>", " ", prose)
    assert advice_reason(prose) is None
    assert "No saved filing matches that." in page_text


def test_a_missing_cover_writes_nothing(tmp_path, monkeypatch):
    from white_cliff.page import CoverError, build_page

    def refuse(_text: str):
        raise CoverError("The filing does not state a ticker.")

    monkeypatch.setattr("white_cliff.page.read_cover", refuse)
    dest = tmp_path / "white-cliff.html"
    with pytest.raises(OutputRefused):
        build_page(dest, PINNED)
    assert not dest.exists()
