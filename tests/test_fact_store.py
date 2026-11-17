from decimal import Decimal

import pytest

from white_cliff.facts import FactStore, format_decimal
from tests.support import make_fact


def test_fact_requires_a_source_pointer():
    store = FactStore()
    fact = make_fact("10")
    blank = fact.source
    broken = type(fact)(
        **{**fact.__dict__, "source": type(blank)(document="", section="", url="", sha256="")}
    )
    with pytest.raises(ValueError):
        store.add(broken)


def test_fact_value_is_decimal_and_id_is_stable():
    store = FactStore()
    fact = make_fact("10")
    store.add(fact)
    assert isinstance(store.get(fact.id).value, Decimal)
    assert store.get(fact.id).value == Decimal("10")
    store.add(fact)
    assert len(store.facts()) == 1


def test_conflicting_id_is_rejected():
    store = FactStore()
    first = make_fact("10", fact_id="factabcdefghijklmnop")
    second = make_fact("11", fact_id="factabcdefghijklmnop")
    store.add(first)
    with pytest.raises(ValueError):
        store.add(second)


def test_format_decimal_round_trips():
    value = Decimal("233602000000") / Decimal("478834000000")
    assert Decimal(format_decimal(value)) == value
