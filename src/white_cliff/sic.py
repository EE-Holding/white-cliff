"""Accept a sector only when it is the filer's EDGAR SIC code."""

from __future__ import annotations

import html
import re
from functools import lru_cache
from pathlib import Path

_FILER_SIC = re.compile(r"https://data\.sec\.gov/submissions/CIK([0-9]{10})\.json\Z")
_LABEL = re.compile(r"SEC industry \(SIC ([0-9]+)\): (.*)\Z")
_CODE = re.compile(r"^[0-9]{3,4}$")


@lru_cache(maxsize=1)
def sic_titles() -> dict[str, str]:
    """SIC code to the title printed in the SEC code list."""
    path = Path(__file__).with_name("data") / "sic-codes.txt"
    titles: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        code, title = line.split("\t", 1)
        titles[code] = title
    return titles


def sic_title(code: str) -> str | None:
    token = str(code).strip()
    if _CODE.fullmatch(token) is None:
        return None
    return sic_titles().get(str(int(token)))


def sector_label(code: str) -> str | None:
    """The only sector text a surface may show."""
    title = sic_title(code)
    if title is None:
        return None
    canon = str(int(code))
    return f"SEC industry (SIC {canon}): {title}"


def exact_sector_label(text: str) -> bool:
    """True when the text is the labelled form and the title matches the list byte for byte."""
    match = _LABEL.fullmatch(html.unescape(text).strip())
    if match is None:
        return False
    title = sic_title(match.group(1))
    return title is not None and match.group(2) == title


def sector_html(code: str, url: str, *, labelled: bool = True) -> str:
    """Link the labelled sector, or nothing when the surface cannot carry the label."""
    if not labelled:
        return ""
    label = sector_label(code)
    match = _FILER_SIC.fullmatch(url.strip())
    if label is None or match is None:
        return ""
    return (
        f'<a class="sector-chip" href="{html.escape(url.strip(), quote=True)}">'
        f"{html.escape(label, quote=False)}</a>"
    )


def accepted_sector(sic: object, cik: str) -> str | None:
    """Return the labelled SEC title when the source is this filer's submissions file."""
    if not isinstance(sic, dict):
        return None
    code = str(sic.get("code", "")).strip()
    source = str(sic.get("source", "")).strip()
    match = _FILER_SIC.fullmatch(source)
    if match is None or _CODE.fullmatch(code) is None:
        return None
    canonical = re.sub(r"\D", "", cik).zfill(10)
    if len(canonical) != 10 or match.group(1) != canonical:
        return None
    return sector_label(code)
