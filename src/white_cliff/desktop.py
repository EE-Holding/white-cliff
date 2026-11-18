"""A page on this computer for one company box and one explanation."""

from __future__ import annotations

import hashlib
import json
import secrets
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
    extra_submission_names,
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
    ENTER_BOTH,
    NO_10KQ,
    NO_INTERNET,
    NO_MATCH,
    ONLY_SEC,
    REFUSED,
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
from white_cliff.secclient import (
    DisallowedHost,
    RateLimiter,
    SecBusy,
    SecClient,
    SecStatus,
    SecUnreachable,
)


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
    idle: float = 30 * 60,
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
        self.token = secrets.token_urlsafe(32)
        self.limiter = RateLimiter(sleep=sleep, clock=clock)

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
                return Page(200, first_run_page(token=self.token))
            return Page(200, edit_page(token=self.token))
        if method == "POST" and path == "/explain":
            return self._lookup(form.get("query", ""), None)
        if method == "POST" and path == "/pick":
            return self._lookup("", form.get("cik", ""))
        if method == "GET" and path == "/":
            return self._home()
        return self._home()

    def _home(self) -> Page:
        if load_identity(self.identity_file) is None:
            return Page(200, first_run_page(token=self.token))
        return Page(200, search_page(token=self.token))

    def _save(self, form: dict[str, str]) -> Page:
        saved = save_identity(
            self.identity_file,
            form.get("name", ""),
            form.get("email", ""),
        )
        if saved is None:
            name = form.get("name", "")
            email = form.get("email", "")
            if load_identity(self.identity_file) is None:
                return Page(
                    200,
                    first_run_page(
                        rejected=True, token=self.token, name=name, email=email
                    ),
                )
            return Page(
                200,
                edit_page(self.token, name=name, email=email, notice=ENTER_BOTH),
            )
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
            limiter=self.limiter,
        )

    def _lookup(self, query: str, cik: str | None) -> Page:
        client = self._client()
        if client is None:
            return Page(200, first_run_page(token=self.token))
        try:
            if cik:
                filing, explained, company = self._explain_cik(client, cik)
            else:
                found = self._search(client, query)
                if isinstance(found, SeveralMatches):
                    return Page(
                        200,
                        choices_page(SEVERAL, found.companies, self.token, query),
                    )
                if isinstance(found, NoMatch):
                    if found.close:
                        return Page(
                            200,
                            choices_page(CLOSE_INTRO, found.close, self.token, query),
                        )
                    return self._fail(NO_MATCH, query)
                if not isinstance(found, OneMatch):
                    return self._fail(NO_MATCH, query)
                filing, explained, company = self._explain_cik(
                    client, found.company.cik, found.company.title
                )
        except EmptyQuery:
            return self._fail(EMPTY_QUERY, query)
        except SecUnreachable:
            return self._fail(NO_INTERNET, query)
        except SecBusy:
            return self._fail(BUSY, query)
        except NoPeriodic:
            return self._fail(NO_10KQ, query)
        except DisallowedHost:
            return self._fail(ONLY_SEC, query)
        except (SecStatus, json.JSONDecodeError, UnicodeError):
            return self._fail(SEC_ODD, query)
        except (OutputRefused, ValueError):
            return self._fail(CANNOT_EXPLAIN, query)
        except Exception:
            return self._fail(CANNOT_EXPLAIN, query)
        return Page(
            200,
            result_page(
                explained,
                form=filing.form,
                period=filing.period,
                filed=filing.filed,
                url=filing.url,
                token=self.token,
                company=company,
            ),
        )

    def _fail(self, sentence: str, query: str) -> Page:
        return Page(200, error_page(sentence, token=self.token, query=query))

    def _search(self, client: SecClient, query: str):
        if not query.strip():
            raise EmptyQuery()
        payload = client.get(TICKERS_URL)
        companies = parse_tickers(payload)
        return resolve_company(query, companies)

    def _explain_cik(self, client: SecClient, cik: str, company: str = ""):
        payload = client.get(submissions_url(cik))
        data = json.loads(payload)
        extras = []
        for name in extra_submission_names(data, cik):
            extra_url = f"https://data.sec.gov/submissions/{name}"
            extras.append(json.loads(client.get(extra_url)))
        filing = select_latest(data, cik, extras)
        if filing is None:
            raise NoPeriodic()
        body = client.get(filing.url)
        directory = write_cache(self.cache, filing, body)
        loaded = load_directory(directory)
        explained = explain_filing(loaded)
        listed = company or str(data.get("name") or "")
        return filing, explained, listed


def _same(left: str, right: str) -> bool:
    if not left or not right or len(left) != len(right):
        return False
    return secrets.compare_digest(left, right)


def _host_name(header: str) -> str:
    host = header.strip()
    if host.startswith("["):
        end = host.find("]")
        return host[: end + 1] if end != -1 else host
    return host.split(":", 1)[0]


def _loopback_origin(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _local_origin(port: int) -> str:
    return "http://" + "local" + "host:" + str(port)


class _Handler(BaseHTTPRequestHandler):
    desktop: Desktop

    def log_message(self, _format: str, *_args) -> None:
        return

    def do_GET(self) -> None:
        self._respond("GET")

    def do_POST(self) -> None:
        self._respond("POST")

    def _port(self) -> int:
        return int(self.server.server_address[1])

    def _origins(self) -> tuple[str, str]:
        port = self._port()
        return _loopback_origin(port), _local_origin(port)

    def _from_here(self, value: str) -> bool:
        return any(value == origin or value.startswith(origin + "/") for origin in self._origins())

    def _post_allowed(self, form: dict[str, str]) -> bool:
        site = (self.headers.get("Sec-Fetch-Site") or "").casefold()
        if site in {"cross-site", "same-site"}:
            return False
        origin = self.headers.get("Origin")
        if origin is None:
            if not self._from_here(self.headers.get("Referer", "")):
                return False
        elif origin not in self._origins():
            return False
        return _same(form.get("token", ""), self.desktop.token)

    def _send(self, status: int, body: bytes, location: str = "") -> None:
        self.send_response(status)
        if location:
            self.send_header("Location", location)
        if body:
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _refused_page(self, path: str, form: dict[str, str]) -> str:
        token = self.desktop.token
        if path == "/identity":
            name = form.get("name", "")
            email = form.get("email", "")
            if load_identity(self.desktop.identity_file) is None:
                return first_run_page(token=token, name=name, email=email, notice=REFUSED)
            return edit_page(token, name=name, email=email, notice=REFUSED)
        if path == "/identity/erase":
            return edit_page(token, notice=REFUSED)
        return error_page(REFUSED, token=token, query=form.get("query", ""))

    def _respond(self, method: str) -> None:
        host = self.headers.get("Host", "")
        if not loopback_host(host):
            self._send(403, error_page(REFUSED, token=self.desktop.token).encode("utf-8"))
            return
        path = urllib.parse.urlsplit(self.path).path
        if method == "GET" and _host_name(host) == "localhost" and path != "/stay":
            self._send(302, b"", location=_loopback_origin(self._port()) + self.path)
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        if length < 0 or length > 10000:
            self._send(400, error_page(REFUSED, token=self.desktop.token).encode("utf-8"))
            return
        raw = self.rfile.read(length) if length else b""
        parsed = urllib.parse.parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True)
        form = {key: values[-1] for key, values in parsed.items()}
        if method == "POST" and not self._post_allowed(form):
            self._send(403, self._refused_page(path, form).encode("utf-8"))
            return
        try:
            page = self.desktop.handle(method, path, form)
        except Exception:
            page = Page(
                200,
                error_page(CANNOT_EXPLAIN, token=self.desktop.token, query=form.get("query", "")),
            )
        self._send(page.status, page.body.encode("utf-8"), page.location)


def make_server(desktop: Desktop) -> ThreadingHTTPServer:
    handler = type("WhiteCliffHandler", (_Handler,), {"desktop": desktop})
    return ThreadingHTTPServer(("127.0.0.1", 0), handler)
