"""Each figure is named for the concept the page actually shows."""

import json
from pathlib import Path

import pytest

from white_cliff.explain import _lead
from white_cliff.pipeline import explain_filing, load_directory
from tests.support import MINI_XML, make_fact, write_filing

ROOT = Path(__file__).resolve().parents[1]
PINNED = ROOT / "pinned"
DOCS = ROOT / "docs"

DEBT_LABELS = {
    "LongTermDebt": "Long-term debt, including current maturities",
    "LongTermDebtNoncurrent": "Long-term debt, excluding current portion",
    "LongTermDebtAndCapitalLeaseObligations": (
        "Long-term debt and finance lease obligations, excluding current portion"
    ),
    "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities": (
        "Long-term debt and finance lease obligations, including current maturities"
    ),
}
CASH_LABEL = "Cash and cash equivalents"
NET_INCOME_LABEL = "Net income attributable to the company"
SHARES_LABEL = "Common shares outstanding at the period end"
CONTRACT_REVENUE = "Revenue from contracts with customers"
CONTRACT_REVENUE_TERM = "revenue from contracts with customers"


@pytest.fixture(scope="module")
def pages():
    manifest = json.loads((PINNED / "manifest.json").read_text(encoding="utf-8"))
    loaded = []
    for entry in manifest["filings"]:
        accession = entry["accession"]
        explained = explain_filing(load_directory(PINNED / "filings" / accession))
        page = (DOCS / f"{accession}.html").read_text(encoding="utf-8")
        loaded.append((explained, page))
    return loaded


def _cited(explained):
    text = explained.markdown
    return [fact for fact in explained.store.facts() if fact.id in text]


def _surfaces(explained, page):
    return (explained.markdown, explained.html, page)


def _explain_xml(tmp_path, xml):
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/mini.xml"
    directory = write_filing(tmp_path / "mini", "mini.xml", xml, url)
    return explain_filing(load_directory(directory))


def _assert_debt(pages, concept):
    label = DEBT_LABELS[concept]
    phrase = f"{label} minus cash and cash equivalents"
    hits = 0
    nets = 0
    for explained, page in pages:
        debt = next((fact for fact in _cited(explained) if fact.role == "debt"), None)
        if debt is None or debt.concept != concept:
            continue
        hits += 1
        shown = any(calc.name == "net_debt" for calc in explained.store.calcs())
        nets += shown
        for surface in _surfaces(explained, page):
            assert f"{label} was" in surface
            assert "Net debt" not in surface
            if shown:
                assert f"{phrase} was" in surface
                assert f"defined as {phrase}" in surface
            else:
                assert phrase not in surface
            for other, other_label in DEBT_LABELS.items():
                if other != concept:
                    assert other_label not in surface
    assert hits >= 1
    assert nets >= 1


def test_long_term_debt_including_current_maturities(pages):
    _assert_debt(pages, "LongTermDebt")


def test_long_term_debt_excluding_current_portion(pages):
    _assert_debt(pages, "LongTermDebtNoncurrent")


def test_long_term_debt_and_finance_lease_obligations_excluding_current_portion(pages):
    _assert_debt(pages, "LongTermDebtAndCapitalLeaseObligations")


def test_long_term_debt_and_finance_lease_obligations_including_current_maturities(tmp_path):
    concept = "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"
    label = DEBT_LABELS[concept]
    phrase = f"{label} minus cash and cash equivalents"
    explained = _explain_xml(tmp_path, MINI_XML.replace("LongTermDebt", concept))
    for surface in (explained.markdown, explained.html):
        assert f"{label} was" in surface
        assert f"{phrase} was" in surface
        assert f"defined as {phrase}" in surface
        assert "Net debt" not in surface


def test_cash_and_cash_equivalents(pages, tmp_path):
    hits = 0
    for explained, page in pages:
        cash = next((fact for fact in _cited(explained) if fact.role == "cash"), None)
        if cash is None:
            continue
        assert cash.concept == "CashAndCashEquivalentsAtCarryingValue"
        hits += 1
        for surface in _surfaces(explained, page):
            assert f"{CASH_LABEL} was" in surface
            assert "Cash at the period end" not in surface
    assert hits >= 1
    withheld = _explain_xml(
        tmp_path,
        MINI_XML.replace("CashAndCashEquivalentsAtCarryingValue", "RestrictedCash"),
    )
    assert "Long-term debt, including current maturities was" in withheld.markdown
    assert "minus cash and cash equivalents" not in withheld.markdown
    assert "minus cash and cash equivalents" not in withheld.html
    from white_cliff.explain import _net_debt_phrase

    debt = make_fact(
        "40",
        concept="LongTermDebt",
        role="debt",
        kind="instant",
        start=None,
        end="2024-12-31",
    )
    cash = make_fact(
        "15",
        concept="CashAndCashEquivalentsAtCarryingValue",
        role="cash",
        kind="instant",
        start=None,
        end="2024-12-31",
    )
    securities = make_fact(
        "15",
        concept="CashAndMarketableSecurities",
        role="cash",
        kind="instant",
        start=None,
        end="2024-12-31",
    )
    restricted = make_fact(
        "15",
        concept="RestrictedCash",
        role="cash",
        kind="instant",
        start=None,
        end="2024-12-31",
    )
    assert _net_debt_phrase(debt, cash) == (
        "Long-term debt, including current maturities minus cash and cash equivalents"
    )
    assert _net_debt_phrase(debt, securities) is None
    assert _net_debt_phrase(debt, restricted) is None


def test_net_income_attributable_to_the_company(pages):
    hits = 0
    for explained, page in pages:
        income = next((fact for fact in _cited(explained) if fact.role == "net_income"), None)
        if income is None:
            continue
        assert income.concept == "NetIncomeLoss"
        revenue = next(fact for fact in _cited(explained) if fact.role == "revenue")
        term = (
            CONTRACT_REVENUE_TERM
            if revenue.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
            else "revenue"
        )
        margin = f"The net margin ({NET_INCOME_LABEL[0].lower()}{NET_INCOME_LABEL[1:]} / {term}) for the "
        hits += 1
        for surface in _surfaces(explained, page):
            assert f"{NET_INCOME_LABEL} for the " in surface
            assert "Net income for the " not in surface
            assert margin in surface
    assert hits >= 1


def test_common_shares_outstanding_at_the_period_end(pages):
    outstanding = 0
    average = 0
    for explained, page in pages:
        shares = next((fact for fact in _cited(explained) if fact.role == "shares"), None)
        if shares is None:
            continue
        if shares.concept == "CommonStockSharesOutstanding":
            outstanding += 1
            for surface in _surfaces(explained, page):
                assert f"{SHARES_LABEL} was" in surface
                assert "The share count at the period end" not in surface
        elif shares.concept == "WeightedAverageNumberOfSharesOutstandingBasic":
            average += 1
            for surface in _surfaces(explained, page):
                assert "The basic average share count for the " in surface
                assert SHARES_LABEL not in surface
        else:
            raise AssertionError(shares.concept)
    assert outstanding >= 1
    assert average >= 1
    entity = make_fact(
        "10",
        concept="EntityCommonStockSharesOutstanding",
        role="shares",
        kind="instant",
        start=None,
        end="2024-12-31",
        unit="shares",
    )
    counted = make_fact(
        "10",
        concept="WeightedAverageNumberOfSharesOutstandingBasic",
        role="shares",
        unit="shares",
    )
    assert _lead("shares", entity, "period end") == f"{SHARES_LABEL} was"
    assert _lead("shares", counted, "fiscal year") == (
        "The basic average share count for the fiscal year was"
    )


def test_revenue_from_contracts_with_customers(pages, tmp_path):
    hits = 0
    for explained, page in pages:
        revenue = next((fact for fact in _cited(explained) if fact.role == "revenue"), None)
        if revenue is None or revenue.concept != "RevenueFromContractWithCustomerExcludingAssessedTax":
            continue
        hits += 1
        for surface in _surfaces(explained, page):
            assert f"{CONTRACT_REVENUE} for the " in surface
            assert "Revenue for the " not in surface
            assert f" / {CONTRACT_REVENUE_TERM}) for the " in surface
            if "yoy_change" in surface:
                assert f"The year over year change in {CONTRACT_REVENUE_TERM} was" in surface
                assert "The year over year change in revenue was" not in surface
    assert hits >= 1
    only = _explain_xml(
        tmp_path,
        MINI_XML.replace("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    )
    assert f"{CONTRACT_REVENUE} for the " in only.markdown
    assert "Revenue for the " not in only.markdown
    assert (
        f"The net margin (net income attributable to the company / {CONTRACT_REVENUE_TERM}) for the "
        in only.markdown
    )
    assert f"The year over year change in {CONTRACT_REVENUE_TERM} was" in only.markdown


def test_revenues_stay_revenue(pages):
    hits = 0
    for explained, page in pages:
        revenue = next((fact for fact in _cited(explained) if fact.role == "revenue"), None)
        if revenue is None or revenue.concept != "Revenues":
            continue
        hits += 1
        for surface in _surfaces(explained, page):
            assert "Revenue for the " in surface
            assert CONTRACT_REVENUE not in surface
            assert " / revenue) for the " in surface
            if "The year over year change in revenue" in surface:
                assert "The year over year change in revenue was" in surface
    assert hits >= 1


def test_no_page_has_a_bare_debt_label(pages):
    seen = False
    for path in sorted(DOCS.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        assert "Debt" not in text.replace("Long-term debt", ""), path.name
        assert "Net debt" not in text
        if "Long-term debt" in text:
            seen = True
    assert seen
    for explained, page in pages:
        for surface in (explained.markdown, explained.html, page):
            assert "Debt" not in surface.replace("Long-term debt", "")
            assert "Net debt" not in surface
