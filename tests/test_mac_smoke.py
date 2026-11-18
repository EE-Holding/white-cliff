"""The Mac jobs smoke the built app, and the driver clicks the real buttons."""

import importlib.util
import re
import struct
import threading
from pathlib import Path

import pytest

from white_cliff.desktop import make_server

ROOT = Path(__file__).resolve().parents[1]
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_ALLOWED_HOSTS = {"example.com", "example.org", "example.net"}


def _driver():
    spec = importlib.util.spec_from_file_location("smoke_mac", ROOT / "scripts" / "smoke_mac.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_both_mac_jobs_smoke_the_built_binary():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    jobs = workflow.split("package-windows", 1)[0]
    silicon, intel = jobs.split("package-intel-mac", 1)
    for job in (silicon, intel):
        assert job.index("PyInstaller") < job.index("scripts/smoke_mac.py")
        assert 'python3 scripts/smoke_mac.py "dist/White Cliff.app/Contents/MacOS/White Cliff"' in job
        assert "if: always()" in job
        assert "smoke-*.png" in job
    driver = (ROOT / "scripts" / "smoke_mac.py").read_text(encoding="utf-8")
    assert 'env["BROWSER"]' in driver
    assert 'env["HOME"]' in driver
    assert "Input.dispatchMouseEvent" in driver
    assert "form.submit" not in driver
    assert "time.monotonic() + 30" in driver
    assert "stderr=subprocess.DEVNULL" not in driver
    desktop = (ROOT / "tests" / "test_desktop_app.py").read_text(encoding="utf-8")
    chrome_test = desktop.split("def test_chrome_submits_setup_search_pick_and_erase", 1)[1]
    assert "time.monotonic() + 30" in chrome_test
    assert "stderr=subprocess.DEVNULL" not in chrome_test
    assert "smoke-{ARCH}-1-first-run.png" in driver
    assert "smoke-{ARCH}-2-search.png" in driver
    assert "smoke-{ARCH}-3-nvda.png" in driver
    assert "smoke-{ARCH}-4-loading.png" in driver
    assert "smoke-{ARCH}-5-reduced.png" in driver
    assert "smoke-{ARCH}-6-result-640.png" in driver
    assert "smoke-{ARCH}-7-result-420.png" in driver
    assert "prefers-reduced-motion" in driver
    tracked = driver + "\n" + workflow
    offenders = [
        match.group(0)
        for match in _EMAIL.finditer(tracked)
        if match.group(0).rsplit("@", 1)[1].lower() not in _ALLOWED_HOSTS
    ]
    assert offenders == []


def test_launch_resolves_a_relative_binary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    binary = tmp_path / "dist" / "White Cliff"
    binary.parent.mkdir()
    binary.write_text(
        "#!/bin/sh\n" + '"$BROWSER" "http://127.0.0.1:9/"\n' + "sleep 30\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    driver = _driver()
    proc, url, log = driver.launch("dist/White Cliff")
    try:
        assert url == "http://127.0.0.1:9/"
    finally:
        driver.stop(proc, log)


def test_smoke_driver_clicks_save_and_explain(monkeypatch, tmp_path):
    from tests.test_desktop_app import _Transport, _app

    driver = _driver()
    if driver.chrome_binary() is None:
        pytest.skip("chrome is not installed")
    transport = _Transport()
    app = _app(monkeypatch, tmp_path, transport)
    server = make_server(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        driver.drive(
            f"http://127.0.0.1:{port}/",
            tmp_path,
            query="AAPL",
            heading="Apple",
            suffix="million",
        )
    finally:
        server.shutdown()
        server.server_close()
    joined = " ".join(user_agent for _url, user_agent in transport.calls)
    assert "wc-test" in joined
    assert "example.invalid" in joined
    assert "eicke" not in joined.casefold()
    for name in (
        f"smoke-{driver.ARCH}-1-first-run.png",
        f"smoke-{driver.ARCH}-2-search.png",
        f"smoke-{driver.ARCH}-3-nvda.png",
        f"smoke-{driver.ARCH}-4-loading.png",
        f"smoke-{driver.ARCH}-5-reduced.png",
        f"smoke-{driver.ARCH}-6-result-640.png",
        f"smoke-{driver.ARCH}-7-result-420.png",
    ):
        assert (tmp_path / name).stat().st_size > 1000
    wide = (tmp_path / f"smoke-{driver.ARCH}-6-result-640.png").read_bytes()
    narrow = (tmp_path / f"smoke-{driver.ARCH}-7-result-420.png").read_bytes()
    assert struct.unpack(">I", wide[16:20])[0] == 640
    assert struct.unpack(">I", narrow[16:20])[0] == 420
