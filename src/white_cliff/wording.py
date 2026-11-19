"""Cleared sentence templates. Slots are filled from filing figures. No free-hand digits."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlsplit

from white_cliff.advice import advice_reason
from white_cliff.checks import ONE_OFF, CheckResult, run_checks
from white_cliff.compare import Cell, columns_for, percent_change
from white_cliff.explain import _lead, _span, statement_name
from white_cliff.facts import Fact, format_decimal
from white_cliff.german import format_measure, german_hit
from white_cliff.i18n import choose, fill, german, phrase, shown_copy, ui
from white_cliff.present import shown_amount
from white_cliff.strings import EN
from white_cliff.thresholds import CASH_CONVERSION

FRAME = (
    "These checks compare the company's own reported numbers with each other. "
    "They are not a judgement of the company and not investment advice."
)
LIMIT = (
    "This check is arithmetic on the filing's own numbers. "
    "It does not say whether the numbers are right or wrong, and it is not an audit."
)
WHY = {
    "C1": (
        "Net income includes amounts recorded before cash is received or paid, "
        "so it is often compared with the cash the business actually brought in over the same period."
    ),
    "C2": "Receivables are sales not yet paid for, so their change is often compared with the change in sales.",
    "C3": "Inventory is goods held for sale, so its change is often compared with the change in the cost of goods sold.",
    "C4": (
        "Items like restructuring, impairments and gains on sales can be large in one period "
        "and absent in the next, so their size is often compared with operating income."
    ),
    "C6": (
        "The diluted share count includes shares that options, convertible securities and similar "
        "awards could add, so its change shows how much the number of shares changed."
    ),
    "C7": "Margins show each figure as a share of revenue, so a change in margin shows costs moving faster or slower than sales.",
    "C8": (
        "The effective tax rate shows tax expense as a share of pre-tax income, "
        "and changes in it affect net income separately from the business itself."
    ),
}
CAUSES = {
    "C1": (
        "A gap can come from timing of customer payments, building inventory, large non-cash gains, "
        "or tax and working-capital timing. The filing's cash flow statement and notes may explain it."
    ),
    "C2": (
        "This can come from sales concentrated near the year end, changed payment terms, an acquisition, "
        "or a change in accounting. The filing's notes may explain it."
    ),
    "C3": (
        "This can come from stocking up ahead of expected sales, seasonal patterns, supply changes, "
        "an acquisition, or a change in accounting. The filing's notes may explain it."
    ),
    "C4": (
        "Such items follow events the company describes in its filing, such as a reorganisation, a sale, "
        "or a change in the value of assets. The filing's notes may explain it."
    ),
    "C6": (
        "This can come from employee share awards, convertible securities, or shares issued for an "
        "acquisition or to raise money. The filing's notes may explain it."
    ),
    "C7": (
        "This can come from changes in prices or costs, the mix of products sold, one-time items, "
        "or an acquisition or sale. The filing's notes may explain it."
    ),
    "C8": (
        "This can come from tax law changes, one-time tax items, income earned in different countries, "
        "or settlements with tax authorities. The filing's tax note may explain it."
    ),
}
HEADINGS = {
    "C1": "Profit and operating cash flow",
    "C2": "Receivables and revenue",
    "C3": "Inventory and cost of sales",
    "C4": "Items tagged as restructuring, impairment, disposal or acquisition costs",
    "C6": "Diluted and basic shares",
    "C7": "Gross margin and operating margin",
    "C8": "Income tax and pre-tax income",
}
ITEM_LABELS = {
    "RestructuringCharges": "restructuring charges",
    "GoodwillImpairmentLoss": "goodwill impairment",
    "ImpairmentOfIntangibleAssetsExcludingGoodwill": "impairment of intangible assets",
    "AssetImpairmentCharges": "asset impairment charges",
    "GainLossOnDispositionOfAssets": "gain or loss on disposal of assets",
    "GainLossOnSaleOfPropertyPlantEquipment": "gain or loss on sale of property and equipment",
    "DisposalGroupNotDiscontinuedOperationGainLossOnDisposal": "gain or loss on disposal of a business unit",
    "GainsLossesOnExtinguishmentOfDebt": "gain or loss on paying off debt early",
    "BusinessCombinationAcquisitionRelatedCosts": "acquisition-related costs",
}
DEFINITIONS = {
    "revenue": "the amount the company recorded from sales during the period",
    "gross_profit": "revenue minus the cost of goods or services sold",
    "operating_income": "profit from operations before interest and income tax",
    "net_income": "profit after expenses and income tax for the period",
    "operating_cash_flow": "the cash the company's day-to-day business brought in or paid out during the period",
    "debt": "the long-term debt figure, using the filing's own line",
    "cash": "cash and cash equivalents the company reports at the period end",
    "shares": "the number of shares the filing reports",
    "gross_margin": "gross profit divided by revenue",
    "operating_margin": "operating income divided by revenue",
    "net_margin": "net income divided by revenue",
    "yoy_change": "the change in revenue from the same period a year earlier",
    "net_debt": "the debt figure minus cash and cash equivalents",
    "per_share": "earnings divided by the number of shares",
}
TEMPLATES = frozenset(
    {
        "C1",
        "C2",
        "C3",
        "C4",
        "C5",
        "C6",
        "M1",
        "M2",
        "M3",
        "M4",
        "M5",
        "M6",
        "E1",
        "E2",
        "E3",
        "SECTION",
        "MARKER",
        "NUMBERS",
        "THRESHOLD",
        "WHY",
        "CAUSES",
        "LIMIT",
        "FRAME",
        "DECREASE",
        "FORMULA",
    }
)
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_BANNED = (
    "fraud",
    "fraudulent",
    "manipulation",
    "manipulated",
    "cooked",
    "fudged",
    "massaged",
    "doctored",
    "inflated",
    "suspicious",
    "questionable",
    "misleading",
    "healthy",
    "unhealthy",
    "strong",
    "weak",
    "solid",
    "poor",
    "bad",
    "good",
    "concerning",
    "worrying",
    "alarming",
    "impressive",
    "buy",
    "sell",
    "hold",
    "avoid",
    "opportunity",
    "bargain",
    "cheap",
    "expensive",
    "overvalued",
    "undervalued",
    "upside",
    "downside",
    "better",
    "worse",
    "winner",
    "leader",
    "laggard",
    "beats",
    "misses",
    "outperforms",
    "underperforms",
    "ranking",
    "score",
    "grade",
    "rating",
    "warning",
    "risk",
    "concern",
    "aggressive",
    "should",
    "investors",
    "clean",
    "dirty",
    "real",
    "true",
    "artificial",
    "sharply",
    "dramatically",
    "merely",
    "surprisingly",
    "worth",
)
_BANNED_PHRASES = (
    "red flag",
    "earnings quality",
    "quality of earnings",
    "the market",
    "window dressing",
    "too good to be true",
    "you should",
    "fair value",
    "warning sign",
    "per share",
)


@dataclass(frozen=True)
class Additions:
    before: dict[str, str]
    after: dict[str, str]
    quality: str
    plain: str
    skip: frozenset[str] = frozenset()
    statement: dict[str, str] = field(default_factory=dict)
    heading: dict[str, str] = field(default_factory=dict)
    fold: dict[str, str] = field(default_factory=dict)


def long_date(iso: str) -> str:
    if german():
        from white_cliff.german import german_date

        return german_date(iso)
    year, month, day = (int(part) for part in iso.split("-"))
    return f"{_MONTHS[month - 1]}\u00a0{day},\u00a0{year}"


_PERIOD_NOUN = (
    ("six months", "Sechsmonatszeitraum"),
    ("nine months", "Neunmonatszeitraum"),
    ("quarter", "Quartal"),
    ("year", "Geschäftsjahr"),
    ("period", "Zeitraum"),
)


def _dated_german_period(period: str) -> str:
    """Section 2 period form, without an article. Empty when the phrase has no date."""
    found = re.search(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})", period)
    if found is None or found.group(1) not in _MONTHS:
        return ""
    month = _MONTHS.index(found.group(1)) + 1
    when = long_date(f"{int(found.group(3)):04d}-{month:02d}-{int(found.group(2)):02d}")
    noun = "Zeitraum"
    lowered = period.lower()
    for needle, name in _PERIOD_NOUN:
        if needle in lowered:
            noun = name
            break
    return f"{noun} zum {when}"


def _german_gap(figure: str, period: str, *, structural: bool = False, head: str = "") -> tuple[str, str]:
    """M6 only for a prior quarter this filing does not carry. Every other gap uses its M2.de line."""
    if structural:
        return "M6", phrase("M6").replace("{figure}", figure)
    dated = _dated_german_period(period)
    if dated:
        return "M2", phrase("M2").replace("{figure}", figure).replace("{period_prev}", dated)
    ident = {
        "the prior quarter": "M2.de.prior_quarter",
        "the same quarter a year earlier": "M2.de.same_quarter",
        "the same six months a year earlier": "M2.de.same_ytd",
        "the same nine months a year earlier": "M2.de.same_ytd",
        "the prior year": "M2.de.prior_year",
        "the prior fiscal year end": "M2.de.prior_fy_end",
        "the same period a year earlier": "M2.de.same_period",
        "the prior period": "M2.de.same_period",
    }.get(period)
    if ident is None:
        ident = {
            EN["prior_quarter"]: "M2.de.prior_quarter",
            EN["same_quarter"]: "M2.de.same_quarter",
            EN["same_six"]: "M2.de.same_ytd",
            EN["same_nine"]: "M2.de.same_ytd",
            EN["prior_year"]: "M2.de.prior_year",
        }.get(head, "M2.de.same_period")
    template = phrase(ident)
    if ident == "M2.de.same_ytd":
        months = "neun" if "nine" in period or head == EN["same_nine"] else "sechs"
        template = choose(template, {"sechs|neun": months})
    return ident, template.replace("{figure}", figure)


def _span_key(kind: str, start: str | None, end: str) -> str:
    if not end:
        return ""
    if kind == "instant":
        return "instant"
    days = _period_days(start, end)
    if 80 <= days <= 100:
        return "3"
    if 170 <= days <= 200:
        return "6"
    if 250 <= days <= 290:
        return "9"
    if 330 <= days <= 380:
        return "12"
    return "date"


def _period_days(start: str | None, end: str) -> int:
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start or end)).days
    except ValueError:
        return 0


def period_phrase(kind: str, start: str | None, end: str) -> str:
    when = long_date(end) if end else ""
    if german():
        key = _span_key(kind, start, end)
        noun = {
            "3": "Quartal",
            "6": "Sechsmonatszeitraum",
            "9": "Neunmonatszeitraum",
            "12": "Geschäftsjahr",
        }.get(key, "Zeitraum")
        return f"{noun} zum {when}" if when else ""
    if kind == "instant":
        return f"the period ended {when}"
    days = _period_days(start, end)
    if 80 <= days <= 100:
        return f"the quarter ended {when}"
    if 170 <= days <= 200:
        return f"the six months ended {when}"
    if 250 <= days <= 290:
        return f"the nine months ended {when}"
    if 330 <= days <= 380:
        return f"the year ended {when}"
    return f"the period ended {when}"


def column_header(kind: str, start: str | None, end: str) -> str:
    """The column name. The date is the period end, written as the filing states it."""
    when = long_date(end) if end else ""
    if not when:
        return ""
    if german():
        key = _span_key(kind, start, end)
        names = {"3": "COL.3m", "6": "COL.6m", "9": "COL.9m", "12": "COL.12m"}
        if key in names:
            return phrase(names[key]).replace("{date}", when)
        return when
    if kind == "instant":
        return when
    days = _period_days(start, end)
    if 80 <= days <= 100:
        return f"Three months ended {when}"
    if 170 <= days <= 200:
        return f"Six months ended {when}"
    if 250 <= days <= 290:
        return f"Nine months ended {when}"
    if 330 <= days <= 380:
        return f"Year ended {when}"
    return when


def show_measure(value: Decimal, unit: str) -> str:
    """Every displayed measure, including a per-share amount, goes through one formatter."""
    if unit in {"percent", "percentage points"}:
        value = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if german():
        return format_measure(value, unit)
    if unit == "percent":
        return shown_amount(f"{value:.1f} percent")
    if unit == "percentage points":
        return f"{value:.1f} percentage points"
    return shown_amount(f"{format_decimal(value)} {unit}")


def fact_href(fact: Fact) -> str:
    url = fact.source.url.split("#", 1)[0]
    if not url.startswith("https://www.sec.gov/"):
        return ""
    return f"{url}#fact={fact.id}&start={fact.source.char_start}&end={fact.source.char_end}"


def _filing_href(url: str) -> str:
    base = url.split("#", 1)[0]
    if base.startswith("https://www.sec.gov/"):
        return base
    return ""


def _parts_html(template_id: str, parts: list[tuple], class_name: str = "") -> str:
    if template_id not in TEMPLATES:
        raise ValueError(template_id)
    body: list[str] = []
    notes: list[str] = []
    for part in parts:
        if part[0] == "text":
            body.append(html.escape(part[1]))
            continue
        if part[0] == "percent":
            display, current_href, prior_href, current_shown, prior_shown = part[1:6]
            notes.append(_percent_note(display, current_href, prior_href, current_shown, prior_shown, len(notes)))
            body.append(notes[-1][0])
            continue
        display, href = part[1], part[2]
        if not href.startswith("https://www.sec.gov/"):
            raise ValueError("number without a filing link")
        folded = display.casefold()
        link_class = ' class="pct"' if "percent" in folded or "prozent" in folded else ""
        body.append(
            f'<a{link_class} href="{html.escape(href, quote=True)}">{html.escape(display)}</a>'
        )
    class_attr = f' class="{class_name}"' if class_name else ""
    note_html = "".join(note[1] for note in notes)
    return f'<p{class_attr} data-template="{template_id}">{"".join(body)}</p>\n' + note_html


def _percent_note(
    display: str,
    current_href: str,
    prior_href: str,
    current_shown: str,
    prior_shown: str,
    index: int,
) -> tuple[str, str]:
    """The percent opens one note that links this figure and the earlier figure."""
    for href in (current_href, prior_href):
        if not href.startswith("https://www.sec.gov/"):
            raise ValueError("number without a filing link")
    digest = hashlib.sha256(f"{index}|{current_href}|{prior_href}|{display}".encode()).hexdigest()[:16]
    note_id = "pct-" + digest
    link = f'<a class="pct" href="#{note_id}">{html.escape(display)}</a>'
    note = (
        f'<p class="pct-note" id="{note_id}">'
        f'<a href="{html.escape(current_href, quote=True)}">{html.escape(current_shown)}</a>'
        f'<a href="{html.escape(prior_href, quote=True)}">{html.escape(prior_shown)}</a>'
        f"</p>\n"
    )
    return link, note


def _plain(parts: list[tuple]) -> str:
    words = []
    for part in parts:
        words.append(part[1])
    return "".join(words)


_DEBT_LBL = {
    "LongTermDebt": "LBL.debt",
    "LongTermDebtNoncurrent": "LBL.debt_noncurrent",
    "LongTermDebtAndCapitalLeaseObligations": "LBL.debt_lease",
    "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities": "LBL.debt_lease_incl",
}


def _debt_noun(fact: Fact | None) -> str:
    """The cleared German name of the debt concept actually used."""
    ident = _DEBT_LBL.get(fact.concept) if fact is not None else None
    if ident:
        return phrase(ident)
    return phrase("LBL.debt")


def _eps_label(fact: Fact) -> str:
    """The filing's English label, in quotes. A per-share figure is never left unnamed."""
    raw = (fact.label or "").strip()
    if not raw or raw == fact.concept:
        raw = "Earnings per share"
    return f"„{raw}“"


def label_for(role: str, fact: Fact) -> str:
    margin_name = {
        "gross_margin": "U8.lbl.gross_margin",
        "operating_margin": "U8.lbl.operating_margin",
        "net_margin": "U8.lbl.net_margin",
    }.get(role)
    if margin_name:
        return phrase(margin_name)
    if role == "net_debt" and german():
        return phrase("LBL.net_debt").replace("{debt_label}", _debt_noun(fact))
    if german() and (role == "per_share" or fact.unit.split()[0] == "USD/shares"):
        return _eps_label(fact)
    lead = _lead(role if role in {"revenue", "gross_profit", "operating_income", "net_income", "operating_cash_flow", "debt", "cash", "shares"} else "revenue", fact, _span(fact))
    if role not in {"revenue", "gross_profit", "operating_income", "net_income", "operating_cash_flow", "debt", "cash", "shares"}:
        names = {
            "gross_margin": "Gross margin",
            "operating_margin": "Operating margin",
            "net_margin": "Net margin",
            "yoy_change": "Revenue year over year",
            "net_debt": "Net debt",
            "per_share": "Earnings per share",
        }
        text = names.get(role, role)
        if german():
            from white_cliff.present import _german_label

            return _german_label(text)
        return text
    text = re.sub(r"\s+was$", "", lead)
    text = re.sub(r"\s+for the .+$", "", text)
    if german():
        from white_cliff.present import _german_label

        return _german_label(text)
    return text


def _shown_margin(value: Decimal) -> Decimal:
    """The one-decimal percent a bar actually shows."""
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _margin_gap(current: Decimal, prior: Decimal) -> Decimal:
    """Difference of the shown percents. The words use this, not the raw ratio."""
    return _shown_margin(current) - _shown_margin(prior)


def _displays_match(current: Cell, prior: Cell) -> bool:
    unit = current.unit or prior.unit or ""
    other = prior.unit or unit
    return show_measure(current.value, unit) == show_measure(prior.value, other)


def _direction(current: Decimal, prior: Decimal) -> str:
    if current > prior:
        return "rose"
    if current < prior:
        return "fell"
    return "was unchanged"


def _higher(current: Decimal, prior: Decimal) -> str:
    return "higher" if current >= prior else "lower"


def _link_fact(fact: Fact) -> tuple:
    return ("link", show_measure(fact.value, fact.unit), fact_href(fact))


def _period_link(phrase: str, fact: Fact) -> tuple:
    return ("link", phrase, _filing_href(fact.source.url))


def _m2(figure: str, period: str) -> list[tuple]:
    if german():
        _template, text = _german_gap(figure, period, structural=False)
        return [("text", text)]
    return [("text", f"{figure} for {period} is not in the filings White Cliff read, so no change is shown.")]


def _change_parts(figure: str, current: Cell, prior: Cell, measure: str) -> list[list[tuple]]:
    """Change sentences for one column. Percent only when the CTO rule allows it."""
    if german():
        return _change_parts_de(figure, current, prior, measure)
    if not prior.available or prior.fact is None or current.fact is None or prior.value is None or current.value is None:
        return []
    if prior.basis == "currency":
        return [[("text", "The figures are in different currencies, so no change is shown.")]]
    if prior.basis == "length":
        return [[("text", "The periods are different lengths.")]]
    if current.value == prior.value and measure != "margin":
        return [[
            ("text", f"{figure} was unchanged from "),
            _period_link(period_phrase(prior.kind, prior.period_start, prior.period_end), prior.fact),
            ("text", " at "),
            _link_fact(current.fact),
            ("text", "."),
        ]]
    if measure == "margin":
        return _margin_lines(current, prior)
    if measure == "net_debt":
        word = _higher(current.value, prior.value)
        return [[
            ("text", "It was "),
            ("link", show_measure(abs(current.value - prior.value), current.unit), fact_href(current.fact)),
            ("text", f" {word} than "),
            _period_link(period_phrase(prior.kind, prior.period_start, prior.period_end), prior.fact),
            ("text", "."),
        ]]
    if _displays_match(current, prior):
        return [[
            ("text", f"{figure} was unchanged from "),
            _period_link(period_phrase(prior.kind, prior.period_start, prior.period_end), prior.fact),
            ("text", " at "),
            _link_fact(current.fact),
            ("text", "."),
        ]]
    pct = percent_change(current.value, prior.value)
    if pct == 0:
        word = _higher(current.value, prior.value)
        return [[
            ("text", "It was "),
            ("link", show_measure(abs(current.value - prior.value), current.unit), fact_href(current.fact)),
            ("text", f" {word} than "),
            _period_link(period_phrase(prior.kind, prior.period_start, prior.period_end), prior.fact),
            ("text", "."),
        ]]
    sign_flip = current.value != 0 and prior.value != 0 and (current.value > 0) != (prior.value > 0)
    if pct is None:
        reason = ""
        if prior.value == 0:
            reason = "the earlier figure was zero"
        elif prior.value < 0 < current.value or (prior.value < 0 and current.value == 0):
            reason = "the figure changed from a loss to a profit"
        elif current.value < 0 < prior.value:
            reason = "the figure changed from a profit to a loss"
        lines = []
        if reason:
            lines.append([
                ("text", f"{figure} was "),
                _link_fact(current.fact),
                ("text", " in "),
                _period_link(period_phrase(current.kind, current.period_start, current.period_end), current.fact),
                ("text", ", compared with "),
                _link_fact(prior.fact),
                ("text", " in "),
                _period_link(period_phrase(prior.kind, prior.period_start, prior.period_end), prior.fact),
                ("text", f". A percentage change is not shown because {reason}."),
            ])
        else:
            word = _higher(current.value, prior.value)
            lines.append([
                ("text", "It was "),
                ("link", show_measure(abs(current.value - prior.value), current.unit), fact_href(current.fact)),
                ("text", f" {word} than "),
                _period_link(period_phrase(prior.kind, prior.period_start, prior.period_end), prior.fact),
                ("text", "."),
            ])
        if sign_flip and not reason:
            pass
        return lines
    direction = _direction(current.value, prior.value)
    if direction == "was unchanged":
        return [[
            ("text", f"{figure} was unchanged from "),
            _period_link(period_phrase(prior.kind, prior.period_start, prior.period_end), prior.fact),
            ("text", " at "),
            _link_fact(current.fact),
            ("text", "."),
        ]]
    return [[
        ("text", f"It {direction} "),
        ("link", show_measure(abs(pct), "percent"), fact_href(current.fact)),
        ("text", " from "),
        _period_link(period_phrase(prior.kind, prior.period_start, prior.period_end), prior.fact),
        ("text", "."),
    ]]


def _change_parts_de(figure: str, current: Cell, prior: Cell, measure: str) -> list[list[tuple]]:
    if not prior.available or prior.fact is None or current.fact is None or prior.value is None or current.value is None:
        return []
    if prior.basis == "currency":
        return [[("text", phrase("C6.currency"))]]
    if prior.basis == "length":
        return [[("text", phrase("C6.lengths"))]]
    earlier = _period_link(period_phrase(prior.kind, prior.period_start, prior.period_end), prior.fact)
    if current.value == prior.value and measure != "margin":
        return [[
            ("text", f"Der Wert der Position „{figure}“ blieb gegenüber dem "),
            earlier,
            ("text", " unverändert bei "),
            _link_fact(current.fact),
            ("text", "."),
        ]]
    if measure == "margin":
        return _margin_lines(current, prior)
    if measure == "net_debt":
        word = "höher" if current.value >= prior.value else "niedriger"
        return [[
            ("text", "Der Wert war um "),
            ("link", show_measure(abs(current.value - prior.value), current.unit), fact_href(current.fact)),
            ("text", f" {word} als im "),
            earlier,
            ("text", "."),
        ]]
    if _displays_match(current, prior):
        return [[
            ("text", f"Der Wert der Position „{figure}“ blieb gegenüber dem "),
            earlier,
            ("text", " unverändert bei "),
            _link_fact(current.fact),
            ("text", "."),
        ]]
    pct = percent_change(current.value, prior.value)
    if pct == 0:
        word = "höher" if current.value >= prior.value else "niedriger"
        return [[
            ("text", "Der Wert war um "),
            ("link", show_measure(abs(current.value - prior.value), current.unit), fact_href(current.fact)),
            ("text", f" {word} als im "),
            earlier,
            ("text", "."),
        ]]
    if pct is None:
        if prior.value == 0:
            reason = phrase("C4.reason.zero")
        elif prior.value < 0 < current.value or (prior.value < 0 and current.value == 0):
            reason = phrase("C4.reason.loss_to_profit")
        elif current.value < 0 < prior.value:
            reason = phrase("C4.reason.profit_to_loss")
        else:
            word = "höher" if current.value >= prior.value else "niedriger"
            return [[
                ("text", "Der Wert war um "),
                ("link", show_measure(abs(current.value - prior.value), current.unit), fact_href(current.fact)),
                ("text", f" {word} als im "),
                earlier,
                ("text", "."),
            ]]
        return [[
            ("text", f"Der Wert der Position „{figure}“ lag bei "),
            _link_fact(current.fact),
            ("text", " im "),
            _period_link(period_phrase(current.kind, current.period_start, current.period_end), current.fact),
            ("text", ", verglichen mit "),
            _link_fact(prior.fact),
            ("text", " im "),
            earlier,
            ("text", f". Eine prozentuale Veränderung wird nicht angezeigt, weil {reason}."),
        ]]
    verb = "stieg" if _direction(current.value, prior.value) == "rose" else "sank"
    return [[
        ("text", f"Der Wert der Position „{figure}“ {verb} um "),
        ("link", show_measure(abs(pct), "percent"), fact_href(current.fact)),
        ("text", " gegenüber dem "),
        earlier,
        ("text", "."),
    ]]
    if prior.basis == "currency":
        return [[("text", "The figures are in different currencies, so no change is shown.")]]
    if prior.basis == "length":
        return [[("text", "The periods are different lengths.")]]
    if current.value == prior.value and measure != "margin":
        return [[
            ("text", f"{figure} was unchanged from "),
            _period_link(period_phrase(prior.kind, prior.period_start, prior.period_end), prior.fact),
            ("text", " at "),
            _link_fact(current.fact),
            ("text", "."),
        ]]
    if measure == "margin":
        return _margin_lines(current, prior)
    if measure == "net_debt":
        word = _higher(current.value, prior.value)
        return [[
            ("text", "It was "),
            ("link", show_measure(abs(current.value - prior.value), current.unit), fact_href(current.fact)),
            ("text", f" {word} than "),
            _period_link(period_phrase(prior.kind, prior.period_start, prior.period_end), prior.fact),
            ("text", "."),
        ]]
    if _displays_match(current, prior):
        return [[
            ("text", f"{figure} was unchanged from "),
            _period_link(period_phrase(prior.kind, prior.period_start, prior.period_end), prior.fact),
            ("text", " at "),
            _link_fact(current.fact),
            ("text", "."),
        ]]
    pct = percent_change(current.value, prior.value)
    if pct == 0:
        word = _higher(current.value, prior.value)
        return [[
            ("text", "It was "),
            ("link", show_measure(abs(current.value - prior.value), current.unit), fact_href(current.fact)),
            ("text", f" {word} than "),
            _period_link(period_phrase(prior.kind, prior.period_start, prior.period_end), prior.fact),
            ("text", "."),
        ]]
    sign_flip = current.value != 0 and prior.value != 0 and (current.value > 0) != (prior.value > 0)
    if pct is None:
        reason = ""
        if prior.value == 0:
            reason = "the earlier figure was zero"
        elif prior.value < 0 < current.value or (prior.value < 0 and current.value == 0):
            reason = "the figure changed from a loss to a profit"
        elif current.value < 0 < prior.value:
            reason = "the figure changed from a profit to a loss"
        lines = []
        if reason:
            lines.append([
                ("text", f"{figure} was "),
                _link_fact(current.fact),
                ("text", " in "),
                _period_link(period_phrase(current.kind, current.period_start, current.period_end), current.fact),
                ("text", ", compared with "),
                _link_fact(prior.fact),
                ("text", " in "),
                _period_link(period_phrase(prior.kind, prior.period_start, prior.period_end), prior.fact),
                ("text", f". A percentage change is not shown because {reason}."),
            ])
        else:
            word = _higher(current.value, prior.value)
            lines.append([
                ("text", "It was "),
                ("link", show_measure(abs(current.value - prior.value), current.unit), fact_href(current.fact)),
                ("text", f" {word} than "),
                _period_link(period_phrase(prior.kind, prior.period_start, prior.period_end), prior.fact),
                ("text", "."),
            ])
        if sign_flip and not reason:
            pass
        return lines
    direction = _direction(current.value, prior.value)
    if direction == "was unchanged":
        return [[
            ("text", f"{figure} was unchanged from "),
            _period_link(period_phrase(prior.kind, prior.period_start, prior.period_end), prior.fact),
            ("text", " at "),
            _link_fact(current.fact),
            ("text", "."),
        ]]
    return [[
        ("text", f"It {direction} "),
        ("link", show_measure(abs(pct), "percent"), fact_href(current.fact)),
        ("text", " from "),
        _period_link(period_phrase(prior.kind, prior.period_start, prior.period_end), prior.fact),
        ("text", "."),
    ]]


def _comparison_block(
    role: str,
    fact: Fact,
    last: Cell | None,
    year: Cell | None,
    measure: str,
    form_words: str,
    filed: str,
    form: str = "",
) -> tuple[str, str]:
    label = label_for(role, fact)
    current = Cell(
        True,
        value=fact.value,
        unit=fact.unit,
        period_end=fact.period.end or "",
        period_start=fact.period.start,
        kind=fact.period.kind,
        fact=fact,
    )
    if last is None and year is None:
        return "", ""
    chunks: list[str] = []
    _append_changes(chunks, label, current, last, year, measure, form_words, filed)
    current_caption = column_header(current.kind, current.period_start, current.period_end)
    named = ""
    if _span_key(current.kind, current.period_start, current.period_end) in {"6", "9"}:
        named = f'<p class="caption">{html.escape(current_caption)}</p>\n'
    chart = _chart(label, current, last, year, fact, form, current_caption)
    short = _short_line(label, current, last, year, measure, form, chunks)
    note = ""
    if measure == "net_debt":
        amounts = [fact.value]
        for cell in (last, year):
            if cell is not None and cell.value is not None:
                amounts.append(cell.value)
        if any(amount < 0 for amount in amounts):
            note = f"<p>{html.escape(phrase('U9.neg'))}</p>\n"
    face = named + note + short + chart
    return face, "".join(chunks)


def _right_head(cell: Cell | None, current: Fact, form: str) -> str:
    kind = current.period.kind
    start = current.period.start
    end = current.period.end or ""
    if cell is not None and cell.period_end:
        kind = cell.kind or kind
        start = cell.period_start
        end = cell.period_end
    key = _span_key(kind, start, end)
    if key == "6":
        return EN["same_six"]
    if key == "9":
        return EN["same_nine"]
    if key == "12" or form == "10-K":
        return EN["prior_year"]
    return EN["same_quarter"]


def _phrase_for(head: str) -> str:
    if german():
        if head == EN["same_six"]:
            return choose(phrase("S1.period.same_ytd"), {"sechs|neun": "sechs"})
        if head == EN["same_nine"]:
            return choose(phrase("S1.period.same_ytd"), {"sechs|neun": "neun"})
        names = {
            EN["prior_quarter"]: "S1.period.prior_quarter",
            EN["same_quarter"]: "S1.period.same_quarter",
            EN["prior_year"]: "S1.period.prior_year",
        }
        ident = names.get(head, "")
        return phrase(ident) if ident else ""
    phrases = {
        EN["prior_quarter"]: EN["phrase_prior_quarter"],
        EN["same_quarter"]: EN["phrase_same_quarter"],
        EN["same_six"]: EN["phrase_same_six"],
        EN["same_nine"]: EN["phrase_same_nine"],
        EN["prior_year"]: EN["phrase_prior_year"],
    }
    return phrases.get(head, "")


def _show_head(head: str) -> str:
    if not german():
        return head
    if head == EN["same_six"]:
        return choose(phrase("H1.same_ytd"), {"sechs|neun": "sechs"})
    if head == EN["same_nine"]:
        return choose(phrase("H1.same_ytd"), {"sechs|neun": "neun"})
    names = {
        EN["prior_quarter"]: "H1.prior_quarter",
        EN["same_quarter"]: "H1.same_quarter",
        EN["prior_year"]: "H1.prior_year",
    }
    ident = names.get(head, "")
    return phrase(ident) if ident else head


def _scale(values: list[Decimal]) -> tuple[Decimal, Decimal]:
    """Shared zero. The width of a bar is its absolute value over the same span."""
    if not values:
        return Decimal("0.00"), Decimal(0)
    negative = max((abs(value) for value in values if value < 0), default=Decimal(0))
    positive = max((value for value in values if value > 0), default=Decimal(0))
    span = negative + positive
    if span == 0:
        return Decimal("0.00"), Decimal(0)
    zero = (negative / span * Decimal(100)).quantize(Decimal("0.01"))
    return zero, span


def _bar_box(value: Decimal, zero: Decimal, span: Decimal) -> tuple[str, str]:
    if span == 0:
        return "0.00", "0.00"
    width = (abs(value) / span * Decimal(100)).quantize(Decimal("0.01"))
    left = (zero - width) if value < 0 else zero
    return f"{left:.2f}", f"{width:.2f}"


def _value_link(cell_fact: Fact) -> tuple[str, str, str]:
    value = html.escape(show_measure(cell_fact.value, cell_fact.unit))
    href = fact_href(cell_fact)
    if not href.startswith("https://www.sec.gov/"):
        raise ValueError("number without a filing link")
    return f'<a href="{html.escape(href, quote=True)}">{value}</a>', value, href


def _chart(
    label: str,
    current: Cell,
    last: Cell | None,
    year: Cell | None,
    fact: Fact,
    form: str,
    current_caption: str,
) -> str:
    """One CSS bar per period. The bars are filled divs, not inline SVG."""
    rows: list[tuple] = []
    numbers: list[Decimal] = []
    if current.value is not None and current.fact is not None and current_caption:
        rows.append(("current", current_caption, "", current))
        numbers.append(current.value)
    for column, cell in (("c1", last), ("c2", year)):
        if cell is None:
            continue
        head = EN["prior_quarter"] if column == "c1" else _right_head(cell, fact, form)
        if not cell.available or cell.fact is None or cell.value is None:
            if cell.basis == "structural":
                period = cell.missing_period or "the prior quarter"
                if german():
                    template, text = _german_gap(label, period, structural=True, head=head)
                else:
                    text = f"{label} for the prior quarter is not available for this filing."
                    template = "M6"
            else:
                period = cell.missing_period or "the prior period"
                if german():
                    template, text = _german_gap(label, period, structural=False, head=head)
                else:
                    text = f"{label} for {period} is not in the filings White Cliff read, so no change is shown."
                    template = "M2"
            rows.append(("missing", _show_head(head), text, template))
            continue
        caption = column_header(cell.kind, cell.period_start, cell.period_end)
        rows.append(("value", head, caption, cell))
        numbers.append(cell.value)
    if not rows:
        return ""
    zero, span = _scale(numbers)
    spoken: list[str] = []
    items: list[str] = []
    index = 0
    for row in rows:
        kind = row[0]
        if kind == "current":
            _kind, caption, _empty, cell = row
            link, shown, _href = _value_link(cell.fact)
            left, width = _bar_box(cell.value, zero, span)
            negative = " neg" if cell.value < 0 else ""
            spoken.append(f"{caption}: {shown}")
            date = ""
            items.append(
                f'<li class="bar-row cur" style="--i:{index}">'
                f'<div class="bar-text"><p class="bh">{html.escape(caption)}</p>'
                f'<p class="bv">{link}</p>{date}</div>'
                f'<div class="bar-track" style="--zero:{zero:.2f}%" aria-hidden="true">'
                f'<div class="fill{negative}" style="left:{left}%;width:{width}%"></div></div></li>'
            )
        elif kind == "missing":
            _kind, head, text, template = row
            spoken.append(f"{head}: {text}")
            items.append(
                f'<li class="bar-row na" style="--i:{index}">'
                f'<div class="bar-text"><p class="bh">{html.escape(head)}</p></div>'
                f'<p class="m6" data-template="{template}">{html.escape(text)}</p></li>'
            )
        else:
            _kind, head, caption, cell = row
            link, shown, _href = _value_link(cell.fact)
            left, width = _bar_box(cell.value, zero, span)
            negative = " neg" if cell.value < 0 else ""
            spoken.append(f"{_show_head(head)}, {caption}: {shown}" if caption else f"{_show_head(head)}: {shown}")
            date = f'<p class="bd">{html.escape(caption)}</p>' if caption else ""
            items.append(
                f'<li class="bar-row old" style="--i:{index}">'
                f'<div class="bar-text"><p class="bh">{html.escape(_show_head(head))}</p>'
                f'<p class="bv">{link}</p>{date}</div>'
                f'<div class="bar-track" style="--zero:{zero:.2f}%" aria-hidden="true">'
                f'<div class="fill{negative}" style="left:{left}%;width:{width}%"></div></div></li>'
            )
        index += 1
    spoken_text = "; ".join(part.rstrip(".") for part in spoken)
    title = ui("bar_chart").rstrip(".")
    label = f"{title}. {spoken_text}." if spoken_text else title + "."
    label_text = html.escape(label, quote=True)
    return f'<ul class="chart" role="img" aria-label="{label_text}">{"".join(items)}</ul>\n'


def _s1_clause(current: Cell, prior: Cell, measure: str, phrase: str) -> tuple[str, str] | None:
    """One S1 clause. The percent links this figure and the period phrase links the earlier one."""
    if not phrase or measure not in {"money", "shares", "per_share", "net_debt"}:
        return None
    if (
        not prior.available
        or prior.fact is None
        or current.fact is None
        or prior.value is None
        or current.value is None
        or prior.basis in {"currency", "length"}
    ):
        return None
    period = _anchor("per", phrase, fact_href(prior.fact))
    if _displays_match(current, prior):
        if german():
            return "unchanged", "blieb unverändert gegenüber " + period
        return "unchanged", "was unchanged from " + period
    pct = percent_change(current.value, prior.value)
    if measure == "net_debt" or pct is None or pct == 0:
        diff = show_measure(abs(current.value - prior.value), current.unit)
        linked = _anchor("pct", diff, fact_href(current.fact))
        if german():
            word = "höher" if current.value >= prior.value else "niedriger"
            if phrase.startswith("den "):
                named = _anchor("per", phrase, fact_href(prior.fact))
                return "amount", f"war um {linked} {word} als in {named}"
            bare = phrase[4:] if phrase.startswith("dem ") else phrase
            named = _anchor("per", bare, fact_href(prior.fact))
            return "amount", f"war um {linked} {word} als im {named}"
        word = "higher" if current.value >= prior.value else "lower"
        return "amount", f"was {linked} {word} than {period}"
    direction = _direction(current.value, prior.value)
    percent = _anchor("pct", show_measure(abs(pct), "percent"), fact_href(current.fact))
    if german():
        verb = "stieg" if direction == "rose" else "sank"
        return "change", f"{verb} um {percent} gegenüber {period}"
    return "change", f"{direction} {percent} from {period}"


def _anchor(class_name: str, display: str, href: str) -> str:
    if not href.startswith("https://www.sec.gov/"):
        raise ValueError("number without a filing link")
    folded = display.casefold()
    if class_name == "pct" and "percent" not in folded and "prozent" not in folded:
        class_name = "fig"
    return (
        f'<a class="{class_name}" href="{html.escape(href, quote=True)}">{html.escape(display)}</a>'
    )


def _margin_lines(current: Cell, prior: Cell) -> list[list[tuple]]:
    """One margin change. The gap is the two shown percents, and unchanged means they match."""
    delta = _margin_gap(current.value, prior.value)
    period = _period_link(period_phrase(prior.kind, prior.period_start, prior.period_end), prior.fact)
    if delta == 0:
        if german():
            return [[("text", "Der Wert blieb unverändert gegenüber "), period, ("text", ".")]]
        return [[("text", "It was unchanged from "), period, ("text", ".")]]
    linked = ("link", show_measure(abs(delta), "percentage points"), fact_href(current.fact))
    if german():
        verb = "stieg" if delta > 0 else "sank"
        return [[("text", f"Der Wert {verb} um "), linked, ("text", " gegenüber "), period, ("text", ".")]]
    verb = "rose" if delta > 0 else "fell"
    return [[("text", f"It {verb} "), linked, ("text", " from "), period, ("text", ".")]]


def _margin_clause(current: Cell, prior: Cell, spoken: str) -> tuple[str, str] | None:
    if (
        not spoken
        or not prior.available
        or prior.fact is None
        or current.fact is None
        or prior.value is None
        or current.value is None
        or prior.basis in {"currency", "length"}
    ):
        return None
    delta = _margin_gap(current.value, prior.value)
    period = _anchor("per", spoken, fact_href(prior.fact))
    if delta == 0:
        if german():
            return "unchanged", "blieb unverändert gegenüber " + period
        return "unchanged", "was unchanged from " + period
    linked = _anchor("pct", show_measure(abs(delta), "percentage points"), fact_href(current.fact))
    if german():
        verb = "stieg" if delta > 0 else "sank"
        return "change", f"{verb} um {linked} gegenüber {period}"
    verb = "rose" if delta > 0 else "fell"
    return "change", f"{verb} {linked} from {period}"


def _margin_short(current: Cell, last: Cell | None, year: Cell | None, form: str) -> str:
    clauses: list[str] = []
    dated = False
    for column, cell in (("c1", last), ("c2", year)):
        if cell is None:
            continue
        if cell.available and cell.fact is not None and column_header(cell.kind, cell.period_start, cell.period_end):
            dated = True
        head = EN["prior_quarter"] if column == "c1" else _right_head(cell, current.fact, form)
        clause = _margin_clause(current, cell, _phrase_for(head))
        if clause is not None:
            clauses.append(clause[1])
    if not dated or not clauses:
        return ""
    body = (" und " if german() else " and ").join(clauses)
    lead = "Der Wert " if german() else "It "
    return f'<div class="cmp-slot"><p class="cmp" data-template="U8">{lead}{body}.</p></div>\n'


def _short_line(label, current, last, year, measure, form, chunks: list[str]) -> str:
    """S1 on a card that shows an H1 head with its date. Both zeros stay on C3."""
    if measure == "margin":
        return _margin_short(current, last, year, form)
    clauses: list[tuple[str, str]] = []
    dated = False
    for column, cell in (("c1", last), ("c2", year)):
        if cell is None:
            continue
        if cell.available and cell.fact is not None and column_header(cell.kind, cell.period_start, cell.period_end):
            dated = True
        head = EN["prior_quarter"] if column == "c1" else _right_head(cell, current.fact, form)
        clause = _s1_clause(current, cell, measure, _phrase_for(head))
        if clause is not None:
            clauses.append(clause)
    if dated and clauses and not all(kind == "unchanged" for kind, _html in clauses):
        body = " und ".join(html_clause for _kind, html_clause in clauses) if german() else " and ".join(
            html_clause for _kind, html_clause in clauses
        )
        lead = "Der Wert " if german() else "It "
        return f'<div class="cmp-slot"><p class="cmp" data-template="S1">{lead}{body}.</p></div>\n'
    if dated and len(clauses) == 1 and clauses[0][0] == "unchanged":
        lead = "Der Wert " if german() else "It "
        return f'<div class="cmp-slot"><p class="cmp" data-template="S1">{lead}{clauses[0][1]}.</p></div>\n'
    if dated and len(clauses) > 1 and all(kind == "unchanged" for kind, _html in clauses):
        copied = _retitled(chunks, "C3")
        if copied:
            return copied
    copied = _retitled(chunks, "C2", skip=("percentage change",))
    if dated and copied:
        return copied
    return ""


def _retitled(chunks: list[str], template: str, skip: tuple[str, ...] = ()) -> str:
    chosen = []
    for chunk in chunks:
        if f'data-template="{template}"' not in chunk:
            continue
        if any(needle in chunk for needle in skip):
            continue
        chosen.append(chunk.replace('class="change-line"', 'class="cmp"', 1))
    if not chosen:
        return ""
    return '<div class="cmp-slot">' + "".join(chosen) + "</div>\n"


def _emit_lines(chunks: list[str], label: str, lines: list[list[tuple]]) -> None:
    for line in lines:
        template_id = "C2"
        text = _plain(line)
        if text.startswith(f"{label} was unchanged"):
            template_id = "C3"
        elif "percentage change is not shown" in text:
            template_id = "C4"
        elif text.startswith("The periods") or text.startswith("The figures are in different"):
            template_id = "C6"
        chunks.append(_parts_html(template_id, line, "change-line"))


def _percent_clause(current: Cell, prior: Cell, measure: str) -> tuple[str, list[tuple]] | None:
    """One rose, fell, or unchanged clause. None when the column is not a percent change."""
    if measure not in {"money", "shares", "per_share"}:
        return None
    if (
        not prior.available
        or prior.fact is None
        or current.fact is None
        or prior.value is None
        or current.value is None
        or prior.basis in {"currency", "length"}
    ):
        return None
    phrase = period_phrase(prior.kind, prior.period_start, prior.period_end)
    if german():
        if current.value == prior.value:
            return "unchanged", [("text", "blieb unverändert gegenüber dem " + phrase)]
        pct = percent_change(current.value, prior.value)
        if pct is None:
            return None
        if pct == 0 or _direction(current.value, prior.value) == "was unchanged":
            return "unchanged", [("text", "blieb unverändert gegenüber dem " + phrase)]
        verb = "stieg" if _direction(current.value, prior.value) == "rose" else "sank"
        return "change", [
            ("text", f"{verb} um "),
            (
                "percent",
                show_measure(abs(pct), "percent"),
                fact_href(current.fact),
                fact_href(prior.fact),
                show_measure(current.fact.value, current.fact.unit),
                show_measure(prior.fact.value, prior.fact.unit),
            ),
            ("text", " gegenüber dem " + phrase),
        ]
    if current.value == prior.value:
        return "unchanged", [("text", "was unchanged from " + phrase)]
    pct = percent_change(current.value, prior.value)
    if pct is None:
        return None
    if pct == 0 or _direction(current.value, prior.value) == "was unchanged":
        return "unchanged", [("text", "was unchanged from " + phrase)]
    return "change", [
        ("text", f"{_direction(current.value, prior.value)} "),
        (
            "percent",
            show_measure(abs(pct), "percent"),
            fact_href(current.fact),
            fact_href(prior.fact),
            show_measure(current.fact.value, current.fact.unit),
            show_measure(prior.fact.value, prior.fact.unit),
        ),
        ("text", " from " + phrase),
    ]


def _it_line(clauses: list[list[tuple]]) -> list[tuple]:
    parts: list[tuple] = [("text", "Der Wert " if german() else "It ")]
    for index, clause in enumerate(clauses):
        if index:
            parts.append(("text", " und " if german() else ", and "))
        parts.extend(clause)
    parts.append(("text", "."))
    return parts


def _append_changes(chunks, label, current, last, year, measure, form_words, filed) -> None:
    held: list[tuple[Cell, str, list[tuple]]] = []
    for column in (last, year):
        if column is None:
            continue
        if not column.available:
            if column.basis == "length":
                text = phrase("C6.lengths") if german() else "The periods are different lengths."
                chunks.append(_parts_html("C6", [("text", text)], "change-line"))
            if column.basis == "currency":
                text = (
                    phrase("C6.currency")
                    if german()
                    else "The figures are in different currencies, so no change is shown."
                )
                chunks.append(_parts_html("C6", [("text", text)], "change-line"))
            continue
        clause = _percent_clause(current, column, measure)
        if clause is not None:
            held.append((column, clause[0], clause[1]))
        else:
            _emit_lines(chunks, label, _change_parts(label, current, column, measure))
        if column.revised_from is not None and column.fact is not None and current.fact is not None:
            when = long_date(filed) if filed else "the filing date"
            if german():
                chunks.append(_parts_html("C5", [
                    ("text", "Der Wert im "),
                    _period_link(period_phrase(column.kind, column.period_start, column.period_end), column.fact),
                    ("text", f" wird so gezeigt, wie er im am "),
                    ("link", when, _filing_href(current.fact.source.url)),
                    ("text", f" eingereichten Bericht ({form_words}) rückwirkend angepasst wurde; der frühere Bericht wies "),
                    _link_fact(column.revised_from),
                    ("text", " aus."),
                ], "change-line"))
            else:
                chunks.append(_parts_html("C5", [
                    ("text", "The "),
                    _period_link(period_phrase(column.kind, column.period_start, column.period_end), column.fact),
                    ("text", f" figure is shown as restated in the {form_words} filed on "),
                    ("link", when, _filing_href(current.fact.source.url)),
                    ("text", "; the earlier filing showed "),
                    _link_fact(column.revised_from),
                    ("text", "."),
                ], "change-line"))
    if len(held) == 2 and all(kind == "unchanged" for _column, kind, _parts in held):
        for column, _kind, _parts in held:
            _emit_lines(chunks, label, _change_parts(label, current, column, measure))
        return
    if held:
        chunks.append(_parts_html("C2", _it_line([parts for _column, _kind, parts in held]), "change-line"))


_INPUT_LABEL = {
    "gross profit": "LBL.gross_profit",
    "revenue": "LBL.revenue",
    "prior revenue": "LBL.revenue",
    "operating income": "LBL.operating_income",
    "net income": "LBL.net_income",
    "debt": "LBL.debt",
    "cash": "LBL.cash",
}


def _input_name(name: str) -> str:
    if german() and name in _INPUT_LABEL:
        return phrase(_INPUT_LABEL[name])
    return name


def _fill_formula(ident: str, slots: dict[str, str]) -> str:
    text = phrase(ident)
    for key in ("period_prev", "period", "a", "b"):
        if key in slots:
            text = text.replace("{" + key + "}", slots[key])
    return text


def _computed_formula(role: str, inputs: list | None = None) -> str:
    used = list(inputs or [])
    if german():
        revenue = phrase("LBL.revenue")
        if role == "gross_margin":
            return phrase("LBL.gross_margin")
        if role == "operating_margin":
            return phrase("LBL.operating_margin")
        if role == "net_margin":
            return phrase("LBL.net_margin")
        if role == "net_debt":
            debt = used[0][1] if used else None
            return _fill_formula("E2.formula.minus", {"a": _debt_noun(debt), "b": phrase("LBL.cash")})
        if role == "yoy_change" and len(used) >= 2:
            current, prior = used[0][1], used[1][1]
            noun = phrase("LBL.revenue_contract") if current.concept == "RevenueFromContractWithCustomerExcludingAssessedTax" else revenue
            return _fill_formula(
                "E2.formula.yoy",
                {
                    "a": noun,
                    "period": period_phrase(current.period.kind, current.period.start, current.period.end or ""),
                    "period_prev": period_phrase(prior.period.kind, prior.period.start, prior.period.end or ""),
                },
            )
        return ""
    if role == "gross_margin":
        return phrase("LBL.gross_margin")
    if role == "operating_margin":
        return phrase("LBL.operating_margin")
    if role == "net_margin":
        return phrase("LBL.net_margin")
    if role == "net_debt":
        if len(used) >= 2:
            from white_cliff.explain import _net_debt_phrase

            named = _net_debt_phrase(used[0][1], used[1][1])
            if named:
                return named
        return "debt minus cash"
    if role == "yoy_change":
        return "(revenue minus prior revenue) divided by prior revenue"
    return ""


def _explain_amount(role: str, fact: Fact, inputs: list[tuple[str, Fact]]) -> tuple:
    """The figure the explain line states. A year-over-year change is the percent, not the revenue."""
    if role == "yoy_change" and len(inputs) >= 2:
        current, prior = inputs[0][1], inputs[1][1]
        if current.value is not None and prior.value is not None:
            pct = percent_change(current.value, prior.value)
            if pct is not None:
                return ("link", show_measure(pct, "percent"), fact_href(current))
    return _link_fact(fact)


def _filled_parts(ident: str, text_slots: dict[str, str], link_slots: dict[str, tuple]) -> list[tuple]:
    """Fill one cleared sentence. Linked slots stay links; the words stay the template."""
    template = phrase(ident)
    parts: list[tuple] = []
    cursor = 0
    for match in re.finditer(r"\{([^{}]+)\}", template):
        if match.start() > cursor:
            parts.append(("text", template[cursor : match.start()]))
        key = match.group(1)
        parts.append(link_slots[key] if key in link_slots else ("text", text_slots[key]))
        cursor = match.end()
    if cursor < len(template):
        parts.append(("text", template[cursor:]))
    return parts


def _explain_block(role: str, fact: Fact, company: str, statement: str, formula: str, inputs: list[tuple[str, Fact]]) -> str:
    label = label_for(role, fact)
    definition = DEFINITIONS.get(role, "a figure reported in the filing")
    period = period_phrase(fact.period.kind, fact.period.start, fact.period.end or "")
    amount = _explain_amount(role, fact, inputs)
    if fact.period.kind == "instant":
        line = label
        if role == "net_debt" and not german() and len(inputs) >= 2:
            from white_cliff.explain import _net_debt_phrase

            named = _net_debt_phrase(inputs[0][1], inputs[1][1])
            if named:
                line = named
        sentence = _filled_parts(
            "H6.e2",
            {"company": company, "line": line},
            {"amount": amount, "date": _period_link(long_date(fact.period.end or ""), fact)},
        )
        if german():
            parts = []
            if role == "operating_cash_flow":
                parts.append(_parts_html("E1", [("text", phrase("E1.example"))]))
            parts.append(_parts_html("E2", sentence))
            if formula:
                parts.append(_parts_html("E2", [("text", phrase("E2.formula.label") + " " + formula)]))
            return "".join(parts)
        parts = [
            _parts_html("E1", [("text", f"{label} is {definition}.")]),
            _parts_html("E2", sentence),
        ]
        if formula and inputs:
            input_parts: list[tuple] = [("text", f"It is calculated as {formula}, using ")]
            for index, (name, source) in enumerate(inputs):
                if index:
                    input_parts.append(("text", " and " if index == len(inputs) - 1 else ", "))
                input_parts.append(("text", f"{_input_name(name)} of "))
                input_parts.append(_link_fact(source))
            input_parts.append(("text", "."))
            parts.append(_parts_html("E2", input_parts))
        return "".join(parts)
    if german():
        parts = []
        if role == "operating_cash_flow":
            parts.append(_parts_html("E1", [("text", phrase("E1.example"))]))
        source = statement or phrase("ST.s.income")
        parts.append(_parts_html("E2", [
            ("text", f"Bei {company} lag der Wert der Position „{label}“ bei "),
            amount,
            ("text", " im "),
            _period_link(period, fact),
            ("text", f". Er stammt aus der {source}, Position „{label}“."),
        ]))
        if formula:
            parts.append(_parts_html("E2", [("text", phrase("E2.formula.label") + " " + formula)]))
        return "".join(parts)
    parts = [
        _parts_html("E1", [("text", f"{label} is {definition}.")]),
        _parts_html("E2", [
            ("text", f"For {company}, {label} was "),
            amount,
            ("text", " in "),
            _period_link(period, fact),
            ("text", f". It came from the {statement or 'filing'}."),
        ]),
    ]
    if formula and inputs:
        input_parts: list[tuple] = [("text", f"It is calculated as {formula}, using ")]
        for index, (name, source) in enumerate(inputs):
            if index:
                input_parts.append(("text", " and " if index == len(inputs) - 1 else ", "))
            input_parts.append(("text", f"{_input_name(name)} of "))
            input_parts.append(_link_fact(source))
        input_parts.append(("text", "."))
        parts.append(_parts_html("E2", input_parts))
    return "".join(parts)


def _threshold(check_id: str, label: str) -> str:
    if german():
        if check_id == "C1":
            text = phrase("C1.threshold")
        elif check_id in {"C2", "C3"}:
            subject = "die Vorräte" if check_id == "C3" else "die Forderungen"
            other = "der Umsatz" if label == "revenue" or check_id == "C2" else "die Umsatzkosten"
            text = choose(
                phrase("C2C3.threshold"),
                {"die Forderungen|die Vorräte": subject, "der Umsatz|die Umsatzkosten": other},
            )
        elif check_id == "C4":
            text = phrase("C4.threshold")
        elif check_id == "C6":
            text = phrase("C6.threshold")
        elif check_id == "C7":
            text = phrase("C7.threshold")
        else:
            text = phrase("C8.threshold")
        return f'<p data-template="THRESHOLD" data-constant="threshold">{html.escape(text)}</p>\n'
    if check_id == "C1":
        text = f"This check marks results below {format(CASH_CONVERSION, '.2f')} times."
    elif check_id == "C2":
        text = "This check marks results where receivables grew at least 10 percentage points faster than revenue."
    elif check_id == "C3":
        text = f"This check marks results where inventory grew at least 10 percentage points faster than {label}."
    elif check_id == "C4":
        text = "This check marks any item equal to at least 10 percent of operating income."
    elif check_id == "C6":
        text = (
            "This check marks a rise of at least 3 percent in diluted shares, "
            "or diluted shares at least 3 percent above basic shares."
        )
    elif check_id == "C7":
        text = "This check marks a change of at least 3.0 percentage points in either margin."
    else:
        text = "This check marks a change of at least 5.0 percentage points."
    return f'<p data-template="THRESHOLD" data-constant="threshold">{html.escape(text)}</p>\n'


def _marker(outcome: str, reason: str) -> str:
    if outcome == "unusual":
        text = phrase("U10.marker.marked")
    elif outcome == "consistent":
        text = phrase("U10.marker.notmarked")
    else:
        plain = _german_reason(reason) if german() else reason
        text = phrase("U10.marker.notrun").replace("{plain reason}", plain)
    return f'<p class="marker" data-template="MARKER">{html.escape(text)}</p>\n'


def _german_figure(name: str) -> str:
    """A check's figure name from the cleared labels. A name with no label stays as the filing wrote it."""
    labels = {
        "Operating income": "LBL.operating_income",
        "Net income": "LBL.net_income",
        "Revenue": "LBL.revenue",
        "Gross profit": "LBL.gross_profit",
        "Diluted shares": "LBL.diluted_shares",
        "Income tax": "LBL.income_tax",
        "Accounts receivable": "LBL.accounts_receivable",
    }
    ident = labels.get(name)
    if ident:
        return phrase(ident)
    return name


def _german_reason(reason: str) -> str:
    copied = shown_copy(reason)
    if copied != reason:
        return copied
    suffix = " is not in the filing."
    if reason.endswith(suffix):
        figure = _german_figure(reason[: -len(suffix)])
        return phrase("K.notrun.missing").replace("{figure}", figure)
    return reason


def _linked(display: str, href: str) -> str:
    return f'<a href="{html.escape(href, quote=True)}">{html.escape(display)}</a>'


def _pct_num(value: Decimal) -> str:
    from white_cliff.german import german_number

    return german_number(abs(value), 1)


def _date_link(fact: Fact) -> str:
    return _linked(long_date(fact.period.end or ""), _filing_href(fact.source.url))


def _period_html(fact: Fact) -> str:
    return _linked(
        period_phrase(fact.period.kind, fact.period.start, fact.period.end or ""),
        _filing_href(fact.source.url),
    )


def _check_numbers_de(result: CheckResult) -> str:
    from white_cliff.german import german_number
    from white_cliff.lexicon import STRINGS

    facts = list(result.facts)

    def paragraph(body: str) -> str:
        return f'<p data-template="NUMBERS">{body}</p>\n'

    if result.check_id == "C1" and len(facts) >= 2:
        ocf, ni = facts[0], facts[1]
        template = STRINGS["C1.numbers"][1]
        slots = {
            "OCF": _linked(show_measure(ocf.value, ocf.unit), fact_href(ocf)),
            "NI": _linked(show_measure(ni.value, ni.unit), fact_href(ni)),
            "period": _period_html(ocf),
            "ratio": _linked(german_number(result.numbers["ratio"], 1), fact_href(ocf)),
        }
        if "ratio_prior" in result.numbers and len(facts) >= 4:
            prior = facts[2]
            slots["ratio_prior"] = _linked(german_number(result.numbers["ratio_prior"], 1), fact_href(prior))
            slots["period_prior"] = _period_html(prior)
        else:
            template = template.split(" (")[0] + "."
        return _period_lead(ocf) + paragraph(fill(template, slots))
    if result.check_id == "C2" and len(facts) >= 4:
        ar_now, ar_then, rev_now, _rev_then = facts[:4]
        template = choose(
            STRINGS["C2.numbers"][1],
            {
                "stiegen|sanken": "stiegen" if result.numbers["g_ar"] > 0 else "sanken",
                "stieg|sank": "stieg" if result.numbers["g_rev"] > 0 else "sank",
            },
        )
        return paragraph(fill(template, {
            "fy_prior": _date_link(ar_then),
            "fy": _date_link(ar_now),
            "g_AR": _linked(_pct_num(result.numbers["g_ar"]), fact_href(ar_now)),
            "g_Rev": _linked(_pct_num(result.numbers["g_rev"]), fact_href(rev_now)),
            "days_t": _linked(german_number(result.numbers["days_now"], 1), fact_href(ar_now)),
            "days_p": _linked(german_number(result.numbers["days_then"], 1), fact_href(ar_then)),
        }))
    if result.check_id == "C3" and len(facts) >= 4:
        inv_now, inv_then, cost_now, _cost_then = facts[:4]
        revenue = result.labels.get("cost") == "revenue"
        template = choose(
            STRINGS["C3.numbers"][1],
            {
                "stiegen|sanken": "stiegen" if result.numbers["g_inv"] > 0 else "sanken",
                "die Umsatzkosten|der Umsatz": "der Umsatz" if revenue else "die Umsatzkosten",
                "stiegen|sanken / stieg|sank": (
                    ("stieg" if result.numbers["g_cost"] > 0 else "sank")
                    if revenue
                    else ("stiegen" if result.numbers["g_cost"] > 0 else "sanken")
                ),
            },
        )
        return paragraph(fill(template, {
            "fy_prior": _date_link(inv_then),
            "fy": _date_link(inv_now),
            "g_Inv": _linked(_pct_num(result.numbers["g_inv"]), fact_href(inv_now)),
            "g_Cost": _linked(_pct_num(result.numbers["g_cost"]), fact_href(cost_now)),
        }))
    if result.check_id == "C4" and result.items:
        operating = facts[-1]
        lines = []
        for item in result.items:
            template = choose(
                STRINGS["C4.numbers"][1],
                {"einen Aufwand|einen Ertrag": "einen Aufwand" if item.charge else "einen Ertrag"},
            )
            share = (item.share * Decimal(100)).quantize(Decimal("0.1"))
            label = phrase("C4.label." + item.fact.concept) if ("C4.label." + item.fact.concept) in STRINGS else item.fact.concept
            lines.append(paragraph(fill(template, {
                "period": _period_html(item.fact),
                "item plain label": html.escape(label),
                "value": _linked(show_measure(item.fact.value, item.fact.unit), fact_href(item.fact)),
                "share": _linked(_pct_num(share), fact_href(item.fact)),
                "OI": _linked(show_measure(operating.value, operating.unit), fact_href(operating)),
            })))
        return "".join(lines)
    if result.check_id == "C6" and len(facts) >= 2:
        now, earlier = facts[0], facts[1]
        growth = result.numbers["growth"]
        gap = result.numbers["gap"]
        first, second = STRINGS["C6.numbers"][1].split(". ", 1)
        first = choose(first, {"stieg|sank": "stieg" if growth > 0 else "sank"})
        body = paragraph(fill(first + ".", {
            "period_prior": _period_html(earlier),
            "period": _period_html(now),
            "growth": _linked(_pct_num(growth), fact_href(now)),
        }))
        if gap >= 0:
            body += paragraph(fill(second, {
                "period": _period_html(now),
                "gap": _linked(_pct_num(gap), fact_href(now)),
            }))
        return body
    if result.check_id == "C7":
        lines = []
        gross, operating = STRINGS["C7.numbers"][1].split(". ", 1)
        if "gm_delta" in result.numbers and len(facts) >= 4:
            lines.append(paragraph(fill(gross + ".", {
                "gm_t": _linked(_pct_num(result.numbers["gm_now"]), fact_href(facts[2])),
                "period": _period_html(facts[0]),
                "gm_p": _linked(_pct_num(result.numbers["gm_then"]), fact_href(facts[3])),
                "period_prior": _period_html(facts[1]),
                "d": _linked(_pct_num(result.numbers["gm_delta"]), fact_href(facts[2])),
            })))
        if "om_delta" in result.numbers:
            oi = facts[-2]
            operating = operating.replace("{d}", "{d_om}", 1)
            lines.append(paragraph(fill(operating, {
                "om_t": _linked(_pct_num(result.numbers["om_now"]), fact_href(oi)),
                "om_p": _linked(_pct_num(result.numbers["om_then"]), fact_href(oi)),
                "d_om": _linked(_pct_num(result.numbers["om_delta"]), fact_href(oi)),
            })))
        return "".join(lines)
    if result.check_id == "C8" and facts:
        return paragraph(fill(STRINGS["U10.C8.numbers"][1], {
            "rate_t": _linked(_pct_num(result.numbers["rate_now"]), fact_href(facts[0])),
            "period": _period_html(facts[0]),
            "rate_p": _linked(_pct_num(result.numbers["rate_then"]), fact_href(facts[1])),
            "period_prior": _period_html(facts[1]),
            "d": _linked(_pct_num(result.numbers["delta"]), fact_href(facts[0])),
        }))
    return ""


def _check_numbers(result: CheckResult) -> str:
    if german():
        return _check_numbers_de(result)
    facts = list(result.facts)
    if result.check_id == "C1" and len(facts) >= 2:
        ocf, ni = facts[0], facts[1]
        parts: list[tuple] = [
            ("text", "Operating cash flow was "),
            _link_fact(ocf),
            ("text", " and net income was "),
            _link_fact(ni),
            ("text", " for "),
            _period_link(period_phrase(ocf.period.kind, ocf.period.start, ocf.period.end or ""), ocf),
            ("text", ", so operating cash flow was "),
            ("link", f"{result.numbers['ratio']:.1f} times", fact_href(ocf)),
            ("text", " net income"),
        ]
        if "ratio_prior" in result.numbers and len(facts) >= 4:
            prior = facts[2]
            parts.extend([
                ("text", " ("),
                ("link", f"{result.numbers['ratio_prior']:.1f} times", fact_href(prior)),
                ("text", " for "),
                _period_link(period_phrase(prior.period.kind, prior.period.start, prior.period.end or ""), prior),
                ("text", ")"),
            ])
        parts.append(("text", "."))
        return _period_lead(ocf) + _parts_html("NUMBERS", parts)
    if result.check_id == "C2" and len(facts) >= 4:
        ar_now, ar_then, rev_now, rev_then = facts[:4]
        if result.numbers["g_ar"] == 0 or result.numbers["g_rev"] == 0:
            lines = []
            if result.numbers["g_ar"] == 0:
                lines.append(_unchanged_line("Accounts receivable", ar_then, ar_now))
            else:
                lines.append(_parts_html("NUMBERS", [
                    ("text", f"Accounts receivable {_rose(result.numbers['g_ar'])} "),
                    ("link", show_measure(abs(result.numbers["g_ar"]), "percent"), fact_href(ar_now)),
                    ("text", " from "),
                    _period_link(period_phrase("instant", None, ar_then.period.end or ""), ar_then),
                    ("text", " to "),
                    _period_link(period_phrase("instant", None, ar_now.period.end or ""), ar_now),
                    ("text", "."),
                ]))
            if result.numbers["g_rev"] == 0:
                lines.append(_unchanged_line("Revenue", rev_then, rev_now))
            else:
                lines.append(_parts_html("NUMBERS", [
                    ("text", f"Revenue {_rose(result.numbers['g_rev'])} "),
                    ("link", show_measure(abs(result.numbers["g_rev"]), "percent"), fact_href(rev_now)),
                    ("text", "."),
                ]))
            lines.append(_parts_html("NUMBERS", [
                ("text", "Receivables equalled "),
                ("link", f"{result.numbers['days_now']:.1f} days", fact_href(ar_now)),
                ("text", " of sales, compared with "),
                ("link", f"{result.numbers['days_then']:.1f} days", fact_href(ar_then)),
                ("text", " a year earlier."),
            ]))
            return "".join(lines)
        return _parts_html("NUMBERS", [
            ("text", f"Accounts receivable {_rose(result.numbers['g_ar'])} "),
            ("link", show_measure(abs(result.numbers["g_ar"]), "percent"), fact_href(ar_now)),
            ("text", " from "),
            _period_link(period_phrase("instant", None, ar_then.period.end or ""), ar_then),
            ("text", " to "),
            _period_link(period_phrase("instant", None, ar_now.period.end or ""), ar_now),
            ("text", f", while revenue {_rose(result.numbers['g_rev'])} "),
            ("link", show_measure(abs(result.numbers["g_rev"]), "percent"), fact_href(rev_now)),
            ("text", ". Receivables equalled "),
            ("link", f"{result.numbers['days_now']:.1f} days", fact_href(ar_now)),
            ("text", " of sales, compared with "),
            ("link", f"{result.numbers['days_then']:.1f} days", fact_href(ar_then)),
            ("text", " a year earlier."),
        ])
    if result.check_id == "C3" and len(facts) >= 4:
        inv_now, inv_then, cost_now, _cost_then = facts[:4]
        cost_label = result.labels.get("cost", "cost of sales")
        if result.numbers["g_inv"] == 0 or result.numbers["g_cost"] == 0:
            lines = []
            if result.numbers["g_inv"] == 0:
                lines.append(_unchanged_line("Inventory", inv_then, inv_now))
            else:
                lines.append(_parts_html("NUMBERS", [
                    ("text", f"Inventory {_rose(result.numbers['g_inv'])} "),
                    ("link", show_measure(abs(result.numbers["g_inv"]), "percent"), fact_href(inv_now)),
                    ("text", " from "),
                    _period_link(period_phrase("instant", None, inv_then.period.end or ""), inv_then),
                    ("text", " to "),
                    _period_link(period_phrase("instant", None, inv_now.period.end or ""), inv_now),
                    ("text", "."),
                ]))
            cost_name = cost_label[:1].upper() + cost_label[1:]
            if result.numbers["g_cost"] == 0:
                lines.append(_unchanged_line(cost_name, _cost_then, cost_now))
            else:
                lines.append(_parts_html("NUMBERS", [
                    ("text", f"{cost_name} {_rose(result.numbers['g_cost'])} "),
                    ("link", show_measure(abs(result.numbers["g_cost"]), "percent"), fact_href(cost_now)),
                    ("text", "."),
                ]))
            return "".join(lines)
        return _parts_html("NUMBERS", [
            ("text", f"Inventory {_rose(result.numbers['g_inv'])} "),
            ("link", show_measure(abs(result.numbers["g_inv"]), "percent"), fact_href(inv_now)),
            ("text", " from "),
            _period_link(period_phrase("instant", None, inv_then.period.end or ""), inv_then),
            ("text", " to "),
            _period_link(period_phrase("instant", None, inv_now.period.end or ""), inv_now),
            ("text", f", while {cost_label} {_rose(result.numbers['g_cost'])} "),
            ("link", show_measure(abs(result.numbers["g_cost"]), "percent"), fact_href(cost_now)),
            ("text", "."),
        ])
    if result.check_id == "C4" and result.items:
        operating = facts[-1]
        lines = []
        for item in result.items:
            kind = "charge" if item.charge else "gain"
            share = (item.share * Decimal(100)).quantize(Decimal("0.1"))
            lines.append(_parts_html("NUMBERS", [
                ("text", f"The filing tags {ITEM_LABELS.get(item.fact.concept, item.fact.concept)} of "),
                _link_fact(item.fact),
                ("text", " for "),
                _period_link(period_phrase(item.fact.period.kind, item.fact.period.start, item.fact.period.end or ""), item.fact),
                ("text", f", a {kind} equal to "),
                ("link", show_measure(share, "percent"), fact_href(item.fact)),
                ("text", " of operating income of "),
                _link_fact(operating),
                ("text", "."),
            ]))
        return "".join(lines)
    if result.check_id == "C6" and len(facts) >= 2:
        now, earlier = facts[0], facts[1]
        growth = result.numbers["growth"]
        gap = result.numbers["gap"]
        if growth == 0:
            lines = [_unchanged_line("The diluted share count", earlier, now)]
            if gap > 0:
                lines.append(_parts_html("NUMBERS", [
                    ("text", "Diluted shares were "),
                    ("link", show_measure(abs(gap), "percent"), fact_href(now)),
                    ("text", " more than basic shares in "),
                    _period_link(period_phrase(now.period.kind, now.period.start, now.period.end or ""), now),
                    ("text", "."),
                ]))
            return "".join(lines)
        share_parts: list[tuple] = [
            ("text", f"The diluted share count {_rose(growth)} "),
            ("link", show_measure(abs(growth), "percent"), fact_href(now)),
            ("text", " from "),
            _period_link(period_phrase(earlier.period.kind, earlier.period.start, earlier.period.end or ""), earlier),
            ("text", " to "),
            _period_link(period_phrase(now.period.kind, now.period.start, now.period.end or ""), now),
        ]
        if gap >= 0:
            share_parts.extend([
                ("text", ". Diluted shares were "),
                ("link", show_measure(abs(gap), "percent"), fact_href(now)),
                ("text", " more than basic shares in "),
                _period_link(period_phrase(now.period.kind, now.period.start, now.period.end or ""), now),
                ("text", "."),
            ])
        else:
            share_parts.append(("text", "."))
        return _parts_html("NUMBERS", share_parts)
    if result.check_id == "C7":
        lines = []
        if "gm_delta" in result.numbers and len(facts) >= 4:
            lines.append(_parts_html("NUMBERS", [
                ("text", "Gross margin was "),
                ("link", show_measure(result.numbers["gm_now"], "percent"), fact_href(facts[2])),
                ("text", " in "),
                _period_link(period_phrase(facts[0].period.kind, facts[0].period.start, facts[0].period.end or ""), facts[0]),
                ("text", " and "),
                ("link", show_measure(result.numbers["gm_then"], "percent"), fact_href(facts[3])),
                ("text", " in "),
                _period_link(period_phrase(facts[1].period.kind, facts[1].period.start, facts[1].period.end or ""), facts[1]),
                ("text", ", a change of "),
                ("link", show_measure(abs(result.numbers["gm_delta"]).quantize(Decimal("0.1")), "percentage points"), fact_href(facts[2])),
                ("text", "."),
            ]))
        if "om_delta" in result.numbers:
            oi = facts[-2]
            lines.append(_parts_html("NUMBERS", [
                ("text", "Operating margin was "),
                ("link", show_measure(result.numbers["om_now"], "percent"), fact_href(oi)),
                ("text", " and "),
                ("link", show_measure(result.numbers["om_then"], "percent"), fact_href(oi)),
                ("text", ", a change of "),
                ("link", show_measure(abs(result.numbers["om_delta"]).quantize(Decimal("0.1")), "percentage points"), fact_href(oi)),
                ("text", "."),
            ]))
        return "".join(lines)
    if result.check_id == "C8" and facts:
        return _parts_html("NUMBERS", [
            ("text", "Income tax was "),
            ("link", show_measure(result.numbers["rate_now"], "percent"), fact_href(facts[0])),
            ("text", " of income before tax in "),
            _period_link(period_phrase(facts[0].period.kind, facts[0].period.start, facts[0].period.end or ""), facts[0]),
            ("text", " and "),
            ("link", show_measure(result.numbers["rate_then"], "percent"), fact_href(facts[1])),
            ("text", " in "),
            _period_link(period_phrase(facts[1].period.kind, facts[1].period.start, facts[1].period.end or ""), facts[1]),
            ("text", ", a change of "),
            ("link", show_measure(abs(result.numbers["delta"]).quantize(Decimal("0.1")), "percentage points"), fact_href(facts[0])),
            ("text", "."),
        ])
    return ""


def _rose(value: Decimal) -> str:
    if value > 0:
        return "rose"
    if value < 0:
        return "fell"
    return "was unchanged"


def _unchanged_line(figure: str, prior: Fact, current: Fact) -> str:
    return _parts_html("C3", [
        ("text", f"{figure} was unchanged from "),
        _period_link(period_phrase(prior.period.kind, prior.period.start, prior.period.end or ""), prior),
        ("text", " at "),
        _link_fact(current),
        ("text", "."),
    ])


def _check_heading(result: CheckResult) -> str:
    return phrase("U10.h." + result.check_id)


def _check_aside(result: CheckResult) -> str:
    """Threshold, why, ordinary causes and the formula, behind Explain."""
    label = result.labels.get("cost", "cost of sales")
    parts = [_threshold(result.check_id, label)]
    if german():
        why = phrase(result.check_id + ".why")
    else:
        why = WHY[result.check_id]
    if result.check_id == "C1":
        causes = phrase("U10.C1.oc")
    elif german():
        causes = phrase(result.check_id + ".oc")
    else:
        causes = CAUSES[result.check_id]
    parts.append(f'<p data-template="WHY">{html.escape(why)}</p>\n')
    parts.append(f'<p data-template="CAUSES">{html.escape(causes)}</p>\n')
    if result.formula and not german():
        formula = html.escape(phrase("E2.formula.label") + " " + result.formula)
        parts.append(f'<p data-template="FORMULA">{formula}.</p>\n')
    return "".join(parts)


def _period_lead(fact: Fact) -> str:
    lead = column_header(fact.period.kind, fact.period.start, fact.period.end or "")
    if not lead:
        return ""
    return f'<p class="period">{html.escape(lead)}</p>\n'


def _check_html(result: CheckResult) -> str:
    heading = _check_heading(result)
    ident = result.check_id.lower()
    if result.outcome == "not_run":
        return (
            f'<section class="check" data-check="{result.check_id}">\n'
            f"<h3>{html.escape(heading)}</h3>\n"
            f"{_marker(result.outcome, result.reason)}"
            "</section>\n"
        )
    aside = _check_aside(result)
    button = (
        f'<button type="button" class="explain tap" aria-expanded="false" '
        f'aria-controls="formula-{ident}">{html.escape(ui("explain"))}'
        '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 8l5 5 5-5"></path></svg>'
        "</button>\n"
    )
    panel = (
        f'<div id="formula-{ident}" class="detail" aria-hidden="true">'
        f'<div class="detail-inner">{aside}</div></div>\n'
    )
    return (
        f'<section class="check" data-check="{result.check_id}">\n'
        f"<h3>{html.escape(heading)}</h3>\n"
        f"{_marker(result.outcome, result.reason)}{_check_numbers(result)}{button}{panel}</section>\n"
    )


def quality_html(facts: list[Fact], *, form: str, period_end: str | None) -> str:
    blocks = [_check_html(result) for result in run_checks(facts, form=form, period_end=period_end)]
    return (
        '<section class="quality" id="quality">\n'
        f"<h2>{html.escape(phrase('U10.heading'))}</h2>\n"
        f'<p data-template="FRAME">{html.escape(phrase("F.checks"))}</p>\n'
        f'<p data-template="LIMIT">{html.escape(phrase("Q.limit"))}</p>\n'
        + "".join(blocks)
        + "</section>\n"
    )


def _role_of(explained, kind: str, identifier: str) -> tuple[str, Fact | None, list[tuple[str, Fact]]]:
    if kind == "fact":
        fact = explained.store.get(identifier)
        return fact.role or "revenue", fact, []
    calc = explained.store.get_calc(identifier)
    inputs = []
    names = {
        "gross_margin": ("gross profit", "revenue"),
        "operating_margin": ("operating income", "revenue"),
        "net_margin": ("net income", "revenue"),
        "yoy_change": ("revenue", "prior revenue"),
        "net_debt": ("debt", "cash"),
    }.get(calc.name, ("input", "input"))
    for index, fact_id in enumerate(calc.input_ids):
        if explained.store.has_fact(fact_id):
            inputs.append((names[index] if index < len(names) else "input", explained.store.get(fact_id)))
    fact = inputs[0][1] if inputs else None
    return calc.name, fact, inputs


def _statement(name: str) -> str:
    if not german():
        return name
    names = {
        "Income statement": "ST.income",
        "Balance sheet": "ST.balance",
        "Cash flows": "ST.cashflow",
        "Equity": "ST.equity",
        "Document": "ST.document",
        "the filing": "ST.document",
    }
    ident = names.get(name, "")
    return phrase(ident) if ident else name


def _statement_sentence(name: str) -> str:
    """The statement noun that follows 'aus der'."""
    if not german():
        return name
    names = {
        "Income statement": "ST.s.income",
        "Balance sheet": "ST.s.balance",
        "Cash flows": "ST.s.cashflow",
        "Equity": "ST.s.equity",
        "Document": "ST.document",
        "the filing": "ST.document",
    }
    ident = names.get(name, "")
    return phrase(ident) if ident else name


def _section_parts(names: str, statement: str, company: str, form_words: str, fact: Fact) -> list[tuple]:
    period = _period_link(period_phrase(fact.period.kind, fact.period.start, fact.period.end or ""), fact)
    if german():
        return [
            ("text", f"Dieser Abschnitt zeigt {names} im "),
            period,
            ("text", f", entnommen aus der {statement} im Bericht ({form_words}) von {company}."),
        ]
    return [
        ("text", f"This section shows {names} from the {statement} in {company}'s {form_words} for "),
        period,
        ("text", "."),
    ]


def build_additions(
    explained,
    *,
    form: str,
    focus: str | None,
    period_end: str | None,
    fiscal_year_end: str,
    company: str,
    filed: str,
    prior_facts: list[Fact] | None = None,
    prior_end: str | None = None,
) -> Additions:
    facts = explained.store.facts()
    prior_facts = prior_facts or []
    if german():
        form_words = "Jahresbericht" if form == "10-K" else "Quartalsbericht" if form == "10-Q" else "Bericht"
    else:
        form_words = "annual report" if form == "10-K" else "quarterly report" if form == "10-Q" else "report"
    before: dict[str, str] = {}
    after: dict[str, str] = {}
    plain_parts: list[str] = []
    statement_of: dict[str, str] = {}
    headings: dict[str, str] = {}
    known: dict[str, str] = {}
    skip: set[str] = set()
    yoy_notes: dict[str, str] = {}
    fold: dict[str, str] = {}
    order = re.findall(r'data-kind="(fact|calc)" data-id="([^"]+)"', explained.html)
    seen_ids: list[tuple[str, str]] = []
    for kind, identifier in order:
        if (kind, identifier) in seen_ids:
            continue
        seen_ids.append((kind, identifier))
    for kind, identifier in seen_ids:
        role, fact, inputs = _role_of(explained, kind, identifier)
        if fact is None:
            continue
        source_name = statement_name(fact) or "the filing"
        statement = _statement(source_name)
        sentence = _statement_sentence(source_name)
        if role == "yoy_change":
            skip.add(identifier)
            note = _explain_block(
                role, fact, company or "this company", sentence, _computed_formula(role, inputs), inputs
            )
            if inputs:
                yoy_notes[inputs[0][1].id] = note
                fold[identifier] = inputs[0][1].id
            plain_parts.append(re.sub(r"<[^>]+>", " ", note))
            continue
        if statement not in known:
            slug = "section-" + re.sub(r"[^a-z]+", "-", statement.lower()).strip("-") or "section"
            control = slug
            number = 2
            while control in headings:
                control = f"{slug}-{number}"
                number += 1
            known[statement] = control
        control = known[statement]
        statement_of[identifier] = control
        if control not in headings:
            names_for: list[str] = []
            for kind2, id2 in seen_ids:
                role2, fact2, _inputs2 = _role_of(explained, kind2, id2)
                if fact2 is None or role2 == "yoy_change":
                    continue
                if _statement(statement_name(fact2) or "the filing") != statement:
                    continue
                label2 = label_for(role2, fact2)
                if label2 not in names_for:
                    names_for.append(label2)
            names = ", ".join(names_for)
            headings[control] = (
                f'<h2 id="{html.escape(control, quote=True)}">{html.escape(statement)}</h2>\n'
                + _parts_html("SECTION", _section_parts(names, sentence, company, form_words, fact))
            )
        measure = "money"
        if role in {"shares", "diluted"} or fact.unit.split()[0] == "shares":
            measure = "shares"
        if fact.unit.split()[0] == "USD/shares" or role == "per_share":
            measure = "per_share"
        if role in {"gross_margin", "operating_margin", "net_margin"}:
            measure = "margin"
        if role == "net_debt":
            measure = "net_debt"
        anchor_fact = fact
        last = year = None
        column_args = dict(
            form=form,
            focus=focus,
            period_end=period_end,
            fiscal_year_end=fiscal_year_end,
            facts=facts,
            prior_facts=prior_facts,
            prior_end=prior_end,
        )
        if role == "yoy_change":
            pass
        elif measure == "margin" and len(inputs) == 2:
            anchor_fact = _shown_calc(explained, identifier, inputs[0][1], "percent", role)
            last, year = _derived_columns("margin", inputs, **column_args)
        elif measure == "net_debt" and len(inputs) == 2:
            anchor_fact = _shown_calc(explained, identifier, inputs[0][1], inputs[0][1].unit, "net_debt")
            last, year = _derived_columns("net_debt", inputs, **column_args)
        else:
            last, year = columns_for(fact, role=role, **column_args)
        formula = _computed_formula(role, inputs)
        face, lines = "", ""
        if role != "yoy_change":
            face, lines = _comparison_block(
                role,
                anchor_fact,
                last,
                year,
                measure if measure != "per_share" else "money",
                form_words,
                filed,
                form=form,
            )
        control = "explain-" + identifier
        explanation = _explain_block(role, anchor_fact, company or "this company", sentence, formula, inputs)
        after[identifier] = (
            f'<div class="face">{face}</div>\n'
            f'<div id="{control}" class="detail" aria-hidden="true"><div class="detail-inner">'
            f"{lines}{explanation}</div></div>\n"
        )
        plain_parts.append(re.sub(r"<[^>]+>", " ", face + lines + explanation))
    for revenue_id, note in yoy_notes.items():
        block = after.get(revenue_id)
        if not block:
            continue
        after[revenue_id] = block.replace("</div></div>\n", note + "</div></div>\n", 1)
    quality = quality_html(facts, form=form, period_end=period_end)
    plain_parts.append(re.sub(r"<[^>]+>", " ", quality))
    return Additions(
        before,
        after,
        quality,
        "\n".join(plain_parts),
        frozenset(skip),
        statement_of,
        headings,
        fold,
    )


def _shown_calc(explained, identifier: str, source: Fact, unit: str, role: str) -> Fact:
    return Fact(
        id=source.id,
        concept=source.concept,
        label=label_for(role, source),
        value=explained.store.get_calc(identifier).value,
        unit=unit,
        period=source.period,
        source=source.source,
        role=role,
        origin=source.origin,
    )


def _derived_columns(kind: str, inputs, **column_args) -> tuple[Cell | None, Cell | None]:
    left, right = inputs[0][1], inputs[1][1]
    left_last, left_year = columns_for(left, role=left.role or "revenue", **column_args)
    right_last, right_year = columns_for(right, role=right.role or "revenue", **column_args)
    return _combine(kind, left_last, right_last), _combine(kind, left_year, right_year)


def _combine(kind: str, left: Cell | None, right: Cell | None) -> Cell | None:
    if left is None or right is None:
        return None
    missing = left.missing_period or right.missing_period or "the prior period"
    if (
        not left.available
        or not right.available
        or left.fact is None
        or right.fact is None
        or left.value is None
        or right.value is None
    ):
        return Cell(False, missing_period=missing, basis=left.basis or right.basis)
    if left.period_end != right.period_end:
        return Cell(False, missing_period=missing)
    if kind == "margin":
        from white_cliff.compare import margin_value

        value = margin_value(left.value, right.value)
        unit = "percent"
        if value is None:
            return Cell(False, missing_period=missing)
    else:
        value = left.value - right.value
        unit = left.unit
    shown = Fact(
        id=left.fact.id,
        concept=left.fact.concept,
        label=left.fact.label,
        value=value,
        unit=unit,
        period=left.fact.period,
        source=left.fact.source,
        role=left.fact.role,
        origin=left.fact.origin,
    )
    return Cell(
        True,
        value=value,
        unit=unit,
        period_end=left.period_end,
        period_start=left.period_start,
        kind=left.kind,
        fact=shown,
    )


def anchor_id(href: str) -> str:
    fragment = urlsplit(href).fragment
    for key in ("fact", "calc"):
        if fragment.startswith(key + "="):
            return fragment.split("=", 1)[1].split("&", 1)[0]
    return ""


def page_terms(text: str) -> str | None:
    """Banned words on a rendered page. The disclaimer and the framing line are allowed."""
    from white_cliff.advice import advice_reason
    from white_cliff.disclaimer import DISCLAIMER
    from white_cliff.lexicon import STRINGS

    without_code = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    without_code = re.sub(r"<script\b[^>]*>.*?</script>", " ", without_code, flags=re.I | re.S)
    visible = html.unescape(re.sub(r"<[^>]+>", " ", without_code))
    german_line = STRINGS["§1.DISCLAIMER"][1]
    for allowed in (DISCLAIMER, FRAME, german_line, phrase("F.checks") if german() else ""):
        if allowed:
            visible = visible.replace(allowed, " ")
    if german():
        hit = german_hit(visible)
        if hit:
            return hit
        advised = advice_reason(visible)
        if advised:
            return advised
    return banned_term(visible)


def banned_term(text: str) -> str | None:
    tokens = re.findall(r"[a-z0-9']+", text.lower())
    token_set = set(tokens)
    for word in _BANNED:
        if word in token_set:
            return word
    folded = " ".join(tokens)
    for phrase in _BANNED_PHRASES:
        if phrase == "per share":
            continue
        if phrase in folded:
            return phrase
    return None


def text_is_clear(text: str, filing_text: str = "") -> str | None:
    """Advice guard plus both banned lists. The one cleared ordinary-causes line is exact."""
    cleaned = text
    for sentence in CAUSES.values():
        cleaned = cleaned.replace(sentence, " ")
    listed = banned_term(cleaned)
    if listed:
        return listed
    return advice_reason(cleaned, filing_text)


# Imported names kept for the item list contract.
_ = ONE_OFF
