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
    assert index.find(DISCLAIMER) < next(i for i, ch in enumerate(index) if ch.isdigit())
    assert "Report an error" in index
    page = next(site.glob("*.html"))
    page_text = page.read_text(encoding="utf-8")
    assert DISCLAIMER in page_text


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
