"""First run, erase, and a lookup that never leaves sec.gov."""

import html
import json
import re
from pathlib import Path

import pytest

from white_cliff.desktop import Desktop, loopback_host, make_server, should_quit
from white_cliff.desktop_copy import (
    BUSY,
    CANNOT_EXPLAIN,
    DISCLAIMER,
    NO_10KQ,
    NO_INTERNET,
    NO_MATCH,
    SEC_WHY,
    SEVERAL,
)
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
    home.mkdir()
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
    assert "478834 USD millions" in page.body


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

    app.transport = transport
    missing = app.handle("POST", "/explain", {"query": "zzzznomatchqq"})
    assert NO_MATCH in missing.body
    assert "Apple" not in missing.body

    close = app.handle("POST", "/explain", {"query": "Microsft"})
    assert "No exact match. These names are on the SEC list." in close.body
    assert "MICROSOFT CORP" in close.body
    assert "Microsft" not in close.body

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
    busy = app.handle("POST", "/explain", {"query": "AAPL"})
    assert BUSY in busy.body
    assert "Traceback" not in busy.body


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


def test_rejected_identity_is_not_echoed(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    page = app.handle("POST", "/identity", {"name": "A", "email": "not-an-email"})
    assert "not-an-email" not in page.body
    assert "Enter your name and a full email address." in page.body
    assert not (app_data_dir() / "identity.json").exists()


def test_numbers_screen_starts_with_the_disclaimer(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    app.handle("POST", "/identity", {"name": NAME, "email": EMAIL})
    page = app.handle("POST", "/explain", {"query": "AAPL"})
    assert page.body.find(DISCLAIMER) < page.body.find("10-K")
    assert "period ended 2026-09-26" in page.body
    assert "filed 2026-10-31" in page.body
    assert html.escape(DOC, quote=True) in page.body or DOC in page.body


def test_server_binds_loopback_and_quits_when_idle():
    assert loopback_host("127.0.0.1:9")
    assert loopback_host("localhost")
    assert not loopback_host("example.com")
    assert should_quit(0, None, 119) is False
    assert should_quit(0, None, 120) is True
    assert should_quit(0, 50, 64) is False
    assert should_quit(0, 50, 65) is True


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
    assert "dependencies = []" in project
    assert "pywebview" not in project
    assert "pythonnet" not in project


def test_make_server_listens_on_loopback_only(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    server = make_server(app)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()
