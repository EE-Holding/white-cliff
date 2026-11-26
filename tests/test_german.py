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
from white_cliff.german import NBSP, format_measure, format_raw, german_hit
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
    assert len(STRINGS) == 305
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
        assert long_date("2026-04-26") == f"26.{NBSP}April{NBSP}2026"
        assert " " not in long_date("2026-07-26")
    assert long_date("2026-07-26") == f"July{NBSP}26,{NBSP}2026"
    assert " " not in long_date("2026-07-26")
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


def test_a_corrupt_identity_file_is_kept_before_the_language_is_saved(tmp_path):
    path = tmp_path / "identity.json"
    path.write_bytes(b"{not json")
    save_language(path, "de")
    backup = tmp_path / "identity.json.bak"
    assert backup.read_bytes() == b"{not json"
    assert backup.stat().st_mode & 0o777 == 0o600
    assert load_language(path) == "de"
    assert '"language": "de"' in path.read_text(encoding="utf-8")


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


def test_each_scale_word_is_kept_wherever_it_sits():
    with using("de"):
        assert format_measure(Decimal("24190"), "shares millions") == f"24.190{NBSP}Mio.{NBSP}Aktien"
        assert format_raw("24190 shares millions") == f"24.190{NBSP}Mio.{NBSP}Aktien"
        assert format_measure(Decimal("24190"), "millions shares") == f"24.190{NBSP}Mio.{NBSP}Aktien"
        assert format_measure(Decimal("14532259"), "shares thousands") == f"14.532.259{NBSP}Tsd.{NBSP}Aktien"
        assert format_raw("14532259 shares thousands") == f"14.532.259{NBSP}Tsd.{NBSP}Aktien"
        assert show_measure(Decimal("1500"), "USD millions") == f"1.500{NBSP}Mio.{NBSP}USD"
        assert show_measure(Decimal("1.5"), "USD billions") == f"1,5{NBSP}Mrd.{NBSP}USD"
        assert show_measure(Decimal("1.64"), "USD/shares") == f"1,64{NBSP}USD{NBSP}je Aktie"
    assert show_measure(Decimal("24190"), "shares millions") == "24,190 million shares"
    assert show_measure(Decimal("14532259"), "shares thousands") == "14,532,259 thousand shares"
    assert show_measure(Decimal("1.5"), "USD billions") == "$1.5 billion"
    assert show_measure(Decimal("1.64"), "USD/shares") == "$1.64 per share"


def _stored_number(text: str):
    token = re.search(r"\d[\d.,]*", text.replace("\u2212", "-").replace(NBSP, " "))
    raw = token.group(0)

    def thousands(separator: str) -> bool:
        parts = raw.split(separator)
        return len(parts) > 1 and all(len(part) == 3 for part in parts[1:])

    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", "") if thousands(",") else raw.replace(",", ".")
    elif "." in raw and thousands("."):
        raw = raw.replace(".", "")
    return Decimal(raw)


def test_german_and_english_figures_are_the_same_number():
    samples = (
        (Decimal("24190"), "shares millions"),
        (Decimal("14532259"), "shares thousands"),
        (Decimal("96221"), "USD millions"),
        (Decimal("1.5"), "USD billions"),
        (Decimal("1.64"), "USD/shares"),
        (Decimal("17.9"), "percent"),
    )
    for value, unit in samples:
        english = show_measure(value, unit)
        with using("de"):
            deutsch = show_measure(value, unit)
        assert _stored_number(english) == _stored_number(deutsch)


def test_a_longer_margin_name_uses_the_cleared_label():
    from white_cliff.present import _german_label

    with using("de"):
        assert (
            _german_label("The gross margin (gross profit / revenue from contracts with customers)")
            == STRINGS["LBL.gross_margin"][1]
        )
        assert (
            _german_label("The operating margin (operating income / revenue from contracts with customers)")
            == STRINGS["LBL.operating_margin"][1]
        )
        assert (
            _german_label("The net margin (net income / revenue from contracts with customers)")
            == STRINGS["LBL.net_margin"][1]
        )


def test_folded_forbidden_words_match_without_eszett():
    assert german_hit("bloss") is not None
    assert german_hit("einbusse") is not None
    assert german_hit("bloß") is not None
    assert german_hit("einbuße") is not None


def test_a_language_write_keeps_every_existing_key(tmp_path):
    import json

    path = tmp_path / "identity.json"
    path.write_text(
        json.dumps({"name": "Example Person", "email": "person@example.com", "language": "en", "extra": "kept"}) + "\n",
        encoding="utf-8",
    )
    save_language(path, "de")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["extra"] == "kept"
    assert saved["name"] == "Example Person"
    assert saved["email"] == "person@example.com"
    assert saved["language"] == "de"
    assert path.stat().st_mode & 0o777 == 0o600


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


def _visible(page: str) -> str:
    text = re.sub(r'<p class="pct-note"[^>]*>.*?</p>', " ", page, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = text.replace(DISCLAIMER, " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"„[^“]*“", " ", text)
    text = re.sub(r'"[^"]*"', " ", text)
    return text


def _english_template_words() -> set[str]:
    english_words: set[str] = set()
    german_words: set[str] = set()
    for english, deutsch in STRINGS.values():
        english_words.update(word.casefold() for word in re.findall(r"[A-Za-z]{5,}", english))
        german_words.update(word.casefold() for word in re.findall(r"[A-Za-z]{5,}", deutsch))
    return english_words - german_words - {"minus"}


def test_german_pages_do_not_reuse_english_template_words():
    from white_cliff.compare import Cell
    from white_cliff.wording import DEFINITIONS

    current = load_directory(PINNED / "0001045810-26-000075")
    prior = load_directory(PINNED / "0001045810-26-000052")
    explained = explain_filing(current)
    with using("de"):
        pages = [
            first_run_page(token="t"),
            search_page("t"),
            edit_page("t"),
            error_page(NO_MATCH, token="t", query="zz"),
            choices_page(SEVERAL, [], "t", "nv"),
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
            ),
        ]
        gap = _html(
            _quarter("100", "gapnow", "2026-04-27", "2026-07-26"),
            Cell(False, missing_period="the quarter ended April 26, 2026"),
            None,
        )
    words = _english_template_words()
    leaked = []
    for page in pages + [gap]:
        visible = _visible(page)
        for word in sorted(words):
            if re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", visible, re.I):
                leaked.append(word)
    assert leaked == []
    result = pages[-1]
    for role, definition in DEFINITIONS.items():
        if role == "operating_cash_flow":
            continue
        assert definition not in result
    assert "Der operative Cashflow ist der Zahlungsmittelzufluss" in result
    noted = re.sub(r'<p class="pct-note"[^>]*>.*?</p>', " ", result, flags=re.S)
    assert "geteilt durch" in result
    assert "Net debt" not in noted
    assert "divided by" not in noted
    assert "the prior quarter" not in gap
    assert f"Quartal zum 26.{NBSP}April{NBSP}2026" in gap
    assert "96.221" in result
    assert "Prozent" in result
    yoy = result.find("Veränderung des Umsatzes gegenüber dem Vorjahreszeitraum")
    assert yoy > 0
    assert ">Veränderung des Umsatzes gegenüber dem Vorjahreszeitraum</h3>" not in result
    stated = re.sub(r"<[^>]+>", "", result[yoy : yoy + 2500])[:160]
    assert "105,9" in stated and "Prozent" in stated
    assert "96.221" not in stated
    english = result_page(
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
    english_plain = re.sub(r"<[^>]+>", "", english)
    english_at = english_plain.find("was 105.9 percent")
    assert english_at > 0
    assert "96,221" not in english_plain[english_at - 40 : english_at + 40]
