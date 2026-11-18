import os
import subprocess
import sys
from pathlib import Path

import pytest

from white_cliff.disclaimer import DISCLAIMER, OutputRefused, ensure_safe_output
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.sitebuild import build_site

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tests" / "fixtures" / "omissions"


def _env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["WHITE_CLIFF_USER_AGENT"] = "Example Name name@example.com"
    env["WHITE_CLIFF_CONFIG"] = str(home / "missing.toml")
    env["HOME"] = str(home)
    env["PYTHONPATH"] = str(ROOT / "src")
    return env


def test_correction_note_is_stated_and_logged():
    sentence = (
        "A confirmed misstatement is corrected or the output pulled within "
        "2 business days, with a dated correction note."
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    template = (ROOT / ".github" / "ISSUE_TEMPLATE" / "filing_error.md").read_text(encoding="utf-8")
    corrections = (ROOT / "CORRECTIONS.md").read_text(encoding="utf-8")
    assert sentence in readme
    assert sentence in template
    assert "[CORRECTIONS.md](CORRECTIONS.md)" in readme
    assert corrections.startswith("# Corrections\n")
    assert "| Date | Filing | What was wrong | What changed |" in corrections
    assert "| --- | --- | --- | --- |" in corrections


def test_readme_opens_with_the_disclaimer_and_the_warranty():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    first = readme.split("\n\n", 1)[0].strip()
    assert first == DISCLAIMER
    assert "AS IS" in readme
    assert "WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND" in readme
    assert "https://github.com/EE-Holding/white-cliff/issues/new?template=filing_error.md" in readme
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in license_text
    assert "Version 2.0" in license_text
    name = "white-cliff"
    assert "sec" not in name
    assert "edgar" not in name
    template = ROOT / ".github" / "ISSUE_TEMPLATE" / "filing_error.md"
    assert template.is_file()


def test_help_carries_the_disclaimer_without_a_user_agent(tmp_path):
    env = os.environ.copy()
    env.pop("WHITE_CLIFF_USER_AGENT", None)
    env["WHITE_CLIFF_CONFIG"] = str(tmp_path / "missing.toml")
    env["HOME"] = str(tmp_path)
    env["PYTHONPATH"] = str(ROOT / "src")
    for args in (["--help"], ["explain", "--help"], ["site", "--help"]):
        completed = subprocess.run(
            [sys.executable, "-m", "white_cliff", *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        assert completed.returncode == 0
        assert DISCLAIMER in completed.stdout


def test_exports_and_the_public_page_lead_with_the_disclaimer(tmp_path):
    env = _env(tmp_path)
    out = tmp_path / "out"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "white_cliff",
            "explain",
            str(TARGET),
            "--format",
            "both",
            "--output",
            str(out),
            "--copy",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith(DISCLAIMER)
    for name in ("explanation.md", "explanation.html"):
        text = (out / name).read_text(encoding="utf-8")
        assert DISCLAIMER in text
        assert text.find(DISCLAIMER) < next(i for i, ch in enumerate(text) if ch.isdigit())
    site = build_site(tmp_path / "site", ROOT / "pinned")
    index = (site / "index.html").read_text(encoding="utf-8")
    assert index.find(DISCLAIMER) != -1
    assert index.find(DISCLAIMER) < next(i for i, ch in enumerate(index) if ch.isdigit())
    assert "Report an error" in index
    page = next(site.glob("*.html"))
    page_text = page.read_text(encoding="utf-8")
    assert DISCLAIMER in page_text


def test_committed_docs_carry_the_disclaimer_before_any_digit():
    listed = subprocess.check_output(["git", "ls-files", "docs"], cwd=ROOT, text=True)
    pages = [ROOT / name for name in listed.splitlines() if name.endswith(".html")]
    assert pages
    for page in pages:
        text = page.read_text(encoding="utf-8")
        found = text.find(DISCLAIMER)
        assert found != -1, page.name
        digit = next(i for i, ch in enumerate(text) if ch.isdigit())
        assert found < digit, page.name


def test_refused_output_is_a_plain_message(tmp_path, monkeypatch, capsys):
    from white_cliff import cli
    from white_cliff.disclaimer import OutputRefused

    target = tmp_path / "filing.html"
    target.write_text("<p>Total net sales 5</p>", encoding="utf-8")

    def explode(*_args, **_kwargs):
        raise OutputRefused("number before disclaimer")

    monkeypatch.setattr(cli, "explain_filing", explode)
    monkeypatch.setattr(cli, "load_file", lambda _path: object())
    code = cli.main(["explain", str(target)])
    captured = capsys.readouterr()
    assert code == 2
    assert "number before disclaimer" in captured.err
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def test_local_file_without_provenance_invents_no_sec_url(tmp_path, capsys):
    from white_cliff import cli
    from white_cliff.pipeline import load_file

    target = tmp_path / "filing.html"
    target.write_text("<html><body><p>Total net sales 5</p></body></html>", encoding="utf-8")
    try:
        filing = load_file(target)
    except Exception as exc:
        assert "sec.gov" not in str(exc)
        return
    explained = explain_filing(filing)
    rendered = explained.markdown + explained.html
    assert "https://www.sec.gov/" not in rendered
    assert "file://" not in rendered
    assert "This filing has no tagged figures that White Cliff can explain." in rendered
    assert "This filing was not retrieved from EDGAR." in rendered


def test_output_without_the_disclaimer_is_refused():
    with pytest.raises(OutputRefused):
        ensure_safe_output("Revenue was 10.")
    with pytest.raises(OutputRefused):
        ensure_safe_output("1\n" + DISCLAIMER)
    filing = load_directory(TARGET)
    explained = explain_filing(filing)
    assert explained.markdown.startswith(DISCLAIMER)
    assert explained.copy.startswith(DISCLAIMER)
    assert explained.html.find(DISCLAIMER) < next(
        i for i, ch in enumerate(explained.html) if ch.isdigit()
    )
