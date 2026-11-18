"""Inline XBRL fact extraction for a primary 10-K or 10-Q."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
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

_PLAIN_NUMBER = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
_DOT_DECIMAL = re.compile(r"^(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?$")
_ASCII_INT = re.compile(r"-?[0-9]+$")
_INSTANCE_NS = "http://www.xbrl.org/2003/instance"
_ISO_NS = "http://www.xbrl.org/2003/iso4217"
_IX_NS = frozenset(
    {
        "http://www.xbrl.org/2013/inlineXBRL",
        "http://www.xbrl.org/2008/inlineXBRL",
    }
)
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
_CIK_SCHEME = "http://www.sec.gov/CIK"
_NS_SEP = "\x1f"
_SCALE_WORD = {"3": "thousands", "6": "millions", "9": "billions"}
_ALLOWED_SCALE = frozenset({"0", "3", "6", "9"})
_PRIMARY_FORMS = frozenset({"10-K", "10-Q"})
_DEI = frozenset(
    {
        "EntityRegistrantName",
        "DocumentType",
        "DocumentFiscalPeriodFocus",
        "DocumentPeriodEndDate",
        "EntityCentralIndexKey",
    }
)
_DIRECT_TEXT = frozenset({"identifier", "startDate", "endDate", "instant"})
_HIDDEN_STYLE = re.compile(
    r"(?i)(?:^|;)\s*(?:"
    r"display\s*:\s*none\b"
    r"|visibility\s*:\s*hidden\b"
    r"|font-size\s*:\s*0(?:[a-z%]+)?(?![0-9.])"
    r"|height\s*:\s*0(?:[a-z%]+)?(?![0-9.])"
    r")"
)
_STYLE_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
_CLASS_IN_SELECTOR = re.compile(r"\.(-?[_A-Za-z][_A-Za-z0-9-]*)")


def _style_hides(attrs: dict[str, str]) -> bool:
    for key, value in attrs.items():
        local = key.rsplit(_NS_SEP, 1)[-1]
        if local.lower() == "style" and value and _HIDDEN_STYLE.search(value):
            return True
    return False


def _class_names(attrs: dict[str, str]) -> list[str]:
    raw = _attr(attrs, "class")
    return [part for part in raw.split() if part]


def _hiding_classes(css: str) -> set[str]:
    """Class names whose style rule hides the text."""
    found: set[str] = set()
    for selector, body in _STYLE_RULE.findall(css):
        if _HIDDEN_STYLE.search(body) is None:
            continue
        found.update(_CLASS_IN_SELECTOR.findall(selector))
    return found


def _concealed(frame: dict, ancestors: list[dict]) -> bool:
    """A figure inside ix:hidden or a hidden block is not shown."""
    for item in (*ancestors, frame):
        if item["local"] == "hidden" and item["uri"] in _IX_NS:
            return True
        if _style_hides(item["attrs"]):
            return True
    return False


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
    cik: str = ""
    shares_tagged: bool = False


@dataclass
class _BoundUnit:
    measures: tuple[tuple[str, str] | None, ...]
    divide: bool


def _split_name(name: str) -> tuple[str, str]:
    if _NS_SEP in name:
        uri, local = name.split(_NS_SEP, 1)
        return uri, local
    return "", name


def _attr(attrs: dict[str, str], local: str) -> str:
    if local in attrs:
        return attrs[local]
    for key, value in attrs.items():
        if key.split(_NS_SEP)[-1] == local:
            return value
    return ""


def _concept_name(raw: str) -> str:
    return raw.split(":")[-1].strip()


def _cik_number(raw: str) -> int | None:
    digits = re.sub(r"\D", "", raw or "")
    if not digits or len(digits) > 10:
        return None
    return int(digits)


def _cik_text(number: int | None) -> str:
    if number is None:
        return ""
    return str(number).zfill(10)


@dataclass
class _Hit:
    concept: str
    context_id: str
    text: str
    byte_start: int
    byte_end: int
    fmt: str | None = None
    scale: str = ""
    sign: str = ""
    unit_ref: str = ""
    decimals: str = ""
    nil: bool = False
    concealed: bool = False
    transform: str = ""
    classes: tuple[str, ...] = ()


@dataclass
class _Context:
    kind: str
    start: str | None
    end: str | None
    cik: int | None
    scheme: str
    bad: bool = False


class _Scope:
    """One pass over the live element tree. Comments and CDATA stay text."""

    def __init__(self) -> None:
        self.units: dict[str, _BoundUnit] = {}
        self.duplicates: set[str] = set()
        self.contexts: dict[str, _Context] = {}
        self.duplicate_contexts: set[str] = set()
        self.hits: list[_Hit] = []
        self.dei: list[_Hit] = []
        self.seen_roles: set[str] = set()
        self._ns: list[dict[str, str]] = [{}]
        self._frames: list[dict] = []
        self._unit: dict | None = None
        self._ctx: dict | None = None
        self._buf: list[str] = []
        self._styles: list[str] = []
        self._style_chunks: list[str] | None = None
        self._parser: expat.XMLParserType | None = None
        self._raw = b""
        self.ok = True
        self.shifts: tuple[tuple[int, int, int], ...] = ()

    def to_origin(self, index: int) -> int:
        """Map a stored offset back to the downloaded filing."""
        extra = 0
        for start, original_len, repl_len in self.shifts:
            if index >= start + repl_len:
                extra += original_len - repl_len
        return index + extra

    def parse(self, text: str) -> bool:
        self._raw = text.encode("utf-8")
        parser = expat.ParserCreate(namespace_separator=_NS_SEP)
        parser.StartNamespaceDeclHandler = self._start_ns
        parser.EndNamespaceDeclHandler = self._end_ns
        parser.StartElementHandler = self._start
        parser.EndElementHandler = self._end
        parser.CharacterDataHandler = self._text
        parser.ExternalEntityRefHandler = self._external
        try:
            parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
        except AttributeError:
            pass
        self._parser = parser
        try:
            parser.Parse(text, True)
        except expat.ExpatError:
            self.ok = False
            self.units.clear()
            self.duplicates.clear()
            self.contexts.clear()
            self.hits.clear()
            self.dei.clear()
            self.seen_roles.clear()
            return False
        hiding = _hiding_classes("\n".join(self._styles))
        if hiding:
            for hit in self.hits:
                if any(name in hiding for name in hit.classes):
                    hit.concealed = True
        return True

    def _external(self, *_args: object) -> int:
        return 1

    def _start_ns(self, prefix: str | None, uri: str) -> None:
        mapped = dict(self._ns[-1])
        mapped[prefix or ""] = uri
        self._ns.append(mapped)

    def _end_ns(self, prefix: str | None) -> None:
        del prefix
        if len(self._ns) > 1:
            self._ns.pop()

    def _start(self, name: str, attrs: dict[str, str]) -> None:
        uri, local = _split_name(name)
        concept = _concept_name(_attr(attrs, "name"))
        if local.lower() == "style" and uri in {"", "http://www.w3.org/1999/xhtml"}:
            self._style_chunks = []
        keep = False
        if local == "nonFraction" and uri in _IX_NS:
            keep = True
        elif local == "nonNumeric" and uri in _IX_NS and concept in _DEI:
            keep = True
        elif local in _DIRECT_TEXT:
            keep = True
        self._frames.append(
            {
                "local": local,
                "uri": uri,
                "attrs": attrs,
                "fmt": self._format_kind(_attr(attrs, "format")),
                "transform": self._transform_local(_attr(attrs, "format")),
                "chunks": [],
                "byte_start": None,
                "keep": keep,
                "concept": concept,
            }
        )
        if local == "unit" and uri == _INSTANCE_NS and self._unit is None:
            self._unit = {
                "id": _attr(attrs, "id"),
                "measures": [],
                "divide": False,
                "depth": len(self._frames),
            }
        elif self._unit is not None and local == "divide":
            self._unit["divide"] = True
        if local == "measure" and self._unit is not None:
            self._buf = []
        if local == "context" and uri in {_INSTANCE_NS, ""}:
            self._ctx = {
                "id": _attr(attrs, "id"),
                "bad": False,
                "scheme": "",
                "ident": [],
                "start": [],
                "end": [],
                "instant": [],
                "depth": len(self._frames),
            }
        elif self._ctx is not None and local in {"segment", "scenario"}:
            self._ctx["bad"] = True

    def _excluded(self) -> bool:
        return any(frame["local"] == "exclude" and frame["uri"] in _IX_NS for frame in self._frames)

    def _text(self, data: str) -> None:
        if self._style_chunks is not None:
            self._style_chunks.append(data)
        if not data or self._excluded() or not self._frames:
            return
        top = self._frames[-1]
        if top["local"] == "measure" and self._unit is not None:
            self._buf.append(data)
            return
        target = None
        for frame in reversed(self._frames):
            if frame["keep"] and frame["local"] in {"nonFraction", "nonNumeric", *_DIRECT_TEXT}:
                target = frame
                break
        if target is None:
            return
        if target["byte_start"] is None and self._parser is not None:
            target["byte_start"] = self._parser.CurrentByteIndex
        target["chunks"].append(data)

    def _end(self, name: str) -> None:
        uri, local = _split_name(name)
        if local.lower() == "style" and self._style_chunks is not None:
            self._styles.append("".join(self._style_chunks))
            self._style_chunks = None
        del uri
        if not self._frames:
            return
        frame = self._frames.pop()
        if local == "measure" and self._unit is not None:
            self._unit["measures"].append(self._resolve("".join(self._buf).strip()))
            self._buf = []
        if (
            local == "unit"
            and self._unit is not None
            and len(self._frames) + 1 == self._unit["depth"]
        ):
            self._store_unit()
            self._unit = None
        if self._ctx is not None and local in _DIRECT_TEXT:
            self._ctx[{"startDate": "start", "endDate": "end", "instant": "instant"}.get(local, "ident")].extend(
                frame["chunks"]
            )
            if local == "identifier":
                self._ctx["scheme"] = _attr(frame["attrs"], "scheme").strip()
        if (
            local == "context"
            and self._ctx is not None
            and len(self._frames) + 1 == self._ctx["depth"]
        ):
            self._store_context()
            self._ctx = None
        if frame["keep"] and frame["byte_start"] is not None and self._parser is not None:
            self._store_hit(frame, self._parser.CurrentByteIndex)

    def _store_hit(self, frame: dict, byte_end: int) -> None:
        text = "".join(frame["chunks"]).strip()
        if frame["byte_start"] is None or byte_end < frame["byte_start"]:
            return
        attrs = frame["attrs"]
        hit = _Hit(
            concept=frame["concept"],
            context_id=_attr(attrs, "contextRef").strip(),
            text=text,
            byte_start=frame["byte_start"],
            byte_end=byte_end,
            fmt=frame["fmt"],
            scale=_attr(attrs, "scale").strip(),
            sign=_attr(attrs, "sign").strip(),
            unit_ref=_attr(attrs, "unitRef").strip(),
            decimals=_attr(attrs, "decimals").strip(),
            nil=_attr(attrs, "nil").strip().lower() in {"true", "1"},
            transform=frame["transform"],
            classes=tuple(
                name
                for item in (*self._frames, frame)
                for name in _class_names(item["attrs"])
            ),
        )
        if frame["local"] == "nonFraction":
            role = _ROLES.get(frame["concept"], "")
            if role:
                self.seen_roles.add(role)
            hit.concealed = _concealed(frame, self._frames)
            self.hits.append(hit)
        elif frame["local"] == "nonNumeric":
            self.dei.append(hit)

    def _store_context(self) -> None:
        assert self._ctx is not None
        context_id = self._ctx["id"]
        if not context_id:
            return
        instant = "".join(self._ctx["instant"]).strip()
        start = "".join(self._ctx["start"]).strip()
        end = "".join(self._ctx["end"]).strip()
        ident = "".join(self._ctx["ident"]).strip()
        bad = self._ctx["bad"]
        if instant:
            if _strict_date(instant) is None:
                bad = True
            kind, start_value, end_value = "instant", None, instant or None
        else:
            if _strict_date(start) is None or _strict_date(end) is None or start >= end:
                bad = True
            kind, start_value, end_value = "duration", start or None, end or None
        record = _Context(
            kind=kind,
            start=start_value,
            end=end_value,
            cik=_cik_number(ident),
            scheme=self._ctx["scheme"],
            bad=bad,
        )
        if context_id in self.contexts or context_id in self.duplicate_contexts:
            self.duplicate_contexts.add(context_id)
            self.contexts.pop(context_id, None)
            return
        self.contexts[context_id] = record

    def _finish_contexts(self, filer: int | None) -> None:
        for record in self.contexts.values():
            if record.kind == "duration" and record.start and record.end and record.start >= record.end:
                record.bad = True
            if record.scheme.rstrip("/") != _CIK_SCHEME:
                record.bad = True
            if filer is None or record.cik != filer:
                record.bad = True

    def _resolve(self, raw: str) -> tuple[str, str] | None:
        if not raw or not self._ns:
            return None
        if ":" in raw:
            prefix, local = raw.split(":", 1)
        else:
            prefix, local = "", raw
        if prefix not in self._ns[-1]:
            return None
        return self._ns[-1][prefix], local

    def _transform_local(self, fmt: str) -> str:
        token = fmt.strip()
        if not token:
            return ""
        if ":" not in token:
            return "unknown"
        prefix, local = token.split(":", 1)
        if not self._ns or self._ns[-1].get(prefix) not in _IXT_NS:
            return "unknown"
        return local

    def _format_kind(self, fmt: str) -> str | None:
        token = fmt.strip()
        if token == "":
            return "plain"
        if ":" in token:
            prefix, local = token.split(":", 1)
        else:
            prefix, local = "", token
        if not self._ns or self._ns[-1].get(prefix) not in _IXT_NS:
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

    def char_at(self, byte_index: int) -> int | None:
        try:
            return len(self._raw[:byte_index].decode("utf-8"))
        except UnicodeDecodeError:
            return None


def _decimals(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    if raw.upper() == "INF":
        return 10**6
    if _ASCII_INT.fullmatch(raw) is None:
        return None
    return int(raw)


def _read_amount(text: str, kind: str | None) -> Decimal | None:
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


def _unit_with_scale(unit: str, scale: str | None) -> str | None:
    """Keep the digits that are written in the file and name the scale in the unit."""
    if not scale or scale == "0":
        return unit
    if scale not in _ALLOWED_SCALE:
        return None
    word = _SCALE_WORD.get(scale)
    if word is None or unit not in {"USD", "shares"}:
        return None
    return f"{unit} {word}"


def _scale_number(scale: str) -> int | None:
    if scale in {"", "0"}:
        return 0
    if scale not in _ALLOWED_SCALE:
        return None
    return int(scale)


def _strict_date(value: str) -> str | None:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value or ""):
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return value


_MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}
_WORD_DATE_FORMATS = frozenset({"date-monthname-day-year-en", "datemonthdayyearen"})
_MONTHNAME_DATE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)"
    r"[ \u00a0]([1-9]|0[1-9]|[12][0-9]|3[01]),[ \u00a0]([0-9]{4})$"
)
_US_DATE = re.compile(r"^([1-9]|0[1-9]|1[0-2])/([1-9]|0[1-9]|[12][0-9]|3[01])/([0-9]{4})$")


def _calendar_date(year: str, month: int, day: str) -> str | None:
    try:
        found = date(int(year), month, int(day))
    except ValueError:
        return None
    return found.isoformat()


def _cover_date(text: str, transform: str) -> str | None:
    """The cover date from an allow-listed format. Anything else is empty."""
    if transform == "":
        return _strict_date(text)
    if transform in _WORD_DATE_FORMATS:
        match = _MONTHNAME_DATE.fullmatch(text)
        if match is None:
            return None
        return _calendar_date(match.group(3), _MONTHS[match.group(1)], match.group(2))
    if transform == "date-month-day-year":
        match = _US_DATE.fullmatch(text)
        if match is None:
            return None
        return _calendar_date(match.group(3), int(match.group(1)), match.group(2))
    return None


def _iso_date(value: str) -> str | None:
    return _strict_date(value)


def _dei_value(hit: _Hit, contexts: dict[str, _Context]) -> str:
    record = contexts.get(hit.context_id)
    if record is None or record.bad:
        return ""
    if hit.concept == "DocumentPeriodEndDate":
        return _cover_date(hit.text.strip(), hit.transform) or ""
    return hit.text


def _narrow(text: str, start: int, end: int, needle: str) -> tuple[int, int] | None:
    if start < 0 or end > len(text) or start >= end or not needle:
        return None
    at = text[start:end].find(needle)
    if at < 0:
        return None
    return start + at, start + at + len(needle)


def _dei_ciks(scope: _Scope) -> list[int]:
    found: list[int] = []
    for hit in scope.dei:
        if hit.concept != "EntityCentralIndexKey":
            continue
        number = _cik_number(hit.text)
        if number is not None:
            found.append(number)
    return found


def email_shifts(text: str, redactions: list) -> tuple[tuple[int, int, int], ...]:
    """Tracked start, original length, and replacement length for each removed address."""
    cursor = 0
    found: list[tuple[int, int, int]] = []
    for record in redactions:
        replacement = str(record["replacement"])
        lengths = [int(length) for length in record["lengths"]]
        if len(lengths) != int(record["count"]):
            raise ValueError("redaction count")
        for length in lengths:
            at = text.find(replacement, cursor)
            if at < 0:
                raise ValueError("redaction was not found")
            found.append((at, length, len(replacement)))
            cursor = at + len(replacement)
    return tuple(found)


def stored_offset(origin: int, shifts: tuple[tuple[int, int, int], ...]) -> int:
    """Map a downloaded-filing offset onto the stored copy."""
    removed = 0
    for tracked_start, original_len, repl_len in shifts:
        original_start = tracked_start + removed
        if origin >= original_start + original_len:
            removed += original_len - repl_len
    return origin - removed


def parse_inline(
    text: str,
    document: str,
    url: str,
    sha256: str,
    filer_cik: str = "",
    shifts: tuple[tuple[int, int, int], ...] = (),
) -> ParsedFacts:
    """Read live ix:nonFraction elements. A parse error yields no facts."""
    scope = _Scope()
    scope.shifts = shifts
    if not scope.parse(text):
        return ParsedFacts(facts=[])
    filer_number = _cik_number(filer_cik)
    scope._finish_contexts(filer_number)
    cover: dict[str, list[str]] = {"filer": [], "form": [], "focus": [], "period_end": []}
    name_hit: _Hit | None = None
    conflict = False
    for hit in scope.dei:
        key = {
            "EntityRegistrantName": "filer",
            "DocumentType": "form",
            "DocumentFiscalPeriodFocus": "focus",
            "DocumentPeriodEndDate": "period_end",
        }.get(hit.concept)
        if key is None:
            continue
        value = _dei_value(hit, scope.contexts)
        if hit.concept == "DocumentPeriodEndDate":
            record = scope.contexts.get(hit.context_id)
            if not value or record is None or record.end != value:
                conflict = True
                continue
        elif not value:
            continue
        cover[key].append(value)
        if key == "filer" and name_hit is None:
            name_hit = hit
    for values in cover.values():
        if len(set(values)) > 1:
            conflict = True
    meta = {key: values[0] for key, values in cover.items() if values}
    company_ids = _dei_ciks(scope)
    has_company_id = bool(company_ids) or any(record.cik is not None for record in scope.contexts.values())
    filer_ok = (
        filer_number is not None
        and has_company_id
        and all(number == filer_number for number in company_ids)
    )
    facts: list[Fact] = []
    form = meta.get("form", "")
    if conflict:
        filer_ok = False
    if filer_ok and form in _PRIMARY_FORMS:
        for hit in scope.hits:
            fact = _fact_from_hit(
                hit,
                text,
                scope,
                document=document,
                url=url,
                sha256=sha256,
            )
            if fact is not None:
                facts.append(fact)
    filer = meta.get("filer", "")
    bounds = _name_span(text, filer, name_hit, scope)
    return ParsedFacts(
        facts=facts,
        filer=filer,
        form=form,
        focus=meta.get("focus"),
        period_end=meta.get("period_end"),
        price_metric=False,
        filer_start=None if bounds is None else bounds[0],
        filer_end=None if bounds is None else bounds[1],
        cik=_cik_text(filer_number),
        shares_tagged="shares" in scope.seen_roles,
    )


def _name_span(text: str, filer: str, hit: _Hit | None, scope: _Scope) -> tuple[int, int] | None:
    if hit is None or not filer:
        return None
    start = scope.char_at(hit.byte_start)
    end = scope.char_at(hit.byte_end)
    if start is None or end is None:
        return None
    found = registrant_span(filer, text[start:end])
    if found is None:
        return None
    return scope.to_origin(start + found[0]), scope.to_origin(start + found[1])


def _fact_from_hit(
    hit: _Hit,
    text: str,
    scope: _Scope,
    *,
    document: str,
    url: str,
    sha256: str,
) -> Fact | None:
    role = _ROLES.get(hit.concept, "")
    if not role or hit.concept.endswith("TextBlock") or hit.concept.endswith("TableTextBlock"):
        return None
    if hit.nil or not hit.text or is_price_text(hit.concept):
        return None
    if hit.context_id in scope.duplicate_contexts or hit.context_id not in scope.contexts:
        return None
    context = scope.contexts[hit.context_id]
    if context.bad:
        return None
    value = _read_amount(hit.text, hit.fmt)
    if value is None:
        return None
    if hit.sign == "-" and value > 0:
        value = -value
    scale = _scale_number(hit.scale)
    if scale is None:
        return None
    unit = _unit_label(hit.unit_ref, scope.units, scope.duplicates, role)
    if unit is None:
        return None
    scaled = _unit_with_scale(unit, hit.scale)
    if scaled is None:
        return None
    start = scope.char_at(hit.byte_start)
    end = scope.char_at(hit.byte_end)
    if start is None or end is None:
        return None
    narrowed = _narrow(text, start, end, hit.text)
    if narrowed is None:
        return None
    start, end = narrowed
    start = scope.to_origin(start)
    end = scope.to_origin(end)
    fact_id = letter_id("fact", f"{document}|{hit.concept}|{hit.context_id}|{value}|{start}")
    return Fact(
        id=fact_id,
        concept=hit.concept,
        label=hit.concept,
        value=value,
        unit=scaled,
        period=Period(kind=context.kind, start=context.start, end=context.end),
        source=SourcePointer(
            document=document,
            section=_SECTION.get(role, "Statements"),
            url=url,
            sha256=sha256,
            char_start=start,
            char_end=end,
        ),
        role=role,
        origin="ixbrl",
        kind="shares" if scaled == "shares" else "amount",
        decimals=_decimals(hit.decimals),
        scale=scale,
        context_id=hit.context_id,
        entity=_cik_text(context.cik),
        concealed=hit.concealed,
    )
