"""Shown figures and their sentences, German labels, and the saved identity file."""

import json
import re
from pathlib import Path

from white_cliff.compare import Cell
from white_cliff.i18n import using
from white_cliff.identity import save_identity, save_language
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.present import result_page, search_page
from white_cliff.wording import _german_reason
from tests.test_cards import _column, _html, _quarter, _short

PINNED = Path(__file__).resolve().parents[1] / "pinned" / "filings"
COMPANIES = (
    "0000320193-26-000020",
    "0000034088-26-000045",
    "0001045810-26-000075",
    "0001652044-26-000084",
    "0001193125-26-436133",
    "0000104169-26-000055",
)
_ENGLISH = (
    "Diluted shares",
    "Accounts receivable",
    "Income tax",
    "was unchanged",
    "It rose",
    "It fell",
    "It was ",
    "It came from",
    "divided by",
    "Formula:",
    "Income statement",
    "Balance sheet",
    "is not available",
    "percentage points",
    " percent",
    "Check:",
    "This check",
    "The filing says",
    "Bar chart",
    "for the prior quarter",
)


def _plain(html_text: str) -> str:
    text = re.sub(r"<[^>]+>", "", html_text)
    return text.replace("\u00a0", " ").replace("\u2212", "-")


def _percent_fact(value, fact_id, start="2026-01-26", end="2026-04-26"):
    from dataclasses import replace

    return replace(_quarter(value, fact_id, start, end), unit="percent")


def test_a_change_line_matches_the_percents_on_the_bars():
    apart = _html(
        _percent_fact("74.975", "gapnow", "2026-04-27", "2026-07-26"),
        _column(_percent_fact("74.934", "gapthen")),
        None,
        measure="margin",
    )
    shown = _plain(apart)
    assert "rose 0.1 percentage points from the prior quarter" in shown
    assert "unchanged" not in shown.casefold()
    assert "75.0 percent" in shown and "74.9 percent" in shown
    same = _html(
        _percent_fact("75.04", "samenow", "2026-04-27", "2026-07-26"),
        _column(_percent_fact("74.96", "samethen")),
        None,
        measure="margin",
    )
    agreed = _plain(same)
    assert "unchanged" in agreed.casefold()
    assert "0.1 percentage points" not in agreed
    money = _short(
        _html(
            _quarter("100.04", "moneynow", "2026-04-27", "2026-07-26"),
            _column(_quarter("100", "moneythen")),
            None,
        )
    )
    assert money == "It was $0.04 higher than the prior quarter."
    assert "unchanged" not in money.casefold()


def test_year_to_date_amounts_say_als_in_for_six_and_nine_months():
    six_now = _quarter("200", "sixnowytd", "2026-02-01", "2026-07-31")
    six_then = _quarter("-50", "sixthenytd", "2025-02-01", "2025-07-31")
    nine_now = _quarter("90", "ninenowytd", "2025-10-27", "2026-07-26")
    nine_then = _quarter("-40", "ninethenytd", "2024-10-28", "2025-07-27")
    with using("de"):
        six = _short(_html(six_now, None, _column(six_then)))
        nine = _short(_html(nine_now, None, _column(nine_then)))
    assert "als in den gleichen sechs Monaten ein Jahr zuvor." in six
    assert "als in den gleichen neun Monaten ein Jahr zuvor." in nine
    assert "als im den" not in six and "als im den" not in nine


def test_german_pages_do_not_use_an_english_explain_sentence():
    with using("de"):
        diluted = _german_reason("Diluted shares is not in the filing.")
        tax = _german_reason("Income tax is not in the filing.")
        receivables = _german_reason("Accounts receivable is not in the filing.")
    assert diluted == "„Verwässerte Aktienzahl“ ist im Bericht nicht enthalten."
    assert tax == "„Ertragsteuer“ ist im Bericht nicht enthalten."
    assert receivables == "„Forderungen aus Lieferungen und Leistungen“ ist im Bericht nicht enthalten."
    for accession in COMPANIES:
        filing = load_directory(PINNED / accession)
        explained = explain_filing(filing)
        with using("de"):
            page = result_page(
                explained,
                form=filing.form,
                period=filing.period_end or "",
                filed="2026-01-01",
                url=filing.url,
                company=filing.filer,
                focus=filing.focus,
                fiscal_year_end=filing.fiscal_year_end,
            )
        visible = re.sub(r"<h1\b[^>]*>.*?</h1>", " ", page, flags=re.S)
        visible = re.sub(r'<p class="pct-note"[^>]*>.*?</p>', " ", visible, flags=re.S)
        visible = re.sub(r'data-template="E3".*?</p>', " ", visible, flags=re.S)
        visible = re.sub(r"<style\b[^>]*>.*?</style>", " ", visible, flags=re.S)
        visible = re.sub(r"<script\b[^>]*>.*?</script>", " ", visible, flags=re.S)
        text = _plain(visible)
        text = text.split("investment advice.", 1)[-1]
        for sentence in _ENGLISH:
            assert sentence not in text, (accession, sentence)


def test_a_chart_label_does_not_end_in_two_periods():
    current = _quarter("100", "dotnow", "2026-04-27", "2026-07-26")
    missing = Cell(False, missing_period='the "prior" period', basis="absent")
    html_text = _html(current, missing, None)
    label = re.search(r'aria-label="([^"]*)"', html_text).group(1)
    assert label.endswith(".")
    assert not label.endswith("..")
    assert ".." not in label
    assert "&quot;" in label
    assert 'aria-label="' in html_text


def test_the_result_grid_fills_the_column_and_only_percents_are_underlined():
    style = search_page("t").split("</style>", 1)[0]
    assert "grid-template-columns: 1fr 1fr" in style
    assert 'grid-template-areas: "head value" "date date"' in style
    assert "align-items: last baseline" in style
    assert ".change-line a { color: #0a4b8f; text-decoration: none;" in style
    assert ".cmp a.pct, .change-line a.pct" in style
    assert "text-decoration: underline" in style.split(".cmp a.pct, .change-line a.pct", 1)[1].split("}", 1)[0]
    narrow = style.split("@media (max-width: 480px)", 1)[1].split("@media", 1)[0]
    assert ".chart { flex-direction: column;" in narrow
    line = _html(
        _quarter("110", "ulnow", "2026-04-27", "2026-07-26"),
        _column(_quarter("100", "ulthen")),
        None,
    )
    short = line.split('class="chart"', 1)[0]
    percent = re.search(r'<a class="pct" href="#(pct-[0-9a-f]+)">10\.0 percent</a>', short)
    period = re.search(r'<a class="per" href="(https://www\.sec\.gov/[^"]+)">', short)
    assert percent is not None and period is not None
    note = re.search(rf'<p class="pct-note" id="{percent.group(1)}">(.*?)</p>', line, flags=re.S)
    assert note is not None
    links = re.findall(r'href="(https://www\.sec\.gov/[^"]+)"', note.group(1))
    assert len(links) == 2 and len(set(links)) == 2


def test_a_language_save_keeps_unknown_keys_and_the_first_backup(tmp_path):
    path = tmp_path / "identity.json"
    path.write_text(
        json.dumps({"name": "A Person", "email": "a@example.com", "seat": "second", "language": "en"}) + "\n",
        encoding="utf-8",
    )
    save_language(path, "de")
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["seat"] == "second"
    assert stored["name"] == "A Person"
    assert stored["email"] == "a@example.com"
    assert stored["language"] == "de"
    save_identity(path, "B Person", "b@example.com")
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["seat"] == "second"
    assert stored["language"] == "de"
    assert stored["name"] == "B Person"
    path.write_bytes(b"{not json")
    save_language(path, "en")
    backup = path.with_name("identity.json.bak")
    assert backup.read_bytes() == b"{not json"
    path.write_bytes(b"{still bad")
    save_identity(path, "C Person", "c@example.com")
    assert backup.read_bytes() == b"{not json"
    assert json.loads(path.read_text(encoding="utf-8"))["name"] == "C Person"
