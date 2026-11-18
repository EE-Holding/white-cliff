"""The fact store. Every number the tool shows comes from here."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Period:
    kind: str
    start: str | None = None
    end: str | None = None
    key: str = ""
    span: str = ""


@dataclass(frozen=True)
class SourcePointer:
    document: str
    section: str
    url: str
    sha256: str
    table: str | None = None
    row: str | None = None
    column: str | None = None
    char_start: int | None = None
    char_end: int | None = None

    def located(self) -> bool:
        if not self.document:
            return False
        if self.char_start is not None and self.char_end is not None:
            return self.char_end > self.char_start
        return bool(self.table or self.row or self.column)


@dataclass(frozen=True)
class Fact:
    id: str
    concept: str
    label: str
    value: Decimal
    unit: str
    period: Period
    source: SourcePointer
    role: str = ""
    origin: str = "xbrl"
    kind: str = "amount"
    decimals: int | None = None
    table_kind: str = ""
    span_hint: str = ""
    header: str = ""
    scale: int = 0
    context_id: str = ""
    entity: str = ""
    concealed: bool = False


@dataclass(frozen=True)
class Calculation:
    id: str
    name: str
    formula: str
    value: Decimal
    unit: str
    period: Period
    input_ids: tuple[str, ...]


_ID = re.compile(r"(?:fact|calc)[a-z]+$")


class FactStore:
    def __init__(self) -> None:
        self._facts: dict[str, Fact] = {}
        self._calcs: dict[str, Calculation] = {}

    def add(self, fact: Fact) -> None:
        if not isinstance(fact.value, Decimal):
            raise ValueError("value must be Decimal")
        if not fact.source or not fact.source.located():
            raise ValueError("missing source pointer")
        if not _ID.fullmatch(fact.id) or not fact.id.startswith("fact"):
            raise ValueError("fact id must be digit-free")
        existing = self._facts.get(fact.id)
        if existing is not None:
            same_place = (
                existing.value == fact.value
                and existing.source.char_start == fact.source.char_start
                and existing.source.document == fact.source.document
            )
            if same_place:
                return
            raise ValueError("fact id collision")
        self._facts[fact.id] = fact

    def add_calc(self, calc: Calculation) -> None:
        if not isinstance(calc.value, Decimal):
            raise ValueError("value must be Decimal")
        if not calc.input_ids or not calc.formula or not calc.name:
            raise ValueError("calculation needs a formula and inputs")
        if not _ID.fullmatch(calc.id) or not calc.id.startswith("calc"):
            raise ValueError("calc id must be digit-free")
        existing = self._calcs.get(calc.id)
        if existing is not None and existing != calc:
            raise ValueError("calc id collision")
        self._calcs[calc.id] = calc

    def get(self, fact_id: str) -> Fact:
        return self._facts[fact_id]

    def get_calc(self, calc_id: str) -> Calculation:
        return self._calcs[calc_id]

    def has_fact(self, fact_id: str) -> bool:
        return fact_id in self._facts

    def has_calc(self, calc_id: str) -> bool:
        return calc_id in self._calcs

    def facts(self) -> list[Fact]:
        return list(self._facts.values())

    def calcs(self) -> list[Calculation]:
        return list(self._calcs.values())


def format_decimal(value: Decimal) -> str:
    """Format a Decimal so the text parses back to the same value."""
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if rendered in {"", "-", "-0"}:
        return "0"
    return rendered
