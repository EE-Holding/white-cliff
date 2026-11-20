"""Classification rules for the full-index harness. The harness itself is not a test."""

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

from white_cliff.disclaimer import DISCLAIMER

ROOT = Path(__file__).resolve().parents[1]


def _harness():
    path = ROOT / "scripts" / "full_index.py"
    spec = importlib.util.spec_from_file_location("full_index_harness", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_constituent_file_is_pinned_to_a_public_source():
    path = ROOT / "pinned" / "sp500-constituents.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["source_url"] == "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    assert document["revision_url"].startswith("https://en.wikipedia.org/w/index.php?title=List_of_S%26P_500_companies&oldid=")
    assert document["retrieved"] == "2026-11-20"
    rows = document["constituents"]
    assert len(rows) == 503
    assert len({row["ticker"] for row in rows}) == 503
    assert len({row["cik"] for row in rows}) == 500
    for row in rows:
        assert row["ticker"]
        assert row["security"]
        assert len(row["cik"]) == 10 and row["cik"].isdigit()
    assert "@" not in path.read_text(encoding="utf-8")


def test_an_equal_absolute_value_matches():
    harness = _harness()
    verdict = harness.classify_value(
        absolute=Decimal("478834000000"),
        decimals=-6,
        same=[Decimal("478834000000")],
        others=[],
    )
    assert verdict.label == "MATCH"
    assert verdict.xbrl_value == "478834000000"


def test_a_scale_factor_is_a_review_and_not_a_match():
    harness = _harness()
    verdict = harness.classify_value(
        absolute=Decimal("478834"),
        decimals=-6,
        same=[Decimal("478834000000")],
        others=[],
    )
    assert verdict.label == "REVIEW"
    assert verdict.reason == "scaling"
    assert verdict.xbrl_value == "478834000000"


def test_a_different_value_is_wrong():
    harness = _harness()
    verdict = harness.classify_value(
        absolute=Decimal("10"),
        decimals=0,
        same=[Decimal("12")],
        others=[],
    )
    assert verdict.label == "WRONG"
    assert verdict.xbrl_value == "12"


def test_a_missing_accession_row_is_not_comparable():
    harness = _harness()
    verdict = harness.classify_value(
        absolute=Decimal("10"),
        decimals=0,
        same=[],
        others=[Decimal("10")],
    )
    assert verdict.label == "NOT_COMPARABLE"
    assert verdict.xbrl_value == ""


def test_a_value_that_matches_another_accession_is_a_restatement_review():
    harness = _harness()
    verdict = harness.classify_value(
        absolute=Decimal("100"),
        decimals=0,
        same=[Decimal("110")],
        others=[Decimal("100")],
    )
    assert verdict.label == "REVIEW"
    assert verdict.reason == "restatement"
    assert verdict.xbrl_value == "110"


def test_rounding_within_the_stated_decimals_matches():
    harness = _harness()
    verdict = harness.classify_value(
        absolute=Decimal("1000000"),
        decimals=-6,
        same=[Decimal("1200000")],
        others=[],
    )
    assert verdict.label == "MATCH"


def test_rounding_past_the_stated_decimals_is_wrong():
    harness = _harness()
    verdict = harness.classify_value(
        absolute=Decimal("1000000"),
        decimals=-6,
        same=[Decimal("1600000")],
        others=[],
    )
    assert verdict.label == "WRONG"


def test_summary_opens_with_the_disclaimer_and_lists_wrong_rows():
    harness = _harness()
    text = harness.render_summary(
        {
            "filings_in_scope": 28,
            "filings_covered": 2,
            "filings_explained": 1,
            "filings_refused": 1,
            "filings_not_retrieved": 0,
            "match": 4,
            "wrong": 1,
            "not_comparable": 3,
            "review": 2,
            "wrong_rows": [
                {
                    "ticker": "AAPL",
                    "accession": "0000320193-26-000026",
                    "concept": "Revenues",
                    "period": "2025-09-28/2026-09-26",
                    "shown": "1 USD",
                    "xbrl": "2",
                }
            ],
        }
    )
    assert text.startswith(DISCLAIMER)
    assert "parse_inline" in text
    assert "does not count as proof" in text
    assert "This filing can't be explained yet." in text
    assert "Dieser Bericht kann noch nicht erklärt werden." in text
    assert "AAPL" in text
    assert "0000320193-26-000026" in text
    assert "@" not in text
