"""Cleared batch-1 wording. Each blocking rule is one test."""

import html
import re

from white_cliff.checks import check_margins
from white_cliff.desktop_copy import EMPTY_QUERY, NO_MATCH, SEC_WHY
from decimal import Decimal

from white_cliff.i18n import using
from white_cliff.lexicon import STRINGS
from white_cliff.present import error_page, first_run_page, search_page, shown_amount
from white_cliff.wording import quality_html, show_measure
from tests.support import make_fact
from tests.test_cards import _column, _html
from tests.test_checks import _pair
from tests.test_desktop_app import _app

U1_EN = (
    "You do this once. The SEC is the US government agency that publishes company reports "
    "on sec.gov. It asks for a name and email; they stay on this computer and go only to sec.gov."
)
U1_DE = (
    "Dieser Schritt ist einmalig. Die SEC ist die US-Behörde, die Unternehmensberichte auf "
    "sec.gov veröffentlicht. Sie verlangt einen Namen und eine E-Mail-Adresse; diese bleiben "
    "auf diesem Computer und gehen ausschließlich an sec.gov."
)
U4_EN = (
    "White Cliff looks for the company on the SEC list. Check the spelling, or try the full "
    "company name or its ticker."
)
U4_DE = (
    "White Cliff sucht das Unternehmen auf der SEC-Liste. Prüfen Sie die Schreibweise oder "
    "versuchen Sie es mit dem vollständigen Unternehmensnamen oder dem Tickersymbol."
)
U8_GROSS_EN = "Gross margin: gross profit as a percent of revenue"
U8_GROSS_DE = "Bruttomarge: Bruttoergebnis in Prozent des Umsatzes"
U8_OP_EN = "Operating margin: operating income as a percent of revenue"
U8_NET_EN = "Net margin: net income attributable to the company as a percent of revenue"
U9_LBL_EN = "Debt minus cash"
U9_LBL_DE = "Finanzschulden abzüglich Zahlungsmittel"
U9_NEG_EN = "A figure below zero means cash was larger than debt."
U9_NEG_DE = (
    "Ein Wert unter null bedeutet, dass die Zahlungsmittel höher waren als die Finanzschulden."
)
U10_HEAD_EN = "Checks on the company's own numbers"
U10_MARKED_EN = "Check: marked"
U10_OPEN_EN = "Check: not marked"
U10_C1_EN = "Profit and operating cash flow"
U10_C8_EN = "Income tax and income before tax"
U10_OC_EN = (
    "A gap can come from when customers pay, building up inventory, large gains that brought "
    "in no cash, or when taxes and suppliers are paid. The filing's cash flow statement and "
    "notes may explain it."
)
U10_C8_NUM_EN = (
    "Income tax was {rate_t} percent of income before tax in {period} and {rate_p} percent "
    "in {period_prior}, a change of {d} percentage points."
)
PRINT_EN = "Print summary"
PRINT_DE = "Zusammenfassung drucken"
SOURCES_EN = "Sources on sec.gov"
SOURCES_DE = "Quellen auf sec.gov"
OLD_GROSS = "The gross margin (gross profit / revenue)"


def test_the_cleared_strings_are_stored_verbatim():
    expected = {
        "U1.lead": (U1_EN, U1_DE),
        "U2.placeholder": ("e.g. Apple or AAPL", "z. B. Apple oder AAPL"),
        "U4.next": (U4_EN, U4_DE),
        "U8.lbl.gross_margin": (U8_GROSS_EN, U8_GROSS_DE),
        "U8.lbl.operating_margin": (
            U8_OP_EN,
            "Operative Marge: Betriebsergebnis in Prozent des Umsatzes",
        ),
        "U8.lbl.net_margin": (
            U8_NET_EN,
            "Nettomarge: auf das Unternehmen entfallendes Nettoergebnis in Prozent des Umsatzes",
        ),
        "U8.line.two": (
            "It {rose|fell} {pp} from the prior quarter and {rose|fell} {pp} from the same quarter a year earlier.",
            "Der Wert {stieg|sank} um {pp} gegenüber dem Vorquartal und {stieg|sank} um {pp} gegenüber dem gleichen Quartal ein Jahr zuvor.",
        ),
        "U8.line.ytd": (
            "It {rose|fell} {pp} from the same {six|nine} months a year earlier.",
            "Der Wert {stieg|sank} um {pp} gegenüber den gleichen {sechs|neun} Monaten ein Jahr zuvor.",
        ),
        "U8.line.10k": (
            "It {rose|fell} {pp} from the prior year.",
            "Der Wert {stieg|sank} um {pp} gegenüber dem Vorjahr.",
        ),
        "U8.line.m6": (
            "It {rose|fell} {pp} from the same quarter a year earlier.",
            "Der Wert {stieg|sank} um {pp} gegenüber dem gleichen Quartal ein Jahr zuvor.",
        ),
        "U8.unchanged": (
            "was unchanged from {period}",
            "blieb unverändert gegenüber dem {period}",
        ),
        "U9.lbl.net_debt": (U9_LBL_EN, U9_LBL_DE),
        "U9.neg": (U9_NEG_EN, U9_NEG_DE),
        "U10.heading": (U10_HEAD_EN, "Abgleiche der eigenen Zahlen des Unternehmens"),
        "U10.marker.marked": (U10_MARKED_EN, "Abgleich: markiert"),
        "U10.marker.notmarked": (U10_OPEN_EN, "Abgleich: nicht markiert"),
        "U10.marker.notrun": (
            "Check: not run: {plain reason}",
            "Abgleich: nicht durchgeführt: {plain reason}",
        ),
        "U10.h.C1": (U10_C1_EN, "Ergebnis und operativer Cashflow"),
        "U10.h.C2": ("Receivables and revenue", "Forderungen und Umsatz"),
        "U10.h.C3": ("Inventory and cost of sales", "Vorräte und Umsatzkosten"),
        "U10.h.C4": (
            "Items tagged as restructuring, impairment, disposal or acquisition costs",
            "Als Restrukturierung, Wertminderung, Abgang oder Erwerbskosten gekennzeichnete Posten",
        ),
        "U10.h.C6": ("Diluted and basic shares", "Verwässerte und unverwässerte Aktienzahl"),
        "U10.h.C7": ("Gross margin and operating margin", "Bruttomarge und operative Marge"),
        "U10.h.C8": (U10_C8_EN, "Ertragsteuer und Ergebnis vor Steuern"),
        "U10.C1.oc": (
            U10_OC_EN,
            "Ein Unterschied kann darauf zurückgehen, wann Kunden zahlen, auf den Aufbau von Vorräten, auf hohe Erträge ohne Zahlungseingang oder darauf, wann Steuern und Lieferanten bezahlt werden. Die Kapitalflussrechnung und der Anhang des Berichts können dies erläutern.",
        ),
        "U10.C8.numbers": (
            U10_C8_NUM_EN,
            "Die Ertragsteuer lag bei {rate_t} Prozent des Ergebnisses vor Steuern im {period} und bei {rate_p} Prozent im {period_prior}, eine Veränderung um {d} Prozentpunkte.",
        ),
        "PRINT.button": (PRINT_EN, PRINT_DE),
        "PRINT.sources": (SOURCES_EN, SOURCES_DE),
    }
    for ident, pair in expected.items():
        assert STRINGS.get(ident) == pair
        german = pair[1]
        assert " nur " not in f" {german} "
        assert "sicher" not in german.casefold()
        assert "Anlage" not in german
    for ident, pair in expected.items():
        assert "safe" not in pair[0].casefold()
        assert "secure" not in pair[0].casefold()


def test_the_lead_sits_above_the_unchanged_sec_explanation():
    page = first_run_page()
    assert U1_EN in page
    assert SEC_WHY in page
    assert page.index(U1_EN) < page.index(SEC_WHY)
    assert STRINGS["SEC_WHY"][0] == SEC_WHY
    with using("de"):
        german = first_run_page()
    assert U1_DE in german
    assert german.index(U1_DE) < german.index(STRINGS["SEC_WHY"][1])


def test_the_search_placeholder_is_not_a_value_or_a_list(monkeypatch, tmp_path):
    page = search_page("t")
    assert 'placeholder="e.g. Apple or AAPL"' in page
    assert 'value="e.g. Apple or AAPL"' not in page
    assert re.search(r'<input id="query"[^>]*value=', page) is None
    stripped = re.sub(r' placeholder="[^"]*"', "", page)
    assert "Apple" not in stripped
    assert "popular" not in page.casefold()
    assert "<ul" not in page
    app = _app(monkeypatch, tmp_path)
    app.handle("POST", "/identity", {"name": "Example Person", "email": "person@example.com"})
    empty = app.handle("POST", "/explain", {"query": ""})
    assert EMPTY_QUERY in empty.body
    assert 'value="e.g. Apple or AAPL"' not in empty.body
    with using("de"):
        deutsch = search_page("t")
    assert 'placeholder="z. B. Apple oder AAPL"' in deutsch


def test_the_no_match_box_carries_the_next_step_under_the_notice():
    page = error_page(NO_MATCH, "t", "zzzz")
    box = page.split('id="failure"', 1)[1].split("</div>", 1)[0]
    assert NO_MATCH in box
    assert U4_EN in box
    assert box.index(NO_MATCH) < box.index(U4_EN)
    with using("de"):
        german = error_page(NO_MATCH, "t", "zzzz")
    german_box = german.split('id="failure"', 1)[1].split("</div>", 1)[0]
    assert STRINGS["NO_MATCH"][1] in german_box
    assert U4_DE in german_box


def test_a_margin_change_is_the_gap_between_the_shown_percents():
    rose = _html(
        _percent("74.96", "ppnow", "2026-04-27", "2026-07-26"),
        _column(_percent("74.94", "ppthen")),
        None,
        measure="margin",
        role="gross_margin",
    )
    assert "rose 0.1 percentage points from the prior quarter" in _plain(rose)
    assert "was unchanged" not in _plain(rose)
    assert re.search(r"rose [\d.]+ percent from", _plain(rose)) is None
    same = _html(
        _percent("75.04", "eqnow", "2026-04-27", "2026-07-26"),
        _column(_percent("74.96", "eqthen")),
        None,
        measure="margin",
        role="gross_margin",
    )
    assert "was unchanged from the prior quarter" in _plain(same)
    assert "percentage points" not in _plain(same)
    revenue_now, revenue_then = _pair("Revenues", "revenue", "1000", "1000")
    gross_now, gross_then = _pair("GrossProfit", "gross_profit", "749.6", "749.4")
    result = check_margins(
        [revenue_now, revenue_then, gross_now, gross_then],
        form="10-K",
        period_end="2025-12-31",
    )
    assert result.numbers["gm_delta"] == result.numbers["gm_now"] - result.numbers["gm_then"]
    assert result.numbers["gm_delta"] == result.numbers["gm_now"].__class__("0.1")
    page = quality_html(
        [revenue_now, revenue_then, gross_now, gross_then],
        form="10-K",
        period_end="2025-12-31",
    )
    check = page.split('data-check="C7"', 1)[1].split("</section>", 1)[0]
    assert "0.1 percentage points" in check
    assert "0.0 percentage points" not in check
    with using("de"):
        german = _html(
            _percent("74.96", "deppnow", "2026-04-27", "2026-07-26"),
            _column(_percent("74.94", "deppthen")),
            None,
            measure="margin",
            role="gross_margin",
        )
    assert show_measure(Decimal("2.6"), "percentage points") == "2.6 percentage points"
    assert "stieg um 0,1\u00a0Prozentpunkte gegenüber dem Vorquartal" in _visible(german)
    with using("de"):
        german_points = show_measure(Decimal("2.6"), "percentage points")
    assert german_points == "2,6\u00a0Prozentpunkte"


def test_margin_names_move_behind_explain_and_a_negative_debt_note_shows_once():
    from white_cliff.present import _plain_label

    assert _plain_label("The gross margin (gross profit / revenue) for the quarter was") == U8_GROSS_EN
    assert _plain_label("The operating margin (operating income / revenue) was") == U8_OP_EN
    assert _plain_label("The net margin (net income attributable to the company / revenue) was") == U8_NET_EN
    debt = "Long-term debt, including current maturities minus cash and cash equivalents was"
    assert _plain_label(debt) == U9_LBL_EN
    with using("de"):
        assert _plain_label("The gross margin (gross profit / revenue) was") == U8_GROSS_DE
        assert _plain_label(debt) == U9_LBL_DE
    below = _html(
        _money("-20", "debtneg", "2026-04-27", "2026-07-26", role="net_debt"),
        _column(_money("-10", "debtnegold", role="net_debt")),
        None,
        measure="net_debt",
        role="net_debt",
    )
    assert below.count(U9_NEG_EN) == 1
    above = _html(
        _money("20", "debtpos", "2026-04-27", "2026-07-26", role="net_debt"),
        _column(_money("10", "debtposold", role="net_debt")),
        None,
        measure="net_debt",
        role="net_debt",
    )
    assert U9_NEG_EN not in above
    money = _html(
        _money("-20", "revneg", "2026-04-27", "2026-07-26"),
        _column(_money("-10", "revnegold")),
        None,
    )
    assert U9_NEG_EN not in money
    from white_cliff.wording import _computed_formula, _explain_block

    debt_fact = _money("100", "debtfull", role="debt", concept="LongTermDebt")
    cash_fact = _money("30", "cashfull", role="cash", concept="CashAndCashEquivalentsAtCarryingValue")
    detail = _explain_block(
        "net_debt",
        debt_fact,
        "Example Co",
        "Balance sheet",
        _computed_formula("net_debt", [("debt", debt_fact), ("cash", cash_fact)]),
        [("debt", debt_fact), ("cash", cash_fact)],
    )
    assert "cash and cash equivalents" in detail
    assert U9_LBL_EN not in detail
    formula = _computed_formula("gross_margin")
    assert formula == OLD_GROSS
    shown = _explain_block(
        "gross_margin",
        _percent("40", "gmfact", "2026-04-27", "2026-07-26"),
        "Example Co",
        "Income statement",
        formula,
        [
            ("gross profit", _money("40", "gpfull")),
            ("revenue", _money("100", "revfull")),
        ],
    )
    plain = _plain(shown)
    assert "The gross margin (gross profit / revenue) is gross profit divided by revenue." in plain
    assert "It is calculated as the gross margin (gross profit / revenue), using " in plain
    assert "It is calculated as The " not in plain
    assert U8_GROSS_EN not in plain


def test_explain_sentences_use_the_lbl_names_in_english_and_german():
    from white_cliff.wording import _computed_formula, _explain_block

    formula = _computed_formula("net_margin")
    shown = _explain_block(
        "net_margin",
        _percent("10", "nmfact", "2026-04-27", "2026-07-26"),
        "Example Co",
        "Income statement",
        formula,
        [
            ("net income", _money("10", "nifull", role="net_income", concept="NetIncomeLoss")),
            ("revenue", _money("100", "nmrev")),
        ],
    )
    plain = _plain(shown)
    assert (
        "The net margin (net income attributable to the company / revenue) is net income divided by revenue."
        in plain
    )
    assert U8_NET_EN not in plain
    assert "It is calculated as the net margin (net income attributable to the company / revenue), using " in plain
    with using("de"):
        german_formula = _computed_formula("operating_margin")
        german = _explain_block(
            "operating_margin",
            _percent("20", "omfact", "2026-04-27", "2026-07-26"),
            "Example Co",
            "Income statement",
            german_formula,
            [
                ("operating income", _money("20", "oifull", role="operating_income", concept="OperatingIncomeLoss")),
                ("revenue", _money("100", "omrev")),
            ],
        )
    german_plain = _plain(german)
    assert STRINGS["LBL.operating_margin"][1] in german_plain
    assert STRINGS["U8.lbl.operating_margin"][1] not in german_plain
    assert "It is calculated as The " not in german_plain


def test_a_zero_margin_change_keeps_the_cleared_c7_line():
    """C7 has no cleared 'was unchanged' sentence, so a zero change stays the numbers line."""
    revenue_now, revenue_then = _pair("Revenues", "revenue", "1000", "1000")
    gross_now, gross_then = _pair("GrossProfit", "gross_profit", "500", "500")
    operating_now, operating_then = _pair("OperatingIncomeLoss", "operating_income", "200", "200")
    facts = [revenue_now, revenue_then, gross_now, gross_then, operating_now, operating_then]
    page = quality_html(facts, form="10-K", period_end="2025-12-31")
    check = _plain(page.split('data-check="C7"', 1)[1].split("</section>", 1)[0])
    assert "a change of 0.0 percentage points" in check
    assert "was unchanged" not in check
    with using("de"):
        german = quality_html(facts, form="10-K", period_end="2025-12-31")
    german_check = german.split('data-check="C7"', 1)[1].split("</section>", 1)[0]
    assert "eine Veränderung um 0,0 Prozentpunkte" in _plain(german_check)
    assert "blieb unverändert" not in _plain(german_check)


def test_negative_money_keeps_the_minus_before_the_dollar():
    assert shown_amount("-4767 USD millions") == "\u2212$4,767 million"
    assert show_measure(__import__("decimal").Decimal("-4767"), "USD millions") == "\u2212$4,767 million"
    chart = _html(
        _money("-4767", "barneg", "2026-04-27", "2026-07-26"),
        _column(_money("100", "barold")),
        None,
    )
    label = re.search(r'aria-label="([^"]*)"', chart)
    assert label is not None
    assert "\u2212$4,767 million" in label.group(1)
    assert "\u2212$4,767 million" in chart
    with using("de"):
        german = show_measure(__import__("decimal").Decimal("-4767"), "USD millions")
    assert german == "\u2212" + "4.767\u00a0Mio.\u00a0USD"


def test_checks_use_one_heading_and_marked_or_not_marked():
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
    intro = page.split('<section class="check"', 1)[0]
    intro_text = html.unescape(intro)
    assert intro.count("<h2") == 1
    assert U10_HEAD_EN in intro_text
    assert STRINGS["F.checks"][0] in intro_text
    assert STRINGS["Q.limit"][0] in intro_text
    assert intro_text.index(U10_HEAD_EN) < intro_text.index(STRINGS["F.checks"][0]) < intro_text.index(STRINGS["Q.limit"][0])
    assert "detail" not in intro
    visible = html.unescape(page)
    assert visible.count(STRINGS["Q.limit"][0]) == 1
    assert visible.count(STRINGS["F.checks"][0]) == 1
    assert "Check: unusual" not in page
    assert "Check: consistent" not in page
    assert U10_MARKED_EN in page
    assert " of 7" not in page
    assert re.search(r"\d+ checks", page) is None
    check = page.split('data-check="C1"', 1)[1].split("</section>", 1)[0]
    assert f"<h3>{U10_C1_EN}</h3>" in check
    face, panel = check.split('class="detail"', 1)
    panel_text = html.unescape(panel)
    assert U10_MARKED_EN in face
    assert "This check marks results below 0.80 times." in panel_text
    assert U10_OC_EN in panel_text
    assert STRINGS["Q.limit"][0] not in html.unescape(check)
    assert 'class="marker"' in check
    assert "color:" not in re.search(r'<p class="marker"[^>]*>', check).group(0)
    quiet_income, quiet_prior = _pair("NetIncomeLoss", "net_income", "100", "100")
    quiet_cash, quiet_cash_prior = _pair(
        "NetCashProvidedByUsedInOperatingActivities",
        "operating_cash_flow",
        "100",
        "100",
    )
    quiet = quality_html(
        [quiet_income, quiet_prior, quiet_cash, quiet_cash_prior],
        form="10-K",
        period_end="2025-12-31",
    )
    quiet_c1 = quiet.split('data-check="C1"', 1)[1].split("</section>", 1)[0]
    assert U10_OPEN_EN in quiet_c1
    assert U10_MARKED_EN not in quiet_c1
    missed = quality_html([income, prior], form="10-K", period_end="2025-12-31")
    missed_c1 = missed.split('data-check="C1"', 1)[1].split("</section>", 1)[0]
    assert "Check: not run: Operating cash flow is not in the filing." in missed_c1
    headings = [html.unescape(item) for item in re.findall(r"<h2[^>]*>([^<]*)</h2>", page)]
    assert headings == [U10_HEAD_EN]


def _percent(value, fact_id, start="2026-01-26", end="2026-04-26"):
    from dataclasses import replace

    fact = make_fact(value, start=start, end=end, fact_id=fact_id)
    return replace(fact, unit="percent", role="gross_margin")


def _money(
    value,
    fact_id,
    start="2026-01-26",
    end="2026-04-26",
    role="revenue",
    concept="Revenues",
    unit="USD millions",
):
    return make_fact(
        value, concept=concept, role=role, unit=unit, start=start, end=end, fact_id=fact_id
    )


def _plain(html_text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_text))


def _visible(html_text: str) -> str:
    return re.sub(r"<[^>]+>", "", html_text)
