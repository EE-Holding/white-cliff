"""Comparison math: percent rules, prior-quarter selection, and pinned figures."""

import html
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
    face, lines = _comparison_block(role, fact, last, year, measure, "quarterly report", "2026-08-01")
    return face + lines


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
    face, lines = _comparison_block(role, current, last, year, measure, "quarterly report", "2026-08-01")
    return face + lines


def _quarter(value, fact_id, start="2026-01-26", end="2026-04-26", role="revenue"):
    return make_fact(value, role=role, start=start, end=end, fact_id=fact_id)


def test_two_rises_read_it_rose_and_it_rose_again():
    current = _quarter("110", "tworisenow", "2026-04-27", "2026-07-26")
    last = _quarter("100", "tworiselast")
    year = _quarter("50", "tworiseyear", "2024-07-29", "2025-07-27")
    html = _change_block(current, _column(last), _column(year))
    plain = _plain_page(html)
    assert (
        "It rose 10.0 percent from the quarter ended April 26, 2026, "
        "and rose 120.0 percent from the year ended July 27, 2025."
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
        "It rose 4.2 percent from the quarter ended April 26, 2026, "
        "and was unchanged from the year ended July 27, 2025."
    ) in plain
    assert "percent percent" not in plain


def test_one_comparison_says_it_rose_or_it_fell_or_it_was_unchanged():
    rose_now = _quarter("104.2", "onenow", "2026-04-27", "2026-07-26")
    rose_last = _quarter("100", "onelast")
    rose = _plain_page(_change_block(rose_now, _column(rose_last), None))
    assert "It rose 4.2 percent from the quarter ended April 26, 2026." in rose
    assert ", and " not in rose
    fell_now = _quarter("90", "fellnow", "2026-04-27", "2026-07-26")
    fell_last = _quarter("100", "felllast")
    fell = _plain_page(_change_block(fell_now, _column(fell_last), None))
    assert "It fell 10.0 percent from the quarter ended April 26, 2026." in fell
    same_now = _quarter("100", "samenow", "2026-04-27", "2026-07-26")
    same_last = _quarter("100", "samelast")
    same = _plain_page(_change_block(same_now, _column(same_last), None))
    assert "It was unchanged from the quarter ended April 26, 2026." in same


def test_a_fall_and_a_rise_share_one_it_line():
    current = _quarter("90", "mixfellnow", "2026-04-27", "2026-07-26")
    last = _quarter("100", "mixfelllast")
    year = _quarter("50", "mixfellyear", "2024-07-29", "2025-07-27")
    plain = _plain_page(_change_block(current, _column(last), _column(year)))
    assert (
        "It fell 10.0 percent from the quarter ended April 26, 2026, "
        "and rose 80.0 percent from the year ended July 27, 2025."
    ) in plain


def test_both_unchanged_comparisons_keep_the_value_sentence():
    current = _quarter("100", "bothnow", "2026-04-27", "2026-07-26")
    last = _quarter("100", "bothlast")
    year = _quarter("100", "bothyear", "2024-07-29", "2025-07-27")
    html = _change_block(current, _column(last), _column(year))
    plain = _plain_page(html)
    assert "Revenue was unchanged from the quarter ended April 26, 2026 at $100." in plain
    assert "Revenue was unchanged from the year ended July 27, 2025 at $100." in plain
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
    assert "It was $50 higher than the quarter ended April 26, 2026." in debt
    margin_now = make_fact("40", role="gross_margin", start="2026-04-27", end="2026-07-26", fact_id="marginow")
    margin_then = make_fact("35.8", role="gross_margin", start="2026-01-26", end="2026-04-26", fact_id="margthen")
    margin = _plain_page(
        _change_block(margin_now, _column(margin_then), None, measure="margin", role="gross_margin")
    )
    assert "It rose 4.2 percentage points from the prior quarter." in margin
    assert "That is" not in debt and "That is" not in margin


def _column_heads(html_text: str) -> list[str]:
    return re.findall(r'class="(?:caption|bd)">([^<]*)', html_text)


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
    assert "Three months ended April 26, 2026" in heads
    assert "Three months ended July 27, 2025" in heads
    assert "Six months ended July 27, 2025" in heads
    assert "Six months ended July 26, 2026" in heads
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
    assert "Nine months ended July 26, 2026" in nine_heads
    assert "Nine months ended July 27, 2025" in nine_heads
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
        start = page.find(f">{label}</h3>")
        assert start > 0
        opening = page.rfind("<article", 0, start)
        closing = page.find("<article", opening + 1)
        return page[opening:closing]

    revenue = block_for("Revenue")
    label_at = revenue.find(">Revenue</h3>")
    figure_at = revenue.find('class="figure"')
    chart_at = revenue.find('class="chart"')
    change_at = revenue.find('class="change-line"')
    assert 0 <= label_at < figure_at < chart_at < change_at
    assert "Prior quarter" in revenue
    assert "Same quarter a year earlier" in revenue
    assert "Three months ended April 26, 2026" in revenue
    assert "$81,615 million" in revenue
    assert "Three months ended July 27, 2025" in revenue
    assert "$46,743 million" in revenue

    cash = block_for("Operating cash flow for the year to date")
    cash_figure = cash.find('class="figure"')
    cash_chart = cash.find('class="chart"')
    cash_caption = cash.find("Six months ended July 26, 2026")
    assert cash.find(">Operating cash flow for the year to date</h3>") < cash_figure < cash_chart
    assert 0 < cash_caption < cash_chart
    assert (
        '<p class="bh">Prior quarter</p></div>'
        '<p class="m6" data-template="M6">'
        "Operating cash flow for the prior quarter is not available for this filing.</p>"
    ) in cash
    assert "Same six months a year earlier" in cash
    assert "Six months ended July 27, 2025" in cash
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
        "It rose 17.9 percent from the quarter ended April 26, 2026, "
        "and rose 105.9 percent from the quarter ended July 27, 2025."
    ) in nvidia_plain
    for plain in (nvidia_plain, _plain_page(apple)):
        assert "That is rose" not in plain
        assert "That is fell" not in plain
        assert "percent percent" not in plain


def _nvidia_page() -> str:
    current = load_directory(PINNED / "0001045810-26-000075")
    prior = load_directory(PINNED / "0001045810-26-000052")
    return result_page(
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


def _apple_page() -> str:
    filing = load_directory(PINNED / "0000320193-26-000026")
    return result_page(
        explain_filing(filing),
        form=filing.form,
        period=filing.period_end or "",
        filed="2026-10-31",
        url=filing.url,
        company=filing.filer,
        focus=filing.focus,
        fiscal_year_end=filing.fiscal_year_end,
    )


def _figure_blocks(page: str) -> list[str]:
    return re.findall(r"<article class=\"card\".*?</article>", page, flags=re.S)


def test_heads_keep_a_caption_and_the_missing_quarter_keeps_its_head():
    nvidia = _nvidia_page()
    revenue = next(block for block in _figure_blocks(nvidia) if ">Revenue</h3>" in block)
    assert '<p class="bh">Prior quarter</p>' in revenue
    assert "Three months ended April 26, 2026" in revenue
    assert '<p class="bh">Same quarter a year earlier</p>' in revenue
    assert "Three months ended July 27, 2025" in revenue
    cash = next(block for block in _figure_blocks(nvidia) if "year to date" in block)
    assert '<p class="bh">Prior quarter</p>' in cash
    assert 'data-template="M6"' in cash
    assert "Same six months a year earlier" in cash
    rights = [head for head in re.findall(r'class="bh">([^<]+)', cash) if head != "Prior quarter"]
    assert rights
    assert all("quarter" not in head.lower() for head in rights)
    style = nvidia.split("</style>", 1)[0]
    missing = re.search(r"\.m6 \{([^}]*)\}", style)
    assert missing is not None
    assert "#3a3a3c" in missing.group(1)
    assert "#555559" not in missing.group(1)
    assert "max-width: 1160px" in style
    for banned in ("Last quarter", "A year ago", "Last year"):
        assert banned not in nvidia

    nine_now = _quarter("90", "ninenowhead", "2025-10-27", "2026-07-26")
    nine_then = _quarter("80", "ninethenhead", "2024-10-28", "2025-07-27")
    missing_left = Cell(False, basis="structural", missing_period="the prior quarter")
    nine_face, nine_lines = _comparison_block(
        "revenue", nine_now, missing_left, _column(nine_then), "money", "quarterly report", "2026-08-01", form="10-Q"
    )
    nine = nine_face + nine_lines
    assert '<p class="bh">Same nine months a year earlier</p>' in nine
    assert "Nine months ended July 27, 2025" in nine
    rights = [head for head in re.findall(r'class="bh">([^<]+)', nine) if head != "Prior quarter"]
    assert rights
    assert all("quarter" not in head.lower() for head in rights)

    quarter = make_fact("300", start="2026-01-27", end="2026-04-26", fact_id="q1headrevenuenow")
    quarter_year = make_fact("250", start="2025-01-27", end="2025-04-27", fact_id="q1headrevenueyr")
    q_last, q_year = columns_for(
        quarter,
        role="revenue",
        form="10-Q",
        focus="Q1",
        period_end="2026-04-26",
        fiscal_year_end="--01-31",
        facts=[quarter, quarter_year],
    )
    q1_face, q1_lines = _comparison_block(
        "revenue", quarter, q_last, q_year, "money", "quarterly report", "2026-06-01", form="10-Q"
    )
    q1 = q1_face + q1_lines
    assert '<p class="bh">Prior quarter</p>' in q1
    assert 'data-template="M6"' in q1
    assert '<p class="bh">Same quarter a year earlier</p>' in q1
    assert "Three months ended April 27, 2025" in q1

    apple = _apple_page()
    assert '<p class="bh">Prior quarter</p>' in apple
    assert '<p class="bh">Prior year</p>' in apple
    assert "Same quarter a year earlier" not in apple
    assert "Same six months a year earlier" not in apple
    assert "Last quarter" not in apple and "A year ago" not in apple and "Last year" not in apple
    assert any(head.startswith("Year ended ") for head in _column_heads(apple))


def test_every_percent_note_shows_a_label_a_date_and_the_formula():
    """A note that is only two amounts, or that drops the label, date, or formula, fails."""
    import json

    from white_cliff.wording import percent_note_gaps

    manifest = json.loads((ROOT / "pinned" / "manifest.json").read_text(encoding="utf-8"))
    checked = 0
    for item in manifest["filings"]:
        directory = PINNED / item["accession"]
        if not directory.is_dir():
            continue
        filing = load_directory(directory)
        page = result_page(
            explain_filing(filing),
            form=filing.form,
            period=filing.period_end or "",
            filed=item.get("period_of_report") or "",
            url=filing.url,
            company=filing.filer,
            focus=filing.focus,
            fiscal_year_end=filing.fiscal_year_end,
        )
        for note in re.findall(r'<p class="pct-note"[^>]*>(.*?)</p>', page, flags=re.S):
            gaps = percent_note_gaps(note)
            assert not gaps, (item["accession"], gaps, re.sub(r"<[^>]+>", "", note)[:240])
            checked += 1
    assert checked == 134


def test_every_percent_link_resolves_to_both_of_its_inputs():
    """A percent opens one note, and that note links this figure and the earlier figure."""
    page = _nvidia_page()
    checked = 0
    for line in re.findall(r'<p class="change-line"[^>]*>(.*?)</p>', page, flags=re.S):
        for attrs, text in re.findall(r"<a\b([^>]*)>(.*?)</a>", line):
            if text.endswith(" percent") and "percentage points" not in text:
                plain = re.sub(r"<[^>]+>", "", line)
                if "rose " in plain or "fell " in plain:
                    assert 'class="pct"' in attrs
    for block in _figure_blocks(page):
        lines = re.findall(r'<p class="change-line" data-template="C2">(.*?)</p>', block, flags=re.S)
        if not lines:
            continue
        figure = re.search(r'<a class="figure" href="([^"]+)"', block)
        assert figure is not None
        priors = re.findall(r'<p class="bv"><a href="([^"]+)"', block)
        for line in lines:
            percents = re.findall(r'<a class="pct" href="#(pct-[0-9a-f]+)">(.*?)</a>', line)
            if not percents:
                continue
            sentence = re.sub(r"<[^>]+>", "", line)
            assert "from the " in sentence
            assert "<a" not in re.sub(r'<a class="pct"[^>]*>.*?</a>', "", line)
            for note_id, text in percents:
                assert text.endswith(" percent")
                note = re.search(
                    rf'<p class="pct-note" id="{note_id}">(.*?)</p>',
                    block,
                    flags=re.S,
                )
                assert note is not None
                hrefs = re.findall(r'<a href="([^"]+)"', note.group(1))
                assert len(hrefs) == 2
                assert len(set(hrefs)) == 2
                assert hrefs[0] == figure.group(1)
                assert hrefs[1] in priors
                assert all(href.startswith("https://www.sec.gov/") for href in hrefs)
                plain_note = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", note.group(1))).strip()
                assert plain_note.startswith("It is calculated as the change from ")
                assert ", divided by the " in plain_note
                assert " figure, using " in plain_note
                assert plain_note.endswith(".")
                checked += 1
    assert checked >= 2


def test_a_percent_without_a_filing_label_or_date_is_removed():
    from white_cliff.wording import _percent_tuple, take_percent_note_counts

    take_percent_note_counts()
    current = make_fact("110", fact_id="gapnow", end="2026-07-26", start="2026-04-27")
    prior = make_fact("100", fact_id="gapold", end="2026-04-26", start="2026-01-26")
    current_cell = Cell(
        True,
        value=current.value,
        unit=current.unit,
        period_end=current.period.end or "",
        period_start=current.period.start,
        kind=current.period.kind,
        fact=current,
    )
    prior_cell = Cell(
        True,
        value=prior.value,
        unit=prior.unit,
        period_end=prior.period.end or "",
        period_start=prior.period.start,
        kind=prior.period.kind,
        fact=prior,
    )
    assert _percent_tuple("100", current_cell, prior_cell, "10.0 percent") is None
    undated = Cell(
        True,
        value=prior.value,
        unit=prior.unit,
        period_end="",
        period_start=prior.period.start,
        kind=prior.period.kind,
        fact=prior,
    )
    assert _percent_tuple("Revenue", current_cell, undated, "10.0 percent") is None
    noted, removed = take_percent_note_counts()
    assert noted == 0
    assert removed == 2


def test_a_percent_note_missing_a_label_or_a_date_or_the_formula_fails():
    from white_cliff.wording import percent_note_gaps

    bare = (
        '<p class="pct-note" id="pct-bare">'
        '<a href="https://www.sec.gov/a">$100 million</a>'
        '<a href="https://www.sec.gov/b">$80 million</a>'
        "</p>"
    )
    assert percent_note_gaps(bare) == {"label", "date", "formula"}
    no_label = (
        "It is calculated as the change from April 26, 2026 to July 26, 2026, "
        "divided by the April 26, 2026 figure, using of $110 million for July 26, 2026 "
        "and of $100 million for April 26, 2026."
    )
    assert percent_note_gaps(no_label) == {"label"}
    no_date = (
        "It is calculated as the change from the prior quarter to this quarter, "
        "divided by the prior quarter figure, using Revenue of $110 million for this quarter "
        "and Revenue of $100 million for the prior quarter."
    )
    assert percent_note_gaps(no_date) == {"date"}
    no_formula = (
        "Revenue of $110 million for July 26, 2026 and Revenue of $100 million for April 26, 2026."
    )
    assert percent_note_gaps(no_formula) == {"formula", "label"}


def test_a_change_percent_states_the_formula_and_links_both_amounts():
    from white_cliff.i18n import using
    from white_cliff.wording import label_for, long_date, show_measure, take_percent_note_counts
    from tests.test_cards import _column, _html, _quarter

    take_percent_note_counts()
    current = _quarter("110", "notenow", "2026-04-27", "2026-07-26")
    last = _quarter("100", "notelast")
    html_text = _html(current, _column(last), None)
    label = label_for("revenue", current)
    period = long_date(current.period.end or "")
    period_prior = long_date(last.period.end or "")
    current_amount = show_measure(current.value, current.unit)
    prior_amount = show_measure(last.value, last.unit)
    expected = (
        "It is calculated as the change from "
        f"{period_prior} to {period}, divided by the {period_prior} figure, using "
        f"{label} of {current_amount} for {period} and "
        f"{label} of {prior_amount} for {period_prior}."
    )
    note = re.search(r'<p class="pct-note"[^>]*>(.*?)</p>', html_text, flags=re.S)
    assert note is not None
    assert re.sub(r"<[^>]+>", "", note.group(1)) == expected
    links = re.findall(r'<a href="([^"]+)">([^<]+)</a>', note.group(1))
    assert [text for _href, text in links] == [current_amount, prior_amount]
    assert links[0][0].startswith("https://www.sec.gov/")
    assert links[1][0].startswith("https://www.sec.gov/")
    assert links[0][0] != links[1][0]
    noted, removed = take_percent_note_counts()
    assert noted == 1
    assert removed == 0
    with using("de"):
        take_percent_note_counts()
        page_de = _html(current, _column(last), None)
        note_de = re.search(r'<p class="pct-note"[^>]*>(.*?)</p>', page_de, flags=re.S)
        assert note_de is not None
        assert re.sub(r"<[^>]+>", "", note_de.group(1)) == expected
        take_percent_note_counts()


def test_a_percent_without_two_filing_links_is_removed():
    from dataclasses import replace

    from white_cliff.wording import take_percent_note_counts
    from tests.test_cards import _column, _html, _quarter

    take_percent_note_counts()
    current = _quarter("110", "dropnow", "2026-04-27", "2026-07-26")
    last = _quarter("100", "droplast")
    shared = replace(last, id=current.id, source=current.source)
    html_text = _html(current, _column(shared), None)
    assert "10.0 percent" not in re.sub(r"<[^>]+>", " ", html_text)
    assert "pct-note" not in html_text
    noted, removed = take_percent_note_counts()
    assert noted == 0
    assert removed >= 1


def test_the_note_uses_the_values_the_percent_was_computed_from():
    """The amount in the note is the table value that was divided, not another reading of the fact."""
    from white_cliff.wording import fact_href

    current = make_fact("110", fact_id="samecur", end="2026-07-26", start="2026-04-27")
    prior_fact = make_fact("50", fact_id="sameold", end="2026-04-26", start="2026-01-26")
    prior = Cell(
        True,
        value=Decimal("100"),
        unit=prior_fact.unit,
        period_end=prior_fact.period.end or "",
        period_start=prior_fact.period.start,
        kind=prior_fact.period.kind,
        fact=prior_fact,
    )
    face, lines = _comparison_block(
        "revenue", current, prior, None, "money", "quarterly report", "2026-08-01"
    )
    note = re.search(r'<p class="pct-note"[^>]*>(.*?)</p>', face + lines, flags=re.S)
    assert note is not None
    links = [
        (html.unescape(href), label)
        for href, label in re.findall(r'<a href="([^"]+)">([^<]+)</a>', note.group(1))
    ]
    assert len(links) == 2
    assert "110" in links[0][1]
    assert "100" in links[1][1]
    assert "50" not in links[1][1]
    assert links[0][0] == fact_href(current)
    assert links[1][0] == fact_href(prior_fact)
    assert links[1][0].startswith("https://www.sec.gov/")
