"""Column binding, scale, and period span for HTML tables."""

from decimal import Decimal
from pathlib import Path

from white_cliff.facts import Period
from white_cliff.formulas import FormulaError, margin, same_period
from white_cliff.pipeline import explain_filing
from white_cliff.tables import parse_tables
from tests.support import make_fact, write_filing

URL = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/table.htm"


def _facts(html: str):
    return parse_tables(html, "table.htm", URL, "abc")[0]


def _revenue(html: str):
    return [fact for fact in _facts(html) if fact.role == "revenue"]


def test_split_loss_uses_the_current_column_not_the_prior_year():
    html = """
    <table>
    <caption>(In millions)</caption>
    <tr><th></th><th>2026</th><th>2025</th></tr>
    <tr><td>Total net sales</td><td>(120</td><td>)</td><td>80</td></tr>
    </table>
    """
    found = _revenue(html)
    assert found
    assert found[0].value == Decimal("-120")
    assert all(fact.value != Decimal("80") for fact in found)


def test_omission_percent_and_footnote_cells_do_not_fall_through():
    cases = (
        "<td>[***]</td><td>900</td>",
        "<td>12%</td><td>80</td>",
        "<td>(1)</td><td>80</td>",
    )
    for current in cases:
        html = f"""
        <table>
        <caption>(In millions)</caption>
        <tr><th></th><th>2026</th><th>2025</th></tr>
        <tr><td>Total net sales</td>{current}</tr>
        </table>
        """
        found = _revenue(html)
        assert found == [], current
        rendered_values = {fact.value for fact in _facts(html)}
        assert Decimal("900") not in rendered_values
        assert Decimal("12") not in rendered_values
        assert Decimal("-1") not in rendered_values
        assert Decimal("80") not in rendered_values


def test_prior_column_first_still_reads_the_current_year():
    html = """
    <table>
    <caption>(In millions)</caption>
    <tr><th></th><th>2025</th><th>2026</th></tr>
    <tr><td>Total net sales</td><td>80</td><td>120</td></tr>
    </table>
    """
    found = _revenue(html)
    assert [fact.value for fact in found] == [Decimal("120")]


def test_scale_ignores_parentheticals_outside_the_table():
    own_caption = """
    <p>A note mentions amounts (in millions) for another schedule.</p>
    <table>
    <caption>(In thousands)</caption>
    <tr><th></th><th>2026</th></tr>
    <tr><td>Total net sales</td><td>1000000</td></tr>
    </table>
    """
    found = _revenue(own_caption)
    assert found
    assert found[0].value == Decimal("1000000")
    assert found[0].unit == "USD thousands"

    mentioned = """
    <p>See the schedule (in millions) discussed above.</p>
    <table>
    <tr><th></th><th>2026</th></tr>
    <tr><td>Total net sales</td><td>100</td></tr>
    </table>
    """
    assert _revenue(mentioned) == []

    header = """
    <p>Elsewhere the notes say (in millions).</p>
    <table>
    <tr><td colspan="2">(In thousands)</td></tr>
    <tr><th></th><th>2026</th></tr>
    <tr><td>Total net sales</td><td>1000000</td></tr>
    </table>
    """
    found = _revenue(header)
    assert found
    assert found[0].unit == "USD thousands"

    introducing = """
    <div>(In thousands)</div>
    <table>
    <tr><th></th><th>2026</th></tr>
    <tr><td>Total net sales</td><td>1000000</td></tr>
    </table>
    """
    found = _revenue(introducing)
    assert found
    assert found[0].value == Decimal("1000000")
    assert found[0].unit == "USD thousands"


def test_scale_comes_from_the_table_caption_only():
    html = """
    <p>Amounts are presented in millions elsewhere in this document.</p>
    <table>
    <caption>(In thousands)</caption>
    <tr><th></th><th>2026</th></tr>
    <tr><td>Total net sales</td><td>1000000</td></tr>
    </table>
    """
    found = _revenue(html)
    assert found
    assert found[0].value == Decimal("1000000")
    assert found[0].unit == "USD thousands"


def test_missing_or_conflicting_scale_refuses_the_fact():
    missing = """
    <p>in millions</p>
    <table>
    <tr><th></th><th>2026</th></tr>
    <tr><td>Total net sales</td><td>100</td></tr>
    </table>
    """
    conflict = """
    <table>
    <caption>(In millions) (In thousands)</caption>
    <tr><th></th><th>2026</th></tr>
    <tr><td>Total net sales</td><td>100</td></tr>
    </table>
    """
    assert _revenue(missing) == []
    assert _revenue(conflict) == []


def test_margin_is_not_computed_across_a_quarter_and_a_year(tmp_path: Path):
    html = """
    <table>
    <caption>(In millions)</caption>
    <tr><th></th><th>Three months ended September 26, 2026</th></tr>
    <tr><td>Total net sales</td><td>1,000</td></tr>
    </table>
    <table>
    <caption>(In millions)</caption>
    <tr><th></th><th>Year ended September 26, 2026</th></tr>
    <tr><td>Operating income</td><td>3,000</td></tr>
    </table>
    """
    directory = write_filing(tmp_path / "span", "table.htm", html, URL, form="10-Q")
    from white_cliff.pipeline import load_directory

    filing = load_directory(directory)
    explained = explain_filing(filing)
    assert "3 ratio" not in explained.markdown
    assert "operating margin" not in explained.markdown
    revenue = [fact for fact in filing.store.facts() if fact.role == "revenue"]
    income = [fact for fact in filing.store.facts() if fact.role == "operating_income"]
    assert revenue and revenue[0].value == Decimal("1000")
    assert income and income[0].value == Decimal("3000")
    assert revenue[0].period.span == "quarter"
    assert income[0].period.span == "fiscal year"
    assert revenue[0].period.end == "2026-09-26"
    assert income[0].period.end == "2026-09-26"
    with __import__("pytest").raises(FormulaError):
        margin(income[0], revenue[0], name="operating_margin")


def test_same_period_requires_span_and_end_when_dates_are_absent():
    quarter = Period(kind="duration", end="2026-09-26", span="quarter", key="income-current")
    year = Period(kind="duration", end="2026-09-26", span="fiscal year", key="income-current")
    unknown = Period(kind="duration", key="income-current")
    assert same_period(quarter, quarter)
    assert not same_period(quarter, year)
    assert not same_period(unknown, unknown)
    left = make_fact("10", start=None, end=None)
    right = make_fact("4", concept="OperatingIncomeLoss", role="operating_income", start=None, end=None)
    with __import__("pytest").raises(FormulaError):
        margin(right, left, name="operating_margin")


def _shares(html: str):
    return [fact for fact in _facts(html) if fact.role == "shares"]


def _one_share(caption: str, cell: str = "7,427", extra: str = ""):
    html = f"""
    <table>
    <caption>{caption}</caption>
    <tr><th></th><th>2026</th></tr>
    <tr><td>Shares outstanding</td><td>{cell}</td></tr>
    {extra}
    </table>
    """
    return _shares(html), html


_SHARE_CAPTIONS = (
    "(In thousands, except share and per share data)",
    "except share and per share amounts",
    "except shares and per share data",
    "except share amounts",
    "except number of shares and per share amounts",
    "except for share and per share data",
    "(In millions, except share and per share data)",
    "(In millions, except per share and share amounts)",
    "(In millions, except per share amounts)",
    "(In millions, except number of shares, which are reflected in thousands, and per-share amounts)",
)


def test_table_share_rows_are_not_rendered(tmp_path: Path):
    from white_cliff.pipeline import load_directory

    for caption in _SHARE_CAPTIONS:
        found, html = _one_share(caption, "7,427,000")
        assert found == [], caption
        assert all(fact.role != "shares" for fact in _facts(html))
        directory = write_filing(tmp_path / "shares", "table.htm", html, URL, form="10-K")
        explained = explain_filing(load_directory(directory))
        rendered = explained.markdown + explained.html
        assert "7427000" not in rendered
        assert "7,427,000" not in rendered
        assert "doesn't tag" in rendered


def test_xbrl_share_fact_still_renders(tmp_path: Path):
    from tests.support import MINI_XML
    from white_cliff.pipeline import load_directory

    directory = write_filing(tmp_path / "xbrl", "instance.xml", MINI_XML, URL, form="10-K")
    explained = explain_filing(load_directory(directory))
    rendered = explained.markdown + explained.html
    assert "50 shares" in rendered
    assert "doesn't tag" not in rendered


def test_per_share_rows_stay_unscaled():
    eps = """
    <tr><td>Earnings per share</td><td>1.25</td></tr>
    """
    found, html = _one_share("(In millions, except per share amounts)", extra=eps)
    assert found == []
    assert all("per share" not in fact.label.lower() for fact in _facts(html))
    assert all(fact.value != Decimal("1250000") for fact in _facts(html))
    assert all(fact.value != Decimal("1.25") for fact in _facts(html))


def _revenue_caption(caption: str, cell: str = "1,000"):
    html = f"""
    <table>
    <caption>{caption}</caption>
    <tr><th></th><th>2026</th></tr>
    <tr><td>Total net sales</td><td>{cell}</td></tr>
    </table>
    """
    return _revenue(html), html


def test_dollars_in_thousands_beside_shares_in_millions_is_not_millions():
    found, html = _revenue_caption("(Dollars in thousands; shares in millions)")
    assert found == [] or (len(found) == 1 and found[0].unit == "USD thousands")
    assert all(fact.unit != "USD millions" for fact in _facts(html))


def test_thousands_except_shares_in_millions_is_refused():
    found, html = _revenue_caption("(In thousands, except shares, which are in millions)")
    assert found == []
    assert all(fact.unit != "USD millions" for fact in _facts(html))


def test_one_scale_word_or_an_explicit_dollar_phrase_sets_the_unit():
    found, _html = _revenue_caption("(In billions)", "4")
    assert found and found[0].unit == "USD billions" and found[0].value == Decimal("4")
    found, _html = _revenue_caption("(Dollars in thousands)")
    assert found and found[0].unit == "USD thousands"
    found, _html = _revenue_caption("(Amounts in millions)")
    assert found and found[0].unit == "USD millions"


def test_current_cell_does_not_match_inside_the_prior_year():
    html = """
    <table>
    <caption>(In millions)</caption>
    <tr><th></th><th>2025</th><th>2026</th></tr>
    <tr><td>Total net sales</td><td>1,100</td><td>100</td></tr>
    </table>
    """
    found = _revenue(html)
    assert found and found[0].value == Decimal("100")
    start, end = found[0].source.char_start, found[0].source.char_end
    assert html[start:end] == "100"
    assert html[start - 1] not in "0123456789,"


def test_year_only_header_does_not_invent_december_31(tmp_path: Path):
    html = """
    <table>
    <caption>(In millions)</caption>
    <tr><th></th><th>2026</th></tr>
    <tr><td>Total net sales</td><td>1,000</td></tr>
    </table>
    <table>
    <caption>(In millions)</caption>
    <tr><th></th><th>2026</th></tr>
    <tr><td>Operating income</td><td>3,000</td></tr>
    </table>
    """
    facts = _facts(html)
    revenue = [fact for fact in facts if fact.role == "revenue"]
    income = [fact for fact in facts if fact.role == "operating_income"]
    assert revenue and revenue[0].period.end == ""
    assert income and income[0].period.end == ""
    assert revenue[0].period.end != "2026-12-31"
    with __import__("pytest").raises(FormulaError):
        margin(income[0], revenue[0], name="operating_margin")
    directory = write_filing(tmp_path / "year", "table.htm", html, URL, form="10-K")
    from white_cliff.pipeline import load_directory

    explained = explain_filing(load_directory(directory))
    assert "operating margin" not in explained.markdown


def test_filer_apostrophe_survives_html_escape(tmp_path: Path):
    html = """
    <p>Lowe's Companies</p>
    <table>
    <caption>(In millions)</caption>
    <tr><th></th><th>2026</th></tr>
    <tr><td>Total net sales</td><td>1,000</td></tr>
    </table>
    """
    directory = write_filing(
        tmp_path / "lowes",
        "table.htm",
        html,
        URL,
        form="10-K",
        filer="Lowe's Companies",
    )
    from white_cliff.pipeline import load_directory

    explained = explain_filing(load_directory(directory))
    assert "Lowe's" in explained.markdown
    assert "Lowe's" in explained.html
    assert "&#x27;" not in explained.html
    assert "Lowe&#" not in explained.html
    assert "registrant-chip" in explained.html
    assert "Registrant name in the filing" in explained.html


def test_cell_pointer_skips_numbers_inside_comments():
    html = """
    <table>
    <caption>(In millions)</caption>
    <tr><th></th><th>2026</th></tr>
    <tr><td>Total net sales</td><td><!-- 100 -->100</td></tr>
    </table>
    """
    found = _revenue(html)
    assert found and found[0].value == Decimal("100")
    start, end = found[0].source.char_start, found[0].source.char_end
    assert html[start:end] == "100"
    assert "<!--" not in html[start:end]
    assert html[:start].rstrip().endswith("-->")


def test_filer_name_is_a_registrant_chip_or_the_filer(tmp_path: Path):
    from white_cliff.pipeline import load_directory

    def explained_for(name: str, *, present: bool):
        body = f"<p>{name}</p>" if present else "<p>Example Co</p>"
        html = f"""
        {body}
        <table>
        <caption>(In millions)</caption>
        <tr><th></th><th>2026</th></tr>
        <tr><td>Total net sales</td><td>1,000</td></tr>
        </table>
        """
        directory = write_filing(tmp_path / "name", "table.htm", html, URL, form="10-K", filer=name)
        return explain_filing(load_directory(directory))

    shown = explained_for("Best Buy Co., Inc.", present=True)
    rendered = shown.markdown + shown.html
    assert "Best Buy Co., Inc." in rendered
    assert "Registrant name in the filing" in rendered
    assert "#registrant=" in rendered
    assert "https://www.sec.gov/" in rendered
    assert "advice" not in shown.reasons

    priced = explained_for("PEG Inc", present=True)
    assert "PEG Inc" in priced.markdown
    assert "price metric" not in priced.reasons

    counted = explained_for("Twelve Inc", present=True)
    assert "Twelve Inc" in counted.markdown
    assert counted.reasons == [] or "number word" not in counted.reasons

    missing = explained_for("Revenue 99999 USD millions", present=False)
    missing_text = missing.markdown + missing.html
    assert "the filer" in missing_text
    assert "99999" not in missing_text
    assert "Revenue 99999 USD millions" not in missing_text

    for name in (
        "Best **Buy**",
        "Best\nBuy",
        "A" * 101,
        "Buy [now](https://example.com)",
    ):
        hidden = explained_for(name, present=True)
        rendered = hidden.markdown + hidden.html
        assert "the filer" in rendered
        assert name not in rendered
        assert "**" not in rendered
        assert "example.com" not in rendered
