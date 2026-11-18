"""Ticker and name resolution, and the latest 10-K or 10-Q."""

import json
from pathlib import Path

from white_cliff.companies import (
    NoMatch,
    OneMatch,
    SeveralMatches,
    extra_submission_names,
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


def test_latest_report_period_wins_over_a_later_filing_date():
    payload = {
        "filings": {
            "recent": {
                "form": ["10-K", "10-Q"],
                "filingDate": ["2026-11-01", "2026-08-01"],
                "reportDate": ["2025-12-31", "2026-06-30"],
                "acceptanceDateTime": [
                    "2026-11-01T12:00:00.000Z",
                    "2026-08-01T12:00:00.000Z",
                ],
                "accessionNumber": ["0000320193-26-000010", "0000320193-26-000020"],
                "primaryDocument": ["k.htm", "q.htm"],
                "isInlineXBRL": [1, 1],
            }
        }
    }
    filing = select_latest(payload, "0000320193")
    assert filing.form == "10-Q"
    assert filing.period == "2026-06-30"
    assert filing.document == "q.htm"


def test_acceptance_time_breaks_a_report_period_tie():
    payload = {
        "filings": {
            "recent": {
                "form": ["10-Q", "10-K"],
                "filingDate": ["2026-08-01", "2026-08-02"],
                "reportDate": ["2026-06-30", "2026-06-30"],
                "acceptanceDateTime": [
                    "2026-08-01T18:00:00.000Z",
                    "2026-08-02T09:00:00.000Z",
                ],
                "accessionNumber": ["0000320193-26-000020", "0000320193-26-000021"],
                "primaryDocument": ["q.htm", "k.htm"],
                "isInlineXBRL": [1, 1],
            }
        }
    }
    filing = select_latest(payload, "0000320193")
    assert filing.document == "k.htm"
    assert filing.filed == "2026-08-02"


def test_a_filing_that_is_not_inline_xbrl_is_skipped():
    payload = {
        "filings": {
            "recent": {
                "form": ["10-K", "10-Q"],
                "filingDate": ["2026-11-01", "2026-08-01"],
                "reportDate": ["2026-09-26", "2026-06-27"],
                "accessionNumber": ["0000320193-26-000026", "0000320193-26-000020"],
                "primaryDocument": ["k.htm", "q.htm"],
                "isInlineXBRL": [0, 1],
            }
        }
    }
    filing = select_latest(payload, "0000320193")
    assert filing.form == "10-Q"
    assert filing.document == "q.htm"


def test_extra_submission_page_can_hold_the_latest_period():
    payload = {
        "filings": {
            "recent": {
                "form": ["10-Q"],
                "filingDate": ["2020-05-01"],
                "reportDate": ["2020-03-28"],
                "accessionNumber": ["0000320193-20-000001"],
                "primaryDocument": ["old.htm"],
                "isInlineXBRL": [1],
            },
            "files": [
                {"name": "CIK0000320193-submissions-001.json"},
                {"name": "CIK0000000001-submissions-001.json"},
                {"name": "../other.json"},
            ],
        }
    }
    assert extra_submission_names(payload, "0000320193") == (
        "CIK0000320193-submissions-001.json",
    )
    extra = {
        "form": ["10-K"],
        "filingDate": ["2026-10-31"],
        "reportDate": ["2026-09-26"],
        "acceptanceDateTime": ["2026-10-31T10:00:00.000Z"],
        "accessionNumber": ["0000320193-26-000026"],
        "primaryDocument": ["aapl-20260926.htm"],
        "isInlineXBRL": [1],
    }
    filing = select_latest(payload, "0000320193", [extra])
    assert filing.accession == "0000320193-26-000026"
    assert filing.period == "2026-09-26"


def test_alphabet_share_classes_show_once():
    found = resolve_company("Alphabet", _companies())
    assert isinstance(found, OneMatch)
    assert found.company.cik == "0001652044"
    assert found.company.ticker == "GOOG/GOOGL"
    assert found.company.title == "Alphabet Inc."


def test_berkshire_class_b_accepts_either_spelling():
    companies = _companies()
    for query in ("BRK.B", "BRK-B", "brk.b"):
        found = resolve_company(query, companies)
        assert isinstance(found, OneMatch), query
        assert found.company.title == "BERKSHIRE HATHAWAY INC"
        assert found.company.ticker == "BRK-B"
        assert found.company.cik == "0001067983"
