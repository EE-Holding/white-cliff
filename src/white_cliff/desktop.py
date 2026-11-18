"""A page on this computer for one company box and one explanation."""

from __future__ import annotations

import email
import hashlib
import json
import secrets
import time
import urllib.parse
from email import policy
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
    quarterly_filings,
    select_latest,
    submissions_url,
)
from white_cliff.compare import PriorCandidate, choose_prior_10q, day_gap, same_fiscal_year_end
from white_cliff.desktop_copy import (
    BUSY,
    CANNOT_EXPLAIN,
    CLOSE_INTRO,
    EMPTY_QUERY,
    ENTER_BOTH,
    FILING_LIST,
    FINDING,
    NO_10KQ,
    NO_INTERNET,
    NO_MATCH,
    ONLY_SEC,
    READING,
    READING_PRIOR,
    REFUSED,
    SEC_CERT,
    SEC_ODD,
    SEC_REFUSED,
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
from white_cliff.thresholds import PRIOR_FILING_MAX, PRIOR_FILING_MIN
from white_cliff.secclient import (
    DisallowedHost,
    RateLimiter,
    SecBusy,
    SecClient,
    SecRefused,
    SecStatus,
    SecTLS,
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
    content_type: str = "text/html; charset=utf-8"


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
        self.step = ""
        self.step_n = 0
        self.reading = READING
        self.steps: list[str] = []

    @classmethod
    def create(cls, transport=None, sleep=time.sleep, clock=time.monotonic):
        return cls(app_data_dir() / "identity.json", cache_dir(), transport, sleep, clock)

    def handle(self, method: str, path: str, form: dict[str, str]) -> Page:
        self.last_seen = self.clock()
        path = path.split("?", 1)[0] or "/"
        if path == "/stay":
            return Page(204, "")
        if method == "GET" and path == "/progress":
            payload = json.dumps({"step": self.step_n, "reading": self.reading})
            return Page(200, payload, content_type="application/json; charset=utf-8")
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

    def _step(self, label: str) -> None:
        if self.steps and self.steps[-1] == READING and label == READING_PRIOR:
            self.steps[-1] = label
        elif not self.steps or self.steps[-1] != label:
            self.steps.append(label)
        self.step = label

    def _mark(self, number: int, reading: str | None = None) -> None:
        self.step_n = number
        if reading:
            self.reading = reading
        label = {1: FINDING, 2: FILING_LIST, 3: self.reading}[number]
        self._step(label)

    def _lookup(self, query: str, cik: str | None) -> Page:
        client = self._client()
        if client is None:
            return Page(200, first_run_page(token=self.token))
        self.steps = []
        self.step_n = 0
        self.reading = READING
        try:
            if cik:
                filing, explained, company, ticker, loaded, prior = self._explain_cik(client, cik)
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
                filing, explained, company, ticker, loaded, prior = self._explain_cik(
                    client, found.company.cik, found.company.title
                )
                ticker = found.company.ticker or ticker
        except EmptyQuery:
            return self._fail(EMPTY_QUERY, query)
        except SecTLS:
            return self._fail(SEC_CERT, query)
        except SecUnreachable:
            return self._fail(NO_INTERNET, query)
        except SecRefused:
            return self._fail(SEC_REFUSED, query)
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
                ticker=ticker,
                cik=filing.cik,
                focus=loaded.focus,
                fiscal_year_end=loaded.fiscal_year_end,
                prior_facts=prior.store.facts() if prior is not None else None,
                prior_end=prior.period_end if prior is not None else None,
            ),
        )

    def _fail(self, sentence: str, query: str) -> Page:
        return Page(200, error_page(sentence, token=self.token, query=query))

    def _search(self, client: SecClient, query: str):
        if not query.strip():
            raise EmptyQuery()
        self._mark(1)
        payload = client.get(TICKERS_URL)
        companies = parse_tickers(payload)
        return resolve_company(query, companies)

    def _explain_cik(self, client: SecClient, cik: str, company: str = ""):
        self._mark(2)
        payload = client.get(submissions_url(cik))
        data = json.loads(payload)
        extras = []
        for name in extra_submission_names(data, cik):
            extra_url = f"https://data.sec.gov/submissions/{name}"
            extras.append(json.loads(client.get(extra_url)))
        filing = select_latest(data, cik, extras)
        if filing is None:
            raise NoPeriodic()
        self._mark(3, READING)
        body = client.get(filing.url)
        directory = write_cache(self.cache, filing, body)
        loaded = load_directory(directory)
        explained = explain_filing(loaded)
        if self._fetches_earlier(data, extras, loaded):
            self._mark(3, READING_PRIOR)
        prior = self._prior_quarter(client, data, extras, loaded)
        listed = company or str(data.get("name") or "")
        raw_tickers = data.get("tickers") or []
        ticker = str(raw_tickers[0]).strip() if raw_tickers else ""
        return filing, explained, listed, ticker, loaded, prior

    def _fetches_earlier(self, data: dict, extras: list, loaded) -> bool:
        """True only when this lookup will download an earlier 10-Q."""
        if loaded.form != "10-Q" or loaded.focus not in {"Q2", "Q3"} or not loaded.period_end:
            return False
        for row in quarterly_filings(data, loaded.cik, extras):
            if row.form != "10-Q" or row.cik != loaded.cik:
                continue
            gap = day_gap(row.period, loaded.period_end)
            if gap is not None and PRIOR_FILING_MIN <= gap <= PRIOR_FILING_MAX:
                return True
        return False

    def _prior_quarter(self, client: SecClient, data: dict, extras: list, loaded):
        """The one prior 10-Q for a second or third quarter. A failure leaves the column blank."""
        if loaded.form != "10-Q" or loaded.focus not in {"Q2", "Q3"} or not loaded.period_end:
            return None
        fiscal = loaded.fiscal_year_end or str(data.get("fiscalYearEnd") or "")
        rows = quarterly_filings(data, loaded.cik, extras)
        candidates = []
        loaded_by_accession = {}
        for row in rows:
            if row.form != "10-Q" or row.cik != loaded.cik:
                continue
            gap = day_gap(row.period, loaded.period_end)
            if gap is None or gap < PRIOR_FILING_MIN or gap > PRIOR_FILING_MAX:
                continue
            year_end, parsed = self._load_prior(client, row)
            loaded_by_accession[row.accession] = parsed
            candidates.append(
                PriorCandidate(
                    form=row.form,
                    period_end=row.period,
                    fiscal_year_end=year_end,
                    cik=row.cik,
                    accession=row.accession,
                )
            )
        chosen = choose_prior_10q(loaded.period_end, fiscal, loaded.cik, candidates)
        if chosen is None:
            return None
        prior = loaded_by_accession.get(chosen.accession)
        if prior is None:
            return None
        if prior.fiscal_year_end and loaded.fiscal_year_end:
            if not same_fiscal_year_end(prior.fiscal_year_end, loaded.fiscal_year_end):
                return None
        return prior

    def _load_prior(self, client: SecClient, row):
        try:
            body = client.get(row.url)
            directory = write_cache(self.cache, row, body)
            parsed = load_directory(directory)
        except Exception:
            return "", None
        return parsed.fiscal_year_end or "", parsed


def _form_fields(raw: bytes, content_type: str) -> dict[str, str]:
    kind = content_type.split(";", 1)[0].strip().casefold()
    if kind == "multipart/form-data":
        header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
        message = email.message_from_bytes(header + raw, policy=policy.default)
        form: dict[str, str] = {}
        if message.is_multipart():
            for part in message.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if not name:
                    continue
                content = part.get_content()
                if isinstance(content, bytes):
                    content = content.decode("utf-8", "replace")
                form[str(name)] = str(content).strip("\r\n")
        return form
    parsed = urllib.parse.parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


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

    def _send(self, status: int, body: bytes, location: str = "", content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(status)
        if location:
            self.send_header("Location", location)
        if body:
            self.send_header("Content-Type", content_type)
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
        if method == "GET" and _host_name(host) == "localhost" and path not in {"/stay", "/progress"}:
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
        form = _form_fields(raw, self.headers.get("Content-Type", ""))
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
        self._send(page.status, page.body.encode("utf-8"), page.location, page.content_type)


def make_server(desktop: Desktop) -> ThreadingHTTPServer:
    handler = type("WhiteCliffHandler", (_Handler,), {"desktop": desktop})
    return ThreadingHTTPServer(("127.0.0.1", 0), handler)
