"""Choose filing figures and write placeholder sentences. No digits in the prose."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

from white_cliff.facts import Fact, FactStore
from white_cliff.formulas import FormulaError, comparable_yoy, margin, net_debt, yoy_change
from white_cliff.redact import Redaction
from white_cliff.quotes import QuoteError, review_quotes
from white_cliff.review import review_text

_REVENUE = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "SalesAndOtherOperatingRevenue",
)
_DEBT = (
    "LongTermDebt",
    "LongTermDebtAndCapitalLeaseObligations",
    "LongTermDebtNoncurrent",
    "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
)
_REASON = (
    ("bare digit", "bare digit"),
    ("number word", "number word"),
    ("markup", "markup"),
    ("personal", "personal"),
    ("unresolved", "placeholder"),
    ("advice", "advice"),
    ("price", "price metric"),
    ("citation", "citation"),
    ("quote", "quote"),
)


_NAME_EXTRA = set(" ., &'()-/\u2019\u2018$€£¥¢%")
_CURRENCY_CODE = frozenset(
    """
    aed afn all amd ang aoa ars aud awg azn bam bbd bdt bgn bhd bif bmd bnd bob brl bsd
    btn bwp byn bzd cad cdf chf clp cny cop crc cup cve czk djf dkk dop dzd egp ern etb
    eur fjd fkp gbp gel ghs gip gmd gnf gtq gyd hkd hnl htg huf idr ils inr iqd irr isk
    jmd jod jpy kes kgs khr kmf kpw krw kwd kyd kzt lak lbp lkr lrd lsl lyd mad mdl mga
    mkd mmk mnt mop mru mur mvr mwk mxn myr mzn nad ngn nio nok npr nzd omr pab pen pgk
    php pkr pln pyg qar ron rsd rub rwf sar sbd scr sdg sek sgd shp sle sos srd stn syp
    szl thb tjs tmt tnd top try ttd twd tzs uah ugx usd uyu uzs ves vnd vuv wst xaf xcd
    xof xpf yer zar zmw zwl
    """.split()
)
_SCALE_TOKEN = frozenset(
    {
        "thousand",
        "thousands",
        "million",
        "millions",
        "billion",
        "billions",
        "trillion",
        "trillions",
        "bn",
        "mln",
        "mn",
        "mm",
    }
)
_UNIT_TOKEN = frozenset({"share", "shares", "cent", "cents", "pct", "percent"})
_SPELLED_CURRENCY = frozenset(
    form
    for word in (
        "dollar",
        "euro",
        "yen",
        "pound",
        "rupee",
        "peso",
        "franc",
        "yuan",
        "won",
        "real",
        "rand",
        "krona",
        "krone",
        "ruble",
    )
    for form in (word, word + "s")
)
_RECORD = re.compile(r"https://data\.sec\.gov/submissions/CIK[0-9]{10}\.json\Z")


_ENTITY = re.compile(r"&(?:#x[0-9A-Fa-f]+|#\d+|[A-Za-z][A-Za-z0-9]+);")


def registrant_span(name: str, filing_text: str) -> tuple[int, int] | None:
    """Raw offsets of the name after HTML entities in the filing are decoded."""
    shown = acceptable_name(name)
    if shown is None or not filing_text:
        return None
    parts: list[str] = []
    chunks: list[tuple[int, int, int, int]] = []
    decoded_len = 0
    pos = 0

    def add(piece: str, raw_start: int, raw_end: int) -> None:
        nonlocal decoded_len
        if not piece:
            return
        parts.append(piece)
        chunks.append((decoded_len, raw_start, raw_end, len(piece)))
        decoded_len += len(piece)

    for match in _ENTITY.finditer(filing_text):
        if match.start() > pos:
            add(filing_text[pos:match.start()], pos, match.start())
        add(html.unescape(match.group(0)), match.start(), match.end())
        pos = match.end()
    if pos < len(filing_text):
        add(filing_text[pos:], pos, len(filing_text))
    found = "".join(parts).find(shown)
    if found < 0:
        return None
    end_at = found + len(shown)
    raw_start = raw_end = None
    for dec_start, start, end, size in chunks:
        dec_end = dec_start + size
        if raw_start is None and dec_start <= found < dec_end:
            raw_start = start if size != end - start else start + (found - dec_start)
        if dec_start < end_at <= dec_end:
            raw_end = end if size != end - start else start + (end_at - dec_start)
            break
    if raw_start is None or raw_end is None:
        return None
    return raw_start, raw_end


def shown_registrant(
    name: str,
    filing_text: str,
    start: int | None,
    end: int | None,
) -> tuple[str, int, int] | None:
    """The XBRL registrant fact, when its text is a short safe label."""
    shown = acceptable_name(name)
    if shown is None or start is None or end is None:
        return None
    if start < 0 or end > len(filing_text) or start >= end:
        return None
    raw = filing_text[start:end]
    if raw != shown and html.unescape(raw) != shown:
        return None
    return shown, start, end


def acceptable_name(name: str) -> str | None:
    """A filing-supplied label: one short line of letters and light punctuation."""
    if not name or name != name.strip():
        return None
    if len(name) > 100 or any(char in "\n\r" for char in name):
        return None
    for char in name:
        if char.isalpha() or char.isdigit() or char in _NAME_EXTRA:
            continue
        return None
    if _money_digit(name):
        return None
    return name


def _name_tokens(name: str) -> list[str]:
    """Words of a name. Punctuation separates tokens and is not itself a token."""
    tokens = []
    for chunk in re.split(r"[\s,;]+", name):
        token = chunk.strip("\"'`“”‘’()[]{}<>.:!?/\\")
        if token:
            tokens.append(token)
    return tokens


def _token_words(token: str) -> list[str]:
    return re.findall(r"[A-Za-z]+|%", token)


def _currency_token(token: str) -> bool:
    if any(symbol in token for symbol in "$€£¥¢"):
        return True
    for word in _token_words(token):
        if word.isupper() and len(word) == 3 and word.lower() in _CURRENCY_CODE:
            return True
        if word.lower() in _SPELLED_CURRENCY:
            return True
    return False


def _scale_or_unit_token(token: str) -> bool:
    if "%" in token:
        return True
    return any(
        word.lower() in _SCALE_TOKEN or word.lower() in _UNIT_TOKEN for word in _token_words(token)
    )


def _single_scale_suffix(token: str) -> bool:
    return re.search(r"(?i)\d[kmb](?![a-z])", token) is not None


def _counts_toward_distance(token: str) -> bool:
    """A dash or other punctuation-only token does not separate a digit from a unit."""
    return any(char.isalnum() or char in "$€£¥¢%" for char in token)


def _money_digit(name: str) -> bool:
    """A digit fused with, or within three tokens of, a currency, scale, or unit."""
    tokens = [token for token in _name_tokens(name) if _counts_toward_distance(token)]
    for index, token in enumerate(tokens):
        if not any(char.isdigit() for char in token):
            continue
        window = tokens[max(0, index - 3) : index + 4]
        if any(_currency_token(item) or _scale_or_unit_token(item) for item in window):
            return True
        if _single_scale_suffix(token) and any(_currency_token(item) for item in window):
            return True
    return False


def filer_record(cik: str) -> str | None:
    """The filer's EDGAR submissions file, when the CIK is the one the filing states."""
    digits = re.sub(r"\D", "", cik or "")
    if not digits or len(digits) > 10:
        return None
    url = f"https://data.sec.gov/submissions/CIK{digits.zfill(10)}.json"
    if _RECORD.fullmatch(url) is None:
        return None
    return url


@dataclass
class Block:
    text: str
    redaction: Redaction | None = None
    reason: str | None = None
    quotes: tuple = ()
    registrant: tuple[str, str, int, int] | None = None


def _length_between(start: str, end: str) -> int | None:
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None


def _length(fact: Fact) -> int | None:
    if not fact.period.start or not fact.period.end:
        return None
    try:
        return (date.fromisoformat(fact.period.end) - date.fromisoformat(fact.period.start)).days
    except ValueError:
        return None


def _absolute(fact: Fact) -> Decimal:
    return fact.value * (Decimal(10) ** fact.scale)


def _base_unit(fact: Fact) -> str:
    return fact.unit.split(" ", 1)[0]


def _group_agrees(group: list[Fact]) -> bool:
    if len(group) < 2:
        return True
    absolutes = [_absolute(fact) for fact in group]
    known = [fact.decimals for fact in group if fact.decimals is not None]
    if len(known) != len(group):
        return len(set(absolutes)) == 1
    quantum = Decimal(1).scaleb(-min(known))
    rounded = [value.quantize(quantum, rounding=ROUND_HALF_EVEN) for value in absolutes]
    return len(set(rounded)) == 1


def _prefer(facts: list[Fact]) -> Fact | None:
    """Keep one fact when the same entity, period, and unit agree after scale."""
    if not facts:
        return None
    periods = {(fact.period.start, fact.period.end) for fact in facts}
    if len(periods) != 1:
        return None
    groups: dict[tuple[str, str, str, str], list[Fact]] = {}
    for fact in facts:
        key = (fact.entity, fact.period.start or "", fact.period.end or "", _base_unit(fact))
        groups.setdefault(key, []).append(fact)
    kept: list[Fact] = []
    for group in groups.values():
        if _group_agrees(group):
            kept.extend(group)
    visible = [fact for fact in kept if not fact.concealed]
    if not visible:
        return None

    def rank(fact: Fact) -> int:
        if fact.decimals is None:
            return 10**9
        return fact.decimals

    best = max(rank(fact) for fact in visible)
    top = [fact for fact in visible if rank(fact) == best]
    if len({_absolute(fact) for fact in top}) != 1:
        return None
    return top[0]


def _span(fact: Fact) -> str:
    if fact.span_hint:
        return fact.span_hint
    if fact.period.kind == "instant":
        return "period end"
    days = _length(fact)
    if days is not None:
        if 80 <= days <= 100:
            return "quarter"
        if 100 < days < 330:
            return "year to date"
        if 330 <= days <= 380:
            return "fiscal year"
    return "reported period"


def _from_filing(fact: Fact) -> bool:
    return fact.origin in {"xbrl", "ixbrl"}


def _duration(facts: list[Fact], focus: str | None, period_end: str | None) -> Fact | None:
    pool = [
        fact
        for fact in facts
        if _from_filing(fact)
        and fact.period.kind == "duration"
        and fact.period.end == period_end
    ]
    if not pool:
        return None

    def within(fact: Fact, low: int, high: int) -> bool:
        days = _length(fact)
        return days is not None and low <= days <= high

    preferred: list[Fact] = []
    if focus == "FY":
        preferred = [fact for fact in pool if within(fact, 330, 380)]
    elif focus in {"Q1", "Q2", "Q3"}:
        preferred = [fact for fact in pool if within(fact, 80, 100)]
        if not preferred:
            longer = [fact for fact in pool if (_length(fact) or 0) > 100]
            if longer:
                longest = max(_length(fact) or 0 for fact in longer)
                preferred = [fact for fact in longer if _length(fact) == longest]
    else:
        preferred = pool
    return _prefer(preferred or pool)


def _instant(facts: list[Fact], period_end: str | None) -> Fact | None:
    pool = [
        fact
        for fact in facts
        if _from_filing(fact)
        and fact.period.kind == "instant"
        and fact.period.end == period_end
    ]
    return _prefer(pool)


def _by_concept(facts: list[Fact], concept: str) -> list[Fact]:
    return [fact for fact in facts if fact.concept == concept]


def _pick_ordered(
    facts: list[Fact],
    concepts: tuple[str, ...],
    focus: str | None,
    period_end: str | None,
    instant: bool,
) -> Fact | None:
    for concept in concepts:
        subset = _by_concept(facts, concept)
        chosen = _instant(subset, period_end) if instant else _duration(subset, focus, period_end)
        if chosen is not None:
            return chosen
    return None


def _prior(facts: list[Fact], current: Fact) -> Fact | None:
    candidates = [
        fact
        for fact in facts
        if fact.origin == current.origin
        and fact.concept == current.concept
        and fact.unit == current.unit
        and fact.id != current.id
        and comparable_yoy(current.period, fact.period)
    ]
    if not candidates or not current.period.end:
        return None
    closest = min(
        candidates,
        key=lambda fact: abs((_length_between(current.period.end, fact.period.end or current.period.end) or 0) - 365),
    )
    same_end = [fact for fact in candidates if fact.period.end == closest.period.end]
    return _prefer(same_end)


def _lead(role: str, fact: Fact, span: str) -> str:
    if role == "shares" and fact.concept == "WeightedAverageNumberOfSharesOutstandingBasic":
        return f"The basic average share count for the {span} was"
    if role == "shares":
        return "The share count at the period end was"
    if role == "debt":
        return "Debt at the period end was"
    if role == "cash":
        return "Cash at the period end was"
    names = {
        "revenue": "Revenue",
        "gross_profit": "Gross profit",
        "operating_income": "Operating income",
        "net_income": "Net income",
        "operating_cash_flow": "Operating cash flow",
    }
    return f"{names[role]} for the {span} was"


_LONG_MONTHS = (
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


def statement_name(fact: Fact) -> str:
    """The statement this fact was read from, or nothing when that is not known."""
    if fact.origin == "table":
        return {
            "income": "Income statement",
            "balance": "Balance sheet",
            "cashflow": "Cash flows",
        }.get(fact.table_kind, "")
    if fact.source.section in {"Income statement", "Balance sheet", "Cash flows", "Equity"}:
        return fact.source.section
    return ""


def _long_date(iso: str) -> str | None:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso or ""):
        return None
    year, month, day = iso.split("-")
    return f"{_LONG_MONTHS[int(month) - 1]} {int(day)}, {year}"


def _period_phrase(fact: Fact) -> str | None:
    date = _long_date(fact.period.end or "")
    if date is None:
        return None
    if fact.origin == "table" and fact.span_hint == "period end":
        return f"period end {date}"
    header = (fact.header or "").lower()
    if "twelve months" in header:
        return f"twelve months ended {date}"
    if "three month" in header:
        return f"three months ended {date}"
    if "nine months" in header:
        return f"nine months ended {date}"
    if "six months" in header:
        return f"six months ended {date}"
    if "fiscal year" in header:
        return f"fiscal year ended {date}"
    if "year ended" in header:
        return f"year ended {date}"
    span = fact.span_hint or (_span(fact) if fact.origin != "table" else "")
    if span == "fiscal year":
        return f"fiscal year ended {date}"
    if span == "quarter":
        return f"three months ended {date}"
    if span == "year to date":
        return f"year to date ended {date}"
    if span == "period end":
        return f"period end {date}"
    return None


def statement_chip(fact: Fact) -> str | None:
    """Statement and period together, or nothing when either one is unknown."""
    name = statement_name(fact)
    phrase = _period_phrase(fact)
    if not name or not phrase:
        return None
    return f"{name}, {phrase}"


def _fact_sentence(role: str, fact: Fact) -> str:
    section = statement_name(fact) or "Document"
    return f"{_lead(role, fact, _span(fact))} {{fact:{fact.id}}} [section:{section}]."


def _calc_sentence(role: str, fact: Fact, calc) -> str:
    section = statement_name(fact) or "Document"
    span = _span(fact)
    if role == "net_debt":
        opening = "Net debt at the period end was"
    elif role == "yoy_change":
        opening = "The year over year change in revenue was"
    else:
        label = {
            "gross_margin": "The gross margin",
            "operating_margin": "The operating margin",
            "net_margin": "The net margin",
        }[role]
        opening = f"{label} for the {span} was"
    inputs = " and ".join(calc.input_ids)
    return (
        f"{opening} {{calc:{calc.id}}} using formula {calc.name} "
        f"defined as {calc.formula} on inputs {inputs} [section:{section}]."
    )


def _form_words(form: str) -> str:
    return {
        "10-K": "an annual report",
        "10-Q": "a quarterly report",
        "8-K": "an earnings exhibit",
    }.get(form, "a filing")


def _omission(section: str, reason: str) -> Block:
    label = "check"
    for needle, word in _REASON:
        if needle in reason:
            label = word
            break
    return Block(
        text=f"This section was omitted because it failed the {label} check [section:{section}].",
        reason=reason,
    )


def build_blocks(
    *,
    store: FactStore,
    filer: str,
    form: str,
    focus: str | None,
    period_end: str | None,
    price_metric: bool,
    redactions: list[Redaction],
    omissions: list[tuple[int, int, str]],
    filing_text: str,
    filing_url: str,
    filer_start: int | None = None,
    filer_end: int | None = None,
    cik: str = "",
    shares_tagged: bool = False,
) -> list[Block]:
    facts = store.facts()
    chip = shown_registrant(filer, filing_text, filer_start, filer_end)
    record = filer_record(cik)
    if chip is not None:
        name, start, end = chip
        cover = Block(
            text=(
                f"This explanation covers {{registrant}} in {_form_words(form)} "
                "[section:Cover]."
            ),
            registrant=(name, filing_url, start, end),
        )
    elif record is not None:
        cover = Block(
            text=(
                f"This explanation covers {{registrant}} in {_form_words(form)} "
                "[section:Cover]."
            ),
            registrant=("the filer", record, -1, -1),
        )
    else:
        cover = Block(
            text=(
                f"This explanation covers the filer in {_form_words(form)} "
                "[section:Cover]."
            )
        )
    blocks: list[Block] = [cover]
    if filing_url and not filing_url.startswith("https://www.sec.gov/"):
        blocks.append(
            Block(text="This filing was not retrieved from EDGAR [section:Document].")
        )

    chosen: dict[str, Fact] = {}
    plans = (
        ("revenue", _REVENUE, False),
        ("gross_profit", ("GrossProfit",), False),
        ("operating_income", ("OperatingIncomeLoss",), False),
        ("net_income", ("NetIncomeLoss",), False),
        ("operating_cash_flow", ("NetCashProvidedByUsedInOperatingActivities",), False),
        ("debt", _DEBT, True),
        ("cash", ("CashAndCashEquivalentsAtCarryingValue",), True),
    )
    for role, concepts, instant in plans:
        picked = _pick_ordered(facts, concepts, focus, period_end, instant)
        if picked is not None:
            chosen[role] = picked
            blocks.append(Block(text=_fact_sentence(role, picked)))

    share = _instant(
        _by_concept(facts, "CommonStockSharesOutstanding"),
        period_end,
    )
    if share is None:
        share = _duration(
            _by_concept(facts, "WeightedAverageNumberOfSharesOutstandingBasic"),
            focus,
            period_end,
        )
    if share is not None and share.origin != "table":
        chosen["shares"] = share
        blocks.append(Block(text=_fact_sentence("shares", share)))
    elif shares_tagged or any(fact.role == "shares" for fact in facts):
        blocks.append(
            Block(text="The share count is tagged but White Cliff can't use it [section:Equity].")
        )
    else:
        blocks.append(
            Block(text="The filing doesn't tag the share count [section:Equity].")
        )

    def add_margin(name: str, part_role: str) -> None:
        part = chosen.get(part_role)
        whole = chosen.get("revenue")
        if part is None or whole is None or part.origin != whole.origin:
            return
        try:
            calc = margin(part, whole, name=name)
        except FormulaError:
            return
        store.add_calc(calc)
        blocks.append(Block(text=_calc_sentence(name, part, calc)))

    add_margin("gross_margin", "gross_profit")
    add_margin("operating_margin", "operating_income")
    add_margin("net_margin", "net_income")

    revenue = chosen.get("revenue")
    if revenue is not None and _from_filing(revenue):
        prior = _prior(facts, revenue)
        if prior is not None:
            try:
                calc = yoy_change(revenue, prior)
            except FormulaError:
                calc = None
            if calc is not None:
                store.add_calc(calc)
                blocks.append(Block(text=_calc_sentence("yoy_change", revenue, calc)))

    debt = chosen.get("debt")
    cash = chosen.get("cash")
    if debt is not None and cash is not None and debt.origin == cash.origin:
        try:
            calc = net_debt(debt, cash)
        except FormulaError:
            calc = None
        if calc is not None:
            store.add_calc(calc)
            blocks.append(Block(text=_calc_sentence("net_debt", debt, calc)))

    if price_metric:
        blocks.append(
            Block(text="A price metric quoted in the filing was omitted [section:Document].")
        )
    for marker_start, _marker_end, marker in omissions:
        del marker_start
        blocks.append(
            Block(
                text=(
                    f"A confidential omission is shown as filed: {marker} "
                    "[section:Document]."
                )
            )
        )
    for redaction in redactions:
        blocks.append(
            Block(
                text=(
                    "A personal data span was omitted from the explanation "
                    "{redaction} [section:Document]."
                ),
                redaction=redaction,
            )
        )
    checked: list[Block] = []
    for block in blocks:
        if block.reason:
            checked.append(block)
            continue
        reason = review_text(block.text, store, filing_text, filing_url)
        if reason:
            checked.append(_omission("Document", reason))
            continue
        try:
            quotes = tuple(review_quotes(block.text, filing_text, filing_url))
        except QuoteError as exc:
            checked.append(_omission("Document", str(exc)))
            continue
        checked.append(
            Block(
                text=block.text,
                redaction=block.redaction,
                quotes=quotes,
                reason=block.reason,
                registrant=block.registrant,
            )
        )
    return checked
