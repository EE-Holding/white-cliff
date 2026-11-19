"""Signed explain figures, the tax rate, and the German lines from the cleared table."""

import re
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from tests.support import make_fact
from white_cliff.checks import check_tax
from white_cliff.i18n import using
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.present import result_page
from white_cliff.wording import _explain_amount, _german_gap, _german_reason, label_for, quality_html, show_measure

PINNED = Path(__file__).resolve().parents[1] / "pinned" / "filings"
_FIGURE = re.compile(r'<a class="figure"[^>]*>(.*?)</a>', re.S)
_CARD = re.compile(r"<article class=\"card\".*?</article>", re.S)
_E2 = re.compile(r'data-template="E2">(.*?)</p>', re.S)
_LINK = re.compile(r"<a\b[^>]*>(.*?)</a>", re.S)


def _plain(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).replace("\u00a0", " ").replace("\u2212", "-").strip()


def _page(directory: Path, language: str) -> str:
    filing = load_directory(directory)
    explained = explain_filing(filing)
    with using(language):
        return result_page(
            explained,
            form=filing.form,
            period=filing.period_end or "",
            filed="2026-01-01",
            url=filing.url,
            company=filing.filer,
            focus=filing.focus,
            fiscal_year_end=filing.fiscal_year_end,
        )


def test_nvidia_income_tax_uses_the_millions_not_zero():
    filing = load_directory(PINNED / "0001045810-26-000075")
    result = check_tax(filing.store.facts(), form=filing.form, period_end=filing.period_end or "")
    assert result.outcome != "not_run"
    assert result.numbers["rate_now"] == Decimal("16.5")
    assert result.numbers["rate_then"] == Decimal("15.3")
    shown = quality_html(filing.store.facts(), form=filing.form, period_end=filing.period_end)
    assert "16.5 percent" in shown
    assert "15.3 percent" in shown
    assert "1.2 percentage points" in shown
    assert "0.0 percent" not in shown


def test_a_scale_mismatch_is_not_shown_as_zero():
    tax = replace(
        make_fact(
            "11.8",
            concept="IncomeTaxExpenseBenefit",
            role="tax",
            unit="USD billions",
            fact_id="facttaxbillions",
            start="2026-04-27",
            end="2026-07-26",
        ),
        scale=9,
        decimals=-8,
    )
    pretax = replace(
        make_fact(
            "71507",
            concept="IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            role="pretax",
            unit="USD millions",
            fact_id="factpretaxmillns",
            start="2026-04-27",
            end="2026-07-26",
        ),
        scale=6,
        decimals=-6,
    )
    prior_tax = replace(
        tax,
        id="facttaxpriorbill",
        value=Decimal("4.8"),
        period=replace(tax.period, start="2025-04-28", end="2025-07-27"),
    )
    prior_pre = replace(
        pretax,
        id="factpretaxpriorm",
        value=Decimal("31206"),
        period=replace(pretax.period, start="2025-04-28", end="2025-07-27"),
    )
    result = check_tax(
        [tax, pretax, prior_tax, prior_pre],
        form="10-Q",
        period_end="2026-07-26",
    )
    assert result.outcome != "not_run"
    assert result.numbers["rate_now"] == Decimal("16.5")
    assert result.numbers["rate_now"] != Decimal("0.0")
    assert result.numbers["rate_then"] != Decimal("0.0")


def test_a_falling_explain_figure_keeps_its_sign():
    current = make_fact("95", fact_id="factfallyoycur", end="2026-07-26", start="2026-04-27")
    prior = make_fact("100", fact_id="factfallyoyold", end="2025-07-27", start="2025-04-28")
    inputs = [("revenue", current), ("prior revenue", prior)]
    _kind, english, _href = _explain_amount("yoy_change", current, inputs)
    assert english.startswith("\u22125.0")
    with using("de"):
        _kind, german, _href = _explain_amount("yoy_change", current, inputs)
    assert german.replace("\u00a0", " ").startswith("\u22125,0")
    assert show_measure(Decimal("-5.0"), "percent") == "\u22125.0 percent"


def test_every_card_figure_matches_its_explain_line():
    companies = (
        PINNED / "0000034088-26-000045",
        PINNED / "0001045810-26-000075",
        PINNED / "0001652044-26-000084",
        PINNED / "0000320193-26-000026",
    )
    saw_fall = False
    for directory in companies:
        for language in ("en", "de"):
            page = _page(directory, language)
            for card in _CARD.findall(page):
                figures = list(_FIGURE.finditer(card))
                explain = _E2.search(card)
                assert figures and explain is not None
                shown = _plain(figures[0].group(1))
                links = [_plain(item) for item in _LINK.findall(explain.group(1))]
                assert shown in links, shown
                if any(_plain(item.group(1)).startswith("-") for item in figures):
                    saw_fall = True
    assert saw_fall


def test_german_uses_m2_when_english_uses_m2():
    period = "the same period a year earlier"
    with using("en"):
        assert "M6" not in period
    with using("de"):
        ident, text = _german_gap("Langfristige Finanzschulden", period)
    assert ident != "M6"
    assert "für das Vorquartal ist für diesen Bericht nicht verfügbar" not in text
    assert "für den gleichen Zeitraum ein Jahr zuvor" in text
    with using("de"):
        structural, structural_text = _german_gap("Umsatz", "the prior quarter", structural=True)
    assert structural == "M6"
    assert "für das Vorquartal ist für diesen Bericht nicht verfügbar" in structural_text


def test_german_net_debt_formula_names_the_debt_that_was_used():
    page = _page(PINNED / "0001652044-26-000084", "de")
    assert "Langfristige Finanzschulden ohne kurzfristig fälligen Anteil minus Zahlungsmittel" in page
    assert "einschließlich kurzfristig fälliger Anteile minus" not in page
    assert "Formel:" in page
    assert "(Umsatz minus Umsatz)" not in page
    assert "im Quartal zum" in page or "im Geschäftsjahr zum" in page


def test_german_yoy_formula_names_the_period():
    page = _page(PINNED / "0001045810-26-000075", "de")
    assert "Formel:" in page
    assert "geteilt durch Umsatz im" in page
    assert "(Umsatz minus Umsatz)" not in page
    assert "Er stammt aus der Gewinn- und Verlustrechnung, Position „Umsatz“." in page
    assert "aus Bilanz" not in re.sub(r"<[^>]+>", " ", page)
    assert "aus der Eigenkapitalveränderungsrechnung" in page or "Eigenkapital" in page


def test_german_check_reasons_use_the_cleared_labels():
    with using("de"):
        operating = _german_reason("Operating income is not in the filing.")
        net = _german_reason("Net income is not in the filing.")
        diluted = _german_reason("Diluted shares is not in the filing.")
    assert operating == "„Betriebsergebnis“ ist im Bericht nicht enthalten."
    assert "Auf das Unternehmen entfallendes Nettoergebnis" in net
    assert "Operating income" not in operating
    assert "Net income" not in net
    assert diluted == "„Verwässerte Aktienzahl“ ist im Bericht nicht enthalten."
    assert "Diluted shares" not in diluted


def test_a_german_per_share_figure_keeps_the_english_label():
    fact = replace(
        make_fact("1.64", unit="USD/shares", concept="EarningsPerShareDiluted", role="per_share", fact_id="factepsdiluted"),
        label="Diluted earnings per share",
    )
    with using("de"):
        assert label_for("per_share", fact) == "„Diluted earnings per share“"
        amount = show_measure(fact.value, fact.unit)
    assert "USD" in amount and "je Aktie" in amount
