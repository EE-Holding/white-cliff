"""The app fetches filings from the SEC, and the page on this computer."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1] / "src" / "white_cliff"
_URL = re.compile(r"https?://[A-Za-z0-9._-]+(?:/[^\s\"'`<>\\)]*)?")
_FETCH = ("urlopen(", "Request(", "build_opener(", "create_connection(", "http.client")
_NEW_CLIENT = ("import requests", "import httpx", "import aiohttp", "import http.client")
_NAMESPACE_HOSTS = {"www.xbrl.org", "www.w3.org"}
_SHOWN_LINK = "https://github.com/EE-Holding/white-cliff/issues/new?template=filing_error.md"


def _allowed(host: str, text: str, url: str) -> bool:
    if host in {"127.0.0.1", "localhost"}:
        return True
    if host == "sec.gov" or host.endswith(".sec.gov"):
        return True
    if any(marker in text for marker in _FETCH):
        return False
    if host in _NAMESPACE_HOSTS:
        return True
    return url.startswith(_SHOWN_LINK)


def test_the_app_does_not_call_another_host():
    offenders: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for banned in _NEW_CLIENT:
            if banned in text:
                offenders.append(f"{path.name} imports {banned}")
        for match in _URL.finditer(text):
            url = match.group(0)
            host = urlsplit(url).hostname or ""
            if "." not in host:
                continue
            if host and not _allowed(host, text, url):
                offenders.append(f"{path.name} {host}")
    assert offenders == []
