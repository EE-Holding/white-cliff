"""Sentences the desktop screen shows. The why-line is one constant."""

from __future__ import annotations

from white_cliff.disclaimer import DISCLAIMER

SEC_WHY = (
    "The SEC asks programs that download filings from sec.gov to include a name "
    "and email with each request. White Cliff keeps yours only on this computer "
    "and sends them only to sec.gov, with each request. We never see them. "
    "You can change or erase them at any time."
)

NO_INTERNET = (
    "White Cliff could not reach sec.gov. Check your internet connection and try again."
)
SEC_CERT = "White Cliff could not confirm the connection to sec.gov. Try again."
SEC_REFUSED = "sec.gov did not accept the name and email. Check them and try again."
NO_MATCH = "No company on the SEC list matches that."
CLOSE_INTRO = "No exact match. These names are on the SEC list."
SEVERAL = "Several companies on the SEC list match. Pick one."
NO_10KQ = "That company has no 10-K or 10-Q on the SEC list."
BUSY = "sec.gov is busy. Wait a moment and try again."
CANNOT_EXPLAIN = "White Cliff cannot explain this filing."
ENTER_BOTH = "Enter your name and a full email address."
SEC_ODD = "sec.gov did not answer. Try again."
EMPTY_QUERY = "Enter a company name or ticker."
ONLY_SEC = "White Cliff only contacts sec.gov."
REFUSED = "White Cliff did not accept that request."
LOOKING = "Looking this up…"
CLOSED = "White Cliff has closed. Open it again to keep going."

__all__ = [
    "BUSY",
    "CANNOT_EXPLAIN",
    "CLOSE_INTRO",
    "DISCLAIMER",
    "EMPTY_QUERY",
    "CLOSED",
    "ENTER_BOTH",
    "LOOKING",
    "NO_10KQ",
    "NO_INTERNET",
    "NO_MATCH",
    "SEC_CERT",
    "SEC_REFUSED",
    "ONLY_SEC",
    "REFUSED",
    "SEC_ODD",
    "SEC_WHY",
    "SEVERAL",
]
