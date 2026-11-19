"""First run, erase, and a lookup that never leaves sec.gov."""

import base64
import html
import http.client
import json
import os
import re
import shutil
import socket
import ssl
import struct
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from white_cliff.advice import advice_reason
from white_cliff.desktop import Desktop, loopback_host, make_server, should_quit
from white_cliff.desktop_copy import (
    BUSY,
    CANNOT_EXPLAIN,
    DISCLAIMER,
    NO_10KQ,
    NO_INTERNET,
    NO_MATCH,
    REFUSED,
    SEC_WHY,
    SEVERAL,
)
from white_cliff.desktop_main import Instance, pid_alive, read_instance, run_until_closed
from white_cliff.disclaimer import OutputRefused
from white_cliff.identity import app_data_dir, cache_dir
from white_cliff.pipeline import explain_filing, load_directory

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "desktop"
PINNED = ROOT / "pinned" / "filings" / "0000320193-26-000026"
NAME = "Example Person"
EMAIL = "person@example.com"
UA = f"{NAME} {EMAIL}"
DOC = (
    "https://www.sec.gov/Archives/edgar/data/320193/"
    "000032019326000026/aapl-20260926.htm"
)


@pytest.fixture(autouse=True)
def _no_live_network(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("live network")

    monkeypatch.setattr("white_cliff.secclient._default_transport", fail)


def _home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    monkeypatch.setenv("WHITE_CLIFF_USER_AGENT", "Other Name other@example.com")
    monkeypatch.setattr("white_cliff.identity.sys.platform", "darwin")
    return home


def _clock():
    state = {"now": 0.0}

    def clock():
        return state["now"]

    def sleep(seconds):
        state["now"] += seconds

    return clock, sleep


class _Transport:
    def __init__(self):
        self.calls = []
        self.apple = json.loads((FIXTURES / "submissions_apple.json").read_text(encoding="utf-8"))
        self.only8k = json.loads((FIXTURES / "submissions_8k.json").read_text(encoding="utf-8"))
        self.tickers = (FIXTURES / "company_tickers.json").read_bytes()
        self.document = (PINNED / "aapl-20260926.htm").read_bytes()
        self.status = 200

    def __call__(self, url, user_agent):
        host = url.split("/", 3)[2]
        assert host in {"www.sec.gov", "data.sec.gov"}
        self.calls.append((url, user_agent))
        if self.status in {403, 429}:
            return self.status, b"Traceback (most recent call last)", {}
        if url.endswith("/files/company_tickers.json"):
            return 200, self.tickers, {}
        if url.endswith("/submissions/CIK0000320193.json"):
            return 200, json.dumps(self.apple).encode("utf-8"), {}
        if url.endswith("/submissions/CIK0001000002.json"):
            return 200, json.dumps(self.only8k).encode("utf-8"), {}
        if url == DOC:
            return 200, self.document, {}
        raise AssertionError(url)


def _app(monkeypatch, tmp_path, transport=None):
    _home(monkeypatch, tmp_path)
    clock, sleep = _clock()
    return Desktop.create(transport=transport or _Transport(), sleep=sleep, clock=clock)


def test_first_run_sends_nothing_and_later_screens_do_not(monkeypatch, tmp_path):
    transport = _Transport()
    app = _app(monkeypatch, tmp_path, transport)
    home = app.handle("GET", "/", {})
    assert SEC_WHY in home.body
    assert 'name="name"' in home.body
    assert DISCLAIMER in home.body
    missed = app.handle("POST", "/explain", {"query": "AAPL"})
    assert SEC_WHY in missed.body
    assert transport.calls == []
    saved = app.handle("POST", "/identity", {"name": f"  {NAME}  ", "email": EMAIL})
    assert saved.location == "/"
    again = app.handle("GET", "/", {})
    assert 'name="name"' not in again.body
    assert 'name="query"' in again.body
    assert ">Explain<" in again.body
    assert 'method="post"' in again.body
    assert "Change my name and email" in again.body
    assert NAME not in again.body
    assert EMAIL not in again.body
    assert SEC_WHY not in again.body


def test_details_file_is_only_in_app_data_and_user_agent_matches(monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path)
    transport = _Transport()
    clock, sleep = _clock()
    app = Desktop.create(transport=transport, sleep=sleep, clock=clock)
    app.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    found = [
        item
        for item in home.rglob("*")
        if item.is_file() and (EMAIL.encode("ascii") in item.read_bytes() or NAME.encode("ascii") in item.read_bytes())
    ]
    assert found == [app_data_dir() / "identity.json"]
    page = app.handle("POST", "/explain", {"query": "aapl"})
    assert transport.calls
    assert {user_agent for _url, user_agent in transport.calls} == {UA}
    assert "other@example.com" not in page.body
    assert NAME not in page.body
    assert EMAIL not in page.body
    cache_hits = [
        item
        for item in cache_dir().rglob("*")
        if item.is_file() and (EMAIL.encode("ascii") in item.read_bytes() or NAME.encode("ascii") in item.read_bytes())
    ]
    assert cache_hits == []
    explained = explain_filing(load_directory(PINNED))
    assert "478834 USD millions" in explained.markdown
    assert "$478,834 million" in page.body
    assert "https://www.sec.gov/" in page.body


def test_erase_returns_to_first_run_and_sends_nothing(monkeypatch, tmp_path):
    transport = _Transport()
    app = _app(monkeypatch, tmp_path, transport)
    app.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    edit = app.handle("GET", "/identity", {})
    assert "Erase" in edit.body
    assert NAME not in edit.body
    assert EMAIL not in edit.body
    assert 'value="' + NAME not in edit.body
    erased = app.handle("POST", "/identity/erase", {})
    assert erased.location == "/"
    assert not (app_data_dir() / "identity.json").exists()
    home = app.handle("GET", "/", {})
    assert SEC_WHY in home.body
    before = len(transport.calls)
    blocked = app.handle("POST", "/explain", {"query": "AAPL"})
    assert SEC_WHY in blocked.body
    assert len(transport.calls) == before


def test_plain_failures(monkeypatch, tmp_path):
    transport = _Transport()
    app = _app(monkeypatch, tmp_path, transport)
    app.handle("POST", "/identity", {"name": NAME, "email": EMAIL})

    def offline(url, user_agent):
        raise OSError("Traceback (most recent call last)")

    app.transport = offline
    page = app.handle("POST", "/explain", {"query": "AAPL"})
    assert NO_INTERNET in page.body
    assert "Traceback" not in page.body

    def broken(url, user_agent):
        raise ssl.SSLCertVerificationError("certificate verify failed")

    app.transport = broken
    certificate = app.handle("POST", "/explain", {"query": "AAPL"})
    assert "could not confirm the connection" in certificate.body
    assert NO_INTERNET not in certificate.body

    def refused(url, user_agent):
        return 403, b"no", {}

    app.transport = refused
    denial = app.handle("POST", "/explain", {"query": "AAPL"})
    assert "did not accept the name and email" in denial.body
    assert NO_INTERNET not in denial.body
    assert BUSY not in denial.body

    app.transport = transport
    missing = app.handle("POST", "/explain", {"query": "zzzznomatchqq"})
    assert NO_MATCH in missing.body
    assert "Apple" not in missing.body

    close = app.handle("POST", "/explain", {"query": "Microsft"})
    assert "No exact match. These names are on the SEC list." in close.body
    assert "MICROSOFT CORP" in close.body
    assert 'value="Microsft"' in close.body
    assert ">Microsft<" not in close.body

    several = app.handle("POST", "/explain", {"query": "Apple"})
    assert SEVERAL in several.body
    assert "Apple Inc." in several.body
    assert "Apple Hospitality REIT, Inc." in several.body

    only = app.handle("POST", "/explain", {"query": "ZZZZ"})
    assert NO_10KQ in only.body

    transport.status = 429
    busy = app.handle("POST", "/explain", {"query": "AAPL"})
    assert BUSY in busy.body
    assert "Traceback" not in busy.body
    transport.status = 403
    denied = app.handle("POST", "/explain", {"query": "AAPL"})
    assert "did not accept the name and email" in denied.body
    assert BUSY not in denied.body
    assert "Traceback" not in denied.body


def test_pipeline_refusal_hides_the_traceback(monkeypatch, tmp_path):
    transport = _Transport()
    app = _app(monkeypatch, tmp_path, transport)
    app.handle("POST", "/identity", {"name": NAME, "email": EMAIL})

    def boom(_filing):
        raise OutputRefused('Traceback (most recent call last)\nFile "secret.py"')

    monkeypatch.setattr("white_cliff.desktop.explain_filing", boom)
    page = app.handle("POST", "/explain", {"query": "AAPL"})
    assert CANNOT_EXPLAIN in page.body
    assert "Traceback" not in page.body
    assert "secret.py" not in page.body
    assert EMAIL not in page.body


def test_rejected_identity_keeps_what_was_typed(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    page = app.handle("POST", "/identity", {"name": "A", "email": "not-an-email"})
    assert 'value="A"' in page.body
    assert 'value="not-an-email"' in page.body
    assert "Enter your name and a full email address." in page.body
    assert 'class="failure"' in page.body
    assert not (app_data_dir() / "identity.json").exists()


def test_numbers_screen_starts_with_the_disclaimer(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    app.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    page = app.handle("POST", "/explain", {"query": "AAPL"})
    assert page.body.find(DISCLAIMER) < page.body.find("Annual report")
    assert "Annual report for the year ended September 26, 2026." in page.body
    assert "10-K" not in page.body
    assert "filed 2026-10-31" not in page.body
    assert html.escape(DOC, quote=True) in page.body or DOC in page.body


def test_server_binds_loopback_and_quits_when_idle():
    assert loopback_host("127.0.0.1:9")
    assert loopback_host("localhost")
    assert not loopback_host("example.com")
    assert should_quit(0, None, 119) is False
    assert should_quit(0, None, 120) is True
    assert should_quit(0, 0, (30 * 60) - 1) is False
    assert should_quit(0, 0, 30 * 60) is True


def test_desktop_source_contacts_only_sec_hosts():
    root = ROOT / "src" / "white_cliff"
    names = (
        "desktop.py",
        "desktop_main.py",
        "desktop_copy.py",
        "secclient.py",
        "companies.py",
        "present.py",
        "identity.py",
    )
    banned = ("googleapis", "sentry", "analytics", "telemetry", "jsdelivr", "unpkg")
    for name in names:
        text = (root / name).read_text(encoding="utf-8")
        for needle in banned:
            assert needle not in text
        for match in re.finditer(r"https?://([^/\"'\s]+)", text):
            host = match.group(1).split(":")[0]
            assert host in {"www.sec.gov", "data.sec.gov", "127.0.0.1"}
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dependencies = ["certifi"]' in project
    assert "pywebview" not in project
    assert "pythonnet" not in project


def test_make_server_listens_on_loopback_only(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    server = make_server(app)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


def _headers(response: http.client.HTTPResponse) -> dict[str, str]:
    return {key.lower(): value for key, value in response.getheaders()}


def _exchange(port: int, method: str, path: str, body: bytes = b"", headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    payload = response.read()
    status, fields = response.status, _headers(response)
    connection.close()
    return status, fields, payload


def _assert_unchanged(path: Path, before: bytes) -> None:
    assert path.read_bytes() == before


def test_cross_origin_posts_leave_the_identity_unchanged(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    app.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    before = app.identity_file.read_bytes()
    server = make_server(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    origin = f"http://127.0.0.1:{port}"
    stolen = urllib.parse.urlencode(
        {"name": "Stolen Name", "email": "stolen@example.com"}
    ).encode("ascii")
    try:
        status, fields, body = _exchange(port, "GET", "/")
        assert status == 200
        assert fields["x-frame-options"] == "DENY"
        assert fields["content-security-policy"] == "frame-ancestors 'none'"
        assert "set-cookie" not in fields
        match = re.search(r'name="token" value="([^"]*)"', body.decode("utf-8"))
        assert match
        token = match.group(1)

        def attack(extra, payload=stolen):
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                **extra,
            }
            code, attack_fields, attack_body = _exchange(
                port, "POST", "/identity", payload, headers
            )
            assert code == 403
            assert REFUSED.encode("utf-8") in attack_body
            assert b'value="stolen@example.com"' in attack_body
            assert b'name="name"' in attack_body
            assert b'name="email"' in attack_body
            assert token.encode("ascii") in attack_body
            assert b".submit(" not in attack_body
            assert b"requestSubmit" not in attack_body
            assert attack_fields["x-frame-options"] == "DENY"
            assert "frame-ancestors 'none'" in attack_fields["content-security-policy"]
            _assert_unchanged(app.identity_file, before)
            return code

        attack(
            {
                "Origin": "https://evil.example",
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "navigate",
            }
        )
        attack(
            {
                "Origin": "http://127.0.0.1:9",
                "Sec-Fetch-Site": "same-site",
                "Sec-Fetch-Mode": "no-cors",
                "Content-Type": "text/plain",
            }
        )
        attack({"Origin": "null"})
        attack({"Origin": origin, "Sec-Fetch-Site": "same-origin"})
        attack(
            {
                "Origin": origin,
                "Sec-Fetch-Site": "same-origin",
                "Cookie": f"wc={token}",
            },
            urllib.parse.urlencode(
                {"name": NAME, "email": "stolen@example.com", "token": "wrong-token"}
            ).encode("ascii"),
        )
        armed = urllib.parse.urlencode(
            {"name": NAME, "email": "stolen@example.com", "token": token}
        ).encode("ascii")
        attack(
            {
                "Origin": origin,
                "Sec-Fetch-Site": "cross-site",
                "Cookie": f"wc={token}",
            },
            armed,
        )
        attack(
            {
                "Origin": origin,
                "Sec-Fetch-Site": "same-site",
                "Sec-Fetch-Mode": "no-cors",
                "Cookie": f"wc={token}",
            },
            armed,
        )
        code, _, _ = _exchange(
            port,
            "POST",
            "/identity/erase",
            b"",
            {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
        )
        assert code == 403
        _assert_unchanged(app.identity_file, before)

        changed = urllib.parse.urlencode(
            {"name": NAME, "email": "other@example.com", "token": token}
        ).encode("ascii")
        code, _, _ = _exchange(
            port,
            "POST",
            "/identity",
            changed,
            {
                "Origin": origin,
                "Referer": origin + "/",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "navigate",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        assert code == 303
        assert b"other@example.com" in app.identity_file.read_bytes()
        kept = app.identity_file.read_bytes()
        code, _, _ = _exchange(
            port,
            "POST",
            "/identity",
            stolen,
            {
                "Origin": "https://evil.example",
                "Sec-Fetch-Site": "cross-site",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        assert code == 403
        assert app.identity_file.read_bytes() == kept
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_parallel_lookups_share_one_locked_limiter(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    calls = []
    state = {"now": 0.0}
    clock_lock = threading.Lock()
    tickers = (FIXTURES / "company_tickers.json").read_bytes()

    def clock():
        with clock_lock:
            return state["now"]

    def sleep(seconds):
        with clock_lock:
            state["now"] += float(seconds)

    def transport(url, user_agent):
        calls.append(clock())
        host = url.split("/", 3)[2]
        assert host in {"www.sec.gov", "data.sec.gov"}
        return 200, tickers, {}

    app = Desktop.create(transport=transport, sleep=sleep, clock=clock)
    app.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    assert type(app.limiter._lock) is type(threading.Lock())
    assert app._client().limiter is app.limiter
    errors = []

    def run():
        try:
            app.handle("POST", "/explain", {"query": "zzzznomatchqq"})
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(30)]
    for worker in threads:
        worker.start()
    for worker in threads:
        worker.join()
    assert errors == []
    assert len(calls) == 30
    ordered = sorted(calls)
    for start in ordered:
        count = sum(1 for stamp in ordered if start <= stamp < start + 1)
        assert count <= 10


def test_refused_pick_list_name_falls_back_to_ticker_and_cik(monkeypatch, tmp_path):
    hostile = "<script>alert(1)</script>"
    payload = json.dumps(
        {
            "0": {"cik_str": 99, "ticker": "EVIL", "title": hostile},
            "1": {"cik_str": 98, "ticker": "LONG", "title": hostile},
        }
    ).encode("utf-8")

    def transport(url, user_agent):
        return 200, payload, {}

    app = _app(monkeypatch, tmp_path, transport)
    app.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    page = app.handle("POST", "/explain", {"query": hostile})
    assert SEVERAL in page.body
    assert hostile not in page.body
    kept = 'value="&lt;script&gt;alert(1)&lt;/script&gt;"'
    assert kept in page.body
    assert "alert(1)" not in page.body.replace(kept, "")
    assert "EVIL" in page.body
    assert "0000000099" in page.body
    assert "LONG" in page.body
    assert "0000000098" in page.body
    assert advice_reason(re.sub(r"<[^>]+>", " ", page.body).replace(DISCLAIMER, " ")) is None


def test_an_extra_submission_page_is_read(monkeypatch, tmp_path):
    base = _Transport()
    base.apple["filings"]["recent"] = {
        "accessionNumber": ["0000320193-20-000001"],
        "filingDate": ["2020-05-01"],
        "reportDate": ["2020-03-28"],
        "form": ["10-Q"],
        "primaryDocument": ["old.htm"],
        "isInlineXBRL": [1],
    }
    base.apple["filings"]["files"] = [{"name": "CIK0000320193-submissions-001.json"}]
    extra = {
        "form": ["10-K"],
        "filingDate": ["2026-10-31"],
        "reportDate": ["2026-09-26"],
        "acceptanceDateTime": ["2026-10-31T10:00:00.000Z"],
        "accessionNumber": ["0000320193-26-000026"],
        "primaryDocument": ["aapl-20260926.htm"],
        "isInlineXBRL": [1],
    }

    def transport(url, user_agent):
        if url.endswith("CIK0000320193-submissions-001.json"):
            base.calls.append((url, user_agent))
            return 200, json.dumps(extra).encode("utf-8"), {}
        return base(url, user_agent)

    app = _app(monkeypatch, tmp_path, transport)
    app.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    page = app.handle("POST", "/explain", {"query": "AAPL"})
    assert any(url.endswith("CIK0000320193-submissions-001.json") for url, _ua in base.calls)
    assert "Annual report for the year ended September 26, 2026." in page.body
    assert "10-K" not in page.body
    assert "aapl-20260926.htm" in page.body


def test_ctrl_c_exits_without_a_traceback():
    class _Server:
        def __init__(self):
            self.shut = False

        def shutdown(self):
            self.shut = True

        def server_close(self):
            self.shut = True

    desktop = type("Desktop", (), {"last_seen": None})()
    server = _Server()

    def sleep(_seconds):
        raise KeyboardInterrupt

    code = run_until_closed(server, desktop, sleep=sleep, clock=lambda: 0)
    assert code == 0
    assert server.shut


def _serve(app):
    server = make_server(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _token(port: int) -> str:
    status, _fields, body = _exchange(port, "GET", "/")
    assert status == 200
    match = re.search(r'name="token" value="([^"]*)"', body.decode("utf-8"))
    assert match
    return match.group(1)


def test_two_instances_on_one_cookie_jar(monkeypatch, tmp_path):
    left_home = tmp_path / "left"
    right_home = tmp_path / "right"
    monkeypatch.setenv("HOME", str(left_home))
    app_a = _app(monkeypatch, left_home)
    app_a.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    monkeypatch.setenv("HOME", str(right_home))
    app_b = _app(monkeypatch, right_home)
    app_b.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    server_a = _serve(app_a)
    server_b = _serve(app_b)
    try:
        port_a = server_a.server_address[1]
        port_b = server_b.server_address[1]
        token_a = _token(port_a)
        token_b = _token(port_b)
        jar = f"wc={token_b}"
        for port, token, other in (
            (port_a, token_a, token_b),
            (port_b, token_b, token_a),
        ):
            origin = f"http://127.0.0.1:{port}"
            body = urllib.parse.urlencode({"query": "NVDA", "token": token}).encode("ascii")
            code, _fields, payload = _exchange(
                port,
                "POST",
                "/explain",
                body,
                {
                    "Origin": origin,
                    "Sec-Fetch-Site": "same-origin",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Cookie": jar if port == port_a else f"wc={other}",
                },
            )
            assert code == 200
            assert REFUSED.encode("utf-8") not in payload
            assert b'value="NVDA"' in payload
            assert b'class="failure"' in payload
    finally:
        server_a.shutdown()
        server_a.server_close()
        server_b.shutdown()
        server_b.server_close()


def test_localhost_host_and_origin_and_a_client_with_no_cookies(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    app.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    server = _serve(app)
    try:
        port = server.server_address[1]
        status, fields, _body = _exchange(
            port, "GET", "/", headers={"Host": f"localhost:{port}"}
        )
        assert status == 302
        assert fields["location"] == f"http://127.0.0.1:{port}/"
        token = _token(port)
        local = "http://" + "local" + "host:" + str(port)
        body = urllib.parse.urlencode({"query": "AAPL", "token": token}).encode("ascii")
        code, response_fields, payload = _exchange(
            port,
            "POST",
            "/explain",
            body,
            {
                "Host": f"localhost:{port}",
                "Origin": local,
                "Sec-Fetch-Site": "same-origin",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        assert "set-cookie" not in response_fields
        assert code == 200
        assert b"Annual report" in payload
        assert REFUSED.encode("utf-8") not in payload
    finally:
        server.shutdown()
        server.server_close()


def test_a_refused_identity_shows_setup_again(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    server = _serve(app)
    try:
        port = server.server_address[1]
        token = _token(port)
        typed = urllib.parse.urlencode(
            {"name": "Ada Example", "email": "ada@example.com", "token": "nope"}
        ).encode("ascii")
        code, _fields, payload = _exchange(
            port,
            "POST",
            "/identity",
            typed,
            {
                "Origin": f"http://127.0.0.1:{port}",
                "Sec-Fetch-Site": "same-origin",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        text = payload.decode("utf-8")
        assert code == 403
        assert REFUSED in text
        assert 'value="Ada Example"' in text
        assert 'value="ada@example.com"' in text
        assert f'value="{token}"' in text
        assert 'action="/identity"' in text
        assert 'id="query"' not in text
        assert ".submit(" not in text
        assert not (app_data_dir() / "identity.json").exists()
    finally:
        server.shutdown()
        server.server_close()


def test_csrf_matrix(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    app.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    server = _serve(app)
    try:
        port = server.server_address[1]
        token = _token(port)
        origins = {
            "missing": None,
            "loopback": f"http://127.0.0.1:{port}",
            "localhost": "http://" + "local" + "host:" + str(port),
            "null": "null",
            "evil": "https://evil.example",
        }
        sites = ("missing", "same-origin", "same-site", "cross-site")
        tokens = ("missing", "right", "wrong")
        refused = 0
        accepted = 0
        seen = 0
        for origin_name, site, token_name in (
            (origin_name, site, token_name)
            for origin_name in origins
            for site in sites
            for token_name in tokens
        ):
            seen += 1
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": "wc=from-the-other-instance",
            }
            if origin_name != "missing":
                headers["Origin"] = origins[origin_name]
            if site != "missing":
                headers["Sec-Fetch-Site"] = site
            fields = {"query": "NVDA"}
            if token_name == "right":
                fields["token"] = token
            elif token_name == "wrong":
                fields["token"] = "wrong-token"
            code, _fields, payload = _exchange(
                port,
                "POST",
                "/explain",
                urllib.parse.urlencode(fields).encode("ascii"),
                headers,
            )
            allowed = (
                origin_name in {"loopback", "localhost"}
                and site not in {"same-site", "cross-site"}
                and token_name == "right"
            )
            if allowed:
                assert code != 403
                assert REFUSED.encode("utf-8") not in payload
                accepted += 1
            else:
                assert code == 403, (origin_name, site, token_name, code)
                assert b'value="NVDA"' in payload
                assert b'class="failure"' in payload
                refused += 1
        assert seen == 60
        assert refused == 56
        assert accepted == 4
    finally:
        server.shutdown()
        server.server_close()


def test_a_dead_instance_does_not_keep_the_port(tmp_path):
    directory = tmp_path / "slot"
    directory.mkdir()
    dead = 2_000_000_000
    assert pid_alive(dead) is False
    (directory / "instance.port").write_text(f"{dead} 9\n", encoding="ascii")
    slot = Instance(directory)
    owner, url = slot.start_or_url(lambda _port: True, sleep=lambda _seconds: None)
    assert owner is True
    assert url is None
    slot.publish(9)
    record_pid, record_port = read_instance(directory)
    assert record_port == 9
    assert pid_alive(record_pid)
    quiet = Instance(directory)
    owner, url = quiet.start_or_url(lambda _port: False, sleep=lambda _seconds: None)
    assert owner is False
    assert url is None
    opened = Instance(tmp_path / "other")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "instance.port").write_text(
        f"{os.getpid()} 4321\n", encoding="ascii"
    )
    owner, url = opened.start_or_url(
        lambda port: port == 4321, sleep=lambda _seconds: None
    )
    assert owner is False
    assert url == "http://127.0.0.1:4321/"


def test_failures_keep_the_typed_query(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    app.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    missing = app.handle("POST", "/explain", {"query": "zzzznomatchqq"})
    assert 'value="zzzznomatchqq"' in missing.body
    assert 'class="failure"' in missing.body
    assert NO_MATCH in missing.body
    fresh = app.handle("GET", "/", {})
    assert 'class="failure"' not in fresh.body
    assert 'id="query" name="query" autocomplete="off" autofocus' in fresh.body


def test_a_multipart_post_is_accepted(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    app.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    server = _serve(app)
    try:
        port = server.server_address[1]
        token = _token(port)
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="token"\r\n\r\n'
            f"{token}\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="query"\r\n\r\n'
            "AAPL\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        code, _fields, payload = _exchange(
            port,
            "POST",
            "/explain",
            body,
            {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Origin": f"http://127.0.0.1:{port}",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        assert code == 200
        assert b"Annual report" in payload
        assert REFUSED.encode("utf-8") not in payload
    finally:
        server.shutdown()
        server.server_close()


def _stderr_text(path: Path) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return text[-4000:]


def _chrome_binary() -> str | None:
    for candidate in (
        os.environ.get("CHROME", ""),
        "/opt/google/chrome/chrome",
        "/usr/bin/google-chrome",
        shutil.which("google-chrome") or "",
        shutil.which("google-chrome-stable") or "",
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


class _DevTools:
    def __init__(self, ws_url: str) -> None:
        parsed = urllib.parse.urlsplit(ws_url)
        self.sock = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        host = f"{parsed.hostname}:{parsed.port}"
        self.sock.sendall(
            (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode("ascii")
        )
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            data += chunk
        if b" 101 " not in data.split(b"\r\n", 1)[0]:
            raise AssertionError(data[:200])
        self._buf = data.split(b"\r\n\r\n", 1)[1]
        self._next = 0

    def call(self, method: str, params: dict | None = None, timeout: float = 15):
        self._next += 1
        ident = self._next
        payload = json.dumps({"id": ident, "method": method, "params": params or {}}).encode()
        self._send(payload)
        deadline = time.time() + timeout
        while time.time() < deadline:
            message = self._read(deadline)
            if message is None:
                break
            data = json.loads(message)
            if data.get("id") == ident:
                if "error" in data:
                    raise AssertionError(data["error"])
                return data.get("result", {})
        raise AssertionError(method)

    def close(self) -> None:
        self.sock.close()

    def _send(self, payload: bytes) -> None:
        mask = os.urandom(4)
        header = bytearray([0x81])
        size = len(payload)
        if size < 126:
            header.append(0x80 | size)
        else:
            header.append(0x80 | 126)
            header.extend(struct.pack(">H", size))
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _fill(self, deadline: float) -> None:
        self.sock.settimeout(max(0.1, deadline - time.time()))
        chunk = self.sock.recv(65536)
        if not chunk:
            raise AssertionError("devtools closed")
        self._buf += chunk

    def _read(self, deadline: float):
        while len(self._buf) < 2:
            self._fill(deadline)
        first, second = self._buf[0], self._buf[1]
        opcode = first & 0x0F
        masked = second & 0x80
        length = second & 0x7F
        offset = 2
        if length == 126:
            while len(self._buf) < 4:
                self._fill(deadline)
            length = struct.unpack(">H", self._buf[2:4])[0]
            offset = 4
        elif length == 127:
            while len(self._buf) < 10:
                self._fill(deadline)
            length = struct.unpack(">Q", self._buf[2:10])[0]
            offset = 10
        extra = 4 if masked else 0
        while len(self._buf) < offset + extra + length:
            self._fill(deadline)
        if masked:
            mask = self._buf[offset : offset + 4]
            start = offset + 4
            payload = bytes(
                byte ^ mask[index % 4]
                for index, byte in enumerate(self._buf[start : start + length])
            )
        else:
            start = offset
            payload = self._buf[start : start + length]
        self._buf = self._buf[start + length :]
        if opcode == 0x8:
            raise AssertionError("devtools closed")
        if opcode != 0x1:
            return self._read(deadline)
        return payload.decode("utf-8")


def _eval(page: _DevTools, expression: str):
    result = page.call(
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": True},
    )
    remote = result.get("result", {})
    if remote.get("subtype") == "error" or "exceptionDetails" in result:
        raise AssertionError(result.get("exceptionDetails") or remote)
    return remote.get("value")


def _wait_text(page: _DevTools, needle: str, rounds: int = 80) -> str:
    seen = ""
    for _ in range(rounds):
        seen = _eval(page, "document.body ? document.body.innerText : ''") or ""
        if needle in seen and "did not accept" not in seen:
            return seen
        time.sleep(0.1)
    raise AssertionError(seen[:800])


def test_chrome_submits_setup_search_pick_and_erase(monkeypatch, tmp_path):
    binary = _chrome_binary()
    if binary is None:
        pytest.skip("chrome is not installed")
    app = _app(monkeypatch, tmp_path)
    server = _serve(app)
    debug = socket.socket()
    debug.bind(("127.0.0.1", 0))
    debug_port = debug.getsockname()[1]
    debug.close()
    profile = tmp_path / "chrome"
    stderr_path = tmp_path / "chrome-stderr.txt"
    stderr_file = open(stderr_path, "wb")
    chrome = subprocess.Popen(
        [
            binary,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            f"--remote-debugging-port={debug_port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=stderr_file,
    )
    page = None
    try:
        port = server.server_address[1]
        info = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if chrome.poll() is not None:
                stderr_file.close()
                raise AssertionError(
                    f"chrome exited {chrome.returncode}: {_stderr_text(stderr_path)}"
                )
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{debug_port}/json/list", timeout=0.5
                ) as response:
                    tabs = json.loads(response.read().decode("utf-8"))
                if tabs:
                    info = tabs[0]
                    break
            except (OSError, json.JSONDecodeError):
                time.sleep(0.1)
        if not info or not info.get("webSocketDebuggerUrl"):
            if not stderr_file.closed:
                stderr_file.close()
            detail = _stderr_text(stderr_path)
            message = "chrome did not open a debugging port within 30 seconds"
            if detail:
                message = f"{message}: {detail}"
            raise AssertionError(message)
        page = _DevTools(info["webSocketDebuggerUrl"])
        page.call("Page.enable")
        page.call("Runtime.enable")
        page.call("Page.navigate", {"url": f"http://127.0.0.1:{port}/"})
        _eval(
            page,
            """
            new Promise(function (resolve) {
              var ready = setInterval(function () {
                var form = document.querySelector('form[action="/identity"]');
                if (!form || !document.querySelector("#name")) return;
                clearInterval(ready);
                document.querySelector("#name").value = "Example Person";
                document.querySelector("#email").value = "person@example.com";
                form.requestSubmit();
                resolve("saved");
              }, 50);
            })
            """,
        )
        _wait_text(page, "Company name or ticker")
        _eval(
            page,
            """
            new Promise(function (resolve) {
              var form = document.querySelector('form[action="/explain"]');
              document.querySelector("#query").value = "Apple";
              form.requestSubmit();
              resolve("sent");
            })
            """,
        )
        choices = _wait_text(page, "Apple Inc.")
        assert "Pick one" in choices
        _eval(
            page,
            """
            new Promise(function (resolve) {
              var button = Array.from(document.querySelectorAll("button.choice")).find(function (item) {
                return item.textContent === "Apple Inc.";
              });
              button.form.requestSubmit(button);
              resolve("picked");
            })
            """,
        )
        result = _wait_text(page, "$478,834 million")
        assert "14,532,259 thousand shares" in result
        assert "48.8 percent" in result
        assert "did not accept" not in result
        try:
            _eval(page, "document.querySelector('a[href=\"/identity\"]').click(); 'open'")
        except AssertionError as exc:
            if "navigated" not in str(exc):
                raise
        _wait_text(page, "Erase")
        try:
            _eval(
                page,
                "document.querySelector('form[action=\"/identity/erase\"]').requestSubmit(); 'erased'",
            )
        except AssertionError as exc:
            if "navigated" not in str(exc):
                raise
        fresh = ""
        for _ in range(80):
            fresh = _eval(page, "document.body ? document.body.innerText : ''") or ""
            if (
                "Your name" in fresh
                and "Erase" not in fresh
                and not (app_data_dir() / "identity.json").exists()
            ):
                break
            time.sleep(0.1)
        else:
            raise AssertionError(fresh[:800])
        assert "Annual report" not in fresh
        assert not (app_data_dir() / "identity.json").exists()
    finally:
        if page is not None:
            page.close()
        chrome.kill()
        chrome.wait(timeout=5)
        if not stderr_file.closed:
            stderr_file.close()
        server.shutdown()
        server.server_close()


class _NvidiaTransport:
    """Serves NVIDIA's own 10-Qs. An Apple document is never returned for this CIK."""

    def __init__(self):
        self.calls = []
        root = ROOT / "pinned" / "filings"
        self.documents = {
            "000104581026000075/nvda-20260726.htm": (
                root / "0001045810-26-000075" / "nvda-20260726.htm"
            ).read_bytes(),
            "000104581026000052/nvda-20260426.htm": (
                root / "0001045810-26-000052" / "nvda-20260426.htm"
            ).read_bytes(),
        }
        self.submissions = json.dumps(
            {
                "cik": "0001045810",
                "name": "NVIDIA CORP",
                "fiscalYearEnd": "0131",
                "tickers": ["NVDA"],
                "filings": {
                    "recent": {
                        "form": ["10-Q", "10-Q"],
                        "filingDate": ["2026-08-26", "2026-05-20"],
                        "reportDate": ["2026-07-26", "2026-04-26"],
                        "accessionNumber": ["0001045810-26-000075", "0001045810-26-000052"],
                        "primaryDocument": ["nvda-20260726.htm", "nvda-20260426.htm"],
                        "acceptanceDateTime": [
                            "2026-08-26T16:00:00.000Z",
                            "2026-05-20T16:00:00.000Z",
                        ],
                        "isInlineXBRL": ["1", "1"],
                    }
                },
            }
        ).encode("utf-8")
        self.tickers = json.dumps(
            {"0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"}}
        ).encode("utf-8")

    def __call__(self, url, user_agent):
        host = url.split("/", 3)[2]
        assert host in {"www.sec.gov", "data.sec.gov"}
        assert "320193" not in url and "aapl" not in url
        self.calls.append((url, user_agent))
        if url.endswith("/files/company_tickers.json"):
            return 200, self.tickers, {}
        if url.endswith("/submissions/CIK0001045810.json"):
            return 200, self.submissions, {}
        for suffix, body in self.documents.items():
            if url.endswith(suffix):
                return 200, body, {}
        raise AssertionError(url)


def _quarter_html(period_end, start, fiscal_year_end, revenue, focus):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:us-gaap="http://fasb.org/us-gaap/2026"
      xmlns:dei="http://xbrl.sec.gov/dei/2026">
<body>
<xbrli:context id="c-q">
  <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{period_end}</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
<ix:nonNumeric name="dei:DocumentType" contextRef="c-q">10-Q</ix:nonNumeric>
<ix:nonNumeric name="dei:EntityRegistrantName" contextRef="c-q">Example Co</ix:nonNumeric>
<ix:nonNumeric name="dei:DocumentFiscalPeriodFocus" contextRef="c-q">{focus}</ix:nonNumeric>
<ix:nonNumeric name="dei:DocumentPeriodEndDate" contextRef="c-q">{period_end}</ix:nonNumeric>
<ix:nonNumeric name="dei:EntityCentralIndexKey" contextRef="c-q">0000000001</ix:nonNumeric>
<ix:nonNumeric name="dei:CurrentFiscalYearEndDate" contextRef="c-q">{fiscal_year_end}</ix:nonNumeric>
<ix:nonFraction name="us-gaap:Revenues" contextRef="c-q" unitRef="usd" decimals="0">{revenue}</ix:nonFraction>
</body>
</html>
""".encode("utf-8")


class _CalendarTransport:
    def __init__(self):
        self.calls = []
        self.current = _quarter_html("2026-07-26", "2026-04-27", "--01-31", "888001", "Q2")
        self.prior = _quarter_html("2026-04-26", "2026-01-26", "--06-30", "777001", "Q1")
        self.submissions = json.dumps(
            {
                "cik": "0000000001",
                "name": "Example Co",
                "fiscalYearEnd": "0131",
                "tickers": ["EX"],
                "filings": {
                    "recent": {
                        "form": ["10-Q", "10-Q"],
                        "filingDate": ["2026-08-20", "2026-05-20"],
                        "reportDate": ["2026-07-26", "2026-04-26"],
                        "accessionNumber": ["0000000001-26-000002", "0000000001-26-000001"],
                        "primaryDocument": ["current.htm", "prior.htm"],
                        "acceptanceDateTime": [
                            "2026-08-20T16:00:00.000Z",
                            "2026-05-20T16:00:00.000Z",
                        ],
                        "isInlineXBRL": ["1", "1"],
                    }
                },
            }
        ).encode("utf-8")
        self.tickers = json.dumps(
            {"0": {"cik_str": 1, "ticker": "EX", "title": "Example Co"}}
        ).encode("utf-8")

    def __call__(self, url, user_agent):
        host = url.split("/", 3)[2]
        assert host in {"www.sec.gov", "data.sec.gov"}
        self.calls.append(url)
        if url.endswith("/files/company_tickers.json"):
            return 200, self.tickers, {}
        if url.endswith("/submissions/CIK0000000001.json"):
            return 200, self.submissions, {}
        if url.endswith("/current.htm"):
            return 200, self.current, {}
        if url.endswith("/prior.htm"):
            return 200, self.prior, {}
        raise AssertionError(url)


def test_a_prior_quarter_from_before_a_fiscal_year_change_is_not_used(monkeypatch, tmp_path):
    from white_cliff import desktop as desktop_module

    seen = []
    real = desktop_module.choose_prior_10q

    def spy(current_end, current_fy, current_cik, candidates):
        seen.extend(candidates)
        return real(current_end, current_fy, current_cik, candidates)

    monkeypatch.setattr(desktop_module, "choose_prior_10q", spy)
    app = _app(monkeypatch, tmp_path, _CalendarTransport())
    app.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    page = app.handle("POST", "/explain", {"query": "EX"})
    assert seen and seen[0].fiscal_year_end == "--06-30"
    assert "777,001" not in page.body
    assert "$888,001" in page.body
    assert "Revenue for the prior quarter is not in the filings White Cliff read, so no change is shown." in page.body


class _FirstQuarterTransport:
    def __init__(self):
        self.calls = []
        self.current = _quarter_html("2026-04-26", "2026-01-27", "--01-31", "100", "Q1")
        self.submissions = json.dumps(
            {
                "cik": "0000000001",
                "name": "Example Co",
                "fiscalYearEnd": "0131",
                "tickers": ["EX"],
                "filings": {
                    "recent": {
                        "form": ["10-Q"],
                        "filingDate": ["2026-05-20"],
                        "reportDate": ["2026-04-26"],
                        "accessionNumber": ["0000000001-26-000001"],
                        "primaryDocument": ["current.htm"],
                        "acceptanceDateTime": ["2026-05-20T16:00:00.000Z"],
                        "isInlineXBRL": ["1"],
                    }
                },
            }
        ).encode("utf-8")
        self.tickers = json.dumps(
            {"0": {"cik_str": 1, "ticker": "EX", "title": "Example Co"}}
        ).encode("utf-8")

    def __call__(self, url, user_agent):
        host = url.split("/", 3)[2]
        assert host in {"www.sec.gov", "data.sec.gov"}
        self.calls.append(url)
        if url.endswith("/files/company_tickers.json"):
            return 200, self.tickers, {}
        if url.endswith("/submissions/CIK0000000001.json"):
            return 200, self.submissions, {}
        if url.endswith("/current.htm"):
            return 200, self.current, {}
        raise AssertionError(url)


def test_step_labels_name_an_earlier_quarter_only_when_it_is_fetched(monkeypatch, tmp_path):
    holder: dict[str, Desktop] = {}

    class _Watching(_NvidiaTransport):
        def __call__(self, url, user_agent):
            app = holder["app"]
            if url.endswith("/files/company_tickers.json"):
                assert app.step_n == 1
            elif "/submissions/" in url:
                assert app.step_n == 2
            elif url.endswith(".htm"):
                assert app.step_n == 3
            return super().__call__(url, user_agent)

    nvidia = _Watching()
    app = _app(monkeypatch, tmp_path, nvidia)
    holder["app"] = app
    app.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    app.handle("POST", "/explain", {"query": "NVDA"})
    assert app.steps == [
        "Finding the company",
        "Getting the filing list",
        "Reading the filing and the earlier quarter",
    ]
    progress = app.handle("GET", "/progress", {})
    reported = json.loads(progress.body)
    assert list(reported) == ["step"]
    assert reported["step"] == 3
    assert progress.content_type.startswith("application/json")
    assert any(url.endswith("nvda-20260426.htm") for url, _user_agent in nvidia.calls)

    annual = _app(monkeypatch, tmp_path, _Transport())
    annual.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    annual.handle("POST", "/explain", {"query": "AAPL"})
    assert annual.steps == [
        "Finding the company",
        "Getting the filing list",
        "Reading the filing",
    ]
    assert "Reading the filing and the earlier quarter" not in annual.steps

    first = _FirstQuarterTransport()
    quarter = _app(monkeypatch, tmp_path, first)
    quarter.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    quarter.handle("POST", "/explain", {"query": "EX"})
    assert quarter.steps == [
        "Finding the company",
        "Getting the filing list",
        "Reading the filing",
    ]
    assert not any(url.endswith("prior.htm") for url in first.calls)


def test_progress_refuses_a_missing_or_wrong_token_and_a_cross_origin_request(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    server = make_server(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    origin = f"http://127.0.0.1:{port}"
    try:
        status, _, body = _exchange(port, "GET", "/")
        assert status == 200
        match = re.search(r'name="token" value="([^"]*)"', body.decode("utf-8"))
        assert match
        token = match.group(1)

        def progress(path, headers):
            return _exchange(port, "GET", path, headers=headers)

        same = {"Origin": origin, "Sec-Fetch-Site": "same-origin", "Referer": origin + "/"}
        missing, _, missing_body = progress("/progress", same)
        assert missing == 403
        assert not missing_body.startswith(b"{")
        wrong, _, _ = progress("/progress?token=wrong-token", same)
        assert wrong == 403
        quoted = urllib.parse.quote(token, safe="")
        cross, _, cross_body = progress(
            "/progress?token=" + quoted,
            {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
        )
        assert cross == 403
        assert REFUSED.encode("utf-8") in cross_body
        assert not cross_body.lstrip().startswith(b"{")
        code, fields, payload = progress("/progress?token=" + quoted, same)
        assert code == 200
        assert fields["cache-control"] == "no-store"
        assert fields["content-type"].startswith("application/json")
        assert json.loads(payload) == {"step": 0}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_nvidia_lookup_reads_the_nvidia_filing(monkeypatch, tmp_path):
    transport = _NvidiaTransport()
    app = _app(monkeypatch, tmp_path, transport)
    app.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    page = app.handle("POST", "/explain", {"query": "NVDA"})
    assert "$96,221 million" in page.body
    assert "These checks compare the company" in page.body
    assert "320193" not in page.body
    assert "aapl-" not in page.body
    assert any("/1045810/" in url for url, _user_agent in transport.calls)
    assert any(url.endswith("nvda-20260426.htm") for url, _user_agent in transport.calls)


def _chrome_page(binary: str, profile: Path, stderr_path: Path):
    debug = socket.socket()
    debug.bind(("127.0.0.1", 0))
    debug_port = debug.getsockname()[1]
    debug.close()
    stderr_file = open(stderr_path, "wb")
    chrome = subprocess.Popen(
        [
            binary,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--window-size=1280,900",
            f"--remote-debugging-port={debug_port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=stderr_file,
    )
    info = None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if chrome.poll() is not None:
            stderr_file.close()
            raise AssertionError(
                f"chrome exited {chrome.returncode}: {_stderr_text(stderr_path)}"
            )
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{debug_port}/json/list", timeout=0.5
            ) as response:
                tabs = json.loads(response.read().decode("utf-8"))
            if tabs and tabs[0].get("webSocketDebuggerUrl"):
                info = tabs[0]
                break
        except (OSError, json.JSONDecodeError):
            time.sleep(0.1)
    if not info or not info.get("webSocketDebuggerUrl"):
        if not stderr_file.closed:
            stderr_file.close()
        detail = _stderr_text(stderr_path)
        message = "chrome did not open a debugging port within 30 seconds"
        if detail:
            message = f"{message}: {detail}"
        chrome.kill()
        raise AssertionError(message)
    return chrome, stderr_file, _DevTools(info["webSocketDebuggerUrl"])


def test_chrome_nvidia_result_has_figures_and_an_open_explanation(monkeypatch, tmp_path):
    binary = _chrome_binary()
    if binary is None:
        pytest.skip("chrome is not installed")
    app = _app(monkeypatch, tmp_path, _NvidiaTransport())
    server = _serve(app)
    stderr_path = tmp_path / "chrome-nvda-stderr.txt"
    chrome, stderr_file, page = _chrome_page(binary, tmp_path / "chrome-nvda", stderr_path)
    try:
        port = server.server_address[1]
        page.call("Page.enable")
        page.call("Runtime.enable")
        page.call("Page.navigate", {"url": f"http://127.0.0.1:{port}/"})
        _eval(
            page,
            """
            new Promise(function (resolve) {
              var ready = setInterval(function () {
                var form = document.querySelector('form[action="/identity"]');
                if (!form || !document.querySelector("#name")) return;
                clearInterval(ready);
                document.querySelector("#name").value = "Example Person";
                document.querySelector("#email").value = "person@example.com";
                form.requestSubmit();
                resolve("saved");
              }, 50);
            })
            """,
        )
        _wait_text(page, "Company name or ticker")
        _eval(
            page,
            """
            new Promise(function (resolve) {
              var form = document.querySelector('form[action="/explain"]');
              document.querySelector("#query").value = "NVDA";
              form.requestSubmit();
              resolve("sent");
            })
            """,
        )
        result = _wait_text(page, "$96,221 million", rounds=200)
        assert "These checks compare the company" in result
        assert "Apple" not in result
        _eval(
            page,
            """
            new Promise(function (resolve) {
              var button = Array.from(document.querySelectorAll("button.tap")).find(function (item) {
                return item.textContent === "Explain";
              });
              button.click();
              resolve(button.getAttribute("aria-expanded"));
            })
            """,
        )
        opened = _wait_text(page, "the amount the company recorded from sales")
        assert "These checks compare the company" in opened
        shot = page.call(
            "Page.captureScreenshot",
            {"format": "png", "captureBeyondViewport": True, "fromSurface": True},
        )
        image = base64.b64decode(shot["data"])
        assert image.startswith(b"\x89PNG")
    finally:
        page.close()
        chrome.kill()
        chrome.wait(timeout=5)
        if not stderr_file.closed:
            stderr_file.close()
        server.shutdown()
        server.server_close()
