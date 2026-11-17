"""Named, deterministic formulas. The library refuses bad units, periods, and prices."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from white_cliff.facts import Calculation, Fact, Period, format_decimal
from white_cliff.ids import letter_id
from white_cliff.prices import is_price_text

REFUSED_FORMULAS = frozenset(
    {
        "pe",
        "pe_ratio",
        "price_to_earnings",
        "ev_ebitda",
        "ev_to_ebitda",
        "enterprise_value",
        "market_cap",
        "market_capitalization",
        "dividend_yield",
        "pb",
        "p_b",
        "price_to_book",
        "price_to_sales",
        "ev_sales",
        "peg",
        "peg_ratio",
    }
)


class FormulaError(Exception):
    pass


class PriceInputError(FormulaError):
    pass


def _norm_unit(unit: str) -> str:
    return re.sub(r"\s+", " ", unit.strip().lower())


def _reject_price(fact: Fact) -> None:
    if fact.kind == "price" or is_price_text(fact.concept) or is_price_text(fact.label):
        raise PriceInputError("price input")


def same_period(left: Period, right: Period) -> bool:
    """Two periods match only when their dates, or their span and end, agree."""
    if left.kind != right.kind:
        return False
    if left.kind == "instant":
        return bool(left.end and right.end and left.end == right.end)
    if left.start and right.start and left.end and right.end:
        if left.span and right.span and left.span != right.span:
            return False
        return left.start == right.start and left.end == right.end
    if not left.span or not right.span or not left.end or not right.end:
        return False
    return left.span == right.span and left.end == right.end


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def comparable_yoy(current: Period, prior: Period) -> bool:
    if current.kind != "duration" or prior.kind != "duration":
        return False
    if not (current.start and current.end and prior.start and prior.end):
        return False
    current_len = _days(current.start, current.end)
    prior_len = _days(prior.start, prior.end)
    if abs(current_len - prior_len) > 7:
        return False
    gap = _days(prior.end, current.end)
    return 350 <= gap <= 380


def _build(
    name: str,
    formula: str,
    value: Decimal,
    unit: str,
    period: Period,
    inputs: tuple[str, ...],
) -> Calculation:
    seed = "|".join((name, formula, format_decimal(value), unit, *inputs))
    return Calculation(
        id=letter_id("calc", seed),
        name=name,
        formula=formula,
        value=value,
        unit=unit,
        period=period,
        input_ids=inputs,
    )


def compute(name: str, inputs: list[Fact]) -> Calculation:
    """Dispatch a formula by name. Price-metric names are refused."""
    key = name.strip().lower().replace("-", "_").replace(" ", "_").replace("/", "_")
    if key in REFUSED_FORMULAS:
        raise PriceInputError(name)
    if key == "yoy_change":
        if len(inputs) != 2:
            raise FormulaError("yoy_change needs two inputs")
        return yoy_change(inputs[0], inputs[1])
    if key == "margin":
        if len(inputs) != 2:
            raise FormulaError("margin needs two inputs")
        return margin(inputs[0], inputs[1])
    if key == "net_debt":
        if len(inputs) != 2:
            raise FormulaError("net_debt needs two inputs")
        return net_debt(inputs[0], inputs[1])
    raise FormulaError(f"unknown formula {name}")


def _percent(value: Decimal) -> Decimal:
    """One decimal percent, half up, so the shown figure is not a long ratio."""
    return (value * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def yoy_change(current: Fact, prior: Fact) -> Calculation:
    _reject_price(current)
    _reject_price(prior)
    if _norm_unit(current.unit) != _norm_unit(prior.unit):
        raise FormulaError("mismatched units")
    if not comparable_yoy(current.period, prior.period):
        raise FormulaError("mismatched periods")
    if prior.value == 0:
        raise FormulaError("division by zero")
    value = _percent((current.value - prior.value) / abs(prior.value))
    return _build(
        "yoy_change",
        "(current - prior) / abs(prior)",
        value,
        "percent",
        current.period,
        (current.id, prior.id),
    )


def margin(numerator: Fact, denominator: Fact, name: str = "margin") -> Calculation:
    _reject_price(numerator)
    _reject_price(denominator)
    if name in REFUSED_FORMULAS:
        raise PriceInputError(name)
    if _norm_unit(numerator.unit) != _norm_unit(denominator.unit):
        raise FormulaError("mismatched units")
    if not same_period(numerator.period, denominator.period):
        raise FormulaError("mismatched periods")
    if denominator.value == 0:
        raise FormulaError("division by zero")
    value = _percent(numerator.value / denominator.value)
    return _build(
        name,
        "(numerator / denominator)",
        value,
        "percent",
        numerator.period,
        (numerator.id, denominator.id),
    )


def net_debt(debt: Fact, cash: Fact) -> Calculation:
    _reject_price(debt)
    _reject_price(cash)
    if _norm_unit(debt.unit) != _norm_unit(cash.unit):
        raise FormulaError("mismatched units")
    if not same_period(debt.period, cash.period):
        raise FormulaError("mismatched periods")
    value = debt.value - cash.value
    return _build(
        "net_debt",
        "(debt - cash)",
        value,
        debt.unit,
        debt.period,
        (debt.id, cash.id),
    )
