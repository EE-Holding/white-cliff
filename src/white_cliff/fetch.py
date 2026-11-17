"""EDGAR retrieval with a caller-supplied User-Agent, a rate cap, and backoff.

Only https hosts that publish EDGAR filings are contacted, and only for the
filing that was requested.
"""

from __future__ import annotations

import json
import hashlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from white_cliff.config import valid_user_agent
from white_cliff.config import MissingUserAgent

ALLOWED_HOSTS = frozenset({"www.sec.gov", "data.sec.gov", "efts.sec.gov"})
ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
MAX_FILES = 8


class DisallowedHost(Exception):
    """Raised when a URL is not an EDGAR host."""


class FetchError(Exception):
    pass


def host_allowed(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        return False
    return (parsed.hostname or "") in ALLOWED_HOSTS


def _default_transport(url: str, user_agent: str) -> tuple[int, bytes, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json,text/html,application/xml,*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return exc.code, body, dict(exc.headers.items()) if exc.headers else {}


class EdgarClient:
    def __init__(
        self,
        user_agent: str,
        transport=None,
        sleep=time.sleep,
        clock=time.monotonic,
        now=None,
        rate: float = 10,
    ) -> None:
        if not valid_user_agent(user_agent or ""):
            raise MissingUserAgent(
                "A User-Agent with a name and a contact email is required."
            )
        if rate <= 0 or rate > 10:
            raise ValueError("rate exceeds 10 per second")
        self.user_agent = user_agent
        self.transport = transport or _default_transport
        self.sleep = sleep
        self.clock = clock
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.interval = 1.0 / float(rate)
        self._next: float | None = None

    def _acquire(self) -> None:
        current = self.clock()
        if self._next is not None and current < self._next:
            self.sleep(self._next - current)
            current = self.clock()
        self._next = current + self.interval

    def get(self, url: str) -> bytes:
        if not host_allowed(url):
            raise DisallowedHost(url)
        delay = 1.0
        last_status = None
        for _ in range(6):
            self._acquire()
            status, body, _headers = self.transport(url, self.user_agent)
            if status in (403, 429):
                last_status = status
                self.sleep(delay)
                delay *= 2
                continue
            if status != 200:
                raise FetchError(f"status {status}")
            return body
        raise FetchError(f"gave up after {last_status}")

    def cik_for_accession(self, accession: str) -> str:
        """Resolve the filer CIK for one accession from EDGAR search."""
        if not ACCESSION_RE.fullmatch(accession):
            raise ValueError("accession")
        query = urllib.parse.quote(f'"{accession}"')
        url = f"https://efts.sec.gov/LATEST/search-index?q={query}"
        payload = json.loads(self.get(url).decode("utf-8"))
        for hit in payload.get("hits", {}).get("hits", []):
            if not str(hit.get("_id", "")).startswith(accession):
                continue
            ciks = hit.get("_source", {}).get("ciks") or []
            if ciks:
                return str(ciks[0])
        raise FetchError("accession was not found")

    def fetch_accession(self, accession: str, dest: Path, cik: str) -> list[dict[str, str]]:
        if not ACCESSION_RE.fullmatch(accession):
            raise ValueError("accession")
        cik_path = str(int(cik))
        nodash = accession.replace("-", "")
        base = f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{nodash}"
        index_body = self.get(f"{base}/index.json")
        payload = json.loads(index_body.decode("utf-8"))
        names = [item["name"] for item in payload["directory"]["item"]]
        chosen = _choose_files(names)
        dest.mkdir(parents=True, exist_ok=True)
        records: list[dict[str, str]] = []
        for name in chosen:
            url = f"{base}/{name}"
            body = self.get(url)
            (dest / name).write_bytes(body)
            retrieved = self.now().strftime("%Y-%m-%dT%H:%M:%SZ")
            records.append(
                {
                    "name": name,
                    "url": url,
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "retrieved_at": retrieved,
                }
            )
        provenance = {"accession": accession, "cik": cik, "files": records}
        (dest / "provenance.json").write_text(
            json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
        )
        return records


def _choose_files(names: list[str]) -> list[str]:
    chosen: list[str] = []
    for name in names:
        lower = name.lower()
        if lower.endswith("_htm.xml"):
            chosen.append(name)
        elif ("ex-99" in lower or "ex99" in lower) and lower.endswith(
            (".htm", ".html", ".txt")
        ):
            chosen.append(name)
    if not chosen:
        for name in names:
            lower = name.lower()
            if (
                lower.endswith(".htm")
                and "index" not in lower
                and not re.fullmatch(r"r\d+\.htm", lower)
            ):
                chosen.append(name)
                break
    return chosen[:MAX_FILES]
