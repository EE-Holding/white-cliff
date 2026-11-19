"""The bundled certificate file, and a failure log with nothing personal."""

import ssl
import urllib.error
from pathlib import Path

import certifi

from white_cliff.desktop_copy import BUSY, NO_INTERNET, SEC_CERT, SEC_ODD, SEC_REFUSED
from white_cliff.secclient import SecBusy, SecClient, SecRefused, SecStatus, SecTLS, SecUnreachable
from white_cliff.tls import _MAX_LOG, cafile, cafile_inside_bundle, log_failure, sec_context

TICKERS = "https://www.sec.gov/files/company_tickers.json"
UA = "Jane Doe jane@example.com"


def _clock():
    state = {"now": 0.0}

    def clock():
        return state["now"]

    def sleep(seconds):
        state["now"] += seconds

    return clock, sleep


def _client(transport):
    clock, sleep = _clock()
    return SecClient(UA, transport=transport, sleep=sleep, clock=clock)


def test_shared_context_loads_the_bundled_cas():
    path = cafile()
    assert path == certifi.where()
    assert Path(path).is_file()
    assert cafile_inside_bundle(path)
    context = sec_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.cert_store_stats()["x509_ca"] > 0
    assert sec_context() is context


def test_a_certificate_error_is_not_the_offline_message():
    def transport(url, user_agent):
        raise urllib.error.URLError(ssl.SSLCertVerificationError("certificate verify failed"))

    client = _client(transport)
    try:
        client.get(TICKERS)
    except SecTLS as exc:
        assert str(exc) == SEC_CERT
        assert NO_INTERNET not in str(exc)
    else:
        raise AssertionError("expected a certificate failure")


def test_each_transport_failure_has_its_own_sentence():
    def offline(url, user_agent):
        raise OSError("nodename nor servname")

    try:
        _client(offline).get(TICKERS)
    except SecUnreachable as exc:
        assert str(exc) == NO_INTERNET
        assert SEC_CERT not in str(exc)
    else:
        raise AssertionError("expected no network")

    def denied(url, user_agent):
        return 403, b"no", {}

    try:
        _client(denied).get(TICKERS)
    except SecRefused as exc:
        assert str(exc) == SEC_REFUSED
        assert str(exc) != BUSY
        assert NO_INTERNET not in str(exc)
    else:
        raise AssertionError("expected a refusal")

    def other(url, user_agent):
        return 500, b"no", {}

    try:
        _client(other).get(TICKERS)
    except SecStatus as exc:
        assert str(exc) == SEC_ODD
    else:
        raise AssertionError("expected an odd status")

    def busy(url, user_agent):
        return 429, b"no", {}

    try:
        _client(busy).get(TICKERS)
    except SecBusy as exc:
        assert str(exc) == BUSY
    else:
        raise AssertionError("expected busy")


def test_jane_doe_is_sent_unchanged():
    seen = []

    def transport(url, user_agent):
        seen.append(user_agent)
        return 200, b"ok", {}

    assert _client(transport).get(TICKERS) == b"ok"
    assert seen == [UA]


def test_log_keeps_class_host_and_status_only(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr("white_cliff.identity.sys.platform", "linux")
    contact = "jane" + "@" + "example.com"
    dirty = "https://www.sec.gov/files/company_tickers.json?name=Jane+Doe&contact=" + contact
    hidden = "https://user:secret@" + "www.sec.gov/private?token=abc"
    log_failure("SSLCertVerificationError", dirty, None)
    log_failure("HTTPError", hidden, 403)
    text = (tmp_path / "White Cliff" / "white-cliff.log").read_text(encoding="ascii")
    assert text == "SSLCertVerificationError www.sec.gov -\nHTTPError www.sec.gov 403\n"
    lowered = text.casefold()
    assert "jane" not in lowered
    assert "@" not in text
    assert "token" not in lowered
    assert "secret" not in lowered
    assert "doe" not in lowered


def test_log_stays_under_one_megabyte(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr("white_cliff.identity.sys.platform", "linux")
    monkeypatch.setattr("white_cliff.tls._MAX_LOG", 80)
    assert _MAX_LOG == 1_000_000
    for number in range(20):
        log_failure(f"OSError{number}", "https://data.sec.gov/x", None)
    path = tmp_path / "White Cliff" / "white-cliff.log"
    assert path.stat().st_size <= 80
    assert "OSError19" in path.read_text(encoding="ascii")
    assert "OSError0 " not in path.read_text(encoding="ascii")


def test_unwritable_log_folder_keeps_the_offline_message(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr("white_cliff.identity.sys.platform", "linux")
    folder = tmp_path / "White Cliff"
    folder.mkdir()
    folder.chmod(0o500)

    def transport(url, user_agent):
        raise OSError("network is down")

    try:
        _client(transport).get(TICKERS)
    except SecUnreachable as exc:
        assert str(exc) == NO_INTERNET
    else:
        raise AssertionError("expected the offline message")
