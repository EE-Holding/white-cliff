"""The Mac jobs smoke the built app, and the driver clicks the real buttons."""

import importlib.util
import os
import re
import signal
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
    assert "smoke-{ARCH}-8-result-1100.png" in driver
    assert "smoke-{ARCH}-9-result-1280.png" in driver
    assert "smoke-{ARCH}-10-de-result-1280.png" in driver
    assert "smoke-{ARCH}-11-de-result-420.png" in driver
    assert "smoke-{ARCH}-12-de-first-1280.png" in driver
    assert "smoke-{ARCH}-13-de-first-420.png" in driver
    assert "smoke-{ARCH}-14-de-loading-1280.png" in driver
    assert "smoke-{ARCH}-15-de-loading-420.png" in driver
    assert "smoke-{ARCH}-16-de-shares-1280.png" in driver
    assert "smoke-{ARCH}-17-de-shares-420.png" in driver
    assert "smoke-{ARCH}-18-de-balance-1280.png" in driver
    assert "smoke-{ARCH}-19-de-checks-1280.png" in driver
    assert "smoke-{ARCH}-20-de-explain-1280.png" in driver
    assert "smoke-{ARCH}-21-print-1280.png" in driver
    assert "German did not survive a restart" in driver
    assert "is blank" in driver
    assert "is the same picture as" in driver
    assert "fromSurface" not in driver
    assert "display:none" in driver
    assert '<circle class="arc"' in driver
    assert "getBoundingClientRect" in driver
    assert "prefers-reduced-motion" in driver
    assert "Page.navigate" in driver
    assert "_reduced_steps" in driver
    tracked = driver + "\n" + workflow
    offenders = [
        match.group(0)
        for match in _EMAIL.finditer(tracked)
        if match.group(0).rsplit("@", 1)[1].lower() not in _ALLOWED_HOSTS
    ]
    assert offenders == []


def _ink(driver, data: bytes, x: int, y: int) -> bool:
    width, height, color, _depth, rows = driver._png_rows(data)
    if y >= height or x >= width:
        return False
    channels = {0: 1, 2: 3, 6: 4}[color]
    pixel = rows[y][x * channels : (x + 1) * channels]
    return bool(pixel) and min(pixel[:3]) < 180


def _band(driver, data: bytes, top: int, bottom: int) -> bool:
    width, height, color, _depth, rows = driver._png_rows(data)
    channels = {0: 1, 2: 3, 6: 4}[color]
    for y in range(top, min(bottom, height), 2):
        for x in range(8, min(width, 280), 2):
            pixel = rows[y][x * channels : (x + 1) * channels]
            if pixel and min(pixel[:3]) < 180:
                return True
    return False


def test_intel_photo_shows_the_live_window(tmp_path):
    """A copied document drops a canvas painted by script and the typed ticker."""
    driver = _driver()
    if driver.chrome_binary() is None:
        pytest.skip("chrome is not installed")
    page_path = tmp_path / "page.html"
    page_path.write_text(
        "<!doctype html><style>"
        "html,body{margin:0;background:#fff}"
        "canvas{position:absolute;left:0;top:0}"
        "input{position:absolute;left:0;top:160px;font-size:64px;width:420px;height:80px;"
        "border:0;background:#fff}"
        "</style><canvas id=c width=100 height=100></canvas><input id=q>",
        encoding="utf-8",
    )
    chrome, page = driver._open_chrome(page_path.as_uri())
    try:
        driver._eval(
            page,
            "document.readyState === 'complete' ? true : new Promise((resolve) => addEventListener('load', () => resolve(true)))",
        )
        driver._eval(
            page,
            """(() => {
              const canvas = document.getElementById("c");
              const pen = canvas.getContext("2d");
              pen.fillStyle = "#000";
              pen.fillRect(0, 0, 100, 100);
              const field = document.getElementById("q");
              field.value = "NVDA";
              return field.value;
            })()""",
        )
        painted = driver._intel_photo(
            page, tmp_path, "painted.png", 1100, 400, keep_scroll=False, reveal=False
        )
        driver._eval(
            page,
            """(() => {
              const canvas = document.getElementById("c");
              const pen = canvas.getContext("2d");
              pen.fillStyle = "#fff";
              pen.fillRect(0, 0, 100, 100);
              document.getElementById("q").value = "";
              return true;
            })()""",
        )
        cleared = driver._intel_photo(
            page, tmp_path, "cleared.png", 1100, 400, keep_scroll=False, reveal=False
        )
    finally:
        page.close()
        if chrome.poll() is None:
            os.killpg(chrome.pid, signal.SIGTERM)
    painted_bytes = painted.read_bytes()
    cleared_bytes = cleared.read_bytes()
    assert struct.unpack(">I", painted_bytes[16:20])[0] == 1100
    assert struct.unpack(">I", cleared_bytes[16:20])[0] == 1100
    assert _ink(driver, painted_bytes, 20, 20)
    assert not _ink(driver, cleared_bytes, 20, 20)
    assert _band(driver, painted_bytes, 160, 240)
    assert not _band(driver, cleared_bytes, 160, 240)


def test_intel_photo_shows_the_card_beside_the_first(tmp_path, monkeypatch):
    """The frame waits until the next card has painted, then shows that card."""
    driver = _driver()
    if driver.chrome_binary() is None:
        pytest.skip("chrome is not installed")
    monkeypatch.setattr(driver, "_intel", lambda: True)
    page_path = tmp_path / "rise.html"
    page_path.write_text(
        "<!doctype html><style>"
        "html,body{margin:0;background:#fff}"
        ".grid{display:grid;grid-template-columns:1fr 1fr}"
        "@keyframes rise { from { opacity: 0; } to { opacity: 1; } }"
        "article{height:220px;background:#fff;animation:rise 300ms both;"
        "animation-delay:calc(var(--c) * 700ms)}"
        "</style>",
        encoding="utf-8",
    )
    chrome, page = driver._open_chrome(page_path.as_uri())
    try:
        driver._eval(
            page,
            "document.readyState === 'complete' ? true : new Promise((resolve) => addEventListener('load', () => resolve(true)))",
        )
        driver._eval(
            page,
            """(() => {
              const grid = document.createElement("div");
              grid.className = "grid";
              grid.innerHTML = '<article style="--c:0"></article>'
                + '<article id=b style="--c:1;background:#000"></article>';
              document.body.appendChild(grid);
              return true;
            })()""",
        )
        shot = driver._intel_photo(
            page, tmp_path, "rise.png", 1100, 400, keep_scroll=False, reveal=False
        )
    finally:
        page.close()
        if chrome.poll() is None:
            os.killpg(chrome.pid, signal.SIGTERM)
    data = shot.read_bytes()
    assert struct.unpack(">I", data[16:20])[0] == 1100
    assert _ink(driver, data, 700, 40)


def test_the_settled_pair_is_not_exempt(tmp_path):
    """The 1100 result is not allowed to be a copy of the first result picture."""
    driver = _driver()
    row = bytearray([255, 255, 255] * 60)
    row[0:3] = b"\x00\x00\x00"
    data = driver._png_bytes(60, 60, 2, 8, [bytes(row)] * 60)
    (tmp_path / "smoke-x86_64-3-nvda.png").write_bytes(data)
    (tmp_path / "smoke-arm64-8-result-1100.png").write_bytes(data)
    with pytest.raises(driver.PageError, match="is the same picture as"):
        driver._distinct(tmp_path)


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
        f"smoke-{driver.ARCH}-8-result-1100.png",
        f"smoke-{driver.ARCH}-9-result-1280.png",
        f"smoke-{driver.ARCH}-10-de-result-1280.png",
        f"smoke-{driver.ARCH}-11-de-result-420.png",
        f"smoke-{driver.ARCH}-12-de-first-1280.png",
        f"smoke-{driver.ARCH}-13-de-first-420.png",
        f"smoke-{driver.ARCH}-14-de-loading-1280.png",
        f"smoke-{driver.ARCH}-15-de-loading-420.png",
        f"smoke-{driver.ARCH}-16-de-shares-1280.png",
        f"smoke-{driver.ARCH}-17-de-shares-420.png",
        f"smoke-{driver.ARCH}-18-de-balance-1280.png",
        f"smoke-{driver.ARCH}-19-de-checks-1280.png",
        f"smoke-{driver.ARCH}-20-de-explain-1280.png",
        f"smoke-{driver.ARCH}-21-print-1280.png",
    ):
        assert (tmp_path / name).stat().st_size > 1000
    wide = (tmp_path / f"smoke-{driver.ARCH}-6-result-640.png").read_bytes()
    narrow = (tmp_path / f"smoke-{driver.ARCH}-7-result-420.png").read_bytes()
    desktop = (tmp_path / f"smoke-{driver.ARCH}-8-result-1100.png").read_bytes()
    board = (tmp_path / f"smoke-{driver.ARCH}-9-result-1280.png").read_bytes()
    assert struct.unpack(">I", wide[16:20])[0] == 640
    assert struct.unpack(">I", narrow[16:20])[0] == 420
    assert struct.unpack(">I", desktop[16:20])[0] == 1100
    assert struct.unpack(">I", board[16:20])[0] == 1280
    de_result = (tmp_path / f"smoke-{driver.ARCH}-10-de-result-1280.png").read_bytes()
    de_narrow = (tmp_path / f"smoke-{driver.ARCH}-11-de-result-420.png").read_bytes()
    de_first = (tmp_path / f"smoke-{driver.ARCH}-12-de-first-1280.png").read_bytes()
    de_first_narrow = (tmp_path / f"smoke-{driver.ARCH}-13-de-first-420.png").read_bytes()
    de_loading = (tmp_path / f"smoke-{driver.ARCH}-14-de-loading-1280.png").read_bytes()
    de_loading_narrow = (tmp_path / f"smoke-{driver.ARCH}-15-de-loading-420.png").read_bytes()
    assert struct.unpack(">I", de_result[16:20])[0] == 1280
    assert struct.unpack(">I", de_narrow[16:20])[0] == 420
    assert struct.unpack(">I", de_first[16:20])[0] == 1280
    assert struct.unpack(">I", de_first_narrow[16:20])[0] == 420
    assert struct.unpack(">I", de_loading[16:20])[0] == 1280
    assert struct.unpack(">I", de_loading_narrow[16:20])[0] == 420
    de_shares = (tmp_path / f"smoke-{driver.ARCH}-16-de-shares-1280.png").read_bytes()
    de_shares_narrow = (tmp_path / f"smoke-{driver.ARCH}-17-de-shares-420.png").read_bytes()
    assert struct.unpack(">I", de_shares[16:20])[0] == 1280
    assert struct.unpack(">I", de_shares_narrow[16:20])[0] == 420
    balance = (tmp_path / f"smoke-{driver.ARCH}-18-de-balance-1280.png").read_bytes()
    checks = (tmp_path / f"smoke-{driver.ARCH}-19-de-checks-1280.png").read_bytes()
    formula = (tmp_path / f"smoke-{driver.ARCH}-20-de-explain-1280.png").read_bytes()
    printed = (tmp_path / f"smoke-{driver.ARCH}-21-print-1280.png").read_bytes()
    assert struct.unpack(">I", balance[16:20])[0] == 1280
    assert struct.unpack(">I", checks[16:20])[0] == 1280
    assert struct.unpack(">I", formula[16:20])[0] == 1280
    assert struct.unpack(">I", printed[16:20])[0] == 1280
    assert de_loading != de_loading_narrow
    result = (tmp_path / f"smoke-{driver.ARCH}-3-nvda.png").read_bytes()
    reduced = (tmp_path / f"smoke-{driver.ARCH}-5-reduced.png").read_bytes()
    assert reduced != result
    assert result != desktop
