"""XBRL instance and inline-XBRL fact extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from xml.etree import ElementTree as ET

from white_cliff.facts import Fact, Period, SourcePointer
from white_cliff.ids import letter_id
from white_cliff.prices import is_price_text

_ROLES: dict[str, str] = {}
for _role, _concepts in {
    "revenue": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "SalesAndOtherOperatingRevenue",
    ),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "debt": (
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebtNoncurrent",
        "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
    ),
    "cash": ("CashAndCashEquivalentsAtCarryingValue",),
    "shares": (
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ),
}.items():
    for _concept in _concepts:
        _ROLES.setdefault(_concept, _role)

_SECTION = {
    "revenue": "Income statement",
    "gross_profit": "Income statement",
    "operating_income": "Income statement",
    "net_income": "Income statement",
    "operating_cash_flow": "Cash flows",
    "debt": "Balance sheet",
    "cash": "Balance sheet",
    "shares": "Equity",
}

_ELEMENT = re.compile(
    r"<(?:[A-Za-z_][\w.-]*:)?([A-Za-z_][\w.-]*)\b([^>]*)>([^<]*)</",
    re.DOTALL,
)
_ATTR = re.compile(r'([A-Za-z_:][\w:.-]*)\s*=\s*"([^"]*)"')
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_INLINE = re.compile(
    r"<(?:[A-Za-z_][\w.-]*:)?nonFraction\b([^>]*)>([^<]*)</(?:[A-Za-z_][\w.-]*:)?nonFraction>",
    re.I | re.DOTALL,
)
_NONNUMERIC = re.compile(
    r"<(?:[A-Za-z_][\w.-]*:)?nonNumeric\b([^>]*)>(.*?)</(?:[A-Za-z_][\w.-]*:)?nonNumeric>",
    re.I | re.DOTALL,
)
_SCALE_WORD = {"3": "thousands", "6": "millions", "9": "billions"}
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


@dataclass
class ParsedFacts:
    facts: list[Fact]
    filer: str = ""
    form: str = ""
    focus: str | None = None
    period_end: str | None = None
    price_metric: bool = False


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attrs(text: str) -> dict[str, str]:
    return dict(_ATTR.findall(text))


def _norm_measure(value: str) -> str:
    token = value.strip().split(":")[-1]
    lower = token.lower()
    if lower == "usd":
        return "USD"
    if lower == "shares":
        return "shares"
    if lower in {"pure", "number"}:
        return "pure"
    if lower in {"usdpershare", "usdpershares"}:
        return "USD/shares"
    return token


def _measures(node: ET.Element) -> list[str]:
    found: list[str] = []
    for child in node.iter():
        if _local(child.tag) == "measure" and child.text:
            found.append(_norm_measure(child.text))
    return found


def _parse_contexts(root: ET.Element) -> dict[str, dict]:
    contexts: dict[str, dict] = {}
    for ctx in root.iter():
        if _local(ctx.tag) != "context" or not ctx.get("id"):
            continue
        kind = "duration"
        start = end = None
        dimensional = False
        for child in ctx.iter():
            name = _local(child.tag)
            if name == "instant" and child.text:
                kind = "instant"
                end = child.text.strip()
            elif name == "startDate" and child.text:
                kind = "duration"
                start = child.text.strip()
            elif name == "endDate" and child.text:
                kind = "duration"
                end = child.text.strip()
            elif name in {"explicitMember", "typedMember"}:
                dimensional = True
        contexts[ctx.get("id")] = {
            "kind": kind,
            "start": start,
            "end": end,
            "dimensional": dimensional,
        }
    return contexts


def _parse_units(root: ET.Element) -> dict[str, str]:
    units: dict[str, str] = {}
    for unit in root.iter():
        if _local(unit.tag) != "unit" or not unit.get("id"):
            continue
        divide = None
        for child in list(unit):
            if _local(child.tag) == "divide":
                divide = child
        if divide is not None:
            numerator: list[str] = []
            denominator: list[str] = []
            for part in list(divide):
                if _local(part.tag) == "unitNumerator":
                    numerator = _measures(part)
                elif _local(part.tag) == "unitDenominator":
                    denominator = _measures(part)
            label = "/".join(numerator + denominator) if denominator else "/".join(numerator)
        else:
            found = _measures(unit)
            label = found[0] if found else unit.get("id") or ""
        units[unit.get("id")] = label
    return units


def _dei(root: ET.Element, contexts: dict[str, dict]) -> dict[str, str]:
    wanted = {
        "EntityRegistrantName": "filer",
        "DocumentType": "form",
        "DocumentFiscalPeriodFocus": "focus",
        "DocumentPeriodEndDate": "period_end",
    }
    found: dict[str, str] = {}
    for element in root.iter():
        key = wanted.get(_local(element.tag))
        if not key or key in found or not element.text:
            continue
        context = contexts.get(element.get("contextRef") or "", {})
        if context.get("dimensional"):
            continue
        found[key] = element.text.strip()
    return found


def _decimals(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    if raw.upper() == "INF":
        return 10**6
    try:
        return int(raw)
    except ValueError:
        return None


def _number(text: str) -> Decimal | None:
    cleaned = text.strip().replace(",", "")
    if not _NUMBER.fullmatch(cleaned):
        return None
    return Decimal(cleaned)


def _fact_from_hit(
    *,
    concept: str,
    attr_text: str,
    raw_inner: str,
    inner_start: int,
    contexts: dict[str, dict],
    units: dict[str, str],
    document: str,
    url: str,
    sha256: str,
    origin: str,
) -> Fact | None:
    if concept.endswith("TextBlock") or concept.endswith("TableTextBlock"):
        return None
    attrs = _attrs(attr_text)
    context_id = attrs.get("contextRef")
    if not context_id or context_id not in contexts:
        return None
    context = contexts[context_id]
    if context["dimensional"]:
        return None
    stripped = raw_inner.strip()
    if not stripped:
        return None
    value = _number(stripped)
    if value is None:
        return None
    if attrs.get("sign") == "-" and value > 0:
        value = -value
    if is_price_text(concept):
        return None
    relative = raw_inner.find(stripped)
    start = inner_start + max(relative, 0)
    end = start + len(stripped)
    unit_ref = attrs.get("unitRef", "")
    unit = units.get(unit_ref, _norm_measure(unit_ref) if unit_ref else "")
    scaled = _unit_with_scale(unit, attrs.get("scale"), origin)
    if scaled is None:
        return None
    unit = scaled
    role = _ROLES.get(concept, "")
    period = Period(
        kind=context["kind"],
        start=context["start"],
        end=context["end"],
    )
    fact_id = letter_id(
        "fact",
        f"{document}|{concept}|{context_id}|{value}|{start}",
    )
    kind = "shares" if unit == "shares" else "amount"
    return Fact(
        id=fact_id,
        concept=concept,
        label=concept,
        value=value,
        unit=unit or "number",
        period=period,
        source=SourcePointer(
            document=document,
            section=_SECTION.get(role, "Statements"),
            url=url,
            sha256=sha256,
            char_start=start,
            char_end=end,
        ),
        role=role,
        origin=origin,
        kind=kind,
        decimals=_decimals(attrs.get("decimals")),
    )


def parse_instance(text: str, document: str, url: str, sha256: str) -> ParsedFacts:
    root = ET.fromstring(text)
    contexts = _parse_contexts(root)
    units = _parse_units(root)
    meta = _dei(root, contexts)
    facts: list[Fact] = []
    seen: set[tuple[str, str, str, int]] = set()
    for match in _ELEMENT.finditer(text):
        fact = _fact_from_hit(
            concept=match.group(1),
            attr_text=match.group(2),
            raw_inner=match.group(3),
            inner_start=match.start(3),
            contexts=contexts,
            units=units,
            document=document,
            url=url,
            sha256=sha256,
            origin="xbrl",
        )
        if fact is None:
            continue
        key = (fact.concept, fact.period.end or "", str(fact.value), fact.source.char_start or 0)
        if key in seen:
            continue
        seen.add(key)
        facts.append(fact)
    price = any(is_price_text(fact.concept) or is_price_text(fact.label) for fact in facts)
    return ParsedFacts(
        facts=facts,
        filer=meta.get("filer", ""),
        form=meta.get("form", ""),
        focus=meta.get("focus"),
        period_end=meta.get("period_end"),
        price_metric=price,
    )


def _unit_with_scale(unit: str, scale: str | None, origin: str) -> str | None:
    """Keep the digits that are written in the file and name the scale in the unit."""
    if origin != "ixbrl" or not scale or scale == "0":
        return unit or "number"
    word = _SCALE_WORD.get(scale)
    if word is None or unit not in {"USD", "shares"}:
        return None
    return f"{unit} {word}"


def _iso_date(value: str) -> str | None:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    match = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", value)
    if not match:
        return None
    month = _MONTHS.get(match.group(1).lower())
    if month is None:
        return None
    return f"{int(match.group(3)):04d}-{month:02d}-{int(match.group(2)):02d}"


def _dei_inline(text: str, contexts: dict[str, dict]) -> dict[str, str]:
    """Cover facts in inline XBRL sit inside ix:nonNumeric, often wrapped in HTML."""
    wanted = {
        "EntityRegistrantName": "filer",
        "DocumentType": "form",
        "DocumentFiscalPeriodFocus": "focus",
        "DocumentPeriodEndDate": "period_end",
    }
    found: dict[str, str] = {}
    for match in _NONNUMERIC.finditer(text):
        attrs = _attrs(match.group(1))
        key = wanted.get(attrs.get("name", "").split(":")[-1])
        if not key or key in found:
            continue
        context = contexts.get(attrs.get("contextRef", ""), {})
        if context.get("dimensional"):
            continue
        value = re.sub(r"<[^>]+>", " ", match.group(2))
        value = re.sub(r"\s+", " ", value).strip()
        if key == "period_end":
            value = _iso_date(value) or ""
        if value:
            found[key] = value
    return found


def parse_inline(text: str, document: str, url: str, sha256: str) -> ParsedFacts:
    """Inline XBRL. Contexts are read from the same document when they are present."""
    contexts: dict[str, dict] = {}
    units: dict[str, str] = {}
    meta: dict[str, str] = {}
    try:
        # Inline documents are XHTML. A tolerant parse is enough when the
        # document is well formed; otherwise regex facts still carry context ids
        # only when the context table was parsed.
        root = ET.fromstring(text)
    except ET.ParseError:
        root = None
    if root is not None:
        contexts = _parse_contexts(root)
        units = _parse_units(root)
        meta = _dei(root, contexts)
    for key, value in _dei_inline(text, contexts).items():
        meta.setdefault(key, value)
    facts: list[Fact] = []
    for match in _INLINE.finditer(text):
        attrs = _attrs(match.group(1))
        name = attrs.get("name", "")
        concept = name.split(":")[-1]
        fact = _fact_from_hit(
            concept=concept,
            attr_text=match.group(1),
            raw_inner=match.group(2),
            inner_start=match.start(2),
            contexts=contexts,
            units=units,
            document=document,
            url=url,
            sha256=sha256,
            origin="ixbrl",
        )
        if fact is not None:
            facts.append(fact)
    return ParsedFacts(
        facts=facts,
        filer=meta.get("filer", ""),
        form=meta.get("form", ""),
        focus=meta.get("focus"),
        period_end=meta.get("period_end"),
        price_metric=False,
    )


def is_instance_document(text: str) -> bool:
    head = text.lstrip()[:800].lower()
    return "<xbrl" in head and "nonfraction" not in head
