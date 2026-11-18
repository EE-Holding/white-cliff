"""Ticker and name resolution, and the latest 10-K or 10-Q."""

import json
from pathlib import Path

from white_cliff.companies import (
    NoMatch,
    OneMatch,
    SeveralMatches,
    parse_tickers,
    resolve_company,
    select_latest,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "desktop"


def _companies():
    return parse_tickers((FIXTURES / "company_tickers.json").read_bytes())


def test_exact_ticker_and_lower_case():
    companies = _companies()
    for query in ("AAPL", "aapl"):
        found = resolve_company(query, companies)
        assert isinstance(found, OneMatch)
        assert found.company.ticker == "AAPL"
        assert found.company.cik == "0000320193"
        assert found.company.title == "Apple Inc."


def test_name_with_inc_and_punctuation():
    companies = _companies()
    for query in ("Apple, Inc.", "Apple Inc", "JOHNSON & JOHNSON", "Johnson and Johnson"):
        found = resolve_company(query, companies)
        assert isinstance(found, OneMatch), query
    assert resolve_company("Apple, Inc.", companies).company.ticker == "AAPL"
    assert resolve_company("Johnson and Johnson", companies).company.ticker == "JNJ"


def test_several_matches_are_the_sec_names():
    found = resolve_company("Apple", _companies())
    assert isinstance(found, SeveralMatches)
    titles = [company.title for company in found.companies]
    assert titles == ["Apple Hospitality REIT, Inc.", "Apple Inc."]


def test_no_match_and_close_matches_come_only_from_the_list():
    companies = _companies()
    none = resolve_company("zzzznomatchqq", companies)
    assert isinstance(none, NoMatch)
    assert none.close == ()
    close = resolve_company("Microsft", companies)
    assert isinstance(close, NoMatch)
    assert close.close
    for company in close.close:
        assert company in companies
    assert [company.ticker for company in close.close] == ["MSFT"]


def test_latest_periodic_skips_a_newer_8k():
    payload = json.loads((FIXTURES / "submissions_apple.json").read_text(encoding="utf-8"))
    filing = select_latest(payload, "0000320193")
    assert filing is not None
    assert filing.form == "10-K"
    assert filing.period == "2026-09-26"
    assert filing.filed == "2026-10-31"
    assert filing.accession == "0000320193-26-000026"
    assert filing.url == (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019326000026/aapl-20260926.htm"
    )


def test_company_with_only_8ks_has_no_periodic_report():
    payload = json.loads((FIXTURES / "submissions_8k.json").read_text(encoding="utf-8"))
    assert select_latest(payload, "0001000002") is None


def test_same_filing_date_keeps_the_first_listed():
    payload = {
        "filings": {
            "recent": {
                "form": ["10-Q", "10-K"],
                "filingDate": ["2026-05-01", "2026-05-01"],
                "reportDate": ["2026-03-31", "2025-12-31"],
                "accessionNumber": ["0000320193-26-000020", "0000320193-26-000010"],
                "primaryDocument": ["q.htm", "k.htm"],
            }
        }
    }
    filing = select_latest(payload, "0000320193")
    assert filing.form == "10-Q"
    assert filing.document == "q.htm"
