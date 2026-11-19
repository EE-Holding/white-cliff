"""HTML screens. The disclaimer is the first text, and every figure is a link."""

from __future__ import annotations

import calendar
import html
import re
from datetime import date
from typing import Sequence

from urllib.parse import urlsplit

from white_cliff.desktop_copy import (
    CLOSED,
    DISCLAIMER,
    ENTER_BOTH,
    FILING_LIST,
    FINDING,
    LOOKING,
    READING,
    READING_PRIOR,
    SEC_WHY,
)
from white_cliff.disclaimer import ISSUE_URL, OutputRefused
from white_cliff.explain import acceptable_name
from white_cliff.german import format_measure, format_raw
from white_cliff.i18n import focus_language, german, phrase, shown_copy, ui
from white_cliff.pipeline import Explained
from white_cliff.strings import EN

_DATA_LINK = re.compile(
    r"(.*?)<data\b[^>]*>(.*?)</data>\s*"
    r'<a class="source-chip"[^>]*href="([^"]*)"[^>]*>.*?</a>',
    re.S,
)
_MONEY = re.compile(
    r"^(-?\d+(?:\.\d+)?)(?:\s+USD)?(?:\s+(millions|thousands|billions))?$",
    re.I,
)
_PER_SHARE = re.compile(
    r"^(-?\d+(?:\.\d+)?)\s+USD(?:\s*/\s*shares|\s+per\s+share)"
    r"(?:\s+(millions|thousands|billions))?$",
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
    if german():
        return format_raw(raw)
    text = " ".join(html.unescape(raw).split())
    per_share = _PER_SHARE.fullmatch(text)
    if per_share is not None:
        shown = f"${_commas(per_share.group(1))}"
        scale = per_share.group(2)
        if scale:
            shown = f"{shown} {_SCALE[scale.lower()]}"
        return f"{shown} per share"
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
    if not parts or re.fullmatch(r"-?\d+(?:\.\d+)?", parts[0]) is None:
        return text
    scale = ""
    rest: list[str] = []
    for part in parts[1:]:
        if part.lower() in _SCALE and not scale:
            scale = part.lower()
        else:
            rest.append(part)
    shown = _commas(parts[0])
    if scale:
        shown = f"{shown} {_SCALE[scale]}"
    if rest:
        shown = f"{shown} {' '.join(rest)}"
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
    return f"{calendar.month_name[when.month]}\u00a0{when.day},\u00a0{when.year}"


def plain_report(form: str, period: str) -> str:
    when = _plain_date(period)
    if german():
        from white_cliff.wording import long_date

        dated = long_date(period) if period else ""
        if form == "10-Q":
            if dated:
                return phrase("PR.report_10q").replace("{date}", dated)
            return phrase("PR.report_10q_nodate")
        if form == "10-K":
            if dated:
                return phrase("PR.report_10k").replace("{date}", dated)
            return phrase("PR.report_10k_nodate")
        if dated:
            return phrase("PR.report_other").replace("{date}", dated)
        return ""
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


def _language_control(token: str) -> str:
    """The English/Deutsch switch. It sits after the disclaimer."""

    def segment(code: str, label: str) -> str:
        pressed = "true" if (code == "de") == german() else "false"
        return (
            '<form method="post" action="/language">\n'
            + _hidden(token)
            + f'<input type="hidden" name="language" value="{code}">\n'
            + f'<button type="submit" lang="{code}" aria-pressed="{pressed}">'
            + html.escape(label)
            + "</button>\n"
            + "</form>\n"
        )

    return (
        f'<div class="lang" role="group" aria-label="{html.escape("Language / Sprache", quote=True)}">\n'
        + segment("en", "English")
        + segment("de", "Deutsch")
        + "</div>\n"
    )


def _shell(inner: str, *, result: bool = False, token: str = "") -> str:
    closed = html.escape(shown_copy(CLOSED), quote=True)
    looking = html.escape(shown_copy(LOOKING), quote=True)
    finding = html.escape(shown_copy(FINDING), quote=True)
    filing_list = html.escape(shown_copy(FILING_LIST), quote=True)
    reading = html.escape(shown_copy(READING), quote=True)
    reading_prior = html.escape(shown_copy(READING_PRIOR), quote=True)
    body = '<body class="result">\n' if result else "<body>\n"
    lang = "de" if german() else "en"
    marked = ' data-lang-set="1"' if focus_language.get() else ""
    disclaimer = f'<p class="disclaimer">{DISCLAIMER}</p>\n'
    if german():
        disclaimer += f'<p class="disclaimer" lang="de">{html.escape(phrase("§1.DISCLAIMER"))}</p>\n'
    page = (
        "<!DOCTYPE html>\n"
        f'<html lang="{lang}"{marked}>\n'
        "<head>\n"
        f"<title>{html.escape(ui('app_name'))}</title>\n"
        "</head>\n"
        f"{body}"
        f"{disclaimer}"
        f'<div class="top"><p class="app">{html.escape(ui("app_name"))}</p>'
        f"{_language_control(token)}</div>\n"
        "<style>\n"
        ":root { --bg: #ffffff; --ink: #1d1d1f; --ink-2: #3a3a3c; --ink-3: #555559; "
        "--accent: #0a4b8f; --line: #86868b; --hairline: #e6e6e8; --panel: #f5f5f7; "
        "--btn-busy: #3a3a3c; --on-btn: #ffffff; "
        "--s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px; --s6: 32px; "
        "--s7: 48px; --s8: 64px; "
        "--dur-xs: 100ms; --dur-s: 200ms; --dur-m: 300ms; --dur-l: 400ms; "
        "--spin: 1000ms; --stagger: 60ms; "
        "--ease-standard: cubic-bezier(0.2, 0, 0, 1); "
        "--ease-decel: cubic-bezier(0.05, 0.7, 0.1, 1); "
        "--ease-accel: cubic-bezier(0.3, 0, 0.8, 0.15); }\n"
        "html { box-sizing: border-box; }\n"
        "*, *::before, *::after { box-sizing: inherit; }\n"
        "body { margin: 0; background: #f5f5f7; color: var(--ink); "
        'font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; '
        "font-size: 21px; line-height: 32px; }\n"
        ".disclaimer, .top, .column { max-width: 1160px; margin-left: auto; margin-right: auto; "
        "padding-left: 32px; padding-right: 32px; }\n"
        ".disclaimer { margin-top: 0; margin-bottom: 0; margin-left: auto; margin-right: auto; "
        "padding-top: 40px; color: var(--ink-2); "
        "font-size: 18px; line-height: 27px; }\n"
        ".disclaimer + .disclaimer { padding-top: 8px; }\n"
        ".top { display: flex; align-items: center; justify-content: space-between; "
        "gap: 16px; padding-top: 24px; }\n"
        ".app { margin: 0; font-size: 18px; line-height: 27px; font-weight: 600; color: var(--ink-2); }\n"
        ".lang { display: flex; align-items: stretch; background: #e3e3e8; "
        "border-radius: 12px; padding: 3px; }\n"
        ".lang form { margin: 0; }\n"
        ".lang button { margin: 0; min-height: 44px; min-width: 104px; "
        "padding: 0 12px; border: 0; border-radius: 10px; background: transparent; "
        "color: var(--ink); font-size: 18px; line-height: 27px; font-weight: 600; "
        "box-shadow: none; "
        "transition: background 200ms var(--ease-standard), box-shadow 200ms var(--ease-standard); }\n"
        '.lang button[aria-pressed="true"] { background: #ffffff; '
        "box-shadow: 0 1px 3px rgba(0,0,0,.12); }\n"
        ".column { padding-top: 40px; padding-bottom: 80px; "
        "animation: fade 200ms var(--ease-standard) both; }\n"
        "body.result .column { animation: none; }\n"
        "html[data-lang-set] .column { animation: fade 200ms var(--ease-standard) both; }\n"
        "h1 { font-size: 48px; line-height: 52px; font-weight: 700; letter-spacing: -0.025em; "
        "margin: 0; }\n"
        ".quiet { color: var(--ink-2); font-size: 21px; line-height: 32px; margin: 8px 0 0; }\n"
        ".hero { margin-bottom: 40px; }\n"
        ".notice { margin: 0; font-size: 21px; line-height: 32px; color: var(--ink); }\n"
        ".failure { background: var(--panel); border-left: 4px solid var(--accent); "
        "border-radius: 16px; padding: 20px 24px; margin: 0 0 24px; "
        "animation: enter 200ms var(--ease-decel) both; }\n"
        "label { display: block; margin: 0 0 8px; font-size: 21px; line-height: 32px; }\n"
        "input { font: inherit; font-size: 24px; line-height: 32px; width: 100%; "
        "box-sizing: border-box; min-height: 60px; padding: 14px 16px; "
        "border: 2px solid var(--line); border-radius: 12px; color: var(--ink); "
        "background: var(--bg); }\n"
        "button { font: inherit; font-size: 22px; line-height: 28px; font-weight: 600; "
        "margin-top: 16px; min-height: 56px; background: var(--ink); color: var(--on-btn); "
        "border: 0; border-radius: 12px; padding: 14px 24px; }\n"
        "button.busy { background: var(--btn-busy); color: var(--on-btn); cursor: progress; }\n"
        "form.search, form.pick { background: #ffffff; border: 1px solid #e8e8ed; "
        "border-radius: 22px; padding: 24px 28px; max-width: 680px; "
        "margin-left: auto; margin-right: auto; }\n"
        ".search-row { display: flex; gap: 12px; align-items: center; }\n"
        ".search-row input { flex: 1; min-width: 0; }\n"
        ".search-row button { margin-top: 0; min-height: 60px; }\n"
        "form.pick { margin: 0 auto 8px; }\n"
        "button.choice { display: block; width: 100%; text-align: left; font-weight: 400; "
        "background: var(--bg); color: var(--ink); border: 2px solid var(--line); margin: 0; "
        "min-height: 56px; padding: 14px 24px; }\n"
        ".steps { background: var(--panel); border-radius: 16px; padding: 24px; "
        "margin-top: 24px; max-width: 100%; }\n"
        ".steps.open { animation: enter 200ms var(--ease-decel) both; }\n"
        ".steps.leave { animation: leave 150ms var(--ease-accel) forwards; }\n"
        ".steps-title { margin: 0 0 16px; font-size: 21px; line-height: 32px; color: var(--ink); }\n"
        ".steps ol { list-style: none; margin: 0; padding: 0; }\n"
        ".steps li { min-height: 44px; display: flex; align-items: center; gap: 16px; margin-top: 8px; }\n"
        ".steps li:first-child { margin-top: 0; }\n"
        ".step-label { font-size: 22px; line-height: 30px; transition: color 200ms var(--ease-standard); }\n"
        "li.waiting .step-label { color: var(--ink-3); font-weight: 400; }\n"
        "li.active .step-label { color: var(--ink); font-weight: 600; }\n"
        "li.done .step-label { color: var(--ink-2); font-weight: 400; }\n"
        ".mark svg { display: none; }\n"
        "li.waiting .mark-wait, li.active .mark-active, li.done .mark-done { display: block; }\n"
        ".arc { transform-origin: 14px 14px; animation: spin var(--spin) linear infinite; }\n"
        ".mark-active .dot { display: none; }\n"
        ".done-fill { opacity: 0; animation: fillin 200ms var(--ease-standard) forwards; }\n"
        ".check { stroke-dasharray: 18; stroke-dashoffset: 18; "
        "animation: draw 240ms var(--ease-decel) forwards; }\n"
        ".sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; "
        "overflow: hidden; clip: rect(0, 0, 0, 0); border: 0; }\n"
        "h2 { font-size: 22px; line-height: 30px; font-weight: 600; color: var(--ink); "
        "margin: 48px 0 16px; }\n"
        ".hero + h2, h2:first-child { margin-top: 0; }\n"
        ".grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; align-items: stretch; }\n"
        ".card { background: #ffffff; border: 1px solid #e8e8ed; border-radius: 22px; "
        "padding: 28px 28px 16px; box-shadow: 0 1px 2px rgba(0,0,0,.04); "
        "display: flex; flex-direction: column; "
        "animation: rise 400ms var(--ease-decel) both; "
        "animation-delay: calc(min(var(--c, 0), 6) * 60ms); }\n"
        ".label { margin: 0; font-size: 20px; line-height: 28px; font-weight: 600; color: #3a3a3c; }\n"
        ".caption { margin: 0; font-size: 18px; line-height: 27px; font-weight: 400; color: #555559; }\n"
        ".big { margin: 6px 0 0; }\n"
        ".big a, a.figure { color: #1d1d1f; font-size: 44px; line-height: 52px; font-weight: 700; "
        "letter-spacing: -0.02em; font-variant-numeric: tabular-nums; white-space: nowrap; "
        "text-decoration: underline; text-decoration-color: #c7c7cc; text-decoration-thickness: 2px; "
        "text-underline-offset: 7px; }\n"
        ".cmp { margin: 12px 0 0; font-size: 18px; line-height: 27px; color: #3a3a3c; font-weight: 400; }\n"
        ".cmp a.pct { color: #0a4b8f; font-weight: 700; text-decoration: underline; "
        "text-underline-offset: 3px; white-space: nowrap; }\n"
        ".cmp a.per { color: #3a3a3c; text-decoration: underline; text-decoration-color: #86868b; "
        "text-underline-offset: 3px; }\n"
        ".chart { list-style: none; margin: 24px 0 0; padding: 20px 0 0; border-top: 1px solid #e6e6e8; "
        "display: flex; flex-direction: column; gap: 18px; }\n"
        ".bar-text { display: grid; grid-template-columns: 1fr auto; column-gap: 16px; align-items: baseline; }\n"
        ".bh { margin: 0; font-size: 18px; line-height: 27px; font-weight: 600; color: #3a3a3c; }\n"
        ".cur .bh { color: #1d1d1f; }\n"
        ".bd { grid-column: 1 / -1; margin: 0; font-size: 18px; line-height: 27px; "
        "font-weight: 400; color: #555559; }\n"
        ".m6 { margin: 0; font-size: 18px; line-height: 27px; font-weight: 400; color: #3a3a3c; }\n"
        ".bv { margin: 0; }\n"
        ".bv a { display: inline-block; min-height: 44px; padding: 8px 0; font-size: 18px; "
        "line-height: 28px; font-weight: 600; color: #1d1d1f; font-variant-numeric: tabular-nums; "
        "white-space: nowrap; text-decoration: underline; text-decoration-color: #86868b; "
        "text-underline-offset: 3px; }\n"
        ".bar-track { position: relative; height: 14px; margin-top: 8px; background: #ececf0; "
        "border-radius: 0 7px 7px 0; }\n"
        ".bar-track::before { content: \"\"; position: absolute; left: var(--zero, 0%); top: -4px; "
        "bottom: -4px; width: 2px; background: #3a3a3c; border-radius: 1px; z-index: 1; }\n"
        ".fill { position: absolute; top: 0; height: 100%; border-radius: 0 7px 7px 0; "
        "background: #6f86a8; transform-origin: left center; "
        "animation: grow 400ms var(--ease-standard) both; "
        "animation-delay: calc(min(var(--c, 0), 6) * 60ms + var(--i, 0) * 60ms); }\n"
        ".fill.neg { transform-origin: right center; }\n"
        ".cur .fill { background: #0a4b8f; }\n"
        ".change-line { margin: 12px 0 0; font-size: 18px; line-height: 27px; color: #3a3a3c; "
        "font-weight: 400; }\n"
        ".change-line a { color: #0a4b8f; text-decoration: underline; text-underline-offset: 3px; "
        "white-space: nowrap; }\n"
        ".pct-note { display: none; margin: 8px 0 0; font-size: 18px; line-height: 27px; }\n"
        ".pct-note:target { display: block; }\n"
        ".pct-note a + a { margin-left: 16px; }\n"
        ".detail { display: grid; grid-template-rows: 0fr; opacity: 0; "
        "transition: grid-template-rows 300ms var(--ease-standard), opacity 300ms var(--ease-standard); }\n"
        ".detail.open { grid-template-rows: 1fr; opacity: 1; }\n"
        ".detail-inner { overflow: hidden; }\n"
        "a { color: var(--accent); }\n"
        ".filing { margin-top: 40px; }\n"
        ".filing a, .change a { display: inline-block; min-height: 44px; padding: 8px 0; "
        "line-height: 28px; font-size: 21px; }\n"
        ".change { margin-top: 32px; font-size: 18px; line-height: 27px; }\n"
        ".change a { font-size: 18px; color: var(--ink-2); }\n"
        "button.explain { display: inline-flex; align-items: center; gap: 8px; width: auto; "
        "min-height: 44px; margin: 16px 0 0; padding: 8px 0; background: none; color: #0a4b8f; "
        "border: 0; font-size: 18px; line-height: 27px; font-weight: 600; text-align: left; }\n"
        "button.explain svg { width: 20px; height: 20px; fill: none; stroke: currentColor; "
        "stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; "
        "transition: transform 200ms var(--ease-standard); }\n"
        "button.explain[aria-expanded='true'] svg { transform: rotate(180deg); }\n"
        "h2 button.tap { display: inline-block; width: auto; min-height: 44px; margin: 0; "
        "padding: 0; background: none; color: #1d1d1f; border: 0; font-size: 22px; "
        "line-height: 30px; font-weight: 600; text-align: left; }\n"
        ".explain, .quality, .marker, h2, h3 { font-size: 21px; line-height: 32px; "
        "color: var(--ink); font-weight: 400; }\n"
        ".marker { font-weight: 600; }\n"
        ":focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }\n"
        "@keyframes fade { from { opacity: 0; } to { opacity: 1; } }\n"
        "@keyframes enter { from { opacity: 0; transform: translateY(8px); } "
        "to { opacity: 1; transform: none; } }\n"
        "@keyframes leave { to { opacity: 0; transform: translateY(8px); } }\n"
        "@keyframes spin { to { transform: rotate(360deg); } }\n"
        "@keyframes fillin { to { opacity: 1; } }\n"
        "@keyframes draw { to { stroke-dashoffset: 0; } }\n"
        "@keyframes rise { from { opacity: 0; transform: translateY(12px); } "
        "to { opacity: 1; transform: none; } }\n"
        "@keyframes grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }\n"
        "body.result .hero { animation: rise 400ms var(--ease-decel) both; animation-delay: 60ms; }\n"
        "@media (max-width: 900px) {\n"
        "  .grid { grid-template-columns: 1fr; }\n"
        "}\n"
        "@media (max-width: 480px) {\n"
        "  .disclaimer, .top, .column { padding-left: 20px; padding-right: 20px; }\n"
        "  .disclaimer { padding-top: 28px; }\n"
        "  h1 { font-size: 34px; line-height: 40px; }\n"
        "  .hero { margin-bottom: 28px; }\n"
        "  .card { padding: 22px 20px 12px; border-radius: 22px; }\n"
        "  .big a, a.figure { font-size: 36px; line-height: 44px; }\n"
        "  form.search, form.pick { padding: 20px; }\n"
        "  .search-row { flex-direction: column; }\n"
        "  .search-row button { width: 100%; }\n"
        "  .lang button { min-width: 92px; }\n"
        "}\n"
        "@media (prefers-reduced-motion: reduce) {\n"
        "  .column, html[data-lang-set] .column, .failure, .steps, .steps.open, .steps.leave, "
        "  body.result .hero, .card, .fill, "
        "  .detail, button.explain svg, .lang button "
        "  { animation: none; transition: none; }\n"
        "  .card, .fill { opacity: 1; transform: none; }\n"
        "  .arc { animation: none; display: none; }\n"
        "  .mark-active .track { stroke: #0a4b8f; stroke-width: 4; }\n"
        "  .mark-active .dot { display: block; }\n"
        "  .check { stroke-dashoffset: 0; animation: none; }\n"
        "  .done-fill { opacity: 1; animation: none; }\n"
        "  .step-label { transition: none; }\n"
        "}\n"
        "</style>\n"
        '<div class="column">\n'
        f"{inner}\n"
        "</div>\n"
        "<script>\n"
        "(function () {\n"
        f'  var closed = "{closed}";\n'
        f'  var looking = "{looking}";\n'
        f'  var finding = "{finding}";\n'
        f'  var filingList = "{filing_list}";\n'
        f'  var reading = "{reading}";\n'
        f'  var readingPrior = "{reading_prior}";\n'
        "  var reduce = window.matchMedia(\"(prefers-reduced-motion: reduce)\").matches;\n"
        "  var gap = reduce ? 0 : 120;\n"
        "  var pause = reduce ? 0 : 240;\n"
        "  var shown = 0;\n"
        "  function say(text) {\n"
        '    var box = document.getElementById("failure");\n'
        '    var note = document.getElementById("working");\n'
        "    if (!box || !note) return;\n"
        "    note.textContent = text;\n"
        '    box.classList.add("failure");\n'
        "    box.hidden = false;\n"
        "  }\n"
        "  function items() {\n"
        '    return Array.from(document.querySelectorAll("#steps li"));\n'
        "  }\n"
        "  function paint(item, state) {\n"
        '    item.className = state;\n'
        "    if (state === \"active\") {\n"
        '      item.setAttribute("aria-current", "step");\n'
        '      var live = document.getElementById("step-live");\n'
        "      if (live) live.textContent = item.querySelector(\".step-label\").textContent;\n"
        "    } else {\n"
        '      item.removeAttribute("aria-current");\n'
        "    }\n"
        "  }\n"
        "  function reach(n) {\n"
        "    var list = items();\n"
        "    if (!list.length || n <= shown) return;\n"
        "    var next = shown + 1;\n"
        "    function step() {\n"
        "      list.forEach(function (item, index) {\n"
        "        var number = index + 1;\n"
        "        if (number < next) paint(item, \"done\");\n"
        "        else if (number === next) paint(item, \"active\");\n"
        "        else paint(item, \"waiting\");\n"
        "      });\n"
        "      shown = next;\n"
        "      if (shown < n) { next += 1; setTimeout(step, gap); }\n"
        "    }\n"
        "    step();\n"
        "  }\n"
        "  function finish(html) {\n"
        "    var list = items();\n"
        "    var pending = list.length ? list.length - shown : 0;\n"
        "    if (pending < 0) pending = 0;\n"
        "    reach(list.length);\n"
        "    setTimeout(function () {\n"
        "      document.open();\n"
        "      document.write(html);\n"
        "      document.close();\n"
        "    }, pending * gap + pause);\n"
        "  }\n"
        '  document.querySelectorAll("form").forEach(function (form) {\n'
        '    form.addEventListener("submit", function (event) {\n'
        "      event.preventDefault();\n"
        '      var button = form.querySelector("button");\n'
        '      if (button && button.getAttribute("aria-disabled") === "true") return;\n'
        "      if (button) {\n"
        '        button.setAttribute("aria-disabled", "true");\n'
        '        button.classList.add("busy");\n'
        "      }\n"
        '      form.setAttribute("aria-busy", "true");\n'
        '      var action = form.getAttribute("action") || "";\n'
        '      var panel = document.getElementById("steps");\n'
        "      var poll = null;\n"
        '      if (panel && (action === "/explain" || action === "/pick")) {\n'
        "        panel.hidden = false;\n"
        '        panel.classList.add("open");\n'
        '        if (action === "/pick") reach(2);\n'
        "        else reach(1);\n"
        "        var tokenInput = form.querySelector('input[name=\"token\"]');\n"
        '        var progress = "/progress";\n'
        "        if (tokenInput && tokenInput.value) {\n"
        '          progress += "?token=" + encodeURIComponent(tokenInput.value);\n'
        "        }\n"
        "        poll = setInterval(function () {\n"
        '          fetch(progress, {cache: "no-store", credentials: "same-origin"})\n'
        "            .then(function (response) { return response.json(); })\n"
        "            .then(function (data) {\n"
        "              if (data && data.step) reach(data.step);\n"
        "            })\n"
        "            .catch(function () {});\n"
        "        }, 400);\n"
        "      }\n"
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
        "        if (poll) clearInterval(poll);\n"
        '        if (response.type === "opaqueredirect" || response.status === 303 || response.status === 302) {\n'
        '          window.location.assign("/");\n'
        "          return;\n"
        "        }\n"
        "        return response.text().then(function (html) {\n"
        '          if (action === "/language") {\n'
        "            document.open();\n"
        "            document.write(html);\n"
        "            document.close();\n"
        "            return;\n"
        "          }\n"
        '          var success = html.indexOf("class=\\"figure\\"") !== -1;\n'
        "          if (success && panel) { finish(html); return; }\n"
        "          if (panel) panel.classList.add(\"leave\");\n"
        "          setTimeout(function () {\n"
        "            document.open();\n"
        "            document.write(html);\n"
        "            document.close();\n"
        "          }, panel ? (reduce ? 0 : 150) : 0);\n"
        "        });\n"
        "      }).catch(function () {\n"
        "        if (poll) clearInterval(poll);\n"
        "        if (button) {\n"
        '          button.removeAttribute("aria-disabled");\n'
        '          button.classList.remove("busy");\n'
        "        }\n"
        '        form.removeAttribute("aria-busy");\n'
        "        if (panel) panel.hidden = true;\n"
        "        say(closed);\n"
        "      });\n"
        "    });\n"
        "  });\n"
        '  if (document.documentElement.getAttribute("data-lang-set") === "1") {\n'
        '    var chosen = document.querySelector(".lang button[aria-pressed=\\"true\\"]");\n'
        "    if (chosen) chosen.focus();\n"
        "  }\n"
        "  setInterval(function () {\n"
        '    fetch("/stay", {cache: "no-store", credentials: "same-origin"}).catch(function () {\n'
        "      say(closed);\n"
        "    });\n"
        "  }, 2000);\n"
        '  document.querySelectorAll("button.tap").forEach(function (button) {\n'
        '    button.addEventListener("click", function () {\n'
        '      var panel = document.getElementById(button.getAttribute("aria-controls"));\n'
        "      if (!panel) return;\n"
        '      var open = button.getAttribute("aria-expanded") === "true";\n'
        '      button.setAttribute("aria-expanded", open ? "false" : "true");\n'
        '      if (panel.classList.contains("detail")) {\n'
        '        panel.classList.toggle("open", !open);\n'
        '        panel.setAttribute("aria-hidden", open ? "true" : "false");\n'
        "      } else {\n"
        "        panel.hidden = open;\n"
        "      }\n"
        "    });\n"
        "  });\n"
        "})();\n"
        "</script>\n"
        "</body>\n"
        "</html>\n"
    )
    from white_cliff.wording import page_terms

    found = page_terms(page)
    if found:
        raise OutputRefused(found)
    return page


def _change_link() -> str:
    return f'<p class="change"><a href="/identity">{html.escape(ui("change_identity"))}</a></p>\n'


def _hidden(token: str) -> str:
    if not token:
        return ""
    safe = html.escape(token, quote=True)
    return f'<input type="hidden" name="token" value="{safe}">\n'


def _notice(sentence: str) -> str:
    hidden = "" if sentence else " hidden"
    kind = ' class="failure"' if sentence else ""
    return (
        f"<div{kind} id=\"failure\" role=\"alert\"{hidden}>\n"
        f'<p class="notice" id="working">{html.escape(sentence)}</p>\n'
        "</div>\n"
    )


def _indicator() -> str:
    return (
        '<span class="mark" aria-hidden="true">'
        '<svg class="mark-wait" viewBox="0 0 28 28" width="28" height="28">'
        '<circle cx="14" cy="14" r="12" fill="none" stroke="#86868b" stroke-width="2"></circle></svg>'
        '<svg class="mark-active" viewBox="0 0 28 28" width="28" height="28">'
        '<circle class="track" cx="14" cy="14" r="12" fill="none" stroke="#d2d2d7" stroke-width="3"></circle>'
        '<circle class="arc" cx="14" cy="14" r="12" fill="none" stroke="#0a4b8f" stroke-width="3" '
        'stroke-linecap="round" stroke-dasharray="19 57"></circle>'
        '<circle class="dot" cx="14" cy="14" r="3" fill="#0a4b8f"></circle></svg>'
        '<svg class="mark-done" viewBox="0 0 28 28" width="28" height="28">'
        '<circle class="done-fill" cx="14" cy="14" r="12" fill="#0a4b8f"></circle>'
        '<path class="check" d="M8.5 14.5 l3.6 3.6 l7.4 -8" fill="none" stroke="#ffffff" '
        'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"></path></svg>'
        "</span>"
    )


def _steps_panel() -> str:
    def item(number: int, text: str, template: str) -> str:
        return (
            f'<li class="waiting" data-step="{number}">'
            + _indicator()
            + f'<span class="step-label" data-template="{template}">{html.escape(shown_copy(text))}</span></li>'
        )

    return (
        '<div class="steps" id="steps" hidden role="status">\n'
        f'<p class="steps-title">{html.escape(shown_copy(LOOKING))}</p>\n'
        "<ol>\n"
        + item(1, FINDING, "FINDING")
        + item(2, FILING_LIST, "FILING_LIST")
        + item(3, READING_PRIOR, "READING_PRIOR")
        + "</ol>\n"
        '<p class="sr" id="step-live" aria-live="polite"></p>\n'
        "</div>\n"
    )


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
        '<form class="search" method="post" action="/explain">\n'
        + _hidden(token)
        + _notice(notice)
        + f'<p><label for="query">{html.escape(ui("company_or_ticker"))}</label></p>\n'
        + '<div class="search-row">'
        + f'<input id="query" name="query" autocomplete="off"{_value(query)}{auto}>'
        + f'<button type="submit">{html.escape(ui("explain"))}</button>'
        + "</div>\n"
        + _steps_panel()
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
        '<form class="search" method="post" action="/identity">\n'
        + _hidden(token)
        + _notice(notice)
        + f'<p><label for="name">{html.escape(ui("your_name"))}</label></p>\n'
        + f'<p><input id="name" name="name" autocomplete="name" autofocus{_value(name)}></p>\n'
        + f'<p><label for="email">{html.escape(ui("your_email"))}</label></p>\n'
        + f'<p><input id="email" name="email" type="email" autocomplete="email"{_value(email)}></p>\n'
        + f'<p><button type="submit">{html.escape(ui("save"))}</button></p>\n'
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
    note = shown_copy(notice or (ENTER_BOTH if rejected else ""))
    return _shell(
        f"<p>{html.escape(shown_copy(SEC_WHY))}</p>\n"
        + _identity_form(token, note, name=name, email=email),
        token=token,
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
        + f'<p><button type="submit">{html.escape(ui("erase"))}</button></p>\n'
        + "</form>\n"
    )
    return _shell(
        f"<p>{html.escape(shown_copy(SEC_WHY))}</p>\n"
        + _identity_form(token, shown_copy(notice), name=name, email=email)
        + erase
        + _change_link(),
        token=token,
    )


def search_page(token: str = "") -> str:
    return _shell(_search_form(token) + _change_link(), token=token)


def error_page(sentence: str, token: str = "", query: str = "") -> str:
    return _shell(
        _search_form(token, notice=shown_copy(sentence), query=query) + _change_link(),
        token=token,
    )


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
        return ui("company_fallback")
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
            '<form class="pick" method="post" action="/pick">\n'
            + _hidden(token)
            + '<button class="choice" type="submit" name="cik" value="'
            + cik
            + '">'
            + label
            + "</button>\n"
            + "</form>\n"
        )
    body = f'<p class="notice">{html.escape(shown_copy(heading))}</p>\n' + "".join(buttons)
    return _shell(
        body + _search_form(token, focus=False, query=query) + _change_link(),
        token=token,
    )


def _plain_label(lead: str) -> str:
    text = " ".join(_TAG.sub(" ", html.unescape(lead)).split())
    text = re.sub(r"\s+was$", "", text)
    text = re.sub(r"\s+for the (fiscal year|quarter)$", "", text)
    text = text.strip()
    if not german():
        return text
    return _german_label(text)


def _german_label(text: str) -> str:
    """A known card label from the cleared table. An unknown label stays the filing's words."""
    from white_cliff.lexicon import STRINGS

    exact = {
        english: german_text
        for ident, (english, german_text) in STRINGS.items()
        if ident.startswith("LBL.") and "{" not in english
    }
    exact.update(
        {
            "Gross margin": phrase("LBL.gross_margin"),
            "Operating margin": phrase("LBL.operating_margin"),
            "Net margin": phrase("LBL.net_margin"),
            "Revenue year over year": phrase("LBL.yoy"),
            "Net debt": phrase("LBL.net_debt").replace("{debt_label}", phrase("LBL.debt")),
        }
    )
    if text in exact:
        return exact[text]
    if text.startswith("The gross margin "):
        return phrase("LBL.gross_margin")
    if text.startswith("The operating margin "):
        return phrase("LBL.operating_margin")
    if text.startswith("The net margin "):
        return phrase("LBL.net_margin")
    if text.startswith("The year over year change "):
        return phrase("LBL.yoy")
    if text.endswith(" minus cash and cash equivalents"):
        debt = text[: -len(" minus cash and cash equivalents")]
        debt = exact.get(debt, debt)
        return phrase("LBL.net_debt").replace("{debt_label}", debt)
    shorter = re.sub(r" for the (year to date|reported period)$", "", text)
    if text != shorter and shorter == "Operating cash flow" and "year to date" in text:
        return phrase("LBL.ocf_ytd")
    if shorter in exact:
        return exact[shorter]
    return text


def _anchor_from_href(href: str) -> str:
    fragment = urlsplit(html.unescape(href)).fragment
    for key in ("fact", "calc"):
        token = key + "="
        if token in fragment:
            return fragment.split(token, 1)[1].split("&", 1)[0]
    return ""


def _leading_caption(rest: str) -> tuple[str, str]:
    """Lift this period's caption out of the comparison text so it sits with the figure."""
    match = re.search(r'<p class="caption">.*?</p>\s*', rest, flags=re.S)
    if match is None:
        return "", rest
    return match.group(0), rest[: match.start()] + rest[match.end() :]


def _split_div(after: str, class_name: str) -> tuple[str, str]:
    marker = f'<div class="{class_name}">'
    start = after.find(marker)
    if start < 0:
        return "", after
    inner_at = start + len(marker)
    depth = 1
    index = inner_at
    while index < len(after) and depth:
        if after.startswith("<div", index):
            depth += 1
            index += 4
            continue
        if after.startswith("</div>", index):
            depth -= 1
            if depth == 0:
                inner = after[inner_at:index]
                end = index + len("</div>")
                return inner, after[:start] + after[end:]
            index += 6
            continue
        index += 1
    return "", after


_CHEVRON = (
    '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 8l5 5 5-5"></path></svg>'
)


def _stored_amount(store, identifier: str) -> str:
    if store is None or not identifier:
        return ""
    if store.has_fact(identifier):
        fact = store.get(identifier)
        return format_measure(fact.value, fact.unit)
    if store.has_calc(identifier):
        calc = store.get_calc(identifier)
        return format_measure(calc.value, calc.unit)
    return ""


def _rows(explained_html: str, additions=None, store=None) -> str:
    pieces: list[str] = []
    grid: list[str] = []
    index = 0

    def flush() -> None:
        if grid:
            pieces.append('<div class="grid">' + "".join(grid) + "</div>\n")
            grid.clear()

    for part in re.findall(r"<p\b[^>]*>.*?</p>", explained_html, flags=re.I | re.S):
        if 'class="disclaimer"' in part or "github.com" in part or "Report an error" in part:
            continue
        match = _DATA_LINK.search(part)
        if match is None:
            continue
        label = _plain_label(match.group(1))
        identifier = _anchor_from_href(match.group(3))
        amount = shown_amount(match.group(2))
        if german():
            stored = _stored_amount(store, identifier)
            if stored:
                amount = stored
        href = html.escape(html.unescape(match.group(3)), quote=True)
        if not label:
            continue
        before = ""
        after = ""
        button = ""
        if additions is not None and identifier:
            before = additions.before.get(identifier, "")
            after = additions.after.get(identifier, "")
            if after:
                control = html.escape("explain-" + identifier, quote=True)
                button = (
                    f'<button type="button" class="explain tap" aria-expanded="false" '
                    f'aria-controls="{control}">{html.escape(ui("explain"))}{_CHEVRON}</button>'
                )
        if before:
            flush()
            pieces.append(before)
        face, detail = _split_div(after, "face")
        caption, face = _leading_caption(face)
        label_id = "lab-" + re.sub(r"[^a-z0-9]+", "-", identifier.lower())
        grid.append(
            f'<article class="card" style="--c:{index}" aria-labelledby="{label_id}">'
            f'<h3 class="label" id="{label_id}">{html.escape(label)}</h3>'
            + caption
            + f'<p class="big"><a class="figure" href="{href}">{html.escape(amount)}</a></p>'
            + face
            + button
            + detail
            + "</article>\n"
        )
        index += 1
    flush()
    return "".join(pieces)


def _report_link() -> str:
    href = html.escape(ISSUE_URL, quote=True)
    return f'<p class="change"><a href="{href}">{html.escape(ui("report_error"))}</a></p>\n'


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
    focus: str | None = None,
    fiscal_year_end: str = "",
    prior_facts: Sequence | None = None,
    prior_end: str | None = None,
) -> str:
    from white_cliff.wording import build_additions

    name = _company_name(explained.html, company, ticker, cik)
    additions = build_additions(
        explained,
        form=form,
        focus=focus,
        period_end=period or None,
        fiscal_year_end=fiscal_year_end,
        company=name or company or "this company",
        filed=filed,
        prior_facts=list(prior_facts) if prior_facts else None,
        prior_end=prior_end,
    )
    heading = f"<h1>{html.escape(name)}</h1>\n" if name else ""
    line = plain_report(form, period)
    quiet = f'<p class="quiet">{html.escape(line)}</p>\n' if line else ""
    hero = f'<div class="hero">{heading}{quiet}</div>\n' if heading or quiet else ""
    filing = ""
    if url.startswith("https://www.sec.gov/") or url.startswith("https://data.sec.gov/"):
        href = html.escape(url, quote=True)
        filing = f'<p class="filing"><a href="{href}">{html.escape(ui("the_filing"))}</a></p>\n'
    inner = (
        hero
        + _rows(explained.html, additions, explained.store)
        + additions.quality
        + filing
        + '<div class="next">\n'
        + _report_link()
        + _search_form(token, focus=False)
        + _change_link()
        + "</div>\n"
    )
    return _shell(inner, result=True, token=token)
