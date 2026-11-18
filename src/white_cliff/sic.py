"""Accept a sector only when it is the filer's EDGAR SIC code."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from white_cliff.explain import acceptable_name

_FILER_SIC = re.compile(r"https://data\.sec\.gov/submissions/CIK(\d{10})\.json\Z")


@lru_cache(maxsize=1)
def sic_codes() -> frozenset[str]:
    """SIC codes from the SEC's published code list."""
    path = Path(__file__).with_name("data") / "sic-codes.txt"
    codes: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        code, _title = line.split("\t", 1)
        codes.add(code)
    return frozenset(codes)


def accepted_sector(sic: object, cik: str) -> str | None:
    """Return the description when the source is this filer's submissions file and the code is listed."""
    if not isinstance(sic, dict):
        return None
    description = acceptable_name(str(sic.get("description", "")))
    code = str(sic.get("code", "")).strip()
    source = str(sic.get("source", "")).strip()
    match = _FILER_SIC.fullmatch(source)
    if description is None or match is None or not code.isdigit():
        return None
    canonical = re.sub(r"\D", "", cik).zfill(10)
    if len(canonical) != 10 or match.group(1) != canonical:
        return None
    if str(int(code)) not in sic_codes():
        return None
    return description
