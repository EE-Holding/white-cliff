"""Choose filing figures and write placeholder sentences. No digits in the prose."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from white_cliff.facts import Fact, FactStore
from white_cliff.formulas import FormulaError, comparable_yoy, margin, net_debt, yoy_change
from white_cliff.redact import Redaction
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
_SECTION = {
    "revenue": "Income statement",
    "gross_profit": "Income statement",
    "operating_income": "Income statement",
    "net_income": "Income statement",
    "gross_margin": "Income statement",
    "operating_margin": "Income statement",
    "net_margin": "Income statement",
    "yoy_change": "Income statement",
    "operating_cash_flow": "Cash flows",
    "debt": "Balance sheet",
    "cash": "Balance sheet",
    "net_debt": "Balance sheet",
    "shares": "Equity",
}
_REASON = (
    ("bare digit", "bare digit"),
    ("unresolved", "placeholder"),
    ("advice", "advice"),
    ("price", "price metric"),
    ("citation", "citation"),
    ("quote", "quote"),
)


@dataclass
class Block:
    text: str
    redaction: Redaction | None = None
    reason: str | None = None


def _length(fact: Fact) -> int | None:
    if fact.period.start and fact.period.end:
        return (date.fromisoformat(fact.period.end) - date.fromisoformat(fact.period.start)).days
    return None


def _prefer(facts: list[Fact]) -> Fact | None:
    if not facts:
        return None

    def rank(fact: Fact) -> int:
        if fact.decimals is None:
            return 10**9
        return fact.decimals

    best = max(rank(fact) for fact in facts)
    top = [fact for fact in facts if rank(fact) == best]
    if len({fact.value for fact in top}) != 1:
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


def _duration(facts: list[Fact], focus: str | None, period_end: str | None) -> Fact | None:
    pool = [
        fact
        for fact in facts
        if fact.origin == "xbrl"
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
        if fact.origin == "xbrl"
        and fact.period.kind == "instant"
        and fact.period.end == period_end
    ]
    return _prefer(pool)


def _by_concept(facts: list[Fact], concept: str) -> list[Fact]:
    return [fact for fact in facts if fact.concept == concept]


def _table(facts: list[Fact], role: str, kinds: set[str]) -> Fact | None:
    pool = [
        fact
        for fact in facts
        if fact.origin == "table" and fact.role == role and fact.table_kind in kinds
    ]
    if not pool:
        pool = [fact for fact in facts if fact.origin == "table" and fact.role == role]
    return _prefer(pool)


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
        if fact.origin == "xbrl"
        and fact.concept == current.concept
        and fact.unit == current.unit
        and fact.id != current.id
        and comparable_yoy(current.period, fact.period)
    ]
    if not candidates or not current.period.end:
        return None
    closest = min(
        candidates,
        key=lambda fact: abs(
            (date.fromisoformat(current.period.end) - date.fromisoformat(fact.period.end or current.period.end)).days
            - 365
        ),
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


def _fact_sentence(role: str, fact: Fact) -> str:
    section = _SECTION[role]
    return f"{_lead(role, fact, _span(fact))} {{fact:{fact.id}}} [section:{section}]."


def _calc_sentence(role: str, fact: Fact, calc) -> str:
    section = _SECTION[role]
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


def _safe_name(name: str) -> str:
    if not name or any(char.isdigit() for char in name):
        return "the filer"
    # A period inside a name, as in "Inc.", would split the sentence.
    return name.replace(".", "").strip()


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
    model_text: str | None = None,
) -> list[Block]:
    facts = store.facts()
    blocks: list[Block] = [
        Block(
            text=(
                f"This explanation covers {_safe_name(filer)} in {_form_words(form)} "
                "[section:Cover]."
            )
        )
    ]
    if model_text is not None:
        reason = review_text(model_text, store, filing_text, filing_url)
        if reason:
            blocks.append(_omission("Income statement", reason))
        else:
            blocks.append(Block(text=model_text))

    chosen: dict[str, Fact] = {}
    table_kinds = {
        "revenue": {"income"},
        "gross_profit": {"income"},
        "operating_income": {"income"},
        "net_income": {"income"},
        "operating_cash_flow": {"cashflow"},
        "debt": {"balance"},
        "cash": {"balance"},
        "shares": {"balance", "income", "other"},
    }
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
        if picked is None:
            picked = _table(facts, role, table_kinds[role])
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
    if share is None:
        share = _table(facts, "shares", table_kinds["shares"])
    if share is not None:
        chosen["shares"] = share
        blocks.append(Block(text=_fact_sentence("shares", share)))

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
    if revenue is not None and revenue.origin == "xbrl":
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
        else:
            checked.append(block)
    return checked
