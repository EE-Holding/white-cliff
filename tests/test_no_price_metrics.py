from pathlib import Path

from white_cliff.formulas import PriceInputError, compute
from white_cliff.prices import is_price_text
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


PRICE_PHRASES = (
    "twenty times earnings",
    "price-earnings ratio",
    "price earnings multiple",
    "Market capitalisation",
    "earnings yield",
    "EV to EBITDA",
    "PE multiple",
    "The stock price is high",
    "share price closed higher",
    "share-price",
    "stock-price",
    "market-cap",
    "marketcap",
    "dividend-yield",
    "m\u0430rket cap",
    "market value of the equity",
    "price of the shares",
    "earnings multiple",
    "multiple of earnings",
    "valuation multiple",
    "P E ratio",
    "The PEG is elevated",
    "priced at a premium",
    "valued at a premium",
    "trade for a premium",
    "price to free cash flow",
    "EV/EBIT",
    "EV to revenue",
    "The KGV is high",
    "Marktkapitalisierung",
    "PER",
    "capitalización bursátil",
    "市盈率",
)


def test_price_metrics_in_words_are_refused():
    for phrase in PRICE_PHRASES:
        assert is_price_text(phrase), phrase
    assert is_price_text("Earnings per share were described in the filing.") is False
    assert is_price_text("EARNINGS PER SHARE") is False


def test_formula_library_refuses_price_metrics():
    fact = make_fact("10")
    for name in ("pe", "ev_ebitda", "market_cap", "dividend_yield", "price_to_book"):
        try:
            compute(name, [fact])
        except PriceInputError:
            continue
        raise AssertionError(name)
