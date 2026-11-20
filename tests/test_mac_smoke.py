"""The Mac jobs smoke the built app, and the driver clicks the real buttons."""

import importlib.util
import os
import re
import signal
import struct
import threading
import time
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


def test_a_missing_or_stale_screencast_is_not_a_live_photo(tmp_path, monkeypatch):
    """A copied document must not stand in for a frame the window did not paint."""
    driver = _driver()
    page = object()
    def picture(seed: int) -> bytes:
        rows = [
            bytes((seed + x + y * 3) % 256 for x in range(1100 * 3))
            for y in range(40)
        ]
        return driver._png_bytes(1100, 40, 2, 8, rows)

    copy = picture(1)
    stale = picture(90)
    monkeypatch.setattr(driver, "_copied_png", lambda page, width: copy)
    paused, last, seen = driver._PAUSED, driver._LAST, set(driver._SEEN)
    try:
        driver._PAUSED = True
        driver._LAST = b""
        driver._SEEN = set()
        monkeypatch.setattr(driver, "_live_frame", lambda page, width=0: b"")
        with pytest.raises(driver.PageError, match="no screencast frame"):
            driver._intel_photo(
                page, tmp_path, "missing.png", 1100, 400, keep_scroll=False, reveal=False
            )
        assert not (tmp_path / "missing.png").exists()
        driver._LAST = stale
        driver._SEEN = {stale}
        monkeypatch.setattr(driver, "_live_frame", lambda page, width=0: stale)
        with pytest.raises(driver.PageError, match="previous screencast frame"):
            driver._intel_photo(
                page, tmp_path, "stale.png", 1100, 400, keep_scroll=False, reveal=False
            )
        assert not (tmp_path / "stale.png").exists()
    finally:
        driver._PAUSED = paused
        driver._LAST = last
        driver._SEEN = seen


def test_a_repeated_frame_clears_the_stuck_window(monkeypatch):
    """The Intel override can leave the old picture in place. Clearing it reaches the next size."""
    driver = _driver()

    def picture(seed: int) -> bytes:
        rows = []
        for y in range(8):
            row = bytearray(1100 * 3)
            for x in range(1100 * 3):
                row[x] = (seed * 131 + x * 17 + y * 91 + (x * y) % 251) & 255
            rows.append(bytes(row))
        return driver._png_bytes(1100, 20, 2, 8, rows)

    stale = picture(2)
    fresh = picture(5)
    calls: list[tuple] = []
    sent = {"n": 0}

    class Page:
        def call(self, method, params=None, timeout=20):
            if method == "Emulation.clearDeviceMetricsOverride":
                calls.append(("clear",))
            if method == "Emulation.setDeviceMetricsOverride":
                calls.append(("metrics", (params or {}).get("width")))
            if method == "Page.startScreencast":
                calls.append(("cast",))
            return {}

        def next_event(self, method, timeout):
            sent["n"] += 1
            payload = stale if sent["n"] == 1 else fresh
            raw = __import__("base64").b64encode(payload).decode("ascii")
            return {"method": method, "params": {"data": raw, "sessionId": sent["n"]}}

    monkeypatch.setattr(
        driver,
        "_fit_window",
        lambda page, width, height: calls.append(("bounds", width)),
    )
    paused, last, seen = driver._PAUSED, driver._LAST, set(driver._SEEN)
    driver._PAUSED = False
    driver._LAST = b""
    driver._SEEN = {stale}
    try:
        data = driver._live_frame(Page(), 1100)
    finally:
        driver._PAUSED = paused
        driver._LAST = last
        driver._SEEN = seen
    assert data == fresh
    assert ("clear",) in calls
    assert ("metrics", 1100) in calls
    assert ("bounds", 1100) in calls
    assert ("cast",) in calls[calls.index(("metrics", 1100)) :]


def test_the_result_picture_does_not_wait_on_the_renderer(tmp_path, monkeypatch):
    """Waiting for a paint holds the renderer, so a resized window repeats the last frame."""
    driver = _driver()
    waited: list[bool] = []

    class Page:
        def call(self, method, params=None, timeout=20):
            params = params or {}
            expression = str(params.get("expression") or "")
            if "requestAnimationFrame" in expression:
                waited.append(bool(params.get("awaitPromise")))
            return {}

        def next_event(self, method, timeout):
            rows = []
            for y in range(8):
                row = bytearray(1100 * 3)
                for x in range(1100 * 3):
                    row[x] = (4 * 131 + x * 17 + y * 91 + (x * y) % 251) & 255
                rows.append(bytes(row))
            raw = __import__("base64").b64encode(driver._png_bytes(1100, 20, 2, 8, rows)).decode("ascii")
            return {"method": method, "params": {"data": raw, "sessionId": 1}}

    monkeypatch.setattr(driver, "_window", lambda *args, **kwargs: None)
    monkeypatch.setattr(driver, "_activate", lambda: None)
    paused, last, seen = driver._PAUSED, driver._LAST, set(driver._SEEN)
    driver._PAUSED = False
    driver._LAST = b""
    driver._SEEN = set()
    try:
        driver._intel_photo(Page(), tmp_path, "result.png", 1100, 400, keep_scroll=False, reveal=False)
    finally:
        driver._PAUSED = paused
        driver._LAST = last
        driver._SEEN = seen
    assert waited
    assert waited == [False] * len(waited)


def test_a_wider_result_picture_comes_from_a_new_window(tmp_path, monkeypatch):
    """A wider result is a new window. Resizing the open window keeps the old bitmap."""
    driver = _driver()

    def picture(seed: int, width: int) -> bytes:
        rows = []
        for y in range(60):
            row = bytearray(width * 3)
            for x in range(width * 3):
                row[x] = (seed * 131 + x * 17 + y * 91 + (x * y) % 251) & 255
            rows.append(bytes(row))
        return driver._png_bytes(width, 60, 2, 8, rows)

    fresh = picture(6, 1280)
    order: list[str] = []

    class Source:
        def call(self, method, params=None, timeout=20):
            expression = str((params or {}).get("expression") or "")
            if expression == "location.href":
                return {"result": {"value": "http://127.0.0.1:9/result"}}
            return {}

    class Shot:
        def call(self, method, params=None, timeout=20):
            order.append(method)
            params = params or {}
            expression = str(params.get("expression") or "")
            if method == "Emulation.setEmulatedMedia":
                features = params.get("features") or [{}]
                order.append("media " + str(features[0].get("value")))
            if "document.readyState" in expression:
                return {"result": {"value": "complete"}}
            if "innerText" in expression:
                return {"result": {"value": 80}}
            if "column" in expression and "opacity" in expression:
                return {"result": {"value": True}}
            if "requestAnimationFrame" in expression:
                order.append("paint")
            return {}

        def next_event(self, method, timeout):
            if "paint" not in order:
                raise driver.PageError(method)
            raw = __import__("base64").b64encode(fresh).decode("ascii")
            return {"method": method, "params": {"data": raw, "sessionId": 1}}

    monkeypatch.setattr(driver, "_intel", lambda: True)
    monkeypatch.setattr(
        driver,
        "_fresh_target",
        lambda width, height: order.append(f"createTarget {width}x{height}") or Shot(),
    )
    monkeypatch.setattr(driver, "_window", lambda *args, **kwargs: order.append("resize"))
    monkeypatch.setattr(
        driver, "_copied_png", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("copied"))
    )
    monkeypatch.setattr(driver, "_close_loading_target", lambda page: order.append("close"))
    paused, last, seen = driver._PAUSED, driver._LAST, set(driver._SEEN)
    driver._LAST = b""
    driver._SEEN = set()
    try:
        path = driver._shot(
            Source(), tmp_path, "smoke-x86_64-9-result-1280.png", width=1280, height=2200, full=True
        )
    finally:
        driver._PAUSED = paused
        driver._LAST = last
        driver._SEEN = seen
    assert path.read_bytes() == fresh
    assert order.index("createTarget 1280x900") < order.index("Page.startScreencast")
    assert order.index("Page.startScreencast") < order.index("Page.navigate")
    assert order.index("media reduce") < order.index("Page.navigate")
    assert "resize" not in order
    assert "Page.captureScreenshot" not in order


def test_the_filing_request_waits_until_the_loading_shot_releases():
    """The second sec.gov page stays unanswered until the shot releases it."""
    driver = _driver()
    hold = driver._SecHold()
    hold.arm()
    hold.wait("www.sec.gov")
    hold.wait("data.sec.gov")
    started = []

    def second():
        started.append(time.monotonic())
        hold.wait("www.sec.gov")
        started.append("done")

    thread = threading.Thread(target=second)
    thread.start()
    thread.join(0.2)
    assert thread.is_alive()
    assert started == [started[0]]
    hold.release()
    thread.join(1)
    assert started[-1] == "done"


def test_the_narrow_loading_picture_comes_from_a_new_window(tmp_path, monkeypatch):
    """A loading shot is a new window at that size, cast before it navigates."""
    driver = _driver()

    def picture(seed: int, width: int) -> bytes:
        rows = []
        for y in range(8):
            row = bytearray(width * 3)
            for x in range(width * 3):
                row[x] = (seed * 131 + x * 17 + y * 91 + (x * y) % 251) & 255
            rows.append(bytes(row))
        return driver._png_bytes(width, 20, 2, 8, rows)

    old = picture(3, 1280)
    fresh = picture(9, 420)
    order: list[str] = []
    sent = {"old": False, "fresh": False}

    class Page:
        def call(self, method, params=None, timeout=20):
            order.append(method)
            params = params or {}
            expression = str(params.get("expression") or "")
            if method == "Emulation.setEmulatedMedia":
                features = params.get("features") or [{}]
                order.append("media " + str(features[0].get("value")))
            if method == "Emulation.setDeviceMetricsOverride":
                order.append(f"viewport {params.get('width')}")
            if "requestAnimationFrame" in expression:
                order.append("paint")
            if "document.readyState" in expression:
                order.append("ready")
                return {"result": {"value": "complete"}}
            if "requestSubmit" in expression:
                order.append("requestSubmit")
                return {"result": {"value": True}}
            if "steps.hidden" in expression:
                order.append("view")
                return {"result": {"value": "hidden=true active=0 arc=missing reduce=false"}}
            if "column" in expression and "opacity" in expression:
                order.append("opaque")
                return {"result": {"value": True}}
            return {}

        def next_event(self, method, timeout):
            if method != "Page.screencastFrame":
                raise driver.PageError(method)
            if "paint" not in order:
                if "Page.startScreencast" in order and not sent["old"]:
                    sent["old"] = True
                    raw = __import__("base64").b64encode(old).decode("ascii")
                    return {"method": method, "params": {"data": raw, "sessionId": 1}}
                raise driver.PageError(method)
            if not sent["fresh"]:
                sent["fresh"] = True
                wanted = 420
                for item in reversed(order):
                    if item.startswith("createTarget "):
                        wanted = int(item.split()[1].split("x")[0])
                        break
                payload = fresh if wanted == 420 else picture(wanted, wanted)
                raw = __import__("base64").b64encode(payload).decode("ascii")
                return {"method": method, "params": {"data": raw, "sessionId": 2}}
            raise driver.PageError(method)

    monkeypatch.setattr(driver, "_fresh_target", lambda width, height: order.append(f"createTarget {width}x{height}") or Page())
    monkeypatch.setattr(driver, "_window", lambda *args, **kwargs: order.append("resize"))
    monkeypatch.setattr(driver, "_copied_png", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("copied")))
    monkeypatch.setattr(driver, "_wait_node", lambda *args, **kwargs: None)
    monkeypatch.setattr(driver, "_fill", lambda *args, **kwargs: order.append("fill"))
    monkeypatch.setattr(driver, "_press", lambda *args, **kwargs: order.append("click"))
    monkeypatch.setattr(driver, "_steps_visible", lambda page: True)
    monkeypatch.setattr(driver, "_reduced_steps", lambda page: True)
    monkeypatch.setattr(driver, "_loading", lambda page: True)
    monkeypatch.setattr(driver, "_spinning", lambda page: True)
    monkeypatch.setattr(driver, "_close_loading_target", lambda page: order.append("close"))
    monkeypatch.setattr(driver._sec_hold, "arm", lambda everything=False: order.append("hold"))
    monkeypatch.setattr(driver._sec_hold, "release", lambda: order.append("release"))
    paused, last, seen = driver._PAUSED, driver._LAST, set(driver._SEEN)
    driver._LAST = b""
    driver._SEEN = set()
    try:
        path = driver._loading_shot(
            tmp_path, "smoke-x86_64-15-de-loading-420.png", 420, "http://127.0.0.1:9/", "NVDA"
        )
        assert path.read_bytes() == fresh
        assert path.read_bytes() != old
        assert order.index("hold") < order.index("Page.startScreencast")
        assert order.index("Page.startScreencast") < order.index("Page.navigate")
        assert order.index("media no-preference") < order.index("Page.navigate")
        assert order.index("viewport 420") < order.index("Page.startScreencast")
        assert order.index("ready") < order.index("requestSubmit")
        assert order.index("opaque") < order.index("paint")
        assert order.index("createTarget 420x900") < order.index("Page.startScreencast")
        assert "resize" not in order
        assert "Page.captureScreenshot" not in order
        assert order.index("release") > order.index("Page.navigate")
        order.clear()
        sent["old"] = False
        sent["fresh"] = False
        driver._LAST = b""
        driver._SEEN = set()
        driver._loading_shot(
            tmp_path, "smoke-x86_64-5-reduced.png", 1100, "http://127.0.0.1:9/", "NVDA", reduced=True
        )
        assert order.index("media reduce") < order.index("Page.navigate")
        assert "viewport 1100" not in order
    finally:
        driver._PAUSED = paused
        driver._LAST = last
        driver._SEEN = seen


def test_a_missing_loading_panel_reports_the_page_state(tmp_path, monkeypatch):
    """A shot that never shows the steps says what the document was doing."""
    driver = _driver()
    order: list[str] = []

    class Page:
        def call(self, method, params=None, timeout=20):
            params = params or {}
            expression = str(params.get("expression") or "")
            if "document.readyState" in expression:
                return {"result": {"value": "complete"}}
            if "requestSubmit" in expression:
                order.append("requestSubmit")
                return {"result": {"value": True}}
            if "steps.hidden" in expression:
                return {"result": {"value": "hidden=true active=0 arc=missing reduce=true"}}
            return {}

    monkeypatch.setattr(driver, "_fresh_target", lambda width, height: Page())
    monkeypatch.setattr(driver, "_wait_node", lambda *args, **kwargs: None)
    monkeypatch.setattr(driver, "_fill", lambda *args, **kwargs: None)
    monkeypatch.setattr(driver, "_steps_visible", lambda page: False)
    monkeypatch.setattr(driver, "_spinning", lambda page: False)
    monkeypatch.setattr(driver, "_close_loading_target", lambda page: None)
    monkeypatch.setattr(driver._sec_hold, "arm", lambda everything=False: None)
    monkeypatch.setattr(driver._sec_hold, "release", lambda: None)
    ticks = {"n": 0}

    def warped():
        ticks["n"] += 1
        return 1000.0 if ticks["n"] < 30 else 10000.0

    monkeypatch.setattr(driver.time, "time", warped)
    monkeypatch.setattr(driver.time, "sleep", lambda *_args, **_kwargs: None)
    with pytest.raises(driver.PageError, match="hidden=true active=0 arc=missing reduce=true"):
        driver._loading_shot(tmp_path, "smoke-x86_64-4-loading.png", 1100, "http://127.0.0.1:9/", "NVDA")
    assert "requestSubmit" in order


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
    transport.hold = driver._sec_hold.wait_url
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
