from decimal import Decimal

import pytest

from white_cliff.facts import FactStore, format_decimal
from white_cliff.formulas import FormulaError, PriceInputError, compute, margin, net_debt, yoy_change
from tests.support import make_fact


def test_yoy_change_records_formula_and_inputs():
    current = make_fact("110")
    prior = make_fact("100", start="2023-01-01", end="2023-12-31")
    result = yoy_change(current, prior)
    assert result.name == "yoy_change"
    assert result.formula == "(current - prior) / abs(prior)"
    assert result.input_ids == (current.id, prior.id)
    assert result.value == Decimal("0.1")
    assert result.unit == "ratio"
    assert Decimal(format_decimal(result.value)) == result.value


def test_margin_and_net_debt():
    profit = make_fact("25", concept="GrossProfit", role="gross_profit")
    revenue = make_fact("100")
    gross = margin(profit, revenue, name="gross_margin")
    assert gross.value == Decimal("0.25")
    assert gross.formula == "(numerator / denominator)"
    debt = make_fact("40", concept="LongTermDebt", role="debt", kind="instant", start=None, end="2024-12-31")
    cash = make_fact("15", concept="Cash", role="cash", kind="instant", start=None, end="2024-12-31")
    net = net_debt(debt, cash)
    assert net.value == Decimal("25")
    assert net.formula == "(debt - cash)"
    assert net.input_ids == (debt.id, cash.id)


def test_mismatched_units_and_periods_are_refused():
    usd = make_fact("10")
    shares = make_fact("10", unit="shares")
    with pytest.raises(FormulaError):
        yoy_change(usd, shares)
    other = make_fact("10", end="2024-06-30", start="2024-01-01")
    with pytest.raises(FormulaError):
        margin(usd, other)


def test_price_input_and_price_metric_names_are_refused():
    price = make_fact("20", concept="SharePrice", fact_kind="price")
    other = make_fact("10")
    with pytest.raises(PriceInputError):
        yoy_change(price, other)
    with pytest.raises(PriceInputError):
        compute("pe_ratio", [other, price])
    with pytest.raises(PriceInputError):
        compute("market_cap", [other])
    with pytest.raises(PriceInputError):
        compute("dividend_yield", [other])
    store = FactStore()
    store.add(other)
    assert store.has_fact(other.id)
