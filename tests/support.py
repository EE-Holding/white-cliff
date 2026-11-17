"""Shared builders for filing tests."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from white_cliff.facts import Fact, Period, SourcePointer
from white_cliff.ids import letter_id

MINI_XML = """<?xml version="1.0" encoding="utf-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2026"
      xmlns:dei="http://xbrl.sec.gov/dei/2026"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
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
  <dei:EntityRegistrantName contextRef="c-year">Example Co</dei:EntityRegistrantName>
  <dei:DocumentType contextRef="c-year">10-K</dei:DocumentType>
  <dei:DocumentFiscalPeriodFocus contextRef="c-year">FY</dei:DocumentFiscalPeriodFocus>
  <dei:DocumentPeriodEndDate contextRef="c-year">2024-12-31</dei:DocumentPeriodEndDate>
  <us-gaap:Revenues contextRef="c-year" unitRef="usd" decimals="-3">5000</us-gaap:Revenues>
  <us-gaap:Revenues contextRef="c-prior" unitRef="usd" decimals="-3">4000</us-gaap:Revenues>
  <us-gaap:NetIncomeLoss contextRef="c-year" unitRef="usd" decimals="-3">800</us-gaap:NetIncomeLoss>
  <us-gaap:CashAndCashEquivalentsAtCarryingValue contextRef="c-end" unitRef="usd" decimals="-3">300</us-gaap:CashAndCashEquivalentsAtCarryingValue>
  <us-gaap:LongTermDebt contextRef="c-end" unitRef="usd" decimals="-3">100</us-gaap:LongTermDebt>
  <us-gaap:CommonStockSharesOutstanding contextRef="c-end" unitRef="shares" decimals="0">50</us-gaap:CommonStockSharesOutstanding>
</xbrl>
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
                "retrieved_at": "2026-11-17T17:40:00Z",
            }
        ],
    }
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
