from pathlib import Path

from white_cliff.formulas import PriceInputError, compute
from white_cliff.pipeline import explain_filing, load_directory
from tests.support import make_fact

ROOT = Path(__file__).resolve().parents[1]


def test_fixture_filing_quotes_pe_and_market_cap_and_neither_is_explained():
    filing = load_directory(ROOT / "tests" / "fixtures" / "price_metric")
    explained = explain_filing(filing)
    rendered = explained.markdown + explained.html
    assert "28.4" not in rendered
    assert "2500000" not in rendered
    assert "2,500,000" not in rendered
    assert "price metric" in explained.markdown
    assert "5000" in explained.markdown


def test_formula_library_refuses_price_metrics():
    fact = make_fact("10")
    for name in ("pe", "ev_ebitda", "market_cap", "dividend_yield", "price_to_book"):
        try:
            compute(name, [fact])
        except PriceInputError:
            continue
        raise AssertionError(name)
