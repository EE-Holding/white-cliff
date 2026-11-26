"""Prior-quarter and prior-year values for the calm-page figures.

Math follows the CTO comparison rules. A missing or mismatched input is never
treated as zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation

from white_cliff.explain import _from_filing, _length, _prefer, _prior, _rounding_quantum
from white_cliff.facts import Fact
from white_cliff.formulas import comparable_yoy
from white_cliff.thresholds import (
    DURATION_DAYS,
    PRIOR_FILING_MAX,
    PRIOR_FILING_MIN,
    QUARTER_MAX,
    QUARTER_MIN,
    YEAR_MAX,
    YEAR_MIN,
    YOY_GAP_MAX,
    YOY_GAP_MIN,
)

_INCOME = ("revenue", "gross_profit", "operating_income", "net_income")
_COVER = "EntityCommonStockSharesOutstanding"


@dataclass(frozen=True)
class PriorCandidate:
    form: str
    period_end: str
    fiscal_year_end: str
    cik: str
    accession: str = ""


@dataclass(frozen=True)
class Cell:
    """One column. available is false when the figure cannot be matched."""

    available: bool
    value: Decimal | None = None
    unit: str = ""
    period_end: str = ""
    period_start: str | None = None
    kind: str = ""
    fact: Fact | None = None
    revised_from: Fact | None = None
    missing_period: str = ""
    basis: str = ""


@dataclass(frozen=True)
class FigureComparison:
    role: str
    anchor_id: str
    anchor_kind: str
    label: str
    statement: str
    measure: str
    current: Cell
    last_quarter: Cell | None
    prior_year: Cell | None
    inputs: tuple[tuple[str, Cell], ...] = ()


def day_gap(earlier: str, later: str) -> int | None:
    try:
        return (date.fromisoformat(later) - date.fromisoformat(earlier)).days
    except ValueError:
        return None


def month_day(value: str) -> str:
    text = (value or "").strip()
    if len(text) >= 5 and text[-6:-5] == "-" and text[-3:-2] == "-":
        return text[-5:]
    if len(text) == 4 and text.isdigit():
        return f"{text[:2]}-{text[2:]}"
    return ""


def same_fiscal_year_end(left: str, right: str) -> bool:
    one, two = month_day(left), month_day(right)
    return bool(one) and one == two


def percent_change(current: Decimal, prior: Decimal) -> Decimal | None:
    """One decimal, half up. None unless the prior is positive and the current is not negative."""
    if not (prior > 0 and current >= 0):
        return None
    return ((current - prior) / prior * Decimal(100)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )


def choose_prior_10q(
    current_end: str,
    current_fy: str,
    current_cik: str,
    candidates: list[PriorCandidate],
) -> PriorCandidate | None:
    """The one prior 10-Q in the window with the same fiscal year end, or none."""
    matched: list[PriorCandidate] = []
    for item in candidates:
        if item.cik != current_cik or item.form != "10-Q":
            continue
        if not same_fiscal_year_end(item.fiscal_year_end, current_fy):
            continue
        gap = day_gap(item.period_end, current_end)
        if gap is None or gap < PRIOR_FILING_MIN or gap > PRIOR_FILING_MAX:
            continue
        matched.append(item)
    if len(matched) != 1:
        return None
    return matched[0]


def _base(unit: str) -> str:
    return unit.split(" ", 1)[0]


def _usd(fact: Fact) -> bool:
    return _base(fact.unit) in {"USD", "USD/shares"}


def _clean(facts: list[Fact], concept: str) -> list[Fact]:
    return [
        fact
        for fact in facts
        if fact.concept == concept and _from_filing(fact) and not fact.concealed
    ]


def _band(facts: list[Fact], concept: str, end: str, low: int, high: int, unit: str) -> Fact | None:
    pool = []
    for fact in _clean(facts, concept):
        if fact.period.kind != "duration" or fact.period.end != end or fact.unit != unit:
            continue
        days = _length(fact)
        if days is None or days < low or days > high:
            continue
        pool.append(fact)
    return _prefer(pool)


def _at_instant(facts: list[Fact], concept: str, end: str, unit: str) -> Fact | None:
    pool = [
        fact
        for fact in _clean(facts, concept)
        if fact.period.kind == "instant" and fact.period.end == end and fact.unit == unit
    ]
    return _prefer(pool)


def _cell(fact: Fact | None, *, missing: str = "", basis: str = "") -> Cell:
    if fact is None:
        return Cell(False, missing_period=missing, basis=basis)
    return Cell(
        True,
        value=fact.value,
        unit=fact.unit,
        period_end=fact.period.end or "",
        period_start=fact.period.start,
        kind=fact.period.kind,
        fact=fact,
    )


def _revised(shown: Fact, earlier: Fact) -> bool:
    if shown.value == earlier.value and shown.unit == earlier.unit:
        return False
    if _base(shown.unit) != _base(earlier.unit):
        return False
    known = [item for item in (shown.decimals, earlier.decimals) if item is not None]
    if not known:
        return shown.value != earlier.value
    quantum = _rounding_quantum(min(known))
    if quantum is None:
        return shown.value != earlier.value
    try:
        left = shown.value.quantize(quantum, rounding=ROUND_HALF_EVEN)
        right = earlier.value.quantize(quantum, rounding=ROUND_HALF_EVEN)
    except InvalidOperation:
        return shown.value != earlier.value
    return left != right


def _duration_cell(
    facts: list[Fact],
    concept: str,
    end: str,
    low: int,
    high: int,
    unit: str,
    *,
    missing: str,
) -> Cell:
    return _cell(_band(facts, concept, end, low, high, unit), missing=missing)


def _yoy_duration(facts: list[Fact], current: Fact, *, missing: str) -> Cell:
    prior = _prior(facts, current)
    if prior is not None:
        if _base(prior.unit) != _base(current.unit):
            return Cell(False, missing_period=missing, basis="currency")
        return _cell(prior)
    for fact in _clean(facts, current.concept):
        if fact.period.kind != "duration" or not fact.period.end or not current.period.end:
            continue
        gap = day_gap(fact.period.end, current.period.end)
        if gap is None or gap < YOY_GAP_MIN or gap > YOY_GAP_MAX:
            continue
        if _base(fact.unit) != _base(current.unit):
            return Cell(False, missing_period=missing, basis="currency")
        left, right = _length(current), _length(fact)
        if left is None or right is None or abs(left - right) > DURATION_DAYS:
            return Cell(False, missing_period=missing, basis="length")
    return Cell(False, missing_period=missing)


def _yoy_instant(facts: list[Fact], current: Fact, *, missing: str) -> Cell:
    if current.period.kind != "instant" or not current.period.end:
        return Cell(False, missing_period=missing)
    chosen: list[Fact] = []
    length_mismatch = False
    currency_mismatch = False
    for fact in _clean(facts, current.concept):
        if fact.period.kind != "instant" or not fact.period.end or fact.id == current.id:
            continue
        gap = day_gap(fact.period.end, current.period.end)
        if gap is None or gap < YOY_GAP_MIN or gap > YOY_GAP_MAX:
            continue
        if fact.unit != current.unit:
            if _base(fact.unit) != _base(current.unit):
                currency_mismatch = True
            else:
                length_mismatch = True
            continue
        chosen.append(fact)
    if chosen:
        latest = max(chosen, key=lambda fact: fact.period.end or "")
        return _cell(_prefer([fact for fact in chosen if fact.period.end == latest.period.end]))
    if currency_mismatch:
        return Cell(False, missing_period=missing, basis="currency")
    if length_mismatch:
        return Cell(False, missing_period=missing, basis="length")
    return Cell(False, missing_period=missing)


def _fy_instant(facts: list[Fact], current: Fact, fiscal_year_end: str, period_end: str) -> Cell:
    stamp = month_day(fiscal_year_end)
    missing = "the prior fiscal year end"
    if not stamp or not period_end:
        return Cell(False, missing_period=missing)
    chosen = []
    for fact in _clean(facts, current.concept):
        if fact.period.kind != "instant" or not fact.period.end or fact.unit != current.unit:
            continue
        if fact.period.end >= period_end:
            continue
        if month_day(fact.period.end) != stamp:
            continue
        chosen.append(fact)
    if not chosen:
        return Cell(False, missing_period=missing)
    latest = max(fact.period.end or "" for fact in chosen)
    return _cell(_prefer([fact for fact in chosen if fact.period.end == latest]))


def _structural_quarter() -> Cell:
    """A last-quarter column this form does not carry. Nothing is derived to fill it."""
    return Cell(False, missing_period="the prior quarter", basis="structural")


def _cover(fact: Fact, period_end: str | None) -> bool:
    if fact.concept != _COVER:
        return False
    if fact.period.kind != "instant" or not fact.period.end or not period_end:
        return True
    return fact.period.end != period_end


def _last_duration(
    current: Fact,
    facts: list[Fact],
    prior_facts: list[Fact],
    prior_end: str | None,
    *,
    low: int,
    high: int,
) -> Cell:
    missing = "the prior quarter"
    if not prior_end:
        return Cell(False, missing_period=missing)
    own = _band(facts, current.concept, prior_end, low, high, current.unit)
    earlier = _band(prior_facts, current.concept, prior_end, low, high, current.unit)
    if own is None and earlier is None:
        other = [
            fact
            for fact in _clean(prior_facts, current.concept)
            if fact.period.end == prior_end and fact.period.kind == "duration"
        ]
        if any(_base(fact.unit) != _base(current.unit) for fact in other):
            return Cell(False, missing_period=missing, basis="currency")
        if any(
            _length(fact) is not None and abs((_length(fact) or 0) - (_length(current) or 0)) > DURATION_DAYS
            for fact in other
        ):
            return Cell(False, missing_period=missing, basis="length")
        return Cell(False, missing_period=missing)
    shown = own or earlier
    cell = _cell(shown)
    if own is not None and earlier is not None and _revised(own, earlier):
        cell = Cell(
            True,
            value=own.value,
            unit=own.unit,
            period_end=own.period.end or "",
            period_start=own.period.start,
            kind=own.period.kind,
            fact=own,
            revised_from=earlier,
        )
    return cell


def _last_instant(current: Fact, facts: list[Fact], prior_facts: list[Fact], prior_end: str | None) -> Cell:
    missing = "the prior quarter"
    if not prior_end:
        return Cell(False, missing_period=missing)
    own = _at_instant(facts, current.concept, prior_end, current.unit)
    earlier = _at_instant(prior_facts, current.concept, prior_end, current.unit)
    if own is None and earlier is None:
        return Cell(False, missing_period=missing)
    shown = own or earlier
    if own is not None and earlier is not None and _revised(own, earlier):
        return Cell(
            True,
            value=own.value,
            unit=own.unit,
            period_end=own.period.end or "",
            period_start=own.period.start,
            kind="instant",
            fact=own,
            revised_from=earlier,
        )
    return _cell(shown)


def columns_for(
    fact: Fact,
    *,
    role: str,
    form: str,
    focus: str | None,
    period_end: str | None,
    fiscal_year_end: str,
    facts: list[Fact],
    prior_facts: list[Fact] | None = None,
    prior_end: str | None = None,
) -> tuple[Cell | None, Cell | None]:
    """Last quarter and the same period a year earlier. None means the column does not apply."""
    prior_facts = prior_facts or []
    if _cover(fact, period_end):
        missing = Cell(False, missing_period="the prior period")
        return missing, None
    year_missing = "the same period a year earlier"
    quarter_form = form == "10-Q"
    annual = form == "10-K" or focus == "FY"
    q1 = quarter_form and focus == "Q1"
    later_quarter = quarter_form and focus in {"Q2", "Q3"}
    if fact.period.kind == "instant":
        year = _yoy_instant(facts, fact, missing=year_missing)
        if annual or not quarter_form:
            return _structural_quarter(), year
        if q1:
            return _fy_instant(facts, fact, fiscal_year_end, period_end or ""), year
        if later_quarter or quarter_form:
            return _last_instant(fact, facts, prior_facts, prior_end), year
        return _structural_quarter(), year
    if role == "operating_cash_flow" and (later_quarter or (quarter_form and focus not in {"Q1"})):
        return _structural_quarter(), _yoy_duration(facts, fact, missing=year_missing)
    if annual or q1 or role == "operating_cash_flow":
        return _structural_quarter(), _yoy_duration(facts, fact, missing=year_missing)
    low, high = QUARTER_MIN, QUARTER_MAX
    days = _length(fact)
    if days is not None and (days < low or days > high):
        low, high = max(0, days - DURATION_DAYS), days + DURATION_DAYS
    return (
        _last_duration(fact, facts, prior_facts, prior_end, low=low, high=high),
        _yoy_duration(facts, fact, missing=year_missing),
    )


def comparable_duration(left: Fact, right: Fact) -> bool:
    return comparable_yoy(left.period, right.period) and left.unit == right.unit and left.concept == right.concept


def margin_value(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    return numerator / denominator * Decimal(100)


def points_change(current: Decimal, prior: Decimal) -> Decimal:
    return (current - prior).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def income_roles() -> tuple[str, ...]:
    return _INCOME


def year_band() -> tuple[int, int]:
    return YEAR_MIN, YEAR_MAX


def quarter_band() -> tuple[int, int]:
    return QUARTER_MIN, QUARTER_MAX
