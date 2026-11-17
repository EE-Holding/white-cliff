import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from white_cliff.config import MissingUserAgent
from white_cliff.fetch import DisallowedHost, EdgarClient

ROOT = Path(__file__).resolve().parents[1]
UA = "Example Name name@example.com"
SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?i)(?:api[_-]?key|secret|password)\s*=\s*['\"][^'\"]{8,}['\"]"),
)
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".white-cliff-cache"}


class _Clock:
    def __init__(self) -> None:
        self.ticks = 0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.ticks / 1_000_000

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.ticks += int(round(seconds * 1_000_000))


def test_missing_user_agent_is_refused(tmp_path):
    with pytest.raises(MissingUserAgent):
        EdgarClient("")
    with pytest.raises(MissingUserAgent):
        EdgarClient("NameOnly")
    env = os.environ.copy()
    env.pop("WHITE_CLIFF_USER_AGENT", None)
    env["WHITE_CLIFF_CONFIG"] = str(tmp_path / "missing.toml")
    env["HOME"] = str(tmp_path)
    env["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-m", "white_cliff", "explain", "0000320193-26-000026"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert not re.search(r"\d", completed.stderr)


def test_rate_stays_at_or_under_ten_per_second():
    clock = _Clock()
    times: list[float] = []

    def transport(url, user_agent):
        times.append(clock.clock())
        return 200, b"ok", {}

    client = EdgarClient(UA, transport=transport, sleep=clock.sleep, clock=clock.clock, rate=10)
    for _ in range(20):
        client.get("https://www.sec.gov/Archives/edgar/data/1/index.json")
    assert len(times) == 20
    for start in times:
        count = sum(1 for moment in times if start <= moment < start + 1)
        assert count <= 10
    with pytest.raises(ValueError):
        EdgarClient(UA, rate=11)


def test_backoff_on_403_and_429():
    for status in (403, 429):
        clock = _Clock()
        replies = [status, status, 200]

        def transport(url, user_agent, replies=replies):
            return replies.pop(0), b"ok", {}

        client = EdgarClient(UA, transport=transport, sleep=clock.sleep, clock=clock.clock)
        assert client.get("https://data.sec.gov/submissions/CIK.json") == b"ok"
        assert 1.0 in clock.sleeps
        assert 2.0 in clock.sleeps


def test_non_edgar_hosts_are_refused():
    called = {"value": False}

    def transport(url, user_agent):
        called["value"] = True
        return 200, b"ok", {}

    client = EdgarClient(UA, transport=transport, sleep=lambda _seconds: None, clock=lambda: 0.0)
    for url in (
        "https://example.com/filing",
        "https://www.sec.gov.evil.example/Archives",
        "http://www.sec.gov/Archives/edgar/data/1/index.json",
    ):
        with pytest.raises(DisallowedHost):
            client.get(url)
    assert called["value"] is False


def test_provenance_records_hash_url_and_time(tmp_path):
    body = b"<xbrl>revenue</xbrl>"
    index = json.dumps({"directory": {"item": [{"name": "sample_htm.xml"}]}}).encode()
    seen: list[str] = []

    def transport(url, user_agent):
        assert user_agent == UA
        seen.append(url)
        if url.endswith("/index.json"):
            return 200, index, {}
        return 200, body, {}

    moment = datetime(2026, 11, 17, 17, 40, tzinfo=timezone.utc)
    client = EdgarClient(
        UA,
        transport=transport,
        sleep=lambda _seconds: None,
        clock=lambda: 0.0,
        now=lambda: moment,
    )
    dest = tmp_path / "filing"
    records = client.fetch_accession("0000320193-26-000026", dest, "0000320193")
    assert len(seen) == 2
    assert all(url.startswith("https://www.sec.gov/Archives/edgar/data/320193/") for url in seen)
    provenance = json.loads((dest / "provenance.json").read_text(encoding="utf-8"))
    assert records[0]["sha256"] == provenance["files"][0]["sha256"]
    assert records[0]["url"] == seen[1]
    assert records[0]["retrieved_at"] == "2026-11-17T17:40:00Z"
    import hashlib

    assert hashlib.sha256(body).hexdigest() == records[0]["sha256"]


def test_default_transport_does_not_follow_a_redirect():
    """urlopen must not send the User-Agent to the Location host."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

    from white_cliff.fetch import _default_transport

    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            if self.path == "/start":
                self.send_response(302)
                port = self.server.server_address[1]
                self.send_header("Location", f"http://127.0.0.1:{port}/evil")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"stolen")

        def log_message(self, fmt, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body, _headers = _default_transport(
            f"http://127.0.0.1:{port}/start",
            UA,
        )
    finally:
        server.shutdown()
    assert status == 302
    assert body == b""
    assert hits == ["/start"]


def test_redirects_to_another_host_are_refused():
    calls: list[str] = []

    def transport(url, user_agent):
        calls.append(url)
        return 302, b"", {"Location": "https://example.com/stolen"}

    client = EdgarClient(UA, transport=transport, sleep=lambda _seconds: None, clock=lambda: 0.0)
    with pytest.raises(DisallowedHost):
        client.get("https://www.sec.gov/Archives/edgar/data/1/index.json")
    assert calls == ["https://www.sec.gov/Archives/edgar/data/1/index.json"]


def test_retry_after_is_honoured_and_capped():
    clock = _Clock()
    replies = [429, 200]

    def transport(url, user_agent, replies=replies):
        if replies[0] == 429:
            replies.pop(0)
            return 429, b"", {"Retry-After": "3"}
        replies.pop(0)
        return 200, b"ok", {}

    client = EdgarClient(UA, transport=transport, sleep=clock.sleep, clock=clock.clock)
    assert client.get("https://www.sec.gov/Archives/edgar/data/1/index.json") == b"ok"
    assert 3.0 in clock.sleeps

    clock = _Clock()
    replies = [429, 200]

    def slow(url, user_agent, replies=replies):
        if replies[0] == 429:
            replies.pop(0)
            return 429, b"", {"Retry-After": "100000"}
        replies.pop(0)
        return 200, b"ok", {}

    client = EdgarClient(UA, transport=slow, sleep=clock.sleep, clock=clock.clock)
    assert client.get("https://data.sec.gov/submissions/CIK.json") == b"ok"
    assert clock.sleeps
    assert max(clock.sleeps) <= 30


def test_index_file_names_cannot_escape_the_directory(tmp_path):
    from white_cliff.fetch import FetchError

    index = json.dumps(
        {"directory": {"item": [{"name": "../evil.xml"}, {"name": "/tmp/evil.xml"}]}}
    ).encode()

    def transport(url, user_agent):
        return 200, index, {}

    client = EdgarClient(UA, transport=transport, sleep=lambda _seconds: None, clock=lambda: 0.0)
    with pytest.raises(FetchError):
        client.fetch_accession("0000320193-26-000026", tmp_path / "out", "320193")
    assert not (tmp_path / "evil.xml").exists()


def test_accession_lookup_uses_only_the_requested_filing():
    payload = {
        "hits": {
            "hits": [
                {"_id": "0000000001-00-000001:other.htm", "_source": {"ciks": ["0000000099"]}},
                {
                    "_id": "0001628280-26-010047:ko.htm",
                    "_source": {"ciks": ["0000021344"]},
                },
            ]
        }
    }

    def transport(url, user_agent):
        assert user_agent == UA
        assert url.startswith("https://efts.sec.gov/")
        assert "0001628280-26-010047" in url
        return 200, json.dumps(payload).encode(), {}

    client = EdgarClient(UA, transport=transport, sleep=lambda _seconds: None, clock=lambda: 0.0)
    assert client.cik_for_accession("0001628280-26-010047") == "0000021344"


def test_repository_and_package_have_no_secrets():
    roots = [ROOT, ROOT / "src" / "white_cliff"]
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix in {".png", ".jpg", ".gif", ".webp"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in SECRET_PATTERNS:
                assert pattern.search(text) is None, path
