"""Render checked sentences to Markdown and HTML with source chips."""

from __future__ import annotations

import html
import re
from urllib.parse import urlsplit, urlunsplit

from white_cliff.disclaimer import DISCLAIMER, ISSUE_URL, OutputRefused, ensure_safe_output
from white_cliff.explain import Block
from white_cliff.facts import FactStore, format_decimal

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


def _fill(text: str, store: FactStore, block: Block, mode: str) -> str:
    pieces: list[str] = []
    offset = 0
    for match in _TOKEN.finditer(text):
        raw = text[offset : match.start()]
        pieces.append(html.escape(raw) if mode == "html" else raw)
        if match.group(0) == "{redaction}":
            if block.redaction is None:
                raise OutputRefused("missing redaction")
            redaction = block.redaction
            href = _with_fragment(
                redaction.url,
                f"redaction={redaction.id}&start={redaction.start}&end={redaction.end}",
            )
            if mode == "html":
                pieces.append(
                    f'<a class="redaction-chip" data-id="{redaction.id}" '
                    f'href="{html.escape(href, quote=True)}">source</a>'
                )
            else:
                pieces.append(_markdown_chip("source", href, "Document"))
        elif match.group(3) is not None:
            section = match.group(3)
            pieces.append("Section: " + (html.escape(section) if mode == "html" else section))
        else:
            kind, identifier = match.group(1), match.group(2)
            if kind == "fact":
                fact = store.get(identifier)
                label = f"{format_decimal(fact.value)} {fact.unit}"
                href = _with_fragment(
                    fact.source.url,
                    _fragment(fact.id, fact.source.char_start, fact.source.char_end),
                )
                title = fact.source.section
                if mode == "html":
                    pieces.append(
                        f'<data data-kind="fact" data-id="{fact.id}">{html.escape(format_decimal(fact.value))}</data> '
                        f'{html.escape(fact.unit)} '
                        f'<a class="source-chip" data-id="{fact.id}" '
                        f'href="{html.escape(href, quote=True)}">{html.escape(title)}</a>'
                    )
                else:
                    pieces.append(_markdown_chip(label, href, title))
            else:
                calc = store.get_calc(identifier)
                source_fact = store.get(calc.input_ids[0])
                label = f"{format_decimal(calc.value)} {calc.unit}"
                href = _with_fragment(
                    source_fact.source.url,
                    _fragment(calc.id, source_fact.source.char_start, source_fact.source.char_end),
                )
                title = source_fact.source.section
                if mode == "html":
                    pieces.append(
                        f'<data data-kind="calc" data-id="{calc.id}">{html.escape(format_decimal(calc.value))}</data> '
                        f'{html.escape(calc.unit)} '
                        f'<a class="source-chip" data-id="{calc.id}" '
                        f'href="{html.escape(href, quote=True)}">{html.escape(title)}</a>'
                    )
                else:
                    pieces.append(_markdown_chip(label, href, title))
        offset = match.end()
    tail = text[offset:]
    pieces.append(html.escape(tail) if mode == "html" else tail)
    return "".join(pieces)


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
