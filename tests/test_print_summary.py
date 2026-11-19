"""A local print summary. The operating system prints it. Nothing is uploaded."""

import html
import importlib.util
import re
import shutil
import subprocess
import zlib
from html.parser import HTMLParser
from pathlib import Path

import pytest

from white_cliff.disclaimer import DISCLAIMER
from white_cliff.i18n import using
from white_cliff.lexicon import STRINGS
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.present import first_run_page, result_page
from white_cliff.wording import FRAME

PINNED = Path(__file__).resolve().parents[1] / "pinned" / "filings"
GERMAN = STRINGS["§1.DISCLAIMER"][1]
PRINT_LABEL = "Print summary"
PRINT_LABEL_DE = "Zusammenfassung drucken"
SOURCES = "Sources on sec.gov"
SOURCES_DE = "Quellen auf sec.gov"
LIMIT = STRINGS["Q.limit"][0]
LIMIT_DE = STRINGS["Q.limit"][1]
_SEC = re.compile(r"https://www\.sec\.gov/\S+")


def _page():
    filing = load_directory(PINNED / "0000320193-26-000026")
    explained = explain_filing(filing)
    return filing, result_page(
        explained,
        form=filing.form,
        period=filing.period_end or "",
        filed="2026-11-01",
        url=filing.url,
        company=filing.filer,
        focus=filing.focus,
        fiscal_year_end=filing.fiscal_year_end,
    )


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}


class _Printed(HTMLParser):
    """Text left after the print rules hide chrome, identity fields, and repeated limits."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.values: list[str] = []
        self._stack: list[tuple[str, set[str], bool]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {key: value or "" for key, value in attrs}
        classes = set(ad.get("class", "").split())
        parent_hidden = self._stack[-1][2] if self._stack else False
        hidden = parent_hidden or tag in {"head", "style", "script", "form", "input"}
        if classes & {"top", "next", "lang", "print-row", "change"}:
            hidden = True
        if tag == "p" and ad.get("data-template") == "LIMIT" and "limit-once" not in classes:
            hidden = True
        if tag == "p" and "disclaimer" in classes and self._stack and self._stack[-1][0] == "body":
            hidden = True
        if not hidden and tag == "input":
            self.values.append(ad.get("value", ""))
        self._stack.append((tag, classes, hidden))
        if tag in _VOID:
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._stack and self._stack[-1][2]:
            return
        self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.parts)).strip()


def _printed(page: str) -> _Printed:
    parser = _Printed()
    parser.feed(page)
    return parser


def _print_css(page: str) -> str:
    style = re.search(r"<style>(.*)</style>", page, re.S)
    assert style is not None
    css = style.group(1)
    start = css.find("@media print")
    assert start >= 0
    return css[start:]


def test_print_css_and_the_print_button_call_the_local_dialog():
    _filing, page = _page()
    css = _print_css(page)
    assert "thead.print-head" in css
    assert "table-header-group" in css
    assert "animation: none" in css
    assert '<button type="button" class="print" onclick="window.print()">' in page
    assert f">{PRINT_LABEL}</button>" in page
    button = re.search(r"<button type=\"button\" class=\"print\"[^>]*>", page)
    assert button is not None
    assert "fetch" not in button.group(0)
    script = re.search(r"<script>(.*)</script>", page, re.S)
    assert script is not None
    body = script.group(1)
    assert 'fetch("/stay"' in body
    assert body.index("if (printing) return;") < body.index('fetch("/stay"')
    assert "button.print { min-height: 64px;" in page


def test_the_disclaimer_is_the_first_printed_text_above_any_number():
    _filing, page = _page()
    printed = _printed(page).text()
    assert printed.startswith(DISCLAIMER)
    assert printed.index(DISCLAIMER) < re.search(r"\d", printed).start()
    header = re.search(r'<thead class="print-head">(.*?)</thead>', page, re.S)
    assert header is not None
    assert header.group(1).index(DISCLAIMER) < re.search(r"\d", header.group(1)).start() if re.search(r"\d", header.group(1)) else True
    assert header.group(1).strip().startswith("<tr><td>") or "<p class=\"disclaimer\">" in header.group(1)


def test_german_disclaimer_is_the_next_printed_line():
    filing = load_directory(PINNED / "0000320193-26-000026")
    explained = explain_filing(filing)
    with using("de"):
        page = result_page(
            explained,
            form=filing.form,
            period=filing.period_end or "",
            filed="2026-11-01",
            url=filing.url,
            company=filing.filer,
            focus=filing.focus,
            fiscal_year_end=filing.fiscal_year_end,
        )
    assert f">{PRINT_LABEL_DE}</button>" in page
    assert PRINT_LABEL not in page
    printed = _printed(page).text()
    assert printed.startswith(DISCLAIMER)
    rest = printed[len(DISCLAIMER) :].strip()
    assert rest.startswith(GERMAN)
    header = re.search(r'<thead class="print-head">(.*?)</thead>', page, re.S).group(1)
    between = header[header.index(DISCLAIMER) + len(DISCLAIMER) : header.index(GERMAN)]
    assert re.sub(r"<[^>]+>", "", between).strip() == ""


def test_sec_urls_are_visible_text_for_the_filing_and_each_fact():
    filing, page = _page()
    sources = re.search(r'<section class="sources">(.*?)</section>', page, re.S)
    assert sources is not None
    block = sources.group(1)
    assert f"<h2>{SOURCES}</h2>" in block
    visible = html.unescape(re.sub(r"<[^>]+>", " ", block))
    assert filing.url in visible
    hrefs = [
        html.unescape(item)
        for item in re.findall(r'href="(https://www\.sec\.gov/[^"]*)"', page)
    ]
    assert hrefs
    for url in hrefs:
        assert url in visible
    words = _SEC.sub(" ", visible)
    assert re.sub(r"\s+", " ", words).strip() == SOURCES
    with using("de"):
        _filing, german_page = _page()
    german_sources = re.search(r'<section class="sources">(.*?)</section>', german_page, re.S).group(1)
    assert f"<h2>{SOURCES_DE}</h2>" in german_sources
    assert SOURCES not in german_sources


def test_checks_print_the_framing_line_and_the_limit_once():
    filing = load_directory(PINNED / "0001045810-26-000075")
    explained = explain_filing(filing)
    page = result_page(
        explained,
        form=filing.form,
        period=filing.period_end or "",
        filed="2026-08-26",
        url=filing.url,
        company=filing.filer,
        focus=filing.focus,
        fiscal_year_end=filing.fiscal_year_end,
    )
    printed = _printed(page).text()
    assert printed.count(FRAME) == 1
    assert printed.count(LIMIT) == 1
    assert html.unescape(page).count(LIMIT) > 1
    with using("de"):
        german = result_page(
            explained,
            form=filing.form,
            period=filing.period_end or "",
            filed="2026-11-01",
            url=filing.url,
            company=filing.filer,
        )
    german_printed = _printed(german).text()
    assert german_printed.count(STRINGS["F.checks"][1]) == 1
    assert german_printed.count(LIMIT_DE) == 1


def test_the_printed_summary_has_no_personal_data_and_no_new_words():
    filing, page = _page()
    css = _print_css(page)
    assert "input { display: none !important; }" in css
    assert ".next" in css
    assert "form" in css
    printed = _printed(page)
    text = printed.text()
    assert "IDENTITYMARKER" not in text
    assert "@" not in text
    assert "Change my name and email" not in text
    identity = first_run_page(
        name="IDENTITYMARKER",
        email="person" + "@" + "example.com",
        token="t",
    )
    hidden = _printed(identity)
    assert "IDENTITYMARKER" in identity
    assert "IDENTITYMARKER" not in hidden.text()
    assert "IDENTITYMARKER" not in " ".join(hidden.values)
    assert "example.com" not in " ".join(hidden.values)
    sources = re.search(r'<section class="sources">(.*?)</section>', page, re.S).group(1)
    visible = html.unescape(re.sub(r"<[^>]+>", " ", sources))
    assert re.sub(r"\s+", " ", _SEC.sub(" ", visible)).strip() == SOURCES
    figures = re.findall(r'<a class="figure" href="[^"]*"[^>]*>(.*?)</a>', page)
    assert figures
    for figure in figures:
        assert html.unescape(figure) in text


def test_multi_page_print_repeats_both_disclaimers_before_the_numbers(tmp_path):
    chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    if chrome is None:
        import pytest

        pytest.skip("chrome is not installed")
    filing = load_directory(PINNED / "0000320193-26-000026")
    explained = explain_filing(filing)
    with using("de"):
        page = result_page(
            explained,
            form=filing.form,
            period=filing.period_end or "",
            filed="2026-11-01",
            url=filing.url,
            company=filing.filer,
            focus=filing.focus,
            fiscal_year_end=filing.fiscal_year_end,
        )
    html_path = tmp_path / "summary.html"
    pdf_path = tmp_path / "summary.pdf"
    html_path.write_text(page, encoding="utf-8")
    subprocess.run(
        [
            "timeout",
            "40",
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert pdf_path.is_file()
    pages = _pdf_pages(pdf_path.read_bytes())
    assert len(pages) >= 2
    saw_number = False
    for text in pages:
        assert text.startswith("This tool explains the numbers")
        german_at = text.index("Dieses Werkzeug")
        digit = re.search(r"\d", text)
        if digit is not None:
            assert german_at < digit.start()
            saw_number = True
    assert saw_number


def _pdf_pages(data: bytes) -> list[str]:
    import zlib

    parts: list[bytes] = []
    for match in re.finditer(rb"stream\r?\n", data):
        start = match.end()
        end = data.find(b"endstream", start)
        raw = data[start:end].strip(b"\r\n")
        try:
            parts.append(zlib.decompress(raw))
        except zlib.error:
            parts.append(raw)
    blob = b"\n".join(parts)
    cmap: dict[int, int] = {}
    for match in re.finditer(rb"beginbfrange\n(.*?)endbfrange", blob, re.S):
        for row in re.finditer(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>",
            match.group(1),
        ):
            left, right, dest = (int(row.group(index), 16) for index in (1, 2, 3))
            for offset, src in enumerate(range(left, right + 1)):
                cmap[src] = dest + offset
    for match in re.finditer(rb"beginbfchar\n(.*?)endbfchar", blob, re.S):
        for row in re.finditer(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", match.group(1)):
            cmap[int(row.group(1), 16)] = int(row.group(2), 16)

    def decode(hex_text: str) -> str:
        raw = bytes.fromhex(hex_text)
        chars = []
        for index in range(0, len(raw), 2):
            code = int.from_bytes(raw[index : index + 2], "big")
            chars.append(chr(cmap.get(code, 0xFFFD)))
        return "".join(chars)

    pages = []
    for chunk in blob.split(b"792 cm")[1:]:
        texts = [
            decode(item.group(1).decode())
            for item in re.finditer(rb"<([0-9A-Fa-f]+)>\s*Tj", chunk)
        ]
        pages.append("".join(texts))
    return pages


def _driver():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("smoke_mac", root / "scripts" / "smoke_mac.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_print_strings_use_print_ids():
    assert STRINGS["PRINT.button"] == (PRINT_LABEL, PRINT_LABEL_DE)
    assert STRINGS["PRINT.sources"] == (SOURCES, SOURCES_DE)
    _filing, page = _page()
    assert f">{PRINT_LABEL}</button>" in page
    assert f"<h2>{SOURCES}</h2>" in page
    with using("de"):
        _filing, german = _page()
    assert f">{PRINT_LABEL_DE}</button>" in german
    assert f"<h2>{SOURCES_DE}</h2>" in german
    assert PRINT_LABEL not in german
    assert SOURCES not in german


def test_readable_pdf_text_fails_when_a_page_lacks_the_disclaimer(monkeypatch):
    driver = _driver()
    carried = "This tool explains the numbers " + ("in the filing " * 8)
    missing = "Revenue was one hundred million dollars in the quarter ended July."

    class Header:
        def call(self, *_args, **_kwargs):
            raise AssertionError("the repeating header was used")

    monkeypatch.setattr(driver, "_pdf_page_texts", lambda _data: [carried, missing])
    with pytest.raises(driver.PageError, match="does not carry the disclaimer"):
        driver._require_disclaimer_on_every_page(Header(), b"%PDF")

    urls = "https://www.sec.gov/Archives/edgar/data/0000320193/ " * 6
    monkeypatch.setattr(driver, "_pdf_page_texts", lambda _data: [carried, urls])
    with pytest.raises(driver.PageError, match="does not carry the disclaimer"):
        driver._require_disclaimer_on_every_page(Header(), b"%PDF")

    junk = "Qwxz " * 40
    monkeypatch.setattr(driver, "_pdf_page_texts", lambda _data: [junk, junk])
    monkeypatch.setattr(
        driver,
        "_eval",
        lambda _tab, _expression: {
            "text": "This tool explains the numbers in a public company filing.",
            "display": "table-header-group",
        },
    )
    driver._require_disclaimer_on_every_page(object(), b"/Type /Page /Type /Page")

    monkeypatch.setattr(driver, "_pdf_page_texts", lambda _data: ["", "??"])
    monkeypatch.setattr(
        driver,
        "_eval",
        lambda _tab, _expression: {
            "text": "This tool explains the numbers in a public company filing.",
            "display": "table-header-group",
        },
    )
    driver._require_disclaimer_on_every_page(object(), b"/Type /Page /Type /Page")


def _stream(dictionary: str, text: bytes) -> bytes:
    raw = zlib.compress(text)
    return f"<< {dictionary} /Length {len(raw)} >>\nstream\n".encode() + raw + b"\nendstream"


def _pdf(parts: list[bytes]) -> bytes:
    chunks = [b"%PDF-1.4\n"]
    for index, part in enumerate(parts, start=1):
        chunks.append(f"{index} 0 obj\n".encode() + part + b"\nendobj\n")
    return b"".join(chunks)


def _glyph_header() -> tuple[bytes, bytes]:
    phrase = "This tool explains the numbers"
    rows = [f"<{index + 1:04x}> <{ord(char):04x}>" for index, char in enumerate(phrase)]
    cmap = (
        "begincmap\r\n"
        f"{len(rows)} beginbfchar\r\n"
        + "\r\n".join(rows)
        + "\r\nendbfchar\r\nendcmap\r\n"
    ).encode()
    shown = "\n".join(f"<{index + 1:04x}> Tj" for index in range(len(phrase)))
    return cmap, f"0 792 cm\n{shown}\n".encode()


def test_a_painted_form_is_part_of_its_page_only():
    """A repeated header is a form drawn on a page. A form is not a page by itself."""
    driver = _driver()
    cmap, header = _glyph_header()
    body = b"(Revenue was one hundred million dollars in the quarter ended July.) Tj\n"
    decoy = b"0 792 cm\n(Revenue was one hundred million dollars in the quarter ended July.) Tj\n"
    pdf = _pdf(
        [
            _stream("/Type /XObject /Subtype /Form", cmap),
            _stream("/Type /XObject /Subtype /Form", header),
            _stream("/Type /XObject /Subtype /Form", body),
            _stream("/Type /XObject /Subtype /Form", decoy),
            _stream("", b"0 792 cm\n/H Do\n/B Do\n"),
            _stream("", b"0 792 cm\n/B Do\n"),
            b"<< /Type /Page /Resources << /XObject << /H 2 0 R /B 3 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Page /Resources << /XObject << /H 2 0 R /B 3 0 R >> >> /Contents 6 0 R >>",
        ]
    )
    texts = driver._pdf_page_texts(pdf)
    assert len(texts) == 2
    assert "This tool explains the numbers" in " ".join(texts[0].split())
    assert "Revenue was one hundred million" in " ".join(texts[0].split())
    assert "This tool explains the numbers" not in " ".join(texts[1].split())
    assert driver._read_disclaimer_pages(texts).startswith("a printed page does not carry the disclaimer")
    both = _pdf(
        [
            _stream("/Type /XObject /Subtype /Form", cmap),
            _stream("/Type /XObject /Subtype /Form", header),
            _stream("/Type /XObject /Subtype /Form", body),
            _stream("/Type /XObject /Subtype /Form", decoy),
            _stream("", b"0 792 cm\n/H Do\n/B Do\n"),
            _stream("", b"0 792 cm\n/H Do\n/B Do\n"),
            b"<< /Type /Page /Resources << /XObject << /H 2 0 R /B 3 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Page /Resources << /XObject << /H 2 0 R /B 3 0 R >> >> /Contents 6 0 R >>",
        ]
    )
    assert driver._read_disclaimer_pages(driver._pdf_page_texts(both)) == ""


def test_a_header_drawn_from_the_page_tree_is_part_of_that_page_only():
    driver = _driver()
    cmap, header = _glyph_header()
    body = b"(Revenue was one hundred million dollars in the quarter ended July.) Tj\n"
    pdf = _pdf(
        [
            _stream("/Type /XObject /Subtype /Form", cmap),
            _stream("/Type /XObject /Subtype /Form", header),
            _stream("", b"0 792 cm\n/H Do\n" + body),
            b"<< /Type /Pages /Resources << /XObject << /H 2 0 R >> >> /Kids [5 0 R 7 0 R] /Count 2 >>",
            b"<< /Type /Page /Parent 4 0 R /Contents 3 0 R >>",
            _stream("", b"0 792 cm\n" + body),
            b"<< /Type /Page /Parent 4 0 R /Contents 6 0 R >>",
        ]
    )
    texts = driver._pdf_page_texts(pdf)
    assert len(texts) == 2
    assert "This tool explains the numbers" in " ".join(texts[0].split())
    assert "Revenue was one hundred million" in " ".join(texts[0].split())
    assert "This tool explains the numbers" not in " ".join(texts[1].split())


def test_a_sec_url_is_not_split_across_printed_pages():
    css = _print_css(_page()[1])
    rule = re.search(r"\.sources li \{[^}]*\}", css)
    assert rule is not None
    assert "break-inside: avoid" in rule.group(0)
    assert "page-break-inside: avoid" in rule.group(0)


def test_the_printed_disclaimer_is_at_least_body_text():
    _filing, page = _page()
    body = re.search(r"body \{[^}]*font-size:\s*(\d+)px", page)
    assert body is not None
    css = _print_css(page)
    printed = re.search(r"\.print-head \.disclaimer \{[^}]*font-size:\s*(\d+)px", css)
    assert printed is not None
    assert int(printed.group(1)) >= int(body.group(1))


def test_a_card_is_not_split_across_printed_pages():
    _filing, page = _page()
    css = _print_css(page)
    rule = re.search(r"article\.card \{[^}]*\}", css)
    assert rule is not None
    assert "break-inside: avoid" in rule.group(0)
    assert "page-break-inside: avoid" in rule.group(0)
    tbody = re.search(r"<tbody>(.*)</tbody>", page, re.S)
    assert tbody is not None
    rows = re.findall(r"<tr\b[^>]*>.*?</tr>", tbody.group(1), re.S)
    card_rows = [row for row in rows if "<article" in row]
    assert card_rows
    assert all(row.count("<article") == 1 for row in card_rows)
    assert len(card_rows) == tbody.group(1).count("<article")
    assert "table.print-sheet > tbody > tr { break-inside: avoid; page-break-inside: avoid; }" in css
