"""XBRL instance and inline-XBRL fact extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from xml.etree import ElementTree as ET
from xml.parsers import expat

from white_cliff.explain import registrant_span
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
_PLAIN_NUMBER = re.compile(r"^-?[0-9]+(?:\.[0-9]+)?$")
_DOT_DECIMAL = re.compile(r"^-?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?$")
_ASCII_INT = re.compile(r"-?[0-9]+$")
_INSTANCE_NS = "http://www.xbrl.org/2003/instance"
_ISO_NS = "http://www.xbrl.org/2003/iso4217"
_IXT_NS = frozenset(
    {
        "http://www.xbrl.org/2008/inlineXBRL/transformation",
        "http://www.xbrl.org/inlineXBRL/transformation/2010-04-20",
        "http://www.xbrl.org/inlineXBRL/transformation/2011-07-31",
        "http://www.xbrl.org/inlineXBRL/transformation/2015-02-26",
        "http://www.xbrl.org/inlineXBRL/transformation/2020-02-12",
        "http://www.xbrl.org/inlineXBRL/transformation/2022-02-16",
        "http://www.sec.gov/inlineXBRL/transformation/2015-08-31",
    }
)
_NS_SEP = "\x1f"
_INSTANCE_ROOT = re.compile(r"<xbrl(?:\s|>|/)", re.I)
_HTML_ROOT = re.compile(r"<html(?:\s|>|/)", re.I)
_IX_MARK = re.compile(r"xmlns:ix\b|inlinexbrl|<\s*ix:", re.I)
_XML_DECL = re.compile(r"<\?xml[^>]*\?>", re.I)
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


MONEY_ROLES = frozenset(role for role in _ROLES.values() if role != "shares")


@dataclass
class ParsedFacts:
    facts: list[Fact]
    filer: str = ""
    form: str = ""
    focus: str | None = None
    period_end: str | None = None
    price_metric: bool = False
    filer_start: int | None = None
    filer_end: int | None = None


@dataclass
class _BoundUnit:
    measures: tuple[tuple[str, str] | None, ...]
    divide: bool


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attrs(text: str) -> dict[str, str]:
    return dict(_ATTR.findall(text))


class _Scope:
    """In-scope namespace map, unit measures, and inline format kinds."""

    def __init__(self) -> None:
        self.units: dict[str, _BoundUnit] = {}
        self.duplicates: set[str] = set()
        self.leaves: list[tuple[str, str | None]] = []
        self.inline_formats: list[str | None] = []
        self._ns: list[dict[str, str]] = [{}]
        self._frames: list[dict] = []
        self._unit: dict | None = None
        self._buf: list[str] = []

    def parse(self, text: str) -> None:
        parser = expat.ParserCreate(namespace_separator=_NS_SEP)
        parser.StartNamespaceDeclHandler = self._start_ns
        parser.EndNamespaceDeclHandler = self._end_ns
        parser.StartElementHandler = self._start
        parser.EndElementHandler = self._end
        parser.CharacterDataHandler = self._text
        try:
            parser.Parse(text, True)
        except expat.ExpatError:
            self.units.clear()
            self.duplicates.clear()
            self.leaves.clear()
            self.inline_formats.clear()

    def _start_ns(self, prefix: str | None, uri: str) -> None:
        mapped = dict(self._ns[-1])
        mapped[prefix or ""] = uri
        self._ns.append(mapped)

    def _end_ns(self, prefix: str | None) -> None:
        del prefix
        self._ns.pop()

    def _start(self, name: str, attrs: dict[str, str]) -> None:
        local = name.split(_NS_SEP)[-1]
        self._frames.append(
            {"local": local, "fmt": self._format_kind(attrs.get("format", "")), "child": False}
        )
        if len(self._frames) > 1:
            self._frames[-2]["child"] = True
        if local == "unit" and self._unit is None:
            self._unit = {
                "id": attrs.get("id", ""),
                "measures": [],
                "divide": False,
                "depth": len(self._frames),
            }
        elif self._unit is not None and local == "divide":
            self._unit["divide"] = True
        if local == "measure" and self._unit is not None:
            self._buf = []

    def _text(self, data: str) -> None:
        if self._unit is not None and self._frames and self._frames[-1]["local"] == "measure":
            self._buf.append(data)

    def _end(self, name: str) -> None:
        local = name.split(_NS_SEP)[-1]
        if local == "measure" and self._unit is not None:
            self._unit["measures"].append(self._resolve("".join(self._buf).strip()))
            self._buf = []
        if (
            local == "unit"
            and self._unit is not None
            and len(self._frames) == self._unit["depth"]
        ):
            self._store_unit()
            self._unit = None
        frame = self._frames.pop()
        if not frame["child"]:
            self.leaves.append((frame["local"], frame["fmt"]))
            if local == "nonFraction":
                self.inline_formats.append(frame["fmt"])

    def _resolve(self, raw: str) -> tuple[str, str] | None:
        if not raw:
            return None
        if ":" in raw:
            prefix, local = raw.split(":", 1)
        else:
            prefix, local = "", raw
        if prefix not in self._ns[-1]:
            return None
        return self._ns[-1][prefix], local

    def _format_kind(self, fmt: str) -> str | None:
        token = fmt.strip()
        if token == "":
            return "plain"
        if ":" in token:
            prefix, local = token.split(":", 1)
        else:
            prefix, local = "", token
        if self._ns[-1].get(prefix) not in _IXT_NS:
            return None
        folded = local.lower().replace("-", "").replace("_", "")
        if folded == "numdotdecimal":
            return "dot"
        return None

    def _store_unit(self) -> None:
        assert self._unit is not None
        unit_id = self._unit["id"]
        if not unit_id:
            return
        if unit_id in self.units or unit_id in self.duplicates:
            self.units.pop(unit_id, None)
            self.duplicates.add(unit_id)
            return
        self.units[unit_id] = _BoundUnit(tuple(self._unit["measures"]), self._unit["divide"])


def _read_scope(text: str) -> _Scope:
    scope = _Scope()
    scope.parse(text)
    return scope


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
    if _ASCII_INT.fullmatch(raw) is None:
        return None
    return int(raw)


def _read_amount(text: str, kind: str | None, origin: str) -> Decimal | None:
    del origin
    stripped = text.strip()
    if kind == "plain" and _PLAIN_NUMBER.fullmatch(stripped):
        return Decimal(stripped)
    if kind == "dot" and _DOT_DECIMAL.fullmatch(stripped):
        return Decimal(stripped.replace(",", ""))
    return None


def _unit_label(
    unit_ref: str,
    units: dict[str, _BoundUnit],
    duplicates: set[str],
    role: str,
) -> str | None:
    """Bind a money concept to iso4217:USD and a share concept to xbrli:shares."""
    if not unit_ref or unit_ref in duplicates or unit_ref not in units:
        return None
    bound = units[unit_ref]
    if bound.divide or len(bound.measures) != 1:
        return None
    measure = bound.measures[0]
    if measure is None:
        return None
    uri, local = measure
    if role == "shares":
        if uri == _INSTANCE_NS and local == "shares":
            return "shares"
        return None
    if role in MONEY_ROLES and uri == _ISO_NS and local == "USD":
        return "USD"
    return None


def _leaf_kind(leaves: list[tuple[str, str | None]], index: list[int], concept: str, attr_text: str) -> str | None:
    while index[0] < len(leaves) and leaves[index[0]][0] != concept:
        index[0] += 1
    if index[0] < len(leaves):
        kind = leaves[index[0]][1]
        index[0] += 1
        return kind
    if _attrs(attr_text).get("format", "").strip() == "":
        return "plain"
    return None


def _fact_from_hit(
    *,
    concept: str,
    attr_text: str,
    raw_inner: str,
    inner_start: int,
    contexts: dict[str, dict],
    units: dict[str, _BoundUnit],
    duplicates: set[str],
    format_kind: str | None,
    document: str,
    url: str,
    sha256: str,
    origin: str,
) -> Fact | None:
    role = _ROLES.get(concept, "")
    if not role or concept.endswith("TextBlock") or concept.endswith("TableTextBlock"):
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
    value = _read_amount(stripped, format_kind, origin)
    if value is None:
        return None
    if attrs.get("sign") == "-" and value > 0:
        value = -value
    if is_price_text(concept):
        return None
    relative = raw_inner.find(stripped)
    start = inner_start + max(relative, 0)
    end = start + len(stripped)
    unit = _unit_label(attrs.get("unitRef", ""), units, duplicates, role)
    if unit is None:
        return None
    scaled = _unit_with_scale(unit, attrs.get("scale"))
    if scaled is None:
        return None
    unit = scaled
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


def _name_bounds(name: str, inner: str, base: int) -> tuple[int, int] | None:
    found = registrant_span(name, inner)
    if found is None:
        return None
    return base + found[0], base + found[1]


def _instance_name_bounds(text: str, name: str, contexts: dict[str, dict]) -> tuple[int, int] | None:
    if not name:
        return None
    for match in _ELEMENT.finditer(text):
        if match.group(1) != "EntityRegistrantName":
            continue
        context = contexts.get(_attrs(match.group(2)).get("contextRef", ""), {})
        if context.get("dimensional"):
            continue
        return _name_bounds(name, match.group(3), match.start(3))
    return None


def _inline_name_bounds(text: str, name: str, contexts: dict[str, dict]) -> tuple[int, int] | None:
    if not name:
        return None
    for match in _NONNUMERIC.finditer(text):
        attrs = _attrs(match.group(1))
        if attrs.get("name", "").split(":")[-1] != "EntityRegistrantName":
            continue
        context = contexts.get(attrs.get("contextRef", ""), {})
        if context.get("dimensional"):
            continue
        return _name_bounds(name, match.group(2), match.start(2))
    return None


def parse_instance(text: str, document: str, url: str, sha256: str) -> ParsedFacts:
    root = ET.fromstring(text)
    contexts = _parse_contexts(root)
    scope = _read_scope(text)
    meta = _dei(root, contexts)
    facts: list[Fact] = []
    seen: set[tuple[str, str, str, int]] = set()
    leaf = [0]
    for match in _ELEMENT.finditer(text):
        fact = _fact_from_hit(
            concept=match.group(1),
            attr_text=match.group(2),
            raw_inner=match.group(3),
            inner_start=match.start(3),
            contexts=contexts,
            units=scope.units,
            duplicates=scope.duplicates,
            format_kind=_leaf_kind(scope.leaves, leaf, match.group(1), match.group(2)),
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
    filer = meta.get("filer", "")
    bounds = _instance_name_bounds(text, filer, contexts)
    return ParsedFacts(
        facts=facts,
        filer=filer,
        form=meta.get("form", ""),
        focus=meta.get("focus"),
        period_end=meta.get("period_end"),
        price_metric=price,
        filer_start=None if bounds is None else bounds[0],
        filer_end=None if bounds is None else bounds[1],
    )


def _unit_with_scale(unit: str, scale: str | None) -> str | None:
    """Keep the digits that are written in the file and name the scale in the unit."""
    if not scale or scale == "0":
        return unit
    if re.fullmatch(r"[0-9]+", scale) is None:
        return None
    word = _SCALE_WORD.get(scale)
    if word is None or unit not in {"USD", "shares"}:
        return None
    return f"{unit} {word}"


def _iso_date(value: str) -> str | None:
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return value
    match = re.fullmatch(r"([A-Za-z]+)\s+([0-9]{1,2}),\s*([0-9]{4})", value)
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
    meta: dict[str, str] = {}
    try:
        # Inline documents are XHTML. A tolerant parse is enough when the
        # document is well formed; otherwise regex facts still carry context ids
        # only when the context table was parsed.
        root = ET.fromstring(text)
    except ET.ParseError:
        root = None
    scope = _read_scope(text)
    if root is not None:
        contexts = _parse_contexts(root)
        meta = _dei(root, contexts)
    for key, value in _dei_inline(text, contexts).items():
        meta.setdefault(key, value)
    matches = list(_INLINE.finditer(text))
    if len(scope.inline_formats) == len(matches):
        kinds = scope.inline_formats
    else:
        kinds = [
            "plain" if _attrs(match.group(1)).get("format", "").strip() == "" else None
            for match in matches
        ]
    facts: list[Fact] = []
    for match, kind in zip(matches, kinds):
        attrs = _attrs(match.group(1))
        name = attrs.get("name", "")
        concept = name.split(":")[-1]
        fact = _fact_from_hit(
            concept=concept,
            attr_text=match.group(1),
            raw_inner=match.group(2),
            inner_start=match.start(2),
            contexts=contexts,
            units=scope.units,
            duplicates=scope.duplicates,
            format_kind=kind,
            document=document,
            url=url,
            sha256=sha256,
            origin="ixbrl",
        )
        if fact is not None:
            facts.append(fact)
    filer = meta.get("filer", "")
    bounds = _inline_name_bounds(text, filer, contexts)
    return ParsedFacts(
        facts=facts,
        filer=filer,
        form=meta.get("form", ""),
        focus=meta.get("focus"),
        period_end=meta.get("period_end"),
        price_metric=False,
        filer_start=None if bounds is None else bounds[0],
        filer_end=None if bounds is None else bounds[1],
    )


def _root_is_instance(head: str) -> bool:
    match = re.match(r"<\s*(?:([A-Za-z_][\w.-]*):)?([A-Za-z_][\w.-]*)([^>]*)>", head)
    if not match or match.group(2).lower() != "xbrl":
        return False
    prefix = match.group(1) or ""
    key = f"xmlns:{prefix}" if prefix else "xmlns"
    return _attrs(match.group(3)).get(key) == _INSTANCE_NS


def is_instance_document(text: str) -> bool:
    """An instance has an xbrl root. Inline XBRL has an ix namespace or an html root."""
    head = text.lstrip()
    head = _XML_DECL.sub("", head, count=1).lstrip()
    if _root_is_instance(head):
        return True
    window = head[:8000].lower()
    if _HTML_ROOT.search(window) or _IX_MARK.search(window):
        return False
    return _INSTANCE_ROOT.search(window) is not None
