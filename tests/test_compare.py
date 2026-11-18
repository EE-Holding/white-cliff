"""Comparison math: percent rules, prior-quarter selection, and pinned figures."""

from decimal import Decimal
from pathlib import Path

from white_cliff.compare import (
    PriorCandidate,
    choose_prior_10q,
    columns_for,
    percent_change,
)
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.present import result_page
from white_cliff.wording import _comparison_block
from tests.support import make_fact

ROOT = Path(__file__).resolve().parents[1]
PINNED = ROOT / "pinned" / "filings"


def test_percent_only_when_the_prior_is_positive_and_the_current_is_not_a_loss():
    assert percent_change(Decimal("110"), Decimal("100")) == Decimal("10.0")
    assert percent_change(Decimal("0"), Decimal("100")) == Decimal("-100.0")
    assert percent_change(Decimal("100"), Decimal("0")) is None
    assert percent_change(Decimal("-5"), Decimal("-10")) is None
    assert percent_change(Decimal("5"), Decimal("-10")) is None
    assert percent_change(Decimal("-5"), Decimal("10")) is None


def test_prior_10q_needs_exactly_one_match_and_refuses_an_amendment():
    current = "2026-07-26"
    good = PriorCandidate("10-Q", "2026-04-26", "--01-31", "0001045810", "0001045810-26-000052")
    amendment = PriorCandidate("10-Q/A", "2026-04-26", "--01-31", "0001045810", "0001045810-26-000099")
    other_year = PriorCandidate("10-Q", "2026-04-26", "--06-30", "0001045810", "0001045810-26-000098")
    assert choose_prior_10q(current, "--01-31", "0001045810", [good, amendment, other_year]) == good
    assert choose_prior_10q(current, "--01-31", "0001045810", [amendment]) is None
    assert choose_prior_10q(current, "--01-31", "0001045810", [good, good]) is None
    assert choose_prior_10q(current, "--01-31", "0001045810", []) is None


def test_a_10k_last_quarter_is_not_available_and_the_year_is():
    current = make_fact("478834", end="2026-09-26", start="2025-09-28")
    prior = make_fact("416161", end="2025-09-27", start="2024-09-29", fact_id="factprioryearrevenueaaaa")
    last, year = columns_for(
        current,
        role="revenue",
        form="10-K",
        focus="FY",
        period_end="2026-09-26",
        fiscal_year_end="--09-26",
        facts=[current, prior],
    )
    assert last is not None and not last.available
    assert year is not None and year.available and year.value == Decimal("416161")


def test_nvidia_quarter_uses_the_nvidia_filing_not_another_company():
    current = load_directory(PINNED / "0001045810-26-000075")
    prior = load_directory(PINNED / "0001045810-26-000052")
    assert current.cik == prior.cik == "0001045810"
    assert current.focus == "Q2"
    assert len(current.store.facts()) > 0
    explained = explain_filing(current)
    page = result_page(
        explained,
        form=current.form,
        period=current.period_end or "",
        filed="2026-08-26",
        url=current.url,
        company=current.filer,
        focus=current.focus,
        fiscal_year_end=current.fiscal_year_end,
        prior_facts=prior.store.facts(),
        prior_end=prior.period_end,
    )
    assert "$96,221 million" in page
    assert "$81,615 million" in page
    assert "17.9 percent" in page
    assert "0001045810" in page or "/1045810/" in page
    assert "320193" not in page
    assert "aapl-" not in page


def test_apple_annual_revenue_rose_15_1_percent():
    filing = load_directory(PINNED / "0000320193-26-000026")
    explained = explain_filing(filing)
    page = result_page(
        explained,
        form=filing.form,
        period=filing.period_end or "",
        filed="2026-10-31",
        url=filing.url,
        company=filing.filer,
        focus=filing.focus,
        fiscal_year_end=filing.fiscal_year_end,
    )
    assert "rose" in page
    assert "15.1 percent" in page
    assert "10-K" not in page
    assert 'data-template="C2"' in page
    assert "What stands out in this report" not in page
    assert page.index("This tool explains the numbers in a public company filing.") < page.index(
        "These checks compare the company"
    )


def _shown(role, fact, last, year, measure):
    return _comparison_block(role, fact, last, year, measure, "quarterly report", "2026-08-01")


def test_a_column_the_form_cannot_carry_uses_the_filing_sentence():
    annual = make_fact("100", start="2025-01-01", end="2025-12-31", fact_id="annualrevenueaaaa")
    annual_prior = make_fact("80", start="2024-01-01", end="2024-12-31", fact_id="annualprioryearaa")
    last, year = columns_for(
        annual,
        role="revenue",
        form="10-K",
        focus="FY",
        period_end="2025-12-31",
        fiscal_year_end="--12-31",
        facts=[annual, annual_prior],
    )
    annual_html = _shown("revenue", annual, last, year, "money")
    assert last is not None and last.basis == "structural"
    assert 'data-template="M6"' in annual_html
    assert "Revenue for the prior quarter is not available for this filing." in annual_html
    assert "not in the filings White Cliff read" not in annual_html

    quarter = make_fact("300", start="2026-01-27", end="2026-04-26", fact_id="q1revenuenowaaaa")
    decoy = make_fact("424242", start="2025-10-27", end="2026-01-26", fact_id="q1decoyprioraaaa")
    quarter_year = make_fact("250", start="2025-01-27", end="2025-04-27", fact_id="q1revenueyearaaa")
    q_last, q_year = columns_for(
        quarter,
        role="revenue",
        form="10-Q",
        focus="Q1",
        period_end="2026-04-26",
        fiscal_year_end="--01-31",
        facts=[quarter, decoy, quarter_year],
    )
    quarter_html = _shown("revenue", quarter, q_last, q_year, "money")
    assert q_last is not None and q_last.basis == "structural"
    assert "424242" not in quarter_html
    assert 'data-template="M6"' in quarter_html
    assert "not in the filings White Cliff read" not in quarter_html

    cash = make_fact(
        "900",
        concept="NetCashProvidedByUsedInOperatingActivities",
        role="operating_cash_flow",
        start="2026-04-27",
        end="2026-07-26",
        fact_id="ocfcurrentquarter",
    )
    cash_prior = make_fact(
        "515151",
        concept="NetCashProvidedByUsedInOperatingActivities",
        role="operating_cash_flow",
        start="2026-01-26",
        end="2026-04-26",
        fact_id="ocfpriorshouldno",
    )
    cash_year = make_fact(
        "700",
        concept="NetCashProvidedByUsedInOperatingActivities",
        role="operating_cash_flow",
        start="2025-04-28",
        end="2025-07-27",
        fact_id="ocfprioryearfact",
    )
    c_last, c_year = columns_for(
        cash,
        role="operating_cash_flow",
        form="10-Q",
        focus="Q2",
        period_end="2026-07-26",
        fiscal_year_end="--01-31",
        facts=[cash, cash_prior, cash_year],
        prior_facts=[cash_prior],
        prior_end="2026-04-26",
    )
    cash_html = _shown("operating_cash_flow", cash, c_last, c_year, "money")
    assert c_last is not None and c_last.basis == "structural"
    assert "515151" not in cash_html
    assert "Operating cash flow for the prior quarter is not available for this filing." in cash_html
    assert 'data-template="M2"' not in cash_html

    missing = make_fact("111", start="2026-04-27", end="2026-07-26", fact_id="q2revenueonlyaaa")
    m_last, m_year = columns_for(
        missing,
        role="revenue",
        form="10-Q",
        focus="Q2",
        period_end="2026-07-26",
        fiscal_year_end="--01-31",
        facts=[missing],
    )
    missing_html = _shown("revenue", missing, m_last, m_year, "money")
    assert m_last is not None and m_last.basis != "structural"
    assert 'data-template="M2"' in missing_html
    assert 'data-template="M6"' not in missing_html
