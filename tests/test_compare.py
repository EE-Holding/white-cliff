"""Comparison math: percent rules, prior-quarter selection, and pinned figures."""

import re
from decimal import Decimal
from pathlib import Path

from white_cliff.compare import (
    Cell,
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


def _plain_page(html_text: str) -> str:
    return re.sub(r"<[^>]+>", "", html_text)


def _column(fact):
    return Cell(
        True,
        value=fact.value,
        unit=fact.unit,
        period_end=fact.period.end or "",
        period_start=fact.period.start,
        kind=fact.period.kind,
        fact=fact,
    )


def _change_block(current, last, year, measure="money", role="revenue"):
    return _comparison_block(role, current, last, year, measure, "quarterly report", "2026-08-01")


def _quarter(value, fact_id, start="2026-01-26", end="2026-04-26", role="revenue"):
    return make_fact(value, role=role, start=start, end=end, fact_id=fact_id)


def test_two_rises_read_it_rose_and_it_rose_again():
    current = _quarter("110", "tworisenow", "2026-04-27", "2026-07-26")
    last = _quarter("100", "tworiselast")
    year = _quarter("50", "tworiseyear", "2024-07-29", "2025-07-27")
    html = _change_block(current, _column(last), _column(year))
    plain = _plain_page(html)
    assert (
        "It rose 10.0 percent from the quarter ended April 26, 2026, "
        "and rose 120.0 percent from the year ended July 27, 2025."
    ) in plain
    assert 'data-template="C2"' in html
    assert "That is" not in plain
    assert "percent percent" not in plain


def test_a_rise_and_no_change_share_one_it_line():
    current = _quarter("104.2", "mixednow", "2026-04-27", "2026-07-26")
    last = _quarter("100", "mixedlast")
    year = _quarter("104.2", "mixedyear", "2024-07-29", "2025-07-27")
    plain = _plain_page(_change_block(current, _column(last), _column(year)))
    assert (
        "It rose 4.2 percent from the quarter ended April 26, 2026, "
        "and was unchanged from the year ended July 27, 2025."
    ) in plain
    assert "percent percent" not in plain


def test_one_comparison_says_it_rose_or_it_fell_or_it_was_unchanged():
    rose_now = _quarter("104.2", "onenow", "2026-04-27", "2026-07-26")
    rose_last = _quarter("100", "onelast")
    rose = _plain_page(_change_block(rose_now, _column(rose_last), None))
    assert "It rose 4.2 percent from the quarter ended April 26, 2026." in rose
    assert ", and " not in rose
    fell_now = _quarter("90", "fellnow", "2026-04-27", "2026-07-26")
    fell_last = _quarter("100", "felllast")
    fell = _plain_page(_change_block(fell_now, _column(fell_last), None))
    assert "It fell 10.0 percent from the quarter ended April 26, 2026." in fell
    same_now = _quarter("100", "samenow", "2026-04-27", "2026-07-26")
    same_last = _quarter("100", "samelast")
    same = _plain_page(_change_block(same_now, _column(same_last), None))
    assert "It was unchanged from the quarter ended April 26, 2026." in same


def test_a_fall_and_a_rise_share_one_it_line():
    current = _quarter("90", "mixfellnow", "2026-04-27", "2026-07-26")
    last = _quarter("100", "mixfelllast")
    year = _quarter("50", "mixfellyear", "2024-07-29", "2025-07-27")
    plain = _plain_page(_change_block(current, _column(last), _column(year)))
    assert (
        "It fell 10.0 percent from the quarter ended April 26, 2026, "
        "and rose 80.0 percent from the year ended July 27, 2025."
    ) in plain


def test_both_unchanged_comparisons_keep_the_value_sentence():
    current = _quarter("100", "bothnow", "2026-04-27", "2026-07-26")
    last = _quarter("100", "bothlast")
    year = _quarter("100", "bothyear", "2024-07-29", "2025-07-27")
    html = _change_block(current, _column(last), _column(year))
    plain = _plain_page(html)
    assert "Revenue was unchanged from the quarter ended April 26, 2026 at $100." in plain
    assert "Revenue was unchanged from the year ended July 27, 2025 at $100." in plain
    assert 'data-template="C3"' in html
    assert "It was unchanged" not in plain
    assert ", and was unchanged" not in plain


def test_an_amount_only_change_says_it_was_higher_or_lower():
    current = make_fact(
        "150",
        concept="LongTermDebt",
        role="net_debt",
        start="2026-04-27",
        end="2026-07-26",
        fact_id="debtnow",
    )
    last = make_fact(
        "100",
        concept="LongTermDebt",
        role="net_debt",
        start="2026-01-26",
        end="2026-04-26",
        fact_id="debtlast",
    )
    debt = _plain_page(_change_block(current, _column(last), None, measure="net_debt", role="net_debt"))
    assert "It was $50 higher than the quarter ended April 26, 2026." in debt
    margin_now = make_fact("40", role="gross_margin", start="2026-04-27", end="2026-07-26", fact_id="marginow")
    margin_then = make_fact("35.8", role="gross_margin", start="2026-01-26", end="2026-04-26", fact_id="margthen")
    margin = _plain_page(
        _change_block(margin_now, _column(margin_then), None, measure="margin", role="gross_margin")
    )
    assert "It was 4.2 percentage points higher than the quarter ended April 26, 2026." in margin
    assert "That is" not in debt and "That is" not in margin


def _column_heads(html_text: str) -> list[str]:
    return re.findall(r'class="caption">([^<]*)', html_text)


def test_column_headers_name_the_period_and_do_not_call_a_year_to_date_a_quarter():
    current = load_directory(PINNED / "0001045810-26-000075")
    prior = load_directory(PINNED / "0001045810-26-000052")
    nvidia = result_page(
        explain_filing(current),
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
    heads = _column_heads(nvidia)
    assert "Three months ended April 26, 2026" in heads
    assert "Three months ended July 27, 2025" in heads
    assert "Six months ended July 27, 2025" in heads
    assert "Six months ended July 26, 2026" in heads
    assert all("quarter" not in head.lower() for head in heads)
    assert "for the prior quarter is not available for this filing." in nvidia

    apple_filing = load_directory(PINNED / "0000320193-26-000026")
    apple = result_page(
        explain_filing(apple_filing),
        form=apple_filing.form,
        period=apple_filing.period_end or "",
        filed="2026-10-31",
        url=apple_filing.url,
        company=apple_filing.filer,
        focus=apple_filing.focus,
        fiscal_year_end=apple_filing.fiscal_year_end,
    )
    apple_heads = _column_heads(apple)
    assert any(head.startswith("Year ended ") for head in apple_heads)
    assert all("quarter" not in head.lower() for head in apple_heads)

    nine_now = _quarter("90", "ninenow", "2025-10-27", "2026-07-26")
    nine_then = _quarter("80", "ninethen", "2024-10-28", "2025-07-27")
    nine_heads = _column_heads(_change_block(nine_now, None, _column(nine_then)))
    assert "Nine months ended July 26, 2026" in nine_heads
    assert "Nine months ended July 27, 2025" in nine_heads
    assert all("quarter" not in head.lower() for head in nine_heads)


def test_comparison_markup_is_label_then_figure_then_the_two_cell_grid():
    current = load_directory(PINNED / "0001045810-26-000075")
    prior = load_directory(PINNED / "0001045810-26-000052")
    page = result_page(
        explain_filing(current),
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
    style = page.split("</style>", 1)[0]
    caption_rule = re.search(r"\.caption \{([^}]*)\}", style)
    assert caption_rule is not None
    assert "600" not in caption_rule.group(1)
    assert "font-weight: 400" in caption_rule.group(1)

    def block_for(label: str) -> str:
        start = page.find(f">{label}</span>")
        assert start > 0
        opening = page.rfind('<div class="figure-block">', 0, start)
        closing = page.find('<div class="figure-block">', opening + 1)
        return page[opening:closing]

    revenue = block_for("Revenue")
    label_at = revenue.find(">Revenue</span>")
    figure_at = revenue.find('class="figure"')
    grid_at = revenue.find('class="earlier"')
    change_at = revenue.find('class="change-line"')
    assert 0 <= label_at < figure_at < grid_at < change_at
    cells = re.findall(r'<div class="prior">.*?</div>', revenue)
    assert len(cells) == 2
    assert "Three months ended April 26, 2026" in cells[0]
    assert "$81,615 million" in cells[0]
    assert "Three months ended July 27, 2025" in cells[1]
    assert "$46,743 million" in cells[1]

    cash = block_for("Operating cash flow for the year to date")
    cash_figure = cash.find('class="figure"')
    cash_grid = cash.find('class="earlier"')
    cash_caption = cash.find("Six months ended July 26, 2026")
    assert cash.find(">Operating cash flow for the year to date</span>") < cash_figure < cash_grid
    assert cash_figure > cash_caption > 0
    assert cash_caption < cash_grid
    cash_cells = re.findall(r'<div class="prior">.*?</div>', cash)
    assert cash_cells[0] == (
        '<div class="prior"><p data-template="M6">'
        "Operating cash flow for the prior quarter is not available for this filing.</p></div>"
    )
    assert "Six months ended July 27, 2025" in cash_cells[1]
    assert "<strong" not in page and "<b>" not in page


def test_rendered_pages_do_not_say_that_is_rose_or_percent_percent():
    current = load_directory(PINNED / "0001045810-26-000075")
    prior = load_directory(PINNED / "0001045810-26-000052")
    nvidia = result_page(
        explain_filing(current),
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
    apple_filing = load_directory(PINNED / "0000320193-26-000026")
    apple = result_page(
        explain_filing(apple_filing),
        form=apple_filing.form,
        period=apple_filing.period_end or "",
        filed="2026-10-31",
        url=apple_filing.url,
        company=apple_filing.filer,
        focus=apple_filing.focus,
        fiscal_year_end=apple_filing.fiscal_year_end,
    )
    nvidia_plain = _plain_page(nvidia)
    assert (
        "It rose 17.9 percent from the quarter ended April 26, 2026, "
        "and rose 105.9 percent from the quarter ended July 27, 2025."
    ) in nvidia_plain
    for plain in (nvidia_plain, _plain_page(apple)):
        assert "That is rose" not in plain
        assert "That is fell" not in plain
        assert "percent percent" not in plain
