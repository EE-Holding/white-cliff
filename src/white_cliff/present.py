"""HTML screens. The disclaimer is the first text, and every figure is a link."""

from __future__ import annotations

import calendar
import html
import re
from datetime import date
from typing import Sequence

from white_cliff.desktop_copy import CLOSED, DISCLAIMER, ENTER_BOTH, LOOKING, SEC_WHY
from white_cliff.explain import acceptable_name
from white_cliff.pipeline import Explained

_DATA_LINK = re.compile(
    r"(.*?)<data\b[^>]*>(.*?)</data>\s*"
    r'<a class="source-chip"[^>]*href="([^"]*)"[^>]*>.*?</a>',
    re.S,
)
_MONEY = re.compile(
    r"^(-?\d+(?:\.\d+)?)(?:\s+USD)?(?:\s+(millions|thousands|billions))?$",
    re.I,
)
_TAG = re.compile(r"<[^>]+>")
_SCALE = {
    "millions": "million",
    "thousands": "thousand",
    "billions": "billion",
}


def shown_amount(raw: str) -> str:
    """The filing amount, with separators and a dollar sign. No new rounding."""
    text = " ".join(html.unescape(raw).split())
    match = _MONEY.fullmatch(text)
    if match is not None:
        number, scale = match.group(1), match.group(2)
        shown = _commas(number)
        if "USD" in text:
            shown = f"${shown}"
        if scale:
            shown = f"{shown} {_SCALE.get(scale.lower(), scale.lower())}"
        return shown
    parts = text.split()
    scale = ""
    if len(parts) >= 2 and parts[-1].lower() in _SCALE:
        scale = parts[-1]
        parts = parts[:-1]
    if not parts or re.fullmatch(r"-?\d+(?:\.\d+)?", parts[0]) is None:
        return text
    shown = _commas(parts[0])
    if scale:
        shown = f"{shown} {_SCALE[scale.lower()]}"
    unit = " ".join(parts[1:])
    if unit:
        shown = f"{shown} {unit}"
    return shown


def _commas(number: str) -> str:
    sign = ""
    if number.startswith("-"):
        sign = "-"
        number = number[1:]
    whole, dot, frac = number.partition(".")
    groups: list[str] = []
    while whole:
        groups.append(whole[-3:])
        whole = whole[:-3]
    body = ",".join(reversed(groups)) or "0"
    if dot:
        body = f"{body}.{frac}"
    return sign + body


def _plain_date(iso: str) -> str:
    try:
        year, month, day = (int(part) for part in str(iso).split("-"))
        when = date(year, month, day)
    except (TypeError, ValueError):
        return ""
    return f"{calendar.month_name[when.month]} {when.day}, {when.year}"


def plain_report(form: str, period: str) -> str:
    when = _plain_date(period)
    if form == "10-Q":
        if when:
            return f"Quarterly report for the three months ended {when}."
        return "Quarterly report."
    if form == "10-K":
        if when:
            return f"Annual report for the year ended {when}."
        return "Annual report."
    if when:
        return f"Report for the period ended {when}."
    return ""


def _shell(inner: str) -> str:
    closed = html.escape(CLOSED, quote=True)
    looking = html.escape(LOOKING, quote=True)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        "<title>White Cliff</title>\n"
        "</head>\n"
        "<body>\n"
        f'<p class="disclaimer">{DISCLAIMER}</p>\n'
        "<style>\n"
        "body { margin: 0; background: #ffffff; color: #1d1d1f; "
        'font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; '
        "font-size: 21px; line-height: 1.5; }\n"
        ".disclaimer, .column { max-width: 640px; margin-left: auto; margin-right: auto; "
        "padding-left: 1.5rem; padding-right: 1.5rem; }\n"
        ".disclaimer { margin-top: 4.5rem; margin-bottom: 0; color: #3a3a3c; "
        "font-size: 18px; line-height: 1.5; }\n"
        ".column { padding-top: 2.5rem; padding-bottom: 5rem; }\n"
        "h1 { font-size: 40px; font-weight: 600; letter-spacing: -0.02em; "
        "margin: 0 0 0.35rem; }\n"
        ".quiet { color: #3a3a3c; margin: 0 0 2rem; }\n"
        ".notice { margin: 0 0 1rem; }\n"
        ".failure { background: #f4f4f6; border-radius: 16px; "
        "padding: 1.25rem 1.4rem; margin: 0 0 1.75rem; }\n"
        ".failure .notice { font-size: 21px; margin: 0; }\n"
        "label { display: block; margin: 0 0 0.6rem; }\n"
        "input { font: inherit; font-size: 24px; width: 100%; box-sizing: border-box; "
        "padding: 0.85rem 1rem; border: 1px solid #d2d2d7; border-radius: 12px; "
        "color: #1d1d1f; background: #ffffff; }\n"
        "button { font: inherit; font-size: 21px; margin-top: 1rem; "
        "background: #1d1d1f; color: #ffffff; border: 0; border-radius: 12px; "
        "padding: 0.85rem 1.4rem; }\n"
        "button:disabled { opacity: 0.55; }\n"
        "button.choice { display: block; width: 100%; text-align: left; "
        "background: #ffffff; color: #1d1d1f; border: 1px solid #d2d2d7; "
        "margin: 0.6rem 0; }\n"
        ".progress { height: 2px; background: #e6e6e8; margin: 0.8rem 0 0; overflow: hidden; }\n"
        ".progress span { display: block; height: 100%; width: 40%; background: #0a4b8f; }\n"
        ".row { display: flex; justify-content: space-between; gap: 1.5rem; "
        "padding: 0.9rem 0; border-bottom: 1px solid #e6e6e8; }\n"
        "a { color: #0a4b8f; }\n"
        "a.figure { color: #1d1d1f; text-decoration: none; white-space: nowrap; }\n"
        ".filing { margin-top: 1.5rem; }\n"
        ".change { margin-top: 4rem; font-size: 16px; }\n"
        ".change a { color: #3a3a3c; }\n"
        "</style>\n"
        '<div class="column">\n'
        f"{inner}\n"
        "</div>\n"
        "<script>\n"
        "(function () {\n"
        f'  var closed = "{closed}";\n'
        f'  var looking = "{looking}";\n'
        "  function say(text) {\n"
        '    var note = document.getElementById("working");\n'
        "    if (!note) return;\n"
        "    note.hidden = false;\n"
        "    note.textContent = text;\n"
        "  }\n"
        '  document.querySelectorAll("form").forEach(function (form) {\n'
        '    form.addEventListener("submit", function (event) {\n'
        "      event.preventDefault();\n"
        '      var button = form.querySelector("button");\n'
        "      if (button) button.disabled = true;\n"
        '      var bar = document.getElementById("progress");\n'
        "      if (bar) bar.hidden = false;\n"
        "      say(looking);\n"
        "      var data = new FormData(form);\n"
        "      if (event.submitter && event.submitter.name) {\n"
        "        data.set(event.submitter.name, event.submitter.value);\n"
        "      }\n"
        "      fetch(form.action, {\n"
        '        method: "POST",\n'
        '        headers: {"Content-Type": "application/x-www-form-urlencoded"},\n'
        "        body: new URLSearchParams(data),\n"
        '        credentials: "same-origin",\n'
        '        redirect: "manual",\n'
        '        cache: "no-store"\n'
        "      }).then(function (response) {\n"
        '        if (response.type === "opaqueredirect" || response.status === 303 || response.status === 302) {\n'
        '          window.location.assign("/");\n'
        "          return;\n"
        "        }\n"
        "        return response.text().then(function (html) {\n"
        "          document.open();\n"
        "          document.write(html);\n"
        "          document.close();\n"
        "        });\n"
        "      }).catch(function () {\n"
        "        if (button) button.disabled = false;\n"
        "        if (bar) bar.hidden = true;\n"
        "        say(closed);\n"
        "      });\n"
        "    });\n"
        "  });\n"
        "  setInterval(function () {\n"
        '    fetch("/stay", {cache: "no-store", credentials: "same-origin"}).catch(function () {\n'
        "      say(closed);\n"
        "    });\n"
        "  }, 2000);\n"
        "})();\n"
        "</script>\n"
        "</body>\n"
        "</html>\n"
    )


def _change_link() -> str:
    return '<p class="change"><a href="/identity">Change my name and email</a></p>\n'


def _hidden(token: str) -> str:
    if not token:
        return ""
    safe = html.escape(token, quote=True)
    return f'<input type="hidden" name="token" value="{safe}">\n'


def _notice(sentence: str) -> str:
    if not sentence:
        return '<p class="notice" id="working" hidden></p>\n'
    return (
        '<div class="failure">\n'
        f'<p class="notice" id="working">{html.escape(sentence)}</p>\n'
        "</div>\n"
    )


def _progress() -> str:
    return '<div class="progress" id="progress" hidden><span></span></div>\n'


def _value(text: str) -> str:
    if not text:
        return ""
    return f' value="{html.escape(text, quote=True)}"'


def _search_form(
    token: str = "",
    notice: str = "",
    *,
    focus: bool = True,
    query: str = "",
) -> str:
    auto = " autofocus" if focus else ""
    return (
        '<form method="post" action="/explain">\n'
        + _hidden(token)
        + _notice(notice)
        + _progress()
        + '<p><label for="query">Company name or ticker</label></p>\n'
        + f'<p><input id="query" name="query" autocomplete="off"{_value(query)}{auto}></p>\n'
        + '<p><button type="submit">Explain</button></p>\n'
        + "</form>\n"
    )


def _identity_form(
    token: str = "",
    notice: str = "",
    *,
    name: str = "",
    email: str = "",
) -> str:
    return (
        '<form method="post" action="/identity">\n'
        + _hidden(token)
        + _notice(notice)
        + _progress()
        + '<p><label for="name">Your name</label></p>\n'
        + f'<p><input id="name" name="name" autocomplete="name" autofocus{_value(name)}></p>\n'
        + '<p><label for="email">Your email</label></p>\n'
        + f'<p><input id="email" name="email" type="email" autocomplete="email"{_value(email)}></p>\n'
        + '<p><button type="submit">Save</button></p>\n'
        + "</form>\n"
    )


def first_run_page(
    *,
    rejected: bool = False,
    token: str = "",
    name: str = "",
    email: str = "",
    notice: str = "",
) -> str:
    note = notice or (ENTER_BOTH if rejected else "")
    return _shell(
        f"<p>{html.escape(SEC_WHY)}</p>\n"
        + _identity_form(token, note, name=name, email=email)
    )


def edit_page(
    token: str = "",
    *,
    name: str = "",
    email: str = "",
    notice: str = "",
) -> str:
    erase = (
        '<form method="post" action="/identity/erase">\n'
        + _hidden(token)
        + '<p><button type="submit">Erase</button></p>\n'
        + "</form>\n"
    )
    return _shell(
        f"<p>{html.escape(SEC_WHY)}</p>\n"
        + _identity_form(token, notice, name=name, email=email)
        + erase
        + _change_link()
    )


def search_page(token: str = "") -> str:
    return _shell(_search_form(token) + _change_link())


def error_page(sentence: str, token: str = "", query: str = "") -> str:
    return _shell(_search_form(token, notice=sentence, query=query) + _change_link())


_RATING_WORDS = (
    "strong buy",
    "outperform",
    "underperform",
    "undervalued",
    "overvalued",
    "overweight",
    "underweight",
    "recommended",
    "recommend",
    "downside",
    "upside",
    "target",
    "sell",
    "hold",
    "buy",
)


def _rating_name(name: str) -> bool:
    folded = " ".join(name.casefold().split())
    for phrase in _RATING_WORDS:
        if re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", folded):
            return True
    return False


def _plain_company(name: str) -> str | None:
    cleaned = " ".join(name.split())
    if not cleaned or _rating_name(cleaned):
        return None
    return acceptable_name(cleaned)


def _ticker_cik(ticker: str, cik: str) -> str:
    shown = acceptable_name(f"{ticker} {cik}".strip())
    if shown:
        return shown
    return acceptable_name(cik.strip()) or ""


def _choice_label(company: object) -> str:
    title = str(getattr(company, "title", "") or "")
    ticker = str(getattr(company, "ticker", "") or "")
    cik = str(getattr(company, "cik", "") or "")
    shown = _plain_company(title)
    if shown is None:
        shown = _ticker_cik(ticker, cik) or None
    if shown is None:
        return "A company on the SEC list"
    return shown


def choices_page(
    heading: str,
    companies: Sequence[object],
    token: str = "",
    query: str = "",
) -> str:
    buttons: list[str] = []
    for company in companies:
        label = html.escape(_choice_label(company))
        cik = html.escape(str(getattr(company, "cik", "")), quote=True)
        buttons.append(
            '<form method="post" action="/pick">\n'
            + _hidden(token)
            + f'<p><button class="choice" type="submit" name="cik" value="{cik}">{label}</button></p>\n'
            + "</form>\n"
        )
    body = f'<p class="notice">{html.escape(heading)}</p>\n' + "".join(buttons)
    return _shell(body + _search_form(token, focus=False, query=query) + _change_link())


def _plain_label(lead: str) -> str:
    text = " ".join(_TAG.sub(" ", html.unescape(lead)).split())
    text = re.sub(r"\s+was$", "", text)
    text = re.sub(r"\s+for the (fiscal year|quarter)$", "", text)
    return text.strip()


def _rows(explained_html: str) -> str:
    rows: list[str] = []
    for part in re.findall(r"<p\b[^>]*>.*?</p>", explained_html, flags=re.I | re.S):
        if 'class="disclaimer"' in part or "github.com" in part or "Report an error" in part:
            continue
        match = _DATA_LINK.search(part)
        if match is None:
            continue
        label = _plain_label(match.group(1))
        amount = shown_amount(match.group(2))
        href = html.escape(html.unescape(match.group(3)), quote=True)
        if not label:
            continue
        rows.append(
            '<div class="row">'
            f'<span>{html.escape(label)}</span>'
            f'<a class="figure" href="{href}">{html.escape(amount)}</a>'
            "</div>\n"
        )
    return "".join(rows)


def _company_name(
    explained_html: str,
    company: str,
    ticker: str = "",
    cik: str = "",
) -> str:
    if company:
        chosen = _plain_company(company)
        if chosen:
            return chosen
    match = re.search(r'<a class="registrant-chip"[^>]*>(.*?)</a>', explained_html, re.S)
    if match is not None:
        chip = html.unescape(_TAG.sub("", match.group(1))).strip()
        chosen = _plain_company(chip)
        if chosen:
            return chosen
    return _ticker_cik(ticker, cik)


def result_page(
    explained: Explained,
    *,
    form: str,
    period: str,
    filed: str,
    url: str,
    token: str = "",
    company: str = "",
    ticker: str = "",
    cik: str = "",
) -> str:
    del filed
    name = _company_name(explained.html, company, ticker, cik)
    heading = f"<h1>{html.escape(name)}</h1>\n" if name else ""
    line = plain_report(form, period)
    quiet = f'<p class="quiet">{html.escape(line)}</p>\n' if line else ""
    filing = ""
    if url.startswith("https://www.sec.gov/") or url.startswith("https://data.sec.gov/"):
        href = html.escape(url, quote=True)
        filing = f'<p class="filing"><a href="{href}">The filing</a></p>\n'
    inner = heading + quiet + _rows(explained.html) + filing + _search_form(token, focus=False) + _change_link()
    return _shell(inner)
