"""Cards, shared bar scale, and the cleared S1 short line."""

import re
from decimal import Decimal
from pathlib import Path

from white_cliff.compare import Cell, columns_for
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.present import edit_page, first_run_page, result_page, search_page
from white_cliff.strings import EN
from white_cliff.wording import _comparison_block
from tests.support import make_fact

ROOT = Path(__file__).resolve().parents[1]
PINNED = ROOT / "pinned" / "filings"


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


def _quarter(value, fact_id, start="2026-01-26", end="2026-04-26"):
    return make_fact(value, start=start, end=end, fact_id=fact_id)


def _html(current, last, year, measure="money", role="revenue", form=""):
    face, lines = _comparison_block(
        role, current, last, year, measure, "quarterly report", "2026-08-01", form=form
    )
    return face + lines


def _short(html_text: str) -> str:
    match = re.search(r'<div class="cmp-slot">(.*?)</div>', html_text, flags=re.S)
    assert match is not None
    return re.sub(r"[ \t\n\r\f\v]+", " ", re.sub(r"<[^>]+>", "", match.group(1))).strip()


def _widths(html_text: str) -> list[Decimal]:
    return [Decimal(item) for item in re.findall(r'class="fill(?: neg)?" style="left:[0-9.]+%;width:([0-9.]+)%"', html_text)]


def test_two_changes_use_the_short_line_and_keep_the_dated_sentence():
    current = _quarter("110", "s1now", "2026-04-27", "2026-07-26")
    last = _quarter("100", "s1last")
    year = _quarter("50", "s1year", "2024-07-29", "2025-07-27")
    html_text = _html(current, _column(last), _column(year))
    assert _short(html_text) == (
        "It rose 10.0 percent from the prior quarter and rose 120.0 percent from the prior year."
    )
    assert (
        "It rose 10.0 percent from the quarter ended April 26, 2026, "
        "and rose 120.0 percent from the year ended July 27, 2025."
    ) in re.sub(r"<[^>]+>", "", html_text)
    percents = re.findall(r'<a class="pct" href="([^"]+)">([^<]+)</a>', html_text.split('class="chart"', 1)[0])
    periods = re.findall(r'<a class="per" href="([^"]+)">([^<]+)</a>', html_text)
    assert [text for _href, text in percents] == ["10.0 percent", "120.0 percent"]
    assert [text for _href, text in periods] == ["the prior quarter", "the prior year"]
    assert all(href.startswith("https://www.sec.gov/") for href, _text in percents + periods)
    assert percents[0][0] != periods[0][0]


def test_one_unchanged_comparison_names_the_period_by_its_head():
    current = _quarter("100", "oneunow", "2026-04-27", "2026-07-26")
    last = _quarter("100", "oneulast")
    html_text = _html(current, _column(last), None)
    assert _short(html_text) == "It was unchanged from the prior quarter."
    assert 'data-template="S1"' in html_text
    assert 'data-template="C3"' not in html_text


def test_a_rise_and_no_change_share_the_short_line():
    current = _quarter("104.2", "mixs1now", "2026-04-27", "2026-07-26")
    last = _quarter("100", "mixs1last")
    year = _quarter("104.2", "mixs1year", "2025-04-28", "2025-07-27")
    assert _short(_html(current, _column(last), _column(year))) == (
        "It rose 4.2 percent from the prior quarter and was unchanged "
        "from the same quarter a year earlier."
    )


def test_both_unchanged_comparisons_use_the_value_sentence():
    current = _quarter("100", "boths1now", "2026-04-27", "2026-07-26")
    last = _quarter("100", "boths1last")
    year = _quarter("100", "boths1year", "2025-04-28", "2025-07-27")
    html_text = _html(current, _column(last), _column(year))
    plain = _short(html_text)
    assert "Revenue was unchanged from the quarter ended April 26, 2026 at $100." in plain
    assert "Revenue was unchanged from the quarter ended July 27, 2025 at $100." in plain
    assert 'data-template="S1"' not in html_text
    assert 'data-template="C3"' in html_text


def test_a_missing_prior_quarter_keeps_one_short_clause():
    current = _quarter("300", "m6s1now", "2026-01-27", "2026-04-26")
    year = _quarter("250", "m6s1year", "2025-01-27", "2025-04-27")
    last, found = columns_for(
        current,
        role="revenue",
        form="10-Q",
        focus="Q1",
        period_end="2026-04-26",
        fiscal_year_end="--01-31",
        facts=[current, year],
    )
    html_text = _html(current, last, found, form="10-Q")
    assert _short(html_text) == "It rose 20.0 percent from the same quarter a year earlier."
    assert "for the prior quarter is not available for this filing." in html_text
    missing = re.search(r'<li class="bar-row na".*?</li>', html_text)
    assert missing is not None
    assert "bar-track" not in missing.group(0)


def test_year_to_date_names_the_same_six_or_nine_months():
    cash = make_fact(
        "900",
        concept="NetCashProvidedByUsedInOperatingActivities",
        role="operating_cash_flow",
        start="2026-02-01",
        end="2026-07-26",
        fact_id="s1ocfnow",
    )
    earlier = make_fact(
        "700",
        concept="NetCashProvidedByUsedInOperatingActivities",
        role="operating_cash_flow",
        start="2025-02-02",
        end="2025-07-27",
        fact_id="s1ocfyear",
    )
    missing = Cell(False, basis="structural", missing_period="the prior quarter")
    html_text = _html(cash, missing, _column(earlier), role="operating_cash_flow", form="10-Q")
    assert _short(html_text) == "It rose 28.6 percent from the same six months a year earlier."
    nine_now = _quarter("90", "s1ninenow", "2025-10-27", "2026-07-26")
    nine_then = _quarter("80", "s1ninethen", "2024-10-28", "2025-07-27")
    nine = _html(nine_now, missing, _column(nine_then), form="10-Q")
    assert _short(nine) == "It rose 12.5 percent from the same nine months a year earlier."


def test_an_annual_change_names_the_prior_year():
    annual = make_fact("100", start="2025-01-01", end="2025-12-31", fact_id="s1annualnow")
    prior = make_fact("80", start="2024-01-01", end="2024-12-31", fact_id="s1annualprior")
    last, year = columns_for(
        annual,
        role="revenue",
        form="10-K",
        focus="FY",
        period_end="2025-12-31",
        fiscal_year_end="--12-31",
        facts=[annual, prior],
    )
    html_text = _html(annual, last, year, form="10-K")
    assert _short(html_text) == "It rose 25.0 percent from the prior year."


def test_an_amount_only_change_stays_the_cleared_clause():
    current = make_fact(
        "150",
        concept="LongTermDebt",
        role="net_debt",
        start="2026-04-27",
        end="2026-07-26",
        fact_id="s1debtnow",
    )
    last = make_fact(
        "100",
        concept="LongTermDebt",
        role="net_debt",
        start="2026-01-26",
        end="2026-04-26",
        fact_id="s1debtlast",
    )
    html_text = _html(current, _column(last), None, measure="net_debt", role="net_debt")
    assert _short(html_text) == "It was $50 higher than the prior quarter."
    assert '<p class="cmp" data-template="S1">' in html_text


def test_a_fall_uses_the_short_line():
    current = _quarter("90", "fellnow", "2026-04-27", "2026-07-26")
    last = _quarter("100", "felllast")
    assert _short(_html(current, _column(last), None)) == "It fell 10.0 percent from the prior quarter."


def test_an_amount_only_drop_names_the_prior_quarter():
    current = make_fact(
        "50",
        concept="LongTermDebt",
        role="net_debt",
        start="2026-04-27",
        end="2026-07-26",
        fact_id="s1debtlow",
    )
    last = make_fact(
        "100",
        concept="LongTermDebt",
        role="net_debt",
        start="2026-01-26",
        end="2026-04-26",
        fact_id="s1debtearlier",
    )
    html_text = _html(current, _column(last), None, measure="net_debt", role="net_debt")
    assert _short(html_text) == "It was $50 lower than the prior quarter."
    assert 'data-template="C3"' not in _short(html_text)


def test_bars_share_a_zero_and_keep_the_value_ratio():
    current = _quarter("100", "barnow", "2026-04-27", "2026-07-26")
    last = _quarter("50", "barlast")
    year = _quarter("25", "baryear", "2025-04-28", "2025-07-27")
    html_text = _html(current, _column(last), _column(year))
    widths = _widths(html_text)
    assert widths == [Decimal("100.00"), Decimal("50.00"), Decimal("25.00")]
    assert 'style="--zero:0.00%"' in html_text
    assert abs((widths[0] / widths[2]) - (Decimal(100) / Decimal(25))) < Decimal("0.01")
    hrefs = re.findall(r'<p class="bv"><a href="([^"]+)">', html_text)
    assert len(hrefs) == 3
    assert all(href.startswith("https://www.sec.gov/") for href in hrefs)
    label = re.search(r'aria-label="([^"]+)"', html_text).group(1)
    assert label.startswith(EN["bar_chart"] + " ")
    assert "Prior quarter" in label and "$100" in label and "$25" in label
    assert html_text.count('class="bd"') == 3


def test_a_quote_in_the_bar_label_is_escaped():
    current = _quarter("100", "quotenow", "2026-04-27", "2026-07-26")
    missing = Cell(False, missing_period='the "prior" period', basis="absent")
    html_text = _html(current, missing, None)
    label = re.search(r'aria-label="([^"]*)"', html_text).group(1)
    assert "&quot;" in label
    assert '"prior"' not in label


def test_a_negative_bar_grows_left_from_the_same_zero():
    current = _quarter("100", "negnow", "2026-04-27", "2026-07-26")
    last = _quarter("-50", "neglast")
    year = _quarter("25", "negyear", "2025-04-28", "2025-07-27")
    html_text = _html(current, _column(last), _column(year))
    assert 'style="--zero:33.33%"' in html_text
    assert 'class="fill neg" style="left:0.00%;width:33.33%"' in html_text
    assert 'class="fill" style="left:33.33%;width:66.67%"' in html_text
    assert "-$50" in html_text or "$-50" in html_text or "-50" in html_text
    loss = _quarter("-40", "losscur", "2026-04-27", "2026-07-26")
    loss_html = _html(loss, _column(_quarter("80", "losslast")), _column(year))
    assert 'class="fill neg" style="left:0.00%;width:33.33%"' in loss_html


def test_the_narrow_card_and_the_disclaimer_keep_their_column():
    page = first_run_page(token="t")
    assert "border-radius: 18px" not in page
    assert page.count("border-radius: 22px") >= 2
    assert "margin-left: auto; margin-right: auto" in page


def test_the_page_frame_reads_the_english_table_and_stays_on_sec():
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
    opened = search_page("token")
    first = first_run_page()
    assert EN["your_name"] in first
    assert EN["your_email"] in first
    assert EN["save"] in first
    assert EN["erase"] in edit_page("token")
    for text in (page, opened, first):
        assert EN["app_name"] in text
        assert "Language / Sprache" in text
        assert ">English<" in text
        assert ">Deutsch<" in text
        assert "Entwurf" not in text
        assert "@font-face" not in text
        assert "<img" not in text
        assert "fonts.googleapis" not in text
    assert EN["company_or_ticker"] in opened
    assert EN["bar_chart"] in page
    assert EN["explain"] in page
    assert EN["the_filing"] in page
    assert "animation: grow 400ms" in page
    assert "prefers-reduced-motion" in page
    assert ".fill { opacity: 1; transform: none; }" in page
    for href in re.findall(r'href="([^"]+)"', page):
        target = href.replace("&amp;", "&")
        if target.startswith(("#", "/")) or "github.com" in target:
            continue
        assert target.startswith("https://www.sec.gov/") or target.startswith("https://data.sec.gov/")
