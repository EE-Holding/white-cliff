"""German lines stay off the page until a translation is recorded."""

import re
from decimal import Decimal

from tests.support import make_fact
from white_cliff.checks import CheckResult, ItemShare, check_dilution, check_inventory, check_tax
from white_cliff.compare import Cell
from white_cliff.i18n import using
from white_cliff.lexicon import STRINGS
from white_cliff.wording import (
    _check_html,
    _comparison_block,
    _german_reason,
    _parts_html,
    _section_parts,
    quality_html,
)

_UNTRANSLATED_REASONS = (
    "The earlier revenue figure is zero or less.",
    "The earlier cost of sales figure is zero or less.",
    "The basic share count is zero or less.",
)
_UNLABELLED_FIGURES = {
    "Inventory": "LBL.inventory",
    "Cost of sales": "LBL.cost_of_sales",
    "Basic shares": "LBL.basic_shares",
    "Pre-tax income": "LBL.pretax",
}


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _pair(concept: str, role: str, now: str, then: str, *, kind: str = "duration", unit: str = "USD"):
    if kind == "instant":
        current = make_fact(
            now,
            concept=concept,
            role=role,
            unit=unit,
            kind="instant",
            start=None,
            end="2025-12-31",
            fact_id="fact" + concept.lower()[:10].ljust(10, "n") + "now",
        )
        prior = make_fact(
            then,
            concept=concept,
            role=role,
            unit=unit,
            kind="instant",
            start=None,
            end="2024-12-31",
            fact_id="fact" + concept.lower()[:10].ljust(10, "o") + "old",
        )
        return current, prior
    current = make_fact(
        now,
        concept=concept,
        role=role,
        unit=unit,
        start="2025-01-01",
        end="2025-12-31",
        fact_id="fact" + concept.lower()[:10].ljust(10, "n") + "now",
    )
    prior = make_fact(
        then,
        concept=concept,
        role=role,
        unit=unit,
        start="2024-01-01",
        end="2024-12-31",
        fact_id="fact" + concept.lower()[:10].ljust(10, "o") + "old",
    )
    return current, prior


def _section(page: str, check_id: str) -> str:
    return page.split(f'data-check="{check_id}"', 1)[1].split("</section>", 1)[0]


def test_untranslated_not_run_reasons_are_recorded_and_hidden_in_german():
    by_english = {english: deutsch for english, deutsch in STRINGS.values()}
    for reason in _UNTRANSLATED_REASONS:
        assert reason in by_english
        deutsch = by_english[reason]
        assert deutsch and deutsch != reason
        assert "TODO" not in deutsch
        assert not any(letter in deutsch for letter in "äöüÄÖÜß")

    inventory_now, inventory_then = _pair("InventoryNet", "inventory", "40", "30", kind="instant")
    revenue_now, revenue_then = _pair("Revenues", "revenue", "20", "0")
    revenue_reason = check_inventory(
        [inventory_now, inventory_then, revenue_now, revenue_then],
        form="10-K",
        period_end="2025-12-31",
    )
    assert revenue_reason.reason == "The earlier revenue figure is zero or less."
    cost_now, cost_then = _pair("CostOfGoodsAndServicesSold", "cost", "20", "0")
    cost_reason = check_inventory(
        [inventory_now, inventory_then, cost_now, cost_then],
        form="10-K",
        period_end="2025-12-31",
    )
    assert cost_reason.reason == "The earlier cost of sales figure is zero or less."
    diluted_now, diluted_then = _pair(
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "shares",
        "100",
        "90",
        unit="shares",
    )
    basic_now, basic_then = _pair(
        "WeightedAverageNumberOfSharesOutstandingBasic",
        "shares",
        "0",
        "80",
        unit="shares",
    )
    basic_reason = check_dilution(
        [diluted_now, diluted_then, basic_now, basic_then],
        form="10-K",
        period_end="2025-12-31",
    )
    assert basic_reason.reason == "The basic share count is zero or less."

    with using("de"):
        revenue_page = quality_html(
            [inventory_now, inventory_then, revenue_now, revenue_then],
            form="10-K",
            period_end="2025-12-31",
        )
        cost_page = quality_html(
            [inventory_now, inventory_then, cost_now, cost_then],
            form="10-K",
            period_end="2025-12-31",
        )
        basic_page = quality_html(
            [diluted_now, diluted_then, basic_now, basic_then],
            form="10-K",
            period_end="2025-12-31",
        )
    for page, reason in (
        (revenue_page, "The earlier revenue figure is zero or less."),
        (cost_page, "The earlier cost of sales figure is zero or less."),
        (basic_page, "The basic share count is zero or less."),
    ):
        assert reason not in page
        assert by_english[reason] not in page
        assert "Abgleich: nicht durchgeführt:" not in _section(page, "C3" if "cost" in reason or "revenue" in reason else "C6")
    english = quality_html(
        [inventory_now, inventory_then, cost_now, cost_then],
        form="10-K",
        period_end="2025-12-31",
    )
    assert "The earlier cost of sales figure is zero or less." in english


def test_a_missing_figure_without_a_german_label_is_left_off_the_german_page():
    for english, key in _UNLABELLED_FIGURES.items():
        assert key in STRINGS
        assert STRINGS[key] == (english, STRINGS[key][1])
        assert STRINGS[key][1] and STRINGS[key][1] != english
        assert "TODO" not in STRINGS[key][1]
        assert not any(letter in STRINGS[key][1] for letter in "äöüÄÖÜß")
    with using("de"):
        cash = _german_reason("Operating cash flow is not in the filing.")
        assert cash == "„Operativer Cashflow“ ist im Bericht nicht enthalten."
        for english in _UNLABELLED_FIGURES:
            assert _german_reason(f"{english} is not in the filing.") is None
            page = _check_html(CheckResult("C8", "not_run", f"{english} is not in the filing."))
            assert english not in page
            assert "ist im Bericht nicht enthalten" not in page
            assert STRINGS[_UNLABELLED_FIGURES[english]][1] not in page
    shown = _check_html(CheckResult("C8", "not_run", "Pre-tax income is not in the filing."))
    assert "Pre-tax income is not in the filing." in shown


def test_a_german_item_line_never_shows_an_internal_name():
    operating = make_fact(
        "100",
        concept="OperatingIncomeLoss",
        role="operating_income",
        start="2025-01-01",
        end="2025-12-31",
        fact_id="factoperatingincome",
    )
    known = make_fact(
        "20",
        concept="GoodwillImpairmentLoss",
        role="one_off",
        start="2025-01-01",
        end="2025-12-31",
        fact_id="factgoodwillimpairm",
    )
    unknown = make_fact(
        "30",
        concept="UnlabelledOneOffItem",
        role="one_off",
        start="2025-01-01",
        end="2025-12-31",
        fact_id="factunlabelleditemx",
    )
    result = CheckResult(
        "C4",
        "unusual",
        facts=(known, unknown, operating),
        items=(
            ItemShare(known, Decimal("0.20"), True),
            ItemShare(unknown, Decimal("0.30"), True),
        ),
        numbers={"operating": Decimal("100")},
    )
    with using("de"):
        page = _check_html(result)
    assert "UnlabelledOneOffItem" not in page
    assert "Wertminderung des Geschäfts- oder Firmenwerts" in page
    english = _check_html(result)
    assert "UnlabelledOneOffItem" not in english
    assert "goodwill impairment" in english


def test_a_restated_figure_does_not_repeat_the_article():
    current = make_fact(
        "10",
        start="2025-07-01",
        end="2025-09-30",
        fact_id="factrestatecurrentx",
    )
    shown = make_fact(
        "8",
        start="2025-04-01",
        end="2025-06-30",
        fact_id="factrestateshownxxxx",
    )
    original = make_fact(
        "7",
        start="2025-04-01",
        end="2025-06-30",
        fact_id="factrestateoriginal",
    )
    last = Cell(
        True,
        value=shown.value,
        unit=shown.unit,
        period_end=shown.period.end or "",
        period_start=shown.period.start,
        kind="duration",
        fact=shown,
        revised_from=original,
    )
    _face, lines = _comparison_block(
        "revenue",
        current,
        last,
        None,
        "money",
        "quarterly report",
        "2026-01-15",
    )
    text = _plain(lines)
    assert "The the " not in text
    assert "The quarter ended" in text
    assert "figure is shown as restated" in text


def test_a_company_name_ending_in_a_stop_is_not_given_another():
    fact = make_fact(
        "1",
        start="2025-07-01",
        end="2025-09-30",
        fact_id="factcompanystopname",
    )
    english = _plain(
        _parts_html(
            "SECTION",
            _section_parts("Revenue", "Income statement", "Alphabet Inc.", "quarterly report", fact),
        )
    )
    assert "Alphabet Inc.." not in english
    assert "Alphabet Inc." in english
    with using("de"):
        german = _plain(
            _parts_html(
                "SECTION",
                _section_parts("Umsatz", "Gewinn- und Verlustrechnung", "Alphabet Inc.", "Quartalsbericht", fact),
            )
        )
        named = _plain(
            _parts_html(
                "SECTION",
                _section_parts("Umsatz", "Gewinn- und Verlustrechnung", "NVIDIA CORP", "Quartalsbericht", fact),
            )
        )
    assert "Alphabet Inc.." not in german
    assert "von Alphabet Inc." in german
    assert "von NVIDIA CORP." in named
    assert "NVIDIA CORP.." not in named
