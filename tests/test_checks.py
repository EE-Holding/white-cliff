"""Quality-check outcomes on constructed facts, including the threshold edge."""

from decimal import Decimal
from pathlib import Path

import pytest

from tests.support import make_fact
from white_cliff.checks import (
    check_cash_flow,
    check_dilution,
    check_inventory,
    check_items,
    check_receivables,
    run_checks,
)
from white_cliff.disclaimer import DISCLAIMER, OutputRefused
from white_cliff.facts import Fact
from white_cliff.pipeline import load_directory
from white_cliff.present import _shell
from white_cliff.wording import FRAME, page_terms, quality_html

SEC = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/fixture.xml"


def _pair(concept: str, role: str, now: str, then: str, *, kind: str = "duration", unit: str = "USD"):
    if kind == "duration":
        current = make_fact(
            now,
            concept=concept,
            role=role,
            unit=unit,
            start="2025-01-01",
            end="2025-12-31",
            fact_id="fact" + concept.lower()[:8].ljust(8, "a") + "now",
        )
        prior = make_fact(
            then,
            concept=concept,
            role=role,
            unit=unit,
            start="2024-01-01",
            end="2024-12-31",
            fact_id="fact" + concept.lower()[:8].ljust(8, "a") + "old",
        )
        return current, prior
    current = make_fact(
        now,
        concept=concept,
        role=role,
        unit=unit,
        kind="instant",
        start=None,
        end="2025-12-31",
        fact_id="fact" + concept.lower()[:8].ljust(8, "b") + "now",
    )
    prior = make_fact(
        then,
        concept=concept,
        role=role,
        unit=unit,
        kind="instant",
        start=None,
        end="2024-12-31",
        fact_id="fact" + concept.lower()[:8].ljust(8, "b") + "old",
    )
    return current, prior


def test_cash_flow_below_0_80_is_unusual_and_exactly_0_80_is_consistent():
    unusual_now, unusual_then = _pair("NetIncomeLoss", "net_income", "100", "100")
    cash_now, cash_then = _pair(
        "NetCashProvidedByUsedInOperatingActivities",
        "operating_cash_flow",
        "79",
        "80",
    )
    result = check_cash_flow(
        [unusual_now, unusual_then, cash_now, cash_then],
        form="10-K",
        period_end="2025-12-31",
    )
    assert result.outcome == "unusual"
    edge_cash, edge_prior = _pair(
        "NetCashProvidedByUsedInOperatingActivities",
        "operating_cash_flow",
        "80",
        "80",
    )
    # New ids so the two cash facts do not collide with the ones above.
    edge_cash = Fact(
        id="factcashconversionedgeaa",
        concept=edge_cash.concept,
        label=edge_cash.label,
        value=Decimal("80"),
        unit=edge_cash.unit,
        period=edge_cash.period,
        source=edge_cash.source,
        role=edge_cash.role,
        origin=edge_cash.origin,
    )
    consistent = check_cash_flow(
        [unusual_now, unusual_then, edge_cash, edge_prior],
        form="10-K",
        period_end="2025-12-31",
    )
    assert consistent.outcome == "consistent"
    assert consistent.numbers["ratio"] == Decimal("0.8")


def test_a_missing_input_is_not_run_and_a_quarterly_receivables_check_needs_the_annual_report():
    income, prior = _pair("NetIncomeLoss", "net_income", "100", "100")
    missing = check_cash_flow([income, prior], form="10-K", period_end="2025-12-31")
    assert missing.outcome == "not_run"
    assert missing.reason == "Operating cash flow is not in the filing."
    quarter = check_receivables([income], form="10-Q", period_end="2025-06-30")
    assert quarter.outcome == "not_run"
    assert quarter.reason == "Needs the annual report."


def test_check_sentences_carry_a_template_and_link_filing_numbers():
    income, prior = _pair("NetIncomeLoss", "net_income", "100", "80")
    cash, cash_prior = _pair(
        "NetCashProvidedByUsedInOperatingActivities",
        "operating_cash_flow",
        "50",
        "70",
    )
    page = quality_html(
        [income, prior, cash, cash_prior],
        form="10-K",
        period_end="2025-12-31",
    )
    assert "Check: marked" in page
    assert "Check: unusual" not in page
    assert "Check: consistent" not in page
    quarterly = quality_html(
        [income, prior, cash, cash_prior],
        form="10-Q",
        period_end="2025-12-31",
    )
    assert "Check: not run: Needs the annual report." in quarterly
    assert 'data-template="NUMBERS"' in page
    assert 'data-template="THRESHOLD"' in page
    assert 'data-template="LIMIT"' in page
    assert "https://www.sec.gov/" in page
    assert "below 0.80 times" in page
    assert SEC.split("/Archives/")[0] in page
    results = run_checks([income, prior, cash, cash_prior], form="10-K", period_end="2025-12-31")
    assert [item.check_id for item in results] == ["C1", "C2", "C3", "C4", "C6", "C7", "C8"]


def _shares(concept: str, value: str, start: str, end: str):
    return make_fact(
        value,
        concept=concept,
        role="shares",
        unit="shares",
        start=start,
        end=end,
        fact_id="s" + concept[-8:].lower() + value + end[:4],
    )


def test_pinned_nvidia_share_count_check_runs():
    filing = load_directory(Path(__file__).resolve().parents[1] / "pinned/filings/0001045810-26-000075")
    result = check_dilution(filing.store.facts(), form=filing.form, period_end=filing.period_end or "")
    assert result.outcome in {"unusual", "consistent"}
    assert result.reason == ""
    assert "growth" in result.numbers
    page = quality_html(filing.store.facts(), form=filing.form, period_end=filing.period_end)
    section = page.split('data-check="C6"', 1)[1].split("</section>", 1)[0]
    assert "The figures are not in US dollars." not in section
    assert "Check: not run" not in section


def test_a_missing_current_diluted_count_and_a_zero_basic_count_name_themselves():
    earlier = _shares(
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "100",
        "2024-01-01",
        "2024-12-31",
    )
    missing = check_dilution([earlier], form="10-K", period_end="2025-12-31")
    assert missing.outcome == "not_run"
    assert missing.reason == "Diluted shares is not in the filing."
    diluted_now = _shares(
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "100",
        "2025-01-01",
        "2025-12-31",
    )
    diluted_then = _shares(
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "90",
        "2024-01-01",
        "2024-12-31",
    )
    basic_now = _shares("WeightedAverageNumberOfSharesOutstandingBasic", "0", "2025-01-01", "2025-12-31")
    basic_then = _shares("WeightedAverageNumberOfSharesOutstandingBasic", "80", "2024-01-01", "2024-12-31")
    zero_basic = check_dilution(
        [diluted_now, diluted_then, basic_now, basic_then],
        form="10-K",
        period_end="2025-12-31",
    )
    assert zero_basic.outcome == "not_run"
    assert zero_basic.reason == "The basic share count is zero or less."


def test_a_falling_share_count_does_not_repeat_the_decrease_sentence():
    diluted_now = _shares(
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "90",
        "2025-01-01",
        "2025-12-31",
    )
    diluted_then = _shares(
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "100",
        "2024-01-01",
        "2024-12-31",
    )
    basic_now = _shares("WeightedAverageNumberOfSharesOutstandingBasic", "80", "2025-01-01", "2025-12-31")
    basic_then = _shares("WeightedAverageNumberOfSharesOutstandingBasic", "80", "2024-01-01", "2024-12-31")
    page = quality_html(
        [diluted_now, diluted_then, basic_now, basic_then],
        form="10-K",
        period_end="2025-12-31",
    )
    section = page.split('data-check="C6"', 1)[1].split("</section>", 1)[0]
    assert 'data-template="NUMBERS"' in section
    assert 'data-template="DECREASE"' not in section
    assert section.count("The diluted share count fell") == 1


def test_a_zero_change_in_diluted_shares_does_not_say_rose():
    diluted_now = _shares(
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "100",
        "2025-01-01",
        "2025-12-31",
    )
    diluted_then = _shares(
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "100",
        "2024-01-01",
        "2024-12-31",
    )
    basic_now = _shares("WeightedAverageNumberOfSharesOutstandingBasic", "110", "2025-01-01", "2025-12-31")
    basic_then = _shares("WeightedAverageNumberOfSharesOutstandingBasic", "110", "2024-01-01", "2024-12-31")
    page = quality_html(
        [diluted_now, diluted_then, basic_now, basic_then],
        form="10-K",
        period_end="2025-12-31",
    )
    section = page.split('data-check="C6"', 1)[1].split("</section>", 1)[0]
    assert "rose" not in section
    assert "The diluted share count was unchanged from " in section
    assert 'data-template="C3"' in section


def test_a_zero_earlier_cost_does_not_use_the_inventory_reason():
    inventory_now, inventory_then = _pair("InventoryNet", "inventory", "40", "30", kind="instant")
    cost_now, cost_then = _pair("CostOfGoodsAndServicesSold", "cost", "20", "0")
    result = check_inventory(
        [inventory_now, inventory_then, cost_now, cost_then],
        form="10-K",
        period_end="2025-12-31",
    )
    assert result.outcome == "not_run"
    assert result.reason == "The earlier cost of sales figure is zero or less."


def test_an_in_line_check_lists_only_items_at_or_above_the_threshold():
    operating, _prior = _pair("OperatingIncomeLoss", "operating_income", "100", "100")
    small = make_fact(
        "9",
        concept="RestructuringCharges",
        role="one_off",
        start="2025-01-01",
        end="2025-12-31",
        fact_id="itemsmallrestructuring",
    )
    large = make_fact(
        "10",
        concept="GoodwillImpairmentLoss",
        role="one_off",
        start="2025-01-01",
        end="2025-12-31",
        fact_id="itemlargegoodwillaaaa",
    )
    result = check_items([operating, small, large], form="10-K", period_end="2025-12-31")
    assert result.outcome == "unusual"
    assert [item.fact.concept for item in result.items] == ["GoodwillImpairmentLoss"]
    page = quality_html([operating, small, large], form="10-K", period_end="2025-12-31")
    section = page.split('data-check="C4"', 1)[1].split("</section>", 1)[0]
    assert "goodwill impairment" in section
    assert "restructuring charges" not in section
    quiet = quality_html([operating, small], form="10-K", period_end="2025-12-31")
    quiet_section = quiet.split('data-check="C4"', 1)[1].split("</section>", 1)[0]
    assert "Check: not marked" in quiet_section
    assert "Check: consistent" not in quiet_section
    assert "restructuring charges" not in quiet_section


def test_banned_words_are_refused_on_a_rendered_page_and_the_required_lines_are_allowed():
    allowed = f"<p>{DISCLAIMER}</p><p>{FRAME}</p>"
    assert page_terms(allowed) is None
    assert page_terms(allowed + "<p>This is a red flag.</p>") == "red flag"
    _shell("<p>Revenue was $1.</p>")
    with pytest.raises(OutputRefused):
        _shell("<p>This is a red flag.</p>")


def test_the_disclaimer_comes_before_the_framing_line_and_there_is_no_heading():
    inner = quality_html([], form="10-K", period_end="2025-12-31")
    page = _shell(inner)
    assert "What stands out in this report" not in page
    assert inner.count("<h2>") == 1
    assert "Checks on the company" in inner
    assert page.index(DISCLAIMER) < page.index("These checks compare the company")
