"""Offline commands do not read or require a User-Agent."""

import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PINNED_APPLE = ROOT / "pinned" / "filings" / "0000320193-26-000026"
GOLDEN_APPLE = ROOT / "docs" / "0000320193-26-000026.html"
MESSAGE = "A User-Agent with a name and a contact email is required."
ACCESSION = "0000320193-26-000026"
EDGAR_URL = (
    "https://www.sec.gov/Archives/edgar/data/320193/"
    "000032019326000026/aapl-20260926.htm"
)


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("socket connection")

    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.delenv("WHITE_CLIFF_USER_AGENT", raising=False)


def _forbid_user_agent(*_args, **_kwargs):
    raise AssertionError("offline command read the User-Agent")


def test_explain_on_the_apple_10k_needs_no_user_agent(tmp_path, monkeypatch, capsys):
    from white_cliff import cli

    monkeypatch.setattr(cli, "load_user_agent", _forbid_user_agent)
    output = tmp_path / "out.html"
    code = cli.main(
        [
            "explain",
            str(PINNED_APPLE),
            "--format",
            "html",
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert MESSAGE not in captured.err
    assert output.read_bytes() == GOLDEN_APPLE.read_bytes()


def test_site_needs_no_user_agent(tmp_path, monkeypatch, capsys):
    from white_cliff import cli

    monkeypatch.setattr(cli, "load_user_agent", _forbid_user_agent)
    monkeypatch.chdir(ROOT)
    output = tmp_path / "site"
    code = cli.main(["site", "--output", str(output)])
    captured = capsys.readouterr()
    assert code == 0
    assert MESSAGE not in captured.err
    expected = sorted(
        path.relative_to(ROOT / "docs")
        for path in (ROOT / "docs").rglob("*")
        if path.is_file() and path.name != "de-review.csv"
    )
    actual = sorted(path.relative_to(output) for path in output.rglob("*") if path.is_file())
    assert actual == expected
    for rel in expected:
        assert (output / rel).read_bytes() == (ROOT / "docs" / rel).read_bytes()


def test_an_accession_that_needs_edgar_refuses_before_a_request(tmp_path, monkeypatch, capsys):
    from white_cliff import cli

    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as raised:
        cli.main(["explain", ACCESSION])
    captured = capsys.readouterr()
    assert raised.value.code == 2
    assert captured.err.strip() == MESSAGE
    assert captured.out == ""


def test_a_url_that_needs_edgar_refuses_before_a_request(monkeypatch, capsys):
    from white_cliff import cli

    monkeypatch.chdir(ROOT)
    with pytest.raises(SystemExit) as raised:
        cli.main(["explain", EDGAR_URL])
    captured = capsys.readouterr()
    assert raised.value.code == 2
    assert captured.err.strip() == MESSAGE
    assert captured.out == ""


def test_an_invalid_user_agent_refuses_before_a_request(tmp_path, monkeypatch, capsys):
    from white_cliff import cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHITE_CLIFF_USER_AGENT", "NameOnly")
    with pytest.raises(SystemExit) as raised:
        cli.main(["explain", ACCESSION])
    captured = capsys.readouterr()
    assert raised.value.code == 2
    assert captured.err.strip() == MESSAGE
    assert captured.out == ""


def test_readme_requires_a_user_agent_only_for_sec_downloads():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.startswith(
        "This tool explains the numbers in a public company filing. "
        "It does not recommend buying, selling or holding any security, "
        "and it is not investment advice."
    )
    assert "needed only for a command that downloads from sec.gov" in readme
    offline = (
        "white-cliff explain pinned/filings/0000320193-26-000026 "
        "--format html --output explanation.html"
    )
    assert offline in readme
    export_at = readme.find('export WHITE_CLIFF_USER_AGENT=')
    offline_at = readme.find("white-cliff explain pinned/filings/0000320193-26-000026\n")
    assert offline_at != -1
    assert export_at == -1 or offline_at < export_at
