"""German pages use the cleared table, and the choice is saved on this computer."""

import re
from decimal import Decimal
from pathlib import Path

from white_cliff.compare import columns_for
from white_cliff.desktop import Desktop
from white_cliff.desktop_copy import (
    BUSY,
    CANNOT_EXPLAIN,
    CLOSE_INTRO,
    EMPTY_QUERY,
    ENTER_BOTH,
    NO_10KQ,
    NO_INTERNET,
    NO_MATCH,
    ONLY_SEC,
    REFUSED,
    SEC_CERT,
    SEC_ODD,
    SEC_REFUSED,
    SEC_WHY,
    SEVERAL,
)
from white_cliff.disclaimer import DISCLAIMER
from white_cliff.german import NBSP, format_measure, german_hit
from white_cliff.identity import load_identity, load_language, save_identity, save_language
from white_cliff.i18n import using
from white_cliff.lexicon import STRINGS, SUPERSEDED
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.present import (
    choices_page,
    edit_page,
    error_page,
    first_run_page,
    result_page,
    search_page,
)
from white_cliff.wording import WHY, long_date, show_measure
from tests.test_cards import _html, _quarter, _short

PINNED = Path(__file__).resolve().parents[1] / "pinned" / "filings"
GERMAN_DISCLAIMER = STRINGS["§1.DISCLAIMER"][1]
_SLOT = re.compile(r"\{([^{}]+)\}")


def _names(text: str) -> list[str]:
    return sorted(item for item in _SLOT.findall(text) if "|" not in item)


def test_each_english_id_has_one_german_string():
    assert len(STRINGS) == 252
    assert len(SUPERSEDED) == 25
    for ident, (english, deutsch) in STRINGS.items():
        assert english
        assert deutsch
        assert "betrug" not in deutsch.casefold()
        if ident in SUPERSEDED:
            continue
        assert _names(english) == _names(deutsch), ident


def test_german_money_dates_and_percents_come_from_the_stored_value():
    with using("de"):
        assert show_measure(Decimal("96221"), "USD millions") == f"96.221{NBSP}Mio.{NBSP}USD"
        assert format_measure(Decimal("96221"), "USD millions") == show_measure(
            Decimal("96221"), "USD millions"
        )
        assert show_measure(Decimal("1.64"), "USD") == f"1,64{NBSP}USD"
        assert show_measure(Decimal("1.64"), "USD/shares") == f"1,64{NBSP}USD{NBSP}je Aktie"
        assert show_measure(Decimal("17.9"), "percent") == f"17,9{NBSP}Prozent"
        assert show_measure(Decimal("1.25"), "percent") == f"1,3{NBSP}Prozent"
        assert show_measure(Decimal("-50"), "USD millions") == f"\u221250{NBSP}Mio.{NBSP}USD"
        assert long_date("2026-04-26") == "26. April 2026"
    assert show_measure(Decimal("96221"), "USD millions") == "$96,221 million"
    assert "$96,221 million".replace(",", ".").replace("$", "") != "96.221 Mio. USD"


def test_the_english_share_line_says_changed():
    assert WHY["C6"].endswith("how much the number of shares changed.")
    assert "has grown" not in WHY["C6"]


def test_both_disclaimer_lines_lead_every_german_page():
    with using("de"):
        pages = [
            first_run_page(token="t"),
            search_page("t"),
            edit_page("t"),
            error_page(NO_MATCH, token="t", query="zz"),
            choices_page(SEVERAL, [], "t", "nv"),
        ]
    for page in pages:
        assert page.index(DISCLAIMER) < page.index(GERMAN_DISCLAIMER)
        assert page.index(GERMAN_DISCLAIMER) < page.index("<script")
        assert page.startswith("<!DOCTYPE html>\n")
        assert '<html lang="de"' in page
        assert "betrug" not in page.casefold()
        assert "Entwurf" not in page


def test_german_forbidden_words_refuse_a_rendered_page(tmp_path):
    current = load_directory(PINNED / "0001045810-26-000075")
    prior = load_directory(PINNED / "0001045810-26-000052")
    explained = explain_filing(current)
    sentences = (
        SEC_WHY,
        NO_INTERNET,
        SEC_CERT,
        SEC_REFUSED,
        NO_MATCH,
        CLOSE_INTRO,
        SEVERAL,
        NO_10KQ,
        BUSY,
        CANNOT_EXPLAIN,
        ENTER_BOTH,
        SEC_ODD,
        EMPTY_QUERY,
        ONLY_SEC,
        REFUSED,
    )
    with using("de"):
        pages = [error_page(sentence, token="t") for sentence in sentences]
        pages.append(first_run_page(token="t"))
        pages.append(search_page("t"))
        pages.append(
            result_page(
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
        )
    for page in pages:
        visible = re.sub(r"<style\b[^>]*>.*?</style>", " ", page, flags=re.I | re.S)
        visible = re.sub(r"<script\b[^>]*>.*?</script>", " ", visible, flags=re.I | re.S)
        visible = re.sub(r"<[^>]+>", " ", visible)
        visible = visible.replace(DISCLAIMER, " ").replace(GERMAN_DISCLAIMER, " ")
        assert german_hit(visible) is None
        assert "betrug" not in visible.casefold()


def test_a_missing_prior_quarter_uses_the_german_one_clause_line():
    current = _quarter("300", "degm6now", "2026-01-27", "2026-04-26")
    year = _quarter("250", "degm6year", "2025-01-27", "2025-04-27")
    last, found = columns_for(
        current,
        role="revenue",
        form="10-Q",
        focus="Q1",
        period_end="2026-04-26",
        fiscal_year_end="--01-31",
        facts=[current, year],
    )
    with using("de"):
        html_text = _html(current, last, found, form="10-Q")
    assert _short(html_text).replace("\u00a0", " ") == (
        "Der Wert stieg um 20,0 Prozent gegenüber dem gleichen Quartal ein Jahr zuvor."
    )
    assert "betrug" not in html_text.casefold()
    assert "für das Vorquartal ist für diesen Bericht nicht verfügbar." in html_text


def test_the_saved_language_survives_a_new_app(tmp_path):
    path = tmp_path / "identity.json"
    save_identity(path, "Example Person", "person@example.com")
    save_language(path, "de")
    assert load_language(path) == "de"
    assert load_identity(path) is not None
    clock = lambda: 0
    first = Desktop(path, tmp_path / "cache", None, lambda _seconds: None, clock)
    opened = first.handle("GET", "/", {})
    second = Desktop(path, tmp_path / "cache", None, lambda _seconds: None, clock)
    again = second.handle("GET", "/", {})
    for page in (opened, again):
        assert '<html lang="de"' in page.body
        assert page.body.index('<html lang="de"') < page.body.index("<script")
        assert page.body.index(DISCLAIMER) < page.body.index(GERMAN_DISCLAIMER)
        assert "Unternehmensname oder Tickersymbol" in page.body
        assert "Company name or ticker" not in page.body
    english = second.handle("POST", "/language", {"language": "en"})
    assert '<html lang="en"' in english.body
    assert GERMAN_DISCLAIMER not in english.body
    assert 'data-lang-set="1"' in english.body
    restored = Desktop(path, tmp_path / "cache", None, lambda _seconds: None, clock)
    home = restored.handle("GET", "/", {})
    assert '<html lang="en"' in home.body
    assert 'data-lang-set="1"' not in home.body


def test_a_result_stays_a_result_when_the_language_changes(tmp_path):
    current = load_directory(PINNED / "0001045810-26-000075")
    prior = load_directory(PINNED / "0001045810-26-000052")
    explained = explain_filing(current)
    path = tmp_path / "identity.json"
    save_identity(path, "Example Person", "person@example.com")
    app = Desktop(path, tmp_path / "cache", None, lambda _seconds: None, lambda: 0)
    app.screen = (
        "result",
        {
            "explained": explained,
            "form": current.form,
            "period": current.period_end or "",
            "filed": "2026-08-26",
            "url": current.url,
            "company": current.filer,
            "focus": current.focus,
            "fiscal_year_end": current.fiscal_year_end,
            "prior_facts": prior.store.facts(),
            "prior_end": prior.period_end,
        },
    )
    page = app.handle("POST", "/language", {"language": "de"})
    assert '<html lang="de"' in page.body
    assert "96.221" in page.body
    assert "Umsatz" in page.body
    assert page.body.index(DISCLAIMER) < page.body.index(GERMAN_DISCLAIMER)
    assert "Company name or ticker" not in page.body
