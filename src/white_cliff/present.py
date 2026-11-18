"""HTML screens. The disclaimer is the first text, and every figure is a link."""

from __future__ import annotations

import html
import re
from typing import Sequence

from white_cliff.desktop_copy import DISCLAIMER, ENTER_BOTH, SEC_WHY
from white_cliff.explain import acceptable_name
from white_cliff.pipeline import Explained

_DATA_LINK = re.compile(
    r'<data\b[^>]*>(.*?)</data>\s*'
    r'<a class="source-chip"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
    re.S,
)


def _shell(inner: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        "<title>White Cliff</title>\n"
        "</head>\n"
        "<body>\n"
        f'<p class="disclaimer">{DISCLAIMER}</p>\n'
        "<style>\n"
        "body { font-family: system-ui, sans-serif; font-size: 22px; line-height: 1.6; "
        "color: #111111; background: #ffffff; margin: 1.5rem; }\n"
        "p, label { margin: 1rem 0; }\n"
        "input, button { font: inherit; font-size: 22px; padding: 0.6rem; }\n"
        "a { color: #082567; }\n"
        "button { margin: 0.4rem 0.4rem 0.4rem 0; }\n"
        "</style>\n"
        f"{inner}\n"
        '<script>setInterval(function(){fetch("/stay",{cache:"no-store"})},2000)</script>\n'
        "</body>\n"
        "</html>\n"
    )


def _change_link() -> str:
    return '<p><a href="/identity">Change my name and email</a></p>\n'


def _hidden(token: str) -> str:
    if not token:
        return ""
    safe = html.escape(token, quote=True)
    return f'<input type="hidden" name="token" value="{safe}">\n'


def _search_form(token: str = "") -> str:
    return (
        '<form method="post" action="/explain">\n'
        + _hidden(token)
        + '<p><label for="query">Company name or ticker</label></p>\n'
        '<p><input id="query" name="query" autocomplete="off"></p>\n'
        '<p><button type="submit">Explain</button></p>\n'
        "</form>\n"
    )


def _identity_form(token: str = "") -> str:
    return (
        '<form method="post" action="/identity">\n'
        + _hidden(token)
        + '<p><label for="name">Your name</label></p>\n'
        '<p><input id="name" name="name" autocomplete="name"></p>\n'
        '<p><label for="email">Your email</label></p>\n'
        '<p><input id="email" name="email" type="email" autocomplete="email"></p>\n'
        '<p><button type="submit">Save</button></p>\n'
        "</form>\n"
    )


def first_run_page(*, rejected: bool = False, token: str = "") -> str:
    note = f"<p>{ENTER_BOTH}</p>\n" if rejected else ""
    return _shell(note + f"<p>{html.escape(SEC_WHY)}</p>\n" + _identity_form(token))


def edit_page(token: str = "") -> str:
    erase = (
        '<form method="post" action="/identity/erase">\n'
        + _hidden(token)
        + '<p><button type="submit">Erase</button></p>\n'
        "</form>\n"
    )
    back = '<p><a href="/">Company name or ticker</a></p>\n'
    return _shell(f"<p>{html.escape(SEC_WHY)}</p>\n" + _identity_form(token) + erase + back)


def search_page(token: str = "") -> str:
    return _shell(_change_link() + _search_form(token))


def error_page(sentence: str, token: str = "") -> str:
    return _shell(f"<p>{html.escape(sentence)}</p>\n" + _change_link() + _search_form(token))


def _choice_label(company: object) -> str:
    title = str(getattr(company, "title", "") or "")
    ticker = str(getattr(company, "ticker", "") or "")
    cik = str(getattr(company, "cik", "") or "")
    shown = acceptable_name(f"{title} ({ticker})")
    if shown is None:
        shown = acceptable_name(f"{ticker} {cik}")
    if shown is None:
        shown = acceptable_name(cik)
    if shown is None:
        return "A company on the SEC list"
    return shown


def choices_page(heading: str, companies: Sequence[object], token: str = "") -> str:
    buttons: list[str] = []
    for company in companies:
        label = html.escape(_choice_label(company))
        cik = html.escape(str(getattr(company, "cik", "")), quote=True)
        buttons.append(
            '<form method="post" action="/pick">\n'
            + _hidden(token)
            + f'<p><button type="submit" name="cik" value="{cik}">{label}</button></p>\n'
            "</form>\n"
        )
    body = f"<p>{html.escape(heading)}</p>\n" + "".join(buttons)
    return _shell(body + _change_link() + _search_form(token))


def _link_numbers(page: str) -> str:
    def replace(match: re.Match[str]) -> str:
        label, href, title = match.group(1), match.group(2), match.group(3)
        return f'<a class="figure" href="{href}">{label}</a> {title}'

    return _DATA_LINK.sub(replace, page)


def _explanation_body(explained_html: str) -> str:
    transformed = _link_numbers(explained_html)
    parts = re.findall(r"<p\b[^>]*>.*?</p>", transformed, flags=re.I | re.S)
    kept: list[str] = []
    for part in parts:
        if 'class="disclaimer"' in part or "github.com" in part or "Report an error" in part:
            continue
        kept.append(part)
    return "\n".join(kept)


def _filing_line(form: str, period: str, filed: str, url: str) -> str:
    bits = [form] if form else []
    if period:
        bits.append("period ended " + period)
    if filed:
        bits.append("filed " + filed)
    label = ", ".join(bits)
    if url.startswith("https://www.sec.gov/") or url.startswith("https://data.sec.gov/"):
        href = html.escape(url, quote=True)
        return f'<p><a href="{href}">{html.escape(label)}</a></p>\n'
    if not label:
        return ""
    return f"<p>{html.escape(label)}</p>\n"


def result_page(
    explained: Explained,
    *,
    form: str,
    period: str,
    filed: str,
    url: str,
    token: str = "",
) -> str:
    inner = (
        _change_link()
        + _search_form(token)
        + _filing_line(form, period, filed, url)
        + _explanation_body(explained.html)
    )
    return _shell(inner)
