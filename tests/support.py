"""Shared builders for filing tests."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from white_cliff.facts import Fact, Period, SourcePointer
from white_cliff.fetch import directory_cik, strip_edgar_script
from white_cliff.ids import letter_id

MINI_XML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.xbrl.org/2003/instance"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:us-gaap="http://fasb.org/us-gaap/2026"
      xmlns:dei="http://xbrl.sec.gov/dei/2026"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
<body>
  <context id="c-year">
    <entity><identifier scheme="http://www.sec.gov/CIK">0000000001</identifier></entity>
    <period><startDate>2024-01-01</startDate><endDate>2024-12-31</endDate></period>
  </context>
  <context id="c-prior">
    <entity><identifier scheme="http://www.sec.gov/CIK">0000000001</identifier></entity>
    <period><startDate>2023-01-01</startDate><endDate>2023-12-31</endDate></period>
  </context>
  <context id="c-end">
    <entity><identifier scheme="http://www.sec.gov/CIK">0000000001</identifier></entity>
    <period><instant>2024-12-31</instant></period>
  </context>
  <unit id="usd"><measure>iso4217:USD</measure></unit>
  <unit id="shares"><measure>shares</measure></unit>
  <ix:nonNumeric name="dei:EntityRegistrantName" contextRef="c-year">Example Co</ix:nonNumeric>
  <ix:nonNumeric name="dei:DocumentType" contextRef="c-year">10-K</ix:nonNumeric>
  <ix:nonNumeric name="dei:DocumentFiscalPeriodFocus" contextRef="c-year">FY</ix:nonNumeric>
  <ix:nonNumeric name="dei:DocumentPeriodEndDate" contextRef="c-year">2024-12-31</ix:nonNumeric>
  <ix:nonNumeric name="dei:EntityCentralIndexKey" contextRef="c-year">0000000001</ix:nonNumeric>
  <ix:nonFraction name="us-gaap:Revenues" contextRef="c-year" unitRef="usd" decimals="-3">5000</ix:nonFraction>
  <ix:nonFraction name="us-gaap:Revenues" contextRef="c-prior" unitRef="usd" decimals="-3">4000</ix:nonFraction>
  <ix:nonFraction name="us-gaap:NetIncomeLoss" contextRef="c-year" unitRef="usd" decimals="-3">800</ix:nonFraction>
  <ix:nonFraction name="us-gaap:CashAndCashEquivalentsAtCarryingValue" contextRef="c-end" unitRef="usd" decimals="-3">300</ix:nonFraction>
  <ix:nonFraction name="us-gaap:LongTermDebt" contextRef="c-end" unitRef="usd" decimals="-3">100</ix:nonFraction>
  <ix:nonFraction name="us-gaap:CommonStockSharesOutstanding" contextRef="c-end" unitRef="shares" decimals="0">50</ix:nonFraction>
</body>
</html>
"""


def narrative_instance(note: str) -> str:
    """A small inline 10-K plus one non-numeric note from the filing."""
    escaped = (
        note.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.xbrl.org/2003/instance"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:us-gaap="http://fasb.org/us-gaap/2026"
      xmlns:dei="http://xbrl.sec.gov/dei/2026"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
<body>
  <context id="c-year">
    <entity><identifier scheme="http://www.sec.gov/CIK">0000000001</identifier></entity>
    <period><startDate>2024-01-01</startDate><endDate>2024-12-31</endDate></period>
  </context>
  <unit id="usd"><measure>iso4217:USD</measure></unit>
  <ix:nonNumeric name="dei:EntityRegistrantName" contextRef="c-year">Example Co</ix:nonNumeric>
  <ix:nonNumeric name="dei:DocumentType" contextRef="c-year">10-K</ix:nonNumeric>
  <ix:nonNumeric name="dei:DocumentFiscalPeriodFocus" contextRef="c-year">FY</ix:nonNumeric>
  <ix:nonNumeric name="dei:DocumentPeriodEndDate" contextRef="c-year">2024-12-31</ix:nonNumeric>
  <ix:nonNumeric name="dei:EntityCentralIndexKey" contextRef="c-year">0000000001</ix:nonNumeric>
  <ix:nonFraction name="us-gaap:Revenues" contextRef="c-year" unitRef="usd" decimals="0">5000</ix:nonFraction>
  <ix:nonNumeric name="dei:TradingSymbol" contextRef="c-year">{escaped}</ix:nonNumeric>
</body>
</html>
"""


def write_filing(directory: Path, name: str, text: str, url: str, form: str = "10-K", filer: str = "Example Co") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    data = text.encode("utf-8")
    target.write_bytes(data)
    provenance = {
        "filer": filer,
        "form": form,
        "files": [
            {
                "name": name,
                "url": url,
                "sha256": hashlib.sha256(data).hexdigest(),
                "content_sha256": hashlib.sha256(strip_edgar_script(data)).hexdigest(),
                "retrieved_at": "2026-11-17T17:40:00Z",
            }
        ],
    }
    cik = directory_cik(url)
    if cik:
        provenance["cik"] = cik
    (directory / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return directory


def make_fact(
    value: str,
    *,
    unit: str = "USD",
    concept: str = "Revenues",
    role: str = "revenue",
    kind: str = "duration",
    start: str | None = "2024-01-01",
    end: str | None = "2024-12-31",
    fact_kind: str = "amount",
    fact_id: str | None = None,
) -> Fact:
    identifier = fact_id or letter_id("fact", f"{concept}|{value}|{unit}|{start}|{end}|{kind}")
    return Fact(
        id=identifier,
        concept=concept,
        label=concept,
        value=Decimal(value),
        unit=unit,
        period=Period(kind=kind, start=start, end=end),
        source=SourcePointer(
            document="fixture.xml",
            section="Income statement",
            url="https://www.sec.gov/Archives/edgar/data/1/000000000100000001/fixture.xml",
            sha256="abc",
            char_start=10,
            char_end=20,
        ),
        role=role,
        origin="xbrl",
        kind=fact_kind,
    )


def render_quote_page(text: str, filing_text: str, filing_url: str) -> tuple[str, str]:
    """Render one sentence, linking any quote that survives the quote check."""
    from white_cliff.explain import Block
    from white_cliff.facts import FactStore
    from white_cliff.quotes import QuoteError, review_quotes
    from white_cliff.render import render_html, render_markdown

    store = FactStore()
    try:
        quotes = review_quotes(text, filing_text, filing_url)
        block = Block(text=text, quotes=tuple(quotes))
    except QuoteError:
        block = Block(
            text="This section was omitted because it failed the quote check [section:Notes].",
            reason="quote",
        )
    return render_markdown([block], store), render_html([block], store)
