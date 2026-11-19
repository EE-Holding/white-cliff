"""The saved language. English is the default. German comes only from the cleared table."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token

from white_cliff.lexicon import STRINGS
from white_cliff.strings import EN

_language: ContextVar[str] = ContextVar("white_cliff_language", default="en")
focus_language: ContextVar[bool] = ContextVar("white_cliff_focus_language", default=False)

_UI = {
    "app_name": "UI.appname",
    "bar_chart": "UI.chart.alt",
    "explain": "UI.explain",
    "the_filing": "UI.filing_link",
    "change_identity": "UI.change_identity",
    "company_or_ticker": "UI.query_label",
    "report_error": "QCW.report",
    "prior_quarter": "H1.prior_quarter",
    "same_quarter": "H1.same_quarter",
    "prior_year": "H1.prior_year",
    "phrase_prior_quarter": "S1.period.prior_quarter",
    "phrase_same_quarter": "S1.period.same_quarter",
    "phrase_prior_year": "S1.period.prior_year",
    "your_name": "UI.name_label",
    "your_email": "UI.email_label",
    "save": "UI.save",
    "erase": "UI.erase",
    "company_fallback": "UI.pick_fallback",
}

BY_ENGLISH: dict[str, str] = {}
for _ident, (_english, _german) in STRINGS.items():
    BY_ENGLISH.setdefault(_english, _german)


def language() -> str:
    return _language.get()


def german() -> bool:
    return language() == "de"


def set_language(code: str) -> Token[str]:
    if code not in {"en", "de"}:
        code = "en"
    return _language.set(code)


def reset_language(token: Token[str]) -> None:
    _language.reset(token)


@contextmanager
def using(code: str):
    token = set_language(code)
    try:
        yield
    finally:
        _language.reset(token)


def phrase(ident: str) -> str:
    """The cleared string for this id in the active language."""
    english, deutsch = STRINGS[ident]
    return deutsch if german() else english


def ui(key: str) -> str:
    if german() and key in _UI:
        return phrase(_UI[key])
    return EN[key]


def shown_copy(english: str) -> str:
    """A whole cleared sentence. Unknown text stays as it is."""
    if not german():
        return english
    return BY_ENGLISH.get(english, english)


def choose(template: str, picks: dict[str, str]) -> str:
    """Replace a {one|other} choice. Placeholder names are filled separately."""
    import re

    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        if "|" not in inner:
            return match.group(0)
        if inner not in picks:
            raise KeyError(inner)
        return picks[inner]

    return re.sub(r"\{([^{}]+)\}", repl, template)


def fill(template: str, slots: dict[str, str]) -> str:
    """Fill {name} slots. Values are already safe to place in the sentence."""
    import html as html_lib
    import re

    parts = re.split(r"(\{[^{}]+\})", template)
    out: list[str] = []
    for part in parts:
        if part.startswith("{") and part.endswith("}"):
            key = part[1:-1]
            if key not in slots:
                raise KeyError(key)
            out.append(slots[key])
        else:
            out.append(html_lib.escape(part))
    return "".join(out)
