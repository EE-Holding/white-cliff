"""The disclaimer that every public surface must carry, byte for byte."""

from __future__ import annotations

import re

DISCLAIMER = (
    "This tool explains the numbers in a public company filing. "
    "It does not recommend buying, selling or holding any security, "
    "and it is not investment advice."
)

ISSUE_URL = (
    "https://github.com/EE-Holding/white-cliff/issues/new?template=filing_error.md"
)


class OutputRefused(Exception):
    """Raised when an output would ship without the disclaimer above any number."""


def ensure_safe_output(text: str) -> str:
    """Refuse an output whose disclaimer is missing or sits below a number."""
    if not isinstance(text, str) or DISCLAIMER not in text:
        raise OutputRefused("missing disclaimer")
    index = text.find(DISCLAIMER)
    if index < 0:
        raise OutputRefused("missing disclaimer")
    digit = re.search(r"\d", text)
    if digit is not None and digit.start() < index:
        raise OutputRefused("number before disclaimer")
    if not text.startswith(DISCLAIMER) and "<" not in text[:index]:
        # Plain text and Markdown must open with the disclaimer.
        # HTML may open with a doctype that contains no digits.
        if text[:index].strip():
            raise OutputRefused("disclaimer is not first")
    return text
