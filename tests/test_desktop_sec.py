"""Requests stay on sec.gov, use the saved User-Agent, and back off."""

import pytest

from white_cliff.secclient import DisallowedHost, SecBusy, SecClient, SecUnreachable, host_allowed

UA = "Example Person person@example.com"
TICKERS = "https://www.sec.gov/files/company_tickers.json"


def _clock():
    state = {"now": 0.0}
    slept = []

    def clock():
        return state["now"]

    def sleep(seconds):
        slept.append(seconds)
        state["now"] += seconds

    return clock, sleep, slept


def _client(transport, rate=10):
    clock, sleep, slept = _clock()
    client = SecClient(UA, transport=transport, sleep=sleep, clock=clock, rate=rate)
    return client, slept


def test_other_hosts_are_never_called():
    seen = []

    def transport(url, user_agent):
        seen.append(url)
        return 200, b"{}", {}

    client, _slept = _client(transport)
    for url in (
        "https://efts.sec.gov/LATEST/search-index?q=1",
        "https://example.com/file",
        "http://www.sec.gov/files/company_tickers.json",
        "https://www.sec.gov:8443/files/company_tickers.json",
        "https://www.sec.gov.evil.com/files/company_tickers.json",
        "https://user:pw" + "@" + "www.sec.gov/files/company_tickers.json",
        "https://fonts.googleapis.com/css",
    ):
        with pytest.raises(DisallowedHost):
            client.get(url)
    assert seen == []


def test_user_agent_is_sent_exactly_and_rate_is_capped():
    seen = []

    def transport(url, user_agent):
        seen.append((url, user_agent))
        return 200, b"ok", {}

    client, slept = _client(transport)
    for _ in range(3):
        assert client.get(TICKERS) == b"ok"
    assert seen == [(TICKERS, UA), (TICKERS, UA), (TICKERS, UA)]
    assert slept == [pytest.approx(0.1), pytest.approx(0.1)]
    with pytest.raises(ValueError):
        SecClient(UA, transport=transport, rate=11)


def test_backoff_on_403_and_429():
    for status in (403, 429):
        calls = {"n": 0}

        def transport(url, user_agent, status=status):
            calls["n"] += 1
            if calls["n"] == 1:
                return status, b"Traceback (most recent call last)", {"Retry-After": "0.5"}
            return 200, b"ok", {}

        client, slept = _client(transport)
        assert client.get(TICKERS) == b"ok"
        assert calls["n"] == 2
        assert slept[0] == pytest.approx(0.5)


def test_busy_gives_up_without_the_response_body():
    def transport(url, user_agent):
        return 429, b"Traceback (most recent call last)", {}

    client, _slept = _client(transport)
    with pytest.raises(SecBusy) as raised:
        client.get(TICKERS)
    assert "Traceback" not in str(raised.value)


def test_network_errors_are_unreachable():
    def transport(url, user_agent):
        raise OSError("nodename nor servname")

    client, _slept = _client(transport)
    with pytest.raises(SecUnreachable) as raised:
        client.get(TICKERS)
    assert "nodename" not in str(raised.value)


def test_redirect_off_sec_is_not_followed():
    seen = []

    def transport(url, user_agent):
        seen.append(url)
        return 302, b"", {"Location": "https://example.com/away"}

    client, _slept = _client(transport)
    with pytest.raises(DisallowedHost):
        client.get(TICKERS)
    assert seen == [TICKERS]


def test_allowed_hosts():
    assert host_allowed("https://www.sec.gov/files/company_tickers.json")
    assert host_allowed("https://data.sec.gov/submissions/CIK0000320193.json")
    assert not host_allowed("https://efts.sec.gov/LATEST/search-index")


def test_client_refuses_an_empty_user_agent():
    with pytest.raises(Exception):
        SecClient("", transport=lambda *_args: (200, b"", {}))
