"""Render checked sentences to Markdown and HTML with source chips."""

from __future__ import annotations

import html
import re
from urllib.parse import urlsplit, urlunsplit

from white_cliff.disclaimer import DISCLAIMER, ISSUE_URL, OutputRefused, ensure_safe_output
from white_cliff.explain import Block
from white_cliff.facts import FactStore, format_decimal
from white_cliff.quotes import Quote, QuoteError, review_quotes

_TOKEN = re.compile(r"\{(fact|calc):([a-z]+)\}|\{redaction\}|\[section:([^\]]+)\]")
_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"([^\"]*)\")?\)")


def _with_fragment(url: str, fragment: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, fragment))


def _fragment(identifier: str, start: int | None, end: int | None) -> str:
    kind = "calc" if identifier.startswith("calc") else "fact"
    fragment = f"{kind}={identifier}"
    if start is not None and end is not None:
        fragment += f"&start={start}&end={end}"
    return fragment


def _markdown_chip(label: str, url: str, title: str) -> str:
    return f'[{label}]({url} "{title}")'


def _shown(value, unit: str) -> str:
    if unit == "percent":
        return f"{value:.1f}"
    return format_decimal(value)


def _escape_text(raw: str, mode: str) -> str:
    if mode == "html":
        return html.escape(raw, quote=False)
    return raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _quote_bounds(text: str, quote: Quote) -> tuple[int, int] | None:
    if quote.text_end > quote.text_start:
        return quote.text_start, quote.text_end
    found = text.find(quote.text)
    if found < 0:
        return None
    return found, found + len(quote.text)


def _fill(text: str, store: FactStore, block: Block, mode: str) -> str:
    spans: list[tuple[int, int, str, object]] = []
    for match in _TOKEN.finditer(text):
        spans.append((match.start(), match.end(), "token", match))
    for quote in getattr(block, "quotes", ()) or ():
        bounds = _quote_bounds(text, quote)
        if bounds is not None:
            spans.append((bounds[0], bounds[1], "quote", quote))
    spans.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    pieces: list[str] = []
    offset = 0
    for start, end, kind, payload in spans:
        if start < offset:
            continue
        pieces.append(_escape_text(text[offset:start], mode))
        if kind == "quote":
            pieces.append(_quote_piece(payload, mode))
        else:
            pieces.append(_token_piece(payload, store, block, mode))
        offset = max(offset, end)
    pieces.append(_escape_text(text[offset:], mode))
    return "".join(pieces)


def _quote_piece(quote: object, mode: str) -> str:
    body = quote.text
    if mode == "html":
        return f'<a href="{html.escape(quote.url, quote=True)}">{html.escape(body, quote=False)}</a>'
    visible = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'[{visible}]({quote.url} "filing")'


def _token_piece(match: re.Match[str], store: FactStore, block: Block, mode: str) -> str:
    if match.group(0) == "{redaction}":
        if block.redaction is None:
            raise OutputRefused("missing redaction")
        redaction = block.redaction
        href = _with_fragment(
            redaction.url,
            f"redaction={redaction.id}&start={redaction.start}&end={redaction.end}",
        )
        if mode == "html":
            return (
                f'<a class="redaction-chip" data-id="{redaction.id}" '
                f'href="{html.escape(href, quote=True)}">source</a>'
            )
        return _markdown_chip("source", href, "Document")
    if match.group(3) is not None:
        section = match.group(3)
        return "Section: " + (_escape_text(section, mode) if mode == "html" else section)
    kind, identifier = match.group(1), match.group(2)
    if kind == "fact":
        fact = store.get(identifier)
        label = f"{_shown(fact.value, fact.unit)} {fact.unit}"
        href = _with_fragment(
            fact.source.url,
            _fragment(fact.id, fact.source.char_start, fact.source.char_end),
        )
        title = fact.source.section
        if mode == "html":
            return (
                f'<data data-kind="fact" data-id="{fact.id}">{html.escape(label, quote=False)}</data> '
                f'<a class="source-chip" data-id="{fact.id}" '
                f'href="{html.escape(href, quote=True)}">{html.escape(title, quote=False)}</a>'
            )
        return _markdown_chip(label, href, title)
    calc = store.get_calc(identifier)
    source_fact = store.get(calc.input_ids[0])
    label = f"{_shown(calc.value, calc.unit)} {calc.unit}"
    href = _with_fragment(
        source_fact.source.url,
        _fragment(calc.id, source_fact.source.char_start, source_fact.source.char_end),
    )
    title = source_fact.source.section
    if mode == "html":
        return (
            f'<data data-kind="calc" data-id="{calc.id}">{html.escape(label, quote=False)}</data> '
            f'<a class="source-chip" data-id="{calc.id}" '
            f'href="{html.escape(href, quote=True)}">{html.escape(title, quote=False)}</a>'
        )
    return _markdown_chip(label, href, title)


def render_markdown(blocks: list[Block], store: FactStore) -> str:
    body = [_fill(block.text, store, block, "md") for block in blocks]
    report = f"Report an error: [Report an error]({ISSUE_URL})."
    text = DISCLAIMER + "\n\n" + "\n\n".join(body) + "\n\n" + report + "\n"
    return ensure_safe_output(text)


def render_html(blocks: list[Block], store: FactStore) -> str:
    paragraphs = "".join(f"<p>{_fill(block.text, store, block, 'html')}</p>" for block in blocks)
    document = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        "<title>Filing explanation</title>\n"
        "</head>\n"
        "<body>\n"
        f'<p class="disclaimer">{DISCLAIMER}</p>\n'
        f"{paragraphs}\n"
        f'<p><a href="{ISSUE_URL}">Report an error</a></p>\n'
        "</body>\n"
        "</html>\n"
    )
    return ensure_safe_output(document)


def copy_text(markdown: str) -> str:
    """Copyable export. Same bytes as the Markdown, refused if the disclaimer is absent."""
    return ensure_safe_output(markdown)


def markdown_figure_ids(markdown: str) -> list[tuple[str, str, str]]:
    """Return (label, url, title) for every Markdown link."""
    return [(m.group(1), m.group(2), m.group(3) or "") for m in _LINK.finditer(markdown)]


def render_quote_page(text: str, filing_text: str, filing_url: str) -> tuple[str, str]:
    """Render one sentence, linking any quote that survives the quote check."""
    store = FactStore()
    try:
        quotes = review_quotes(text, filing_text, filing_url)
        block = Block(text=text, quotes=tuple(quotes))
    except QuoteError:
        block = Block(
            text="This section was omitted because it failed the quote check [section:Notes].",
            reason="quote",
        )
    return render_markdown([block], store), render_html([block], store)
