"""A percent on a card face is the card's own figure or a full sentence. Nothing else."""

import html
import re
from pathlib import Path

from white_cliff.i18n import using
from white_cliff.lexicon import STRINGS
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.present import result_page

PINNED = Path(__file__).resolve().parents[1] / "pinned" / "filings"
NVIDIA = "0001045810-26-000075"
NVIDIA_PRIOR = "0001045810-26-000052"
WALMART = "0000104169-26-000055"
JOHNSON = "0000200406-26-000016"
_CARD = re.compile(r'<article class="card".*?</article>', re.S)
_FIGURE = re.compile(r'<a class="figure"[^>]*>(.*?)</a>', re.S)
_BIG = re.compile(r'<p class="big">.*?</p>', re.S)
_LEAF = re.compile(r"<([a-z0-9]+)\b[^>]*>([^<]*)</\1>", re.I)
_BARE_PERCENT = re.compile(
    r"(?:[\u2212+\-])?\d[\d, ]*(?:[.,]\d+)?\s*(?:%|percent|Prozent)\Z",
    re.IGNORECASE,
)
_SIGNED_CHANGE = re.compile(r"[\u2212+\-]\d[\d, ]*(?:[.,]\d+)?\Z")
_PRINT_HIDDEN = (
    "top",
    "next",
    "lang",
    "change",
    "print-row",
)


def _plain(text: str) -> str:
    return html.unescape(text).replace("\u00a0", " ").strip()


def _bare(text: str) -> bool:
    cleaned = _plain(text)
    return bool(_BARE_PERCENT.fullmatch(cleaned) or _SIGNED_CHANGE.fullmatch(cleaned))


def _drop_div(source: str, class_name: str) -> str:
    """Remove each div whose class list contains class_name, including its children."""
    needle = f'class="{class_name}"'
    pieces: list[str] = []
    index = 0
    while index < len(source):
        start = source.find("<div", index)
        if start < 0:
            pieces.append(source[index:])
            break
        end = source.find(">", start)
        if end < 0:
            pieces.append(source[index:])
            break
        tag = source[start : end + 1]
        if needle not in tag and f"{class_name} " not in tag:
            pieces.append(source[index : end + 1])
            index = end + 1
            continue
        depth = 1
        cursor = end + 1
        while cursor < len(source) and depth:
            nxt = source.find("<", cursor)
            if nxt < 0:
                cursor = len(source)
                break
            if source.startswith("</div>", nxt):
                depth -= 1
                cursor = nxt + len("</div>")
                continue
            if source.startswith("<div", nxt):
                depth += 1
                close = source.find(">", nxt)
                cursor = len(source) if close < 0 else close + 1
                continue
            cursor = nxt + 1
        pieces.append(source[index:start])
        index = cursor
    return "".join(pieces)


def _outside_explain(card: str) -> str:
    """Screen and print both leave Explain collapsed, so its text is not on the card.

    The card's own figure, a comparison sentence, and a bar beside its period
    label are labelled. A percent with none of those is bare.
    """
    shown = _drop_div(card, "detail")
    shown = _BIG.sub("", shown, count=1)
    shown = re.sub(r'<ul class="chart"[^>]*>.*?</ul>', "", shown, flags=re.S)
    for class_name in ("cmp-slot", "cmp", "change-line", "pct-note"):
        shown = _drop_div(shown, class_name)
        shown = re.sub(
            rf'<p class="{class_name}"[^>]*>.*?</p>',
            "",
            shown,
            flags=re.S,
        )
    return shown


def _print_page(page: str) -> str:
    shown = re.sub(r"<form\b[^>]*>.*?</form>", "", page, flags=re.S | re.I)
    shown = re.sub(r"<input\b[^>]*>", "", shown, flags=re.I)
    shown = re.sub(r'<p[^>]*data-template="LIMIT"[^>]*>.*?</p>', "", shown, flags=re.S)
    for class_name in _PRINT_HIDDEN:
        shown = _drop_div(shown, class_name)
        shown = re.sub(
            rf'<(?:div|p|nav|header) class="{class_name}"[^>]*>.*?</(?:div|p|nav|header)>',
            "",
            shown,
            flags=re.S,
        )
    return shown


def _bare_outside(card: str) -> list[str]:
    shown = _outside_explain(card)
    found = [_plain(item) for item in _FIGURE.findall(shown) if _bare(item)]
    for match in _LEAF.finditer(shown):
        text = match.group(2)
        if _bare(text) and _plain(text) not in found:
            found.append(_plain(text))
    return found


def _page(accession: str, language: str, prior: str | None = None) -> str:
    filing = load_directory(PINNED / accession)
    explained = explain_filing(filing)
    earlier = load_directory(PINNED / prior) if prior else None
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
            prior_facts=earlier.store.facts() if earlier else None,
            prior_end=earlier.period_end if earlier else None,
        )


def _cases():
    named = {NVIDIA, WALMART, JOHNSON}
    pairs = [(NVIDIA, NVIDIA_PRIOR), (WALMART, None), (JOHNSON, None)]
    for path in sorted(PINNED.iterdir()):
        if path.is_dir() and path.name not in named and path.name != NVIDIA_PRIOR:
            pairs.append((path.name, None))
    return pairs


def _detail(card: str) -> str:
    marker = 'class="detail"'
    start = card.find(marker)
    if start < 0:
        return ""
    open_at = card.rfind("<div", 0, start)
    if open_at < 0:
        return ""
    depth = 0
    index = open_at
    while index < len(card):
        if card.startswith("<div", index):
            depth += 1
            index = card.find(">", index)
            index = len(card) if index < 0 else index + 1
            continue
        if card.startswith("</div>", index):
            depth -= 1
            index += len("</div>")
            if depth == 0:
                return card[open_at:index]
            continue
        index += 1
    return ""


def _label_with_figure(page: str, label: str) -> str:
    """The element inside Explain that carries both the cleared label and its figure."""
    for card in _CARD.findall(page):
        detail = _detail(card)
        for paragraph in re.findall(r"<p\b[^>]*>.*?</p>", detail, re.S):
            figure = _FIGURE.search(paragraph)
            if figure is None or label not in _plain(paragraph):
                continue
            if _bare(figure.group(1)):
                return paragraph
    return ""


def test_the_cleared_label_and_the_figure_share_an_explain_element():
    """EN and DE, on screen and in print, the label and the figure are one element inside Explain."""
    for accession, prior in ((NVIDIA, NVIDIA_PRIOR), (WALMART, None), (JOHNSON, None)):
        for language in ("en", "de"):
            label = STRINGS["LBL.yoy"][0 if language == "en" else 1]
            page = _page(accession, language, prior)
            for surface, body in (("screen", page), ("print", _print_page(page))):
                element = _label_with_figure(body, label)
                assert element, f"{accession} {language} {surface}"
                assert "https://www.sec.gov/" in element


def test_no_bare_percent_outside_explain_on_screen_or_in_print():
    """A bare percent or a signed change outside Explain fails, in English and German."""
    assert STRINGS["LBL.yoy"] == (
        "The year over year change in revenue",
        "Veränderung des Umsatzes gegenüber dem Vorjahreszeitraum",
    )
    leaks = []
    for accession, prior in _cases():
        for language in ("en", "de"):
            page = _page(accession, language, prior)
            for surface, body in (("screen", page), ("print", _print_page(page))):
                for card in _CARD.findall(body):
                    found = _bare_outside(card)
                    if found:
                        label = re.search(r"<h3[^>]*>(.*?)</h3>", card, re.S)
                        name = _plain(label.group(1)) if label else accession
                        leaks.append(f"{accession} {language} {surface} {name}: {found}")
    assert leaks == []


def test_a_parked_figure_without_explain_is_shown_with_its_label():
    """A card with no Explain panel still shows the parked figure, beside the cleared label."""
    from white_cliff.present import _rows
    from white_cliff.wording import Additions

    filing = (
        '<p>Revenue was <data>100 USD millions</data> '
        '<a class="source-chip" href="https://www.sec.gov/Archives/edgar/data/1/x.htm#fact=factrev">source</a></p>'
        '<p>Year over year <data>10.5 percent</data> '
        '<a class="source-chip" href="https://www.sec.gov/Archives/edgar/data/1/x.htm#calc=calcyoy">source</a></p>'
    )
    additions = Additions(
        {},
        {},
        "",
        "",
        frozenset({"calcyoy"}),
        {},
        {},
        {"calcyoy": "factrev"},
    )
    for language, label in (("en", STRINGS["LBL.yoy"][0]), ("de", STRINGS["LBL.yoy"][1])):
        with using(language):
            rendered = _rows(filing, additions)
        assert 'class="detail"' not in rendered
        paragraph = re.search(
            rf"<p>{re.escape(label)} <a class=\"figure\" href=\"[^\"]*calc=calcyoy[^\"]*\">([^<]*)</a></p>",
            rendered,
        )
        assert paragraph is not None, rendered
        assert _bare(paragraph.group(1))
