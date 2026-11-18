"""EDGAR retrieval with a caller-supplied User-Agent, a rate cap, and backoff.

Only https hosts that publish EDGAR filings are contacted, and only for the
filing that was requested.
"""

from __future__ import annotations

import json
import hashlib
import re
from html.parser import HTMLParser
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
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_MAX_WAIT = 30.0
_PRIMARY_FORM = frozenset({"10-K", "10-Q"})
_DIRECTORY = re.compile(r"/Archives/edgar/data/([0-9]{1,10})/([0-9]{18})/")


def directory_cik(url: str) -> str | None:
    """The filer CIK in /Archives/edgar/data/<CIK>/<accession>/, never the accession prefix."""
    if not url.startswith("https://www.sec.gov/"):
        return None
    match = _DIRECTORY.search(url)
    if match is None:
        return None
    return match.group(1).zfill(10)


class DisallowedHost(Exception):
    """Raised when a URL is not an EDGAR host."""


class FetchError(Exception):
    pass


def host_allowed(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        return False
    if parsed.port not in (None, 443):
        return False
    return (parsed.hostname or "") in ALLOWED_HOSTS


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Leave 3xx responses in place so the caller can check Location."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_transport(url: str, user_agent: str) -> tuple[int, bytes, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json,text/html,application/xml,*/*",
        },
    )
    opener = urllib.request.build_opener(_RefuseRedirect)
    try:
        with opener.open(request, timeout=60) as response:
            return response.status, response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return exc.code, body, dict(exc.headers.items()) if exc.headers else {}


def _header(headers: dict[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return ""


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

    def get(self, url: str, hops: int = 0) -> bytes:
        if not host_allowed(url):
            raise DisallowedHost(url)
        delay = 1.0
        waited = 0.0
        last_status = None
        for _ in range(6):
            self._acquire()
            status, body, headers = self.transport(url, self.user_agent)
            if status in _REDIRECTS:
                location = _header(headers, "Location")
                target = urllib.parse.urljoin(url, location) if location else ""
                if hops >= 2 or not target or not host_allowed(target):
                    raise DisallowedHost(target or url)
                return self.get(target, hops + 1)
            if status in (403, 429):
                last_status = status
                pause = delay
                retry_after = _header(headers, "Retry-After")
                if retry_after:
                    try:
                        pause = float(retry_after)
                    except ValueError:
                        pause = delay
                pause = max(0.0, min(pause, _MAX_WAIT - waited))
                self.sleep(pause)
                waited += pause
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
        confirmed = directory_cik(base + "/")
        if confirmed is None or int(confirmed) != int(cik):
            raise FetchError("filer cik")
        index_body = self.get(f"{base}/{accession}-index.html")
        chosen = _primary_documents(index_body.decode("utf-8"))
        if not chosen:
            raise FetchError("no primary document")
        form = chosen[0][1]
        if any(kind != form for _name, kind in chosen):
            raise FetchError("primary form")
        dest.mkdir(parents=True, exist_ok=True)
        records: list[dict[str, str]] = []
        for name, document_type in chosen[:MAX_FILES]:
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
                    "document_type": document_type,
                }
            )
        provenance = {"accession": accession, "cik": confirmed, "form": form, "files": records}
        (dest / "provenance.json").write_text(
            json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
        )
        return records


def _safe_file_name(name: str) -> str:
    if (
        not isinstance(name, str)
        or not _SAFE_NAME.fullmatch(name)
        or name in {".", ".."}
        or ".." in name
        or "/" in name
        or "\\" in name
    ):
        raise FetchError("unsafe file name")
    return name


class _IndexTable(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[list[str], str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
            self._href = ""
        elif tag == "td" and self._row is not None:
            self._cell = []
        elif tag == "a" and self._cell is not None and not self._href:
            self._href = dict(attrs).get("href") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append((self._row, self._href))
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _document_name(href: str) -> str:
    if not href or ".." in href or "\\" in href:
        raise FetchError("unsafe file name")
    if href.startswith("/") and not href.startswith("/Archives/edgar/data/"):
        raise FetchError("unsafe file name")
    if not href.startswith("/") and "/" in href:
        raise FetchError("unsafe file name")
    return _safe_file_name(href.rsplit("/", 1)[-1])


def _primary_documents(html: str) -> list[tuple[str, str]]:
    parser = _IndexTable()
    parser.feed(html)
    chosen: list[tuple[str, str]] = []
    for cells, href in parser.rows:
        kind = next((cell for cell in cells if cell in _PRIMARY_FORM), "")
        if not kind or not href:
            continue
        chosen.append((_document_name(href), kind))
    return chosen
