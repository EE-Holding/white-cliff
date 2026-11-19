"""Margin changes from unrounded ratios, and balance-sheet captions and E2 lines."""

import re
from decimal import Decimal
from pathlib import Path

from white_cliff.compare import margin_value, points_change
from white_cliff.i18n import using
from white_cliff.lexicon import STRINGS
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.present import result_page
from white_cliff.wording import long_date

PINNED = Path(__file__).resolve().parents[1] / "pinned" / "filings"
COMPANIES = (
    "0000320193-26-000020",
    "0000034088-26-000045",
    "0001045810-26-000075",
    "0001652044-26-000084",
    "0001193125-26-436133",
    "0000104169-26-000055",
)
_CARD = re.compile(r'<article class="card".*?</article>', re.S)
_TAG = re.compile(r"<[^>]+>")
_FACT = re.compile(r"fact=([^&\"#]+)")

H6_EN = "For {company}, {line} was {amount} at {date}. It came from the Balance sheet."
H6_DE = "Bei {company} lag die Position „{line}“ zum {date} bei {amount}. Der Wert stammt aus der Bilanz."


def _plain(text: str) -> str:
    return _TAG.sub("", text).replace("\u00a0", " ").replace("\u2212", "-")


def _page(accession: str, language: str, prior: str | None = None) -> tuple[str, object]:
    filing = load_directory(PINNED / accession)
    explained = explain_filing(filing)
    earlier = load_directory(PINNED / prior) if prior else None
    with using(language):
        page = result_page(
            explained,
            form=filing.form,
            period=filing.period_end or "",
            filed="2026-01-01",
            url=filing.url,
            company=filing.filer,
            focus=filing.focus,
            fiscal_year_end=filing.fiscal_year_end,
            prior_facts=earlier.store.facts() if earlier else None,
            prior_end=earlier.period_end if earlier else None,
        )
    return page, explained


def test_h6_balance_sheet_sentences_are_the_cleared_strings():
    assert STRINGS["H6.e2"] == (H6_EN, H6_DE)


def test_points_change_rounds_the_unrounded_margin_once():
    gross_now = margin_value(Decimal("72142"), Decimal("96221"))
    gross_then = margin_value(Decimal("61157"), Decimal("81615"))
    net_now = margin_value(Decimal("59688"), Decimal("96221"))
    net_then = margin_value(Decimal("58321"), Decimal("81615"))
    assert gross_now is not None and gross_then is not None
    assert net_now is not None and net_then is not None
    assert points_change(gross_now, gross_then) == Decimal("0.0")
    assert points_change(net_now, net_then) == Decimal("-9.4")


def _card(page: str, needle: str) -> str:
    for card in _CARD.findall(page):
        label = re.search(r'<h3 class="label"[^>]*>(.*?)</h3>', card, re.S)
        if label and needle in _plain(label.group(1)).casefold():
            return card
    raise AssertionError(needle)


def test_nvidia_gross_margin_of_a_hundredth_reads_unchanged_and_net_reads_9_4():
    for language, gross_name, net_name, unchanged, lower, wrong_gross, wrong_net in (
        (
            "en",
            "gross margin",
            "net margin",
            "was unchanged from the quarter ended April 26, 2026",
            "9.4 percentage points lower than the quarter ended April 26, 2026",
            "0.1 percentage point",
            "9.5 percentage points",
        ),
        (
            "de",
            "bruttomarge",
            "nettomarge",
            "blieb gegenüber dem Quartal zum 26. April 2026 unverändert",
            "9,4 Prozentpunkte niedriger als im Quartal zum 26. April 2026",
            "0,1 Prozentpunkt",
            "9,5 Prozentpunkte",
        ),
    ):
        page, _explained = _page("0001045810-26-000075", language, "0001045810-26-000052")
        gross = _plain(_card(page, gross_name))
        net = _plain(_card(page, net_name))
        assert unchanged in gross
        assert wrong_gross not in gross
        assert lower in net
        assert wrong_net not in net
        for card in (_card(page, gross_name), _card(page, net_name)):
            label = re.search(r'aria-label="([^"]*)"', card)
            assert label is not None
            spoken = _plain(label.group(1))
            assert wrong_gross not in spoken
            assert wrong_net not in spoken


def test_instant_bars_are_dated_and_duration_bars_name_the_period():
    for accession in COMPANIES:
        filing = load_directory(PINNED / accession)
        for language in ("en", "de"):
            page, explained = _page(accession, language)
            instants = durations = 0
            with using(language):
                for card in _CARD.findall(page):
                    figure = re.search(r'<a class="figure"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', card, re.S)
                    caption = re.search(r'<li class="bar-row cur"[^>]*>.*?<p class="bh">(.*?)</p>', card, re.S)
                    label = re.search(r'<h3 class="label"[^>]*>(.*?)</h3>', card, re.S)
                    explain = re.search(r'data-template="E2">(.*?)</p>', card, re.S)
                    if caption is None:
                        continue
                    assert figure and label and explain, accession
                    href = figure.group(1)
                    fact_id = _FACT.search(href)
                    calc_id = re.search(r"calc=([^&\"#]+)", href)
                    if fact_id:
                        period = explained.store.get(fact_id.group(1)).period
                    else:
                        assert calc_id, href
                        period = explained.store.get_calc(calc_id.group(1)).period
                    head = _plain(caption.group(1)).strip()
                    line = _plain(label.group(1)).strip()
                    amount = _plain(figure.group(2)).strip()
                    sentence = _plain(explain.group(1)).strip()
                    when = long_date(period.end or "").replace("\u00a0", " ")
                    if period.kind == "instant":
                        instants += 1
                        assert head == when, (accession, language, line, head)
                        folded = head.casefold()
                        assert "ended" not in folded
                        assert "drei monate" not in folded
                        assert not head.startswith("As of")
                        assert not head.startswith("Zum")
                        template = H6_DE if language == "de" else H6_EN
                        expected = template.format(
                            company=filing.filer, line=line, amount=amount, date=when
                        )
                        assert sentence == expected, (accession, language, sentence)
                    else:
                        durations += 1
                        folded = head.casefold()
                        if language == "en":
                            assert "ended" in folded, (accession, line, head)
                            assert " in the " in f" {sentence} "
                            assert "It came from the Balance sheet." not in sentence
                        else:
                            assert (
                                "monate" in folded or "geschäftsjahr" in folded or "jahr" in folded
                            ), (accession, line, head)
                            assert " im " in f" {sentence} "
                            assert "Der Wert stammt aus der Bilanz." not in sentence
            assert instants, accession
            assert durations, accession
