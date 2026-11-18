"""Replace personal-data-shaped spans with source chips. When unsure, don't show it."""

from __future__ import annotations

import re
from dataclasses import dataclass

from white_cliff.ids import letter_id

_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_SSN_DOTTED = re.compile(r"\b\d{3}\.\d{2}\.\d{4}\b")
_SSN_SPACED = re.compile(r"\b\d{3}\s\d{2}\s\d{4}\b")
_SSN_PLAIN = re.compile(
    r"(?i)\b(?:ssn|social security(?:\s+number)?)\s*[:#]?\s*\d{9}\b"
)
_ACCOUNT = re.compile(
    r"(?i)\b(?:bank\s+)?account(?:\s+(?:number|no\.?))?\s*[:#]?\s*\d[\d\s-]{5,}\d"
)
_ROUTING = re.compile(r"(?i)\b(?:routing|aba)(?:\s+number)?\s*[:#]?\s*\d{9}\b")
_IBAN = re.compile(r"(?i)\b[a-z]{2}\d{2}[a-z0-9]{11,30}\b")
_STREET = (
    r"Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Boulevard|Blvd\.?|"
    r"Lane|Ln\.?|Drive|Dr\.?|Ct\.?|Place|Pl\.?|Terrace|Way|"
    r"Rue|Strasse|Straße|Calle|Via"
)
_ADDRESS = re.compile(
    rf"(?i)\b\d{{1,6}}\s+(?:[A-Za-z0-9.'-]+\s+){{0,3}}(?:{_STREET})\b"
    rf"(?:,\s*[A-Za-z .'-]+){{0,3}}"
    rf"|\b(?:p\.?\s*o\.?\s+box|po box)\s+\d+\b"
    rf"|\bapt(?:\.|\s)\s*[A-Za-z0-9]+\b"
    rf"|(?-i:[A-Z][A-Za-z.'-]*\s+(?:Street|Avenue|Road|Boulevard|Lane|Drive|Terrace|Rue|Via))\b",
)
_ENTITY_ADDRESS = re.compile(
    r"<ix:nonNumeric\b[^>]*\bname=\"[^\"]*EntityAddress[^\"]*\"[^>]*>.*?</ix:nonNumeric>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class Redaction:
    id: str
    kind: str
    start: int
    end: int
    document: str
    url: str
    sha256: str


def _iban_matches(text: str):
    """IBANs in either case. A match needs enough digits to not be a filename."""
    for match in _IBAN.finditer(text):
        if sum(char.isdigit() for char in match.group(0)) >= 8:
            yield match


def find_redactions(text: str, document: str, url: str, sha256: str) -> list[Redaction]:
    spans: list[tuple[int, int, str]] = []
    for kind, pattern in (
        ("ssn", _SSN),
        ("ssn", _SSN_DOTTED),
        ("ssn", _SSN_SPACED),
        ("ssn", _SSN_PLAIN),
        ("account", _ACCOUNT),
        ("account", _ROUTING),
        ("account", _IBAN),
        ("address", _ADDRESS),
    ):
        addresses = [(match.start(), match.end()) for match in _ENTITY_ADDRESS.finditer(text)]
        matches = _iban_matches(text) if pattern is _IBAN else pattern.finditer(text)
        for match in matches:
            if kind == "address" and any(
                start <= match.start() and match.end() <= end for start, end in addresses
            ):
                continue
            spans.append((match.start(), match.end(), kind))
    spans.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    kept: list[tuple[int, int, str]] = []
    covered = -1
    for start, end, kind in spans:
        if start < covered:
            continue
        kept.append((start, end, kind))
        covered = end
    found: list[Redaction] = []
    for start, end, kind in kept:
        seed = f"{document}|{kind}|{start}|{end}|{sha256}"
        found.append(
            Redaction(
                id=letter_id("redact", seed),
                kind=kind,
                start=start,
                end=end,
                document=document,
                url=url,
                sha256=sha256,
            )
        )
    return found


def contains_personal(text: str) -> bool:
    if next(_iban_matches(text), None) is not None:
        return True
    return any(
        pattern.search(text)
        for pattern in (
            _SSN,
            _SSN_DOTTED,
            _SSN_SPACED,
            _SSN_PLAIN,
            _ACCOUNT,
            _ROUTING,
            _ADDRESS,
        )
    )
