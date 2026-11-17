"""Confidential-treatment omissions stay exactly as filed."""

from __future__ import annotations

import re

_OMISSION = re.compile(r"\[\*{2,}\]")


def find_omissions(text: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(0)) for m in _OMISSION.finditer(text)]


def preserves_omissions(source: str, output: str) -> bool:
    """Every distinct omission marker in the source is shown unchanged."""
    markers = {match.group(0) for match in _OMISSION.finditer(source)}
    return all(marker in output for marker in markers)
