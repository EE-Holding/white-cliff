"""A page on this computer for one company box and one explanation."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from white_cliff.companies import (
    NoMatch,
    OneMatch,
    PeriodicFiling,
    SeveralMatches,
    TICKERS_URL,
    parse_tickers,
    resolve_company,
    select_latest,
    submissions_url,
)
from white_cliff.desktop_copy import (
    BUSY,
    CANNOT_EXPLAIN,
    CLOSE_INTRO,
    EMPTY_QUERY,
    NO_10KQ,
    NO_INTERNET,
    NO_MATCH,
    ONLY_SEC,
    SEC_ODD,
    SEVERAL,
)
from white_cliff.disclaimer import OutputRefused
from white_cliff.fetch import strip_edgar_script
from white_cliff.identity import app_data_dir, cache_dir, erase_identity, load_identity, save_identity
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.present import (
    choices_page,
    edit_page,
    error_page,
    first_run_page,
    result_page,
    search_page,
)
from white_cliff.secclient import DisallowedHost, SecBusy, SecClient, SecStatus, SecUnreachable


class EmptyQuery(Exception):
    pass


class NoPeriodic(Exception):
    pass


@dataclass
class Page:
    status: int
    body: str
    location: str = ""


def should_quit(
    started: float,
    last_seen: float | None,
    now: float,
    *,
    startup: float = 120,
    idle: float = 15,
) -> bool:
    if last_seen is None:
        return now - started >= startup
    return now - last_seen >= idle


def loopback_host(value: str) -> bool:
    host = value.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        host = host[1:end] if end != -1 else host
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host in {"127.0.0.1", "localhost"}


def write_cache(cache: Path, filing: PeriodicFiling, body: bytes) -> Path:
    dest = cache / filing.accession
    dest.mkdir(parents=True, exist_ok=True)
    (dest / filing.document).write_bytes(body)
    retrieved = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {
        "name": filing.document,
        "url": filing.url,
        "sha256": hashlib.sha256(body).hexdigest(),
        "content_sha256": hashlib.sha256(strip_edgar_script(body)).hexdigest(),
        "retrieved_at": retrieved,
        "document_type": filing.form,
    }
    provenance = {
        "accession": filing.accession,
        "cik": filing.cik,
        "form": filing.form,
        "files": [record],
    }
    (dest / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n",
        encoding="utf-8",
    )
    return dest


class Desktop:
    def __init__(self, identity_file: Path, cache: Path, transport, sleep, clock) -> None:
        self.identity_file = identity_file
        self.cache = cache
        self.transport = transport
        self.sleep = sleep
        self.clock = clock
        self.last_seen: float | None = None

    @classmethod
    def create(cls, transport=None, sleep=time.sleep, clock=time.monotonic):
        return cls(app_data_dir() / "identity.json", cache_dir(), transport, sleep, clock)

    def handle(self, method: str, path: str, form: dict[str, str]) -> Page:
        self.last_seen = self.clock()
        path = path.split("?", 1)[0] or "/"
        if path == "/stay":
            return Page(204, "")
        if method == "POST" and path == "/identity":
            return self._save(form)
        if method == "POST" and path == "/identity/erase":
            erase_identity(self.identity_file)
            return Page(303, "", location="/")
        if method == "GET" and path == "/identity":
            if load_identity(self.identity_file) is None:
                return Page(200, first_run_page())
            return Page(200, edit_page())
        if method == "POST" and path == "/explain":
            return self._lookup(form.get("query", ""), None)
        if method == "POST" and path == "/pick":
            return self._lookup("", form.get("cik", ""))
        if method == "GET" and path == "/":
            return self._home()
        return self._home()

    def _home(self) -> Page:
        if load_identity(self.identity_file) is None:
            return Page(200, first_run_page())
        return Page(200, search_page())

    def _save(self, form: dict[str, str]) -> Page:
        saved = save_identity(
            self.identity_file,
            form.get("name", ""),
            form.get("email", ""),
        )
        if saved is None:
            return Page(200, first_run_page(rejected=True))
        return Page(303, "", location="/")

    def _client(self) -> SecClient | None:
        identity = load_identity(self.identity_file)
        if identity is None:
            return None
        return SecClient(
            identity.user_agent,
            transport=self.transport,
            sleep=self.sleep,
            clock=self.clock,
        )

    def _lookup(self, query: str, cik: str | None) -> Page:
        client = self._client()
        if client is None:
            return Page(200, first_run_page())
        try:
            if cik:
                filing, explained = self._explain_cik(client, cik)
            else:
                found = self._search(client, query)
                if isinstance(found, SeveralMatches):
                    return Page(200, choices_page(SEVERAL, found.companies))
                if isinstance(found, NoMatch):
                    if found.close:
                        return Page(200, choices_page(CLOSE_INTRO, found.close))
                    return Page(200, error_page(NO_MATCH))
                if not isinstance(found, OneMatch):
                    return Page(200, error_page(NO_MATCH))
                filing, explained = self._explain_cik(client, found.company.cik)
        except EmptyQuery:
            return Page(200, error_page(EMPTY_QUERY))
        except SecUnreachable:
            return Page(200, error_page(NO_INTERNET))
        except SecBusy:
            return Page(200, error_page(BUSY))
        except NoPeriodic:
            return Page(200, error_page(NO_10KQ))
        except DisallowedHost:
            return Page(200, error_page(ONLY_SEC))
        except (SecStatus, json.JSONDecodeError, UnicodeError):
            return Page(200, error_page(SEC_ODD))
        except (OutputRefused, ValueError):
            return Page(200, error_page(CANNOT_EXPLAIN))
        except Exception:
            return Page(200, error_page(CANNOT_EXPLAIN))
        return Page(
            200,
            result_page(
                explained,
                form=filing.form,
                period=filing.period,
                filed=filing.filed,
                url=filing.url,
            ),
        )

    def _search(self, client: SecClient, query: str):
        if not query.strip():
            raise EmptyQuery()
        payload = client.get(TICKERS_URL)
        companies = parse_tickers(payload)
        return resolve_company(query, companies)

    def _explain_cik(self, client: SecClient, cik: str):
        payload = client.get(submissions_url(cik))
        data = json.loads(payload)
        filing = select_latest(data, cik)
        if filing is None:
            raise NoPeriodic()
        body = client.get(filing.url)
        directory = write_cache(self.cache, filing, body)
        loaded = load_directory(directory)
        explained = explain_filing(loaded)
        return filing, explained


class _Handler(BaseHTTPRequestHandler):
    desktop: Desktop

    def log_message(self, _format: str, *_args) -> None:
        return

    def do_GET(self) -> None:
        self._respond("GET")

    def do_POST(self) -> None:
        self._respond("POST")

    def _respond(self, method: str) -> None:
        if not loopback_host(self.headers.get("Host", "")):
            self.send_response(403)
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        if length < 0 or length > 10000:
            self.send_response(400)
            self.end_headers()
            return
        raw = self.rfile.read(length) if length else b""
        parsed = urllib.parse.parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True)
        form = {key: values[-1] for key, values in parsed.items()}
        path = urllib.parse.urlsplit(self.path).path
        try:
            page = self.desktop.handle(method, path, form)
        except Exception:
            page = Page(200, error_page(CANNOT_EXPLAIN))
        body = page.body.encode("utf-8")
        self.send_response(page.status)
        if page.location:
            self.send_header("Location", page.location)
        if body:
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)


def make_server(desktop: Desktop) -> ThreadingHTTPServer:
    handler = type("WhiteCliffHandler", (_Handler,), {"desktop": desktop})
    return ThreadingHTTPServer(("127.0.0.1", 0), handler)
