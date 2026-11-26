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


def test_ticker_filter_keeps_a_shared_class_and_honors_the_limit():
    harness = _harness()
    pending = [
        {"ticker": "MMM", "accession": "1"},
        {"ticker": "GOOGL,GOOG", "accession": "2"},
        {"ticker": "AAPL", "accession": "3"},
        {"ticker": "AAPL", "accession": "4"},
    ]
    chosen = harness.select_pending(pending, ["aapl", "GOOG"], 2)
    assert [item["accession"] for item in chosen] == ["2", "3"]


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


def test_company_facts_keep_the_digits_from_the_response():
    harness = _harness()
    raw = (
        '{"facts":{"us-gaap":{"Revenues":{"units":{"USD":[{'
        '"val":1234567890123456789.25,"accn":"0000000000-20-000001",'
        '"start":"2020-01-01","end":"2020-12-31"}]}}}}}'
    )
    index = harness._facts_index(harness.facts_payload(raw))
    rows = index[("Revenues", "USD", "2020-01-01", "2020-12-31")]
    assert rows == [("0000000000-20-000001", Decimal("1234567890123456789.25"))]


def test_an_exact_figure_matches_only_the_same_digits():
    harness = _harness()
    same = harness.classify_value(
        absolute=Decimal("221460382"),
        decimals=10**6,
        same=[Decimal("221460382")],
        others=[],
    )
    assert same.label == "MATCH"
    different = harness.classify_value(
        absolute=Decimal("221460382"),
        decimals=10**6,
        same=[Decimal("221460383")],
        others=[],
    )
    assert different.label == "WRONG"


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
    assert "AAPL" in text
    assert "0000320193-26-000026" in text
    assert "Filings errored: 0" in text
    assert "Percents with both inputs: 0" in text
    assert "Percents removed: 0" in text
    assert "Percents linked to one input: 0" in text
    assert "Percent recomputes that disagree: 0" in text
    assert "@" not in text


def test_the_harness_checks_both_inputs_of_every_percent():
    harness = _harness()
    full = (
        '<p>It rose <a class="pct" href="#pct-abc">10.0 percent</a> from the prior quarter.</p>'
        '<p class="pct-note" id="pct-abc">It is calculated as the change from '
        "April 26, 2026 to July 26, 2026, divided by the April 26, 2026 figure, using "
        'Revenue of <a href="https://www.sec.gov/Archives/edgar/data/1/a.htm">110 USD</a> '
        "for July 26, 2026 and Revenue of "
        '<a href="https://www.sec.gov/Archives/edgar/data/1/b.htm">100 USD</a> '
        "for April 26, 2026.</p>"
    )
    assert harness.check_percent_notes(full) == {"noted": 1, "single": 0}
    lone = 'It rose <a class="pct" href="https://www.sec.gov/Archives/edgar/data/1/a.htm">10.0 percent</a>'
    assert harness.check_percent_notes(lone) == {"noted": 0, "single": 1}
    one_link = (
        '<a class="pct" href="#pct-one">10.0 percent</a>'
        '<p class="pct-note" id="pct-one">It is calculated as the change from '
        "April 26, 2026 to July 26, 2026, divided by the April 26, 2026 figure, using "
        'Revenue of <a href="https://www.sec.gov/Archives/edgar/data/1/a.htm">110 USD</a> '
        "for July 26, 2026 and Revenue of 100 USD for April 26, 2026.</p>"
    )
    assert harness.check_percent_notes(one_link)["single"] == 1
    amounts_only = (
        '<a class="pct" href="#pct-bare">10.0 percent</a>'
        '<p class="pct-note" id="pct-bare">'
        '<a href="https://www.sec.gov/Archives/edgar/data/1/a.htm">$110 million</a>'
        '<a href="https://www.sec.gov/Archives/edgar/data/1/b.htm">$100 million</a>'
        "</p>"
    )
    assert harness.check_percent_notes(amounts_only) == {"noted": 0, "single": 1}
    no_label = (
        '<a class="pct" href="#pct-nolabel">10.0 percent</a>'
        '<p class="pct-note" id="pct-nolabel">It is calculated as the change from '
        "April 26, 2026 to July 26, 2026, divided by the April 26, 2026 figure, using "
        'of <a href="https://www.sec.gov/Archives/edgar/data/1/a.htm">$110 million</a> '
        "for July 26, 2026 and of "
        '<a href="https://www.sec.gov/Archives/edgar/data/1/b.htm">$100 million</a> '
        "for April 26, 2026.</p>"
    )
    assert harness.check_percent_notes(no_label) == {"noted": 0, "single": 1}


def test_a_percent_that_does_not_recompute_from_its_linked_inputs_is_wrong():
    harness = _harness()
    bad = (
        '<p>It rose <a class="pct" href="#pct-bad">10.0 percent</a>.</p>'
        '<p class="pct-note" id="pct-bad">It is calculated as the change from '
        "April 26, 2026 to July 26, 2026, divided by the April 26, 2026 figure, using "
        'Revenue of <a href="https://www.sec.gov/Archives/edgar/data/1/a.htm">200 USD</a> '
        "for July 26, 2026 and Revenue of "
        '<a href="https://www.sec.gov/Archives/edgar/data/1/b.htm">100 USD</a> '
        "for April 26, 2026.</p>"
    )
    rows = harness.percent_mismatches(bad)
    assert len(rows) == 1
    assert rows[0]["shown"] == "10.0 percent"
    assert rows[0]["recomputed"] == "100.0"
    fell = (
        '<p>It fell <a class="pct" href="#pct-fell">50.0 percent</a>.</p>'
        '<p class="pct-note" id="pct-fell">It is calculated as the change from '
        "April 26, 2026 to July 26, 2026, divided by the April 26, 2026 figure, using "
        'Revenue of <a href="https://www.sec.gov/Archives/edgar/data/1/a.htm">100 USD</a> '
        "for July 26, 2026 and Revenue of "
        '<a href="https://www.sec.gov/Archives/edgar/data/1/b.htm">200 USD</a> '
        "for April 26, 2026.</p>"
    )
    assert harness.percent_mismatches(fell) == []
