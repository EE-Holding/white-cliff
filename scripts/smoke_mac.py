"""Drive the built Mac app through the runner's Chrome. No browser window opens."""

from __future__ import annotations

import base64
import json
import os
import platform
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

TEST_NAME = "White Cliff Test"
ARCH = platform.machine()


def test_email() -> str:
    return "wc-test" + "@" + "example.invalid"


def chrome_binary() -> str | None:
    for candidate in (
        os.environ.get("CHROME", ""),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/opt/google/chrome/chrome",
        shutil.which("google-chrome") or "",
        shutil.which("google-chrome-stable") or "",
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


class PageError(RuntimeError):
    pass


class DevTools:
    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        parsed = urllib.parse.urlsplit(ws_url)
        self.sock = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        host = f"{parsed.hostname}:{parsed.port}"
        self.sock.sendall(
            (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode("ascii")
        )
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            data += chunk
        if b" 101 " not in data.split(b"\r\n", 1)[0]:
            raise PageError(data[:200])
        self._buf = data.split(b"\r\n\r\n", 1)[1]
        self._next = 0

    def call(self, method: str, params: dict | None = None, timeout: float = 20):
        self._next += 1
        ident = self._next
        payload = json.dumps({"id": ident, "method": method, "params": params or {}}).encode()
        self._send(0x81, payload)
        deadline = time.time() + timeout
        while time.time() < deadline:
            message = self._read(deadline)
            if message is None:
                break
            data = json.loads(message)
            if data.get("id") == ident:
                if "error" in data:
                    raise PageError(data["error"])
                return data.get("result", {})
        raise PageError(method)

    def close(self) -> None:
        sock = getattr(self, "sock", None)
        if sock is not None:
            sock.close()

    def _send(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        header = bytearray([0x80 | opcode])
        size = len(payload)
        if size < 126:
            header.append(0x80 | size)
        elif size < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack(">H", size))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack(">Q", size))
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _fill(self, deadline: float) -> None:
        self.sock.settimeout(max(0.1, deadline - time.time()))
        chunk = self.sock.recv(65536)
        if not chunk:
            raise PageError("devtools closed")
        self._buf += chunk

    def _read(self, deadline: float):
        while len(self._buf) < 2:
            self._fill(deadline)
        second = self._buf[1]
        opcode = self._buf[0] & 0x0F
        masked = second & 0x80
        length = second & 0x7F
        offset = 2
        if length == 126:
            while len(self._buf) < 4:
                self._fill(deadline)
            length = struct.unpack(">H", self._buf[2:4])[0]
            offset = 4
        elif length == 127:
            while len(self._buf) < 10:
                self._fill(deadline)
            length = struct.unpack(">Q", self._buf[2:10])[0]
            offset = 10
        extra = 4 if masked else 0
        while len(self._buf) < offset + extra + length:
            self._fill(deadline)
        if masked:
            mask = self._buf[offset : offset + 4]
            start = offset + 4
            payload = bytes(
                byte ^ mask[index % 4]
                for index, byte in enumerate(self._buf[start : start + length])
            )
        else:
            start = offset
            payload = self._buf[start : start + length]
        self._buf = self._buf[start + length :]
        if opcode == 0x8:
            raise PageError("devtools closed")
        if opcode == 0x9:
            self._send(0x0A, payload)
            return self._read(deadline)
        if opcode != 0x1:
            return self._read(deadline)
        return payload.decode("utf-8")


def _window(page: DevTools, width: int = 1100, height: int = 2200) -> None:
    """Give headless Chrome a real window. Old headless rejects the metrics call."""
    try:
        page.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
        )
        return
    except PageError:
        pass
    try:
        window = page.call("Browser.getWindowForTarget")
        page.call(
            "Browser.setWindowBounds",
            {
                "windowId": window["windowId"],
                "bounds": {"width": width, "height": height, "windowState": "normal"},
            },
        )
    except PageError:
        pass


def _shot(page: DevTools, directory: Path, name: str, width: int = 1100, height: int = 2200) -> Path:
    last: Exception | None = None
    for _ in range(2):
        fresh = DevTools(page.ws_url)
        try:
            fresh.call("Page.enable")
            fresh.call("Runtime.enable")
            _window(fresh, width, height)
            fresh.call(
                "Runtime.evaluate",
                {"expression": "window.scrollTo(0, 0)", "returnByValue": True},
            )
            result = fresh.call(
                "Page.captureScreenshot",
                {"format": "png", "optimizeForSpeed": True},
                timeout=8,
            )
            data = base64.b64decode(result["data"])
            if len(data) < 1000:
                result = fresh.call(
                    "Page.captureScreenshot",
                    {
                        "format": "png",
                        "captureBeyondViewport": True,
                        "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": 1},
                    },
                    timeout=8,
                )
                data = base64.b64decode(result["data"])
            path = directory / name
            path.write_bytes(data)
            print(f"screenshot {path}", flush=True)
            return path
        except (PageError, TimeoutError, OSError) as exc:
            last = exc
        finally:
            fresh.close()
    raise PageError(last)


def _layout(page: DevTools, *, columns: int, width: float | None) -> None:
    """Cards sit in two columns above 900px and one column below. The column is 1160px at 1280."""
    measured = _eval(
        page,
        """(() => {
          const cards = Array.from(document.querySelectorAll('article.card')).slice(0, 2);
          const boxes = cards.map((card) => {
            const box = card.getBoundingClientRect();
            return {top: box.top, left: box.left, bottom: box.bottom};
          });
          const column = document.querySelector('body.result .column');
          const wide = column ? column.getBoundingClientRect().width : 0;
          return {boxes, width: wide};
        })()""",
    )
    if not isinstance(measured, dict):
        raise PageError("the card layout was not measured")
    boxes = measured.get("boxes") or []
    if len(boxes) < 2:
        raise PageError("the result did not show two cards")
    first, second = boxes
    if columns == 2 and abs(float(first["top"]) - float(second["top"])) > 2:
        raise PageError("the cards did not share a row")
    if columns == 1 and float(second["top"]) + 1 < float(first["bottom"]):
        raise PageError("the cards did not stack")
    if width is not None and abs(float(measured.get("width") or 0) - width) > 1:
        raise PageError(f"result column is {measured.get('width')}px")


def _eval(page: DevTools, expression: str):
    result = page.call(
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": True},
    )
    remote = result.get("result", {})
    if remote.get("subtype") == "error" or "exceptionDetails" in result:
        raise PageError(result.get("exceptionDetails") or remote)
    return remote.get("value")


def _node(page: DevTools, selector: str) -> int | None:
    root = page.call("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
    found = page.call("DOM.querySelector", {"nodeId": root, "selector": selector})
    node = int(found.get("nodeId") or 0)
    return node or None


def _wait_node(page: DevTools, selector: str, timeout: float) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            node = _node(page, selector)
        except PageError:
            node = None
        if node:
            return node
        time.sleep(0.1)
    raise PageError(selector)


def _click(page: DevTools, selector: str) -> None:
    node = _wait_node(page, selector, 20)
    page.call("DOM.focus", {"nodeId": node})
    try:
        box = page.call("DOM.getBoxModel", {"nodeId": node})["model"]["content"]
        x = (box[0] + box[4]) / 2
        y = (box[1] + box[5]) / 2
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            page.call(
                "Input.dispatchMouseEvent",
                {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1},
            )
    except PageError:
        shown = json.dumps(selector)
        _eval(page, f"document.querySelector({shown}).click()")


def _fill(page: DevTools, selector: str, text: str) -> None:
    try:
        _click(page, selector)
        page.call("Input.insertText", {"text": text})
    except PageError:
        pass
    shown = json.dumps(selector)
    value = _eval(page, f"document.querySelector({shown}).value")
    if value != text:
        _eval(
            page,
            "(() => { const node = document.querySelector("
            + shown
            + "); node.focus(); node.value = "
            + json.dumps(text)
            + "; return node.value; })()",
        )
        value = _eval(page, f"document.querySelector({shown}).value")
    if value != text:
        raise PageError(f"{selector} showed {value!r}")


def _grab(page: DevTools, directory: Path, name: str) -> Path:
    """Photograph the page as it is. A new connection, and no window change, so it stays fast."""
    last: Exception | None = None
    for _ in range(2):
        fresh = DevTools(page.ws_url)
        try:
            fresh.call("Page.enable")
            result = fresh.call(
                "Page.captureScreenshot",
                {"format": "png", "optimizeForSpeed": True},
                timeout=20,
            )
            data = base64.b64decode(result["data"])
            if len(data) < 1000:
                raise PageError(f"{name} was empty")
            path = directory / name
            path.write_bytes(data)
            print(f"screenshot {path}", flush=True)
            return path
        except (PageError, TimeoutError, OSError) as exc:
            last = exc
        finally:
            fresh.close()
    raise PageError(last)


def _loading(page: DevTools) -> bool:
    raw = _eval(
        page,
        """
        (() => {
          const panel = document.getElementById("steps");
          if (!panel || panel.hidden) return false;
          const items = Array.from(panel.querySelectorAll("li"));
          const active = items.filter((item) => item.className === "active").length;
          const done = items.filter((item) => item.className === "done").length;
          return active === 1 && done >= 1;
        })()
        """,
    )
    return raw is True


def _reduced_steps(page: DevTools) -> bool:
    """True when this lookup is showing the static ring, not a spinning arc."""
    raw = _eval(
        page,
        """
        (() => {
          if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
          const panel = document.getElementById("steps");
          if (!panel || panel.hidden) return false;
          const items = Array.from(panel.querySelectorAll("li"));
          const active = items.filter((item) => item.className === "active").length;
          const done = items.filter((item) => item.className === "done").length;
          const arc = document.querySelector("li.active .arc");
          const dot = document.querySelector("li.active .dot");
          const arcHidden = !arc || getComputedStyle(arc).display === "none";
          const dotShown = !!dot && getComputedStyle(dot).display !== "none";
          return active === 1 && done >= 1 && arcHidden && dotShown;
        })()
        """,
    )
    return raw is True


def _hold(page: DevTools) -> None:
    """Stop the page while the picture is taken, so the result cannot replace the steps."""
    try:
        page.call("Debugger.enable")
        page.call("Debugger.pause")
    except PageError:
        pass


def _release(page: DevTools) -> None:
    try:
        page.call("Debugger.resume")
    except PageError:
        pass
    try:
        page.call("Debugger.disable")
    except PageError:
        pass


def _reduced_motion(page: DevTools) -> None:
    page.call(
        "Emulation.setEmulatedMedia",
        {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]},
    )
    matched = _eval(page, "window.matchMedia('(prefers-reduced-motion: reduce)').matches")
    if matched is not True:
        raise PageError("reduced motion was not emulated")


def _state(page: DevTools) -> dict:
    raw = _eval(
        page,
        """
        (() => {
          const fail = document.querySelector(".failure");
          const figures = Array.from(document.querySelectorAll(".figure")).map((node) => node.textContent.trim());
          return JSON.stringify({
            failure: fail ? fail.textContent.trim() : "",
            figures: figures,
            text: document.body ? document.body.innerText : ""
          });
        })()
        """,
    )
    return json.loads(raw or "{}")


def _open_chrome(url: str) -> tuple[subprocess.Popen, DevTools]:
    binary = chrome_binary()
    if binary is None:
        raise PageError("Google Chrome is not installed")
    debug = socket.socket()
    debug.bind(("127.0.0.1", 0))
    port = debug.getsockname()[1]
    debug.close()
    profile = Path(tempfile.mkdtemp(prefix="white-cliff-chrome-"))
    stderr_fd, stderr_name = tempfile.mkstemp(prefix="white-cliff-chrome-err-")
    stderr_path = Path(stderr_name)
    stderr_file = os.fdopen(stderr_fd, "wb")
    command = [
        binary,
        "--headless=old",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile}",
        "--window-size=1100,2200",
        "about:blank",
    ]
    chrome = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=stderr_file,
        start_new_session=True,
    )
    info = None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if chrome.poll() is not None:
            stderr_file.close()
            detail = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
            raise PageError(f"chrome exited {chrome.returncode}: {detail[-4000:]}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=0.5) as response:
                tabs = json.loads(response.read().decode("utf-8"))
            if tabs:
                info = tabs[0]
                break
        except (OSError, json.JSONDecodeError):
            time.sleep(0.1)
    if not stderr_file.closed:
        stderr_file.close()
    if not info or not info.get("webSocketDebuggerUrl"):
        if chrome.poll() is None:
            os.killpg(chrome.pid, signal.SIGTERM)
        detail = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
        message = "chrome did not open a debugging port within 30 seconds"
        if detail:
            message = f"{message}: {detail[-4000:]}"
        raise PageError(message)
    page = DevTools(info["webSocketDebuggerUrl"])
    page.call("Page.enable")
    page.call("Runtime.enable")
    _window(page)
    page.call("Page.navigate", {"url": url})
    return chrome, page


def drive(
    url: str,
    out_dir: Path,
    query: str = "NVDA",
    heading: str = "NVIDIA",
    suffix: str = "million",
) -> None:
    """Click through first run, search, and one live lookup. Fail on any miss."""
    out_dir.mkdir(parents=True, exist_ok=True)
    chrome, page = _open_chrome(url)
    try:
        _wait_node(page, "#name", 20)
        _shot(page, out_dir, f"smoke-{ARCH}-1-first-run.png")
        _fill(page, "#name", TEST_NAME)
        _fill(page, "#email", test_email())
        _click(page, 'form[action="/identity"] button')
        _wait_node(page, "#query", 20)
        _shot(page, out_dir, f"smoke-{ARCH}-2-search.png")
        _fill(page, "#query", query)
        _click(page, 'form[action="/explain"] button')
        _wait_result(page, out_dir, heading, suffix, loading=True)
        loading_shot = out_dir / f"smoke-{ARCH}-4-loading.png"
        result_shot = out_dir / f"smoke-{ARCH}-3-nvda.png"
        if loading_shot.read_bytes() == result_shot.read_bytes():
            raise PageError("the loading picture is the result page")
        _window(page, 1280, 2200)
        _layout(page, columns=2, width=1160)
        _shot(page, out_dir, f"smoke-{ARCH}-9-result-1280.png", width=1280, height=2200)
        _window(page, 1100, 2200)
        _layout(page, columns=2, width=None)
        _shot(page, out_dir, f"smoke-{ARCH}-8-result-1100.png")
        _window(page, 640, 1600)
        _layout(page, columns=1, width=None)
        _shot(page, out_dir, f"smoke-{ARCH}-6-result-640.png", width=640, height=1600)
        _shot(page, out_dir, f"smoke-{ARCH}-7-result-420.png", width=420, height=1800)
        _window(page)
        _reduced_motion(page)
        page.call("Page.navigate", {"url": url})
        _wait_node(page, "#query", 20)
        if _eval(page, "window.matchMedia('(prefers-reduced-motion: reduce)').matches") is not True:
            raise PageError("reduced motion was not emulated")
        _fill(page, "#query", query)
        _click(page, 'form[action="/explain"] button')
        reduced_deadline = time.time() + 60
        while time.time() < reduced_deadline:
            try:
                if _reduced_steps(page):
                    _hold(page)
                    try:
                        _grab(page, out_dir, f"smoke-{ARCH}-5-reduced.png")
                    finally:
                        _release(page)
                    break
            except PageError:
                _release(page)
            time.sleep(0.02)
        else:
            raise PageError("the reduced-motion steps were not shown")
        _wait_result(page, out_dir, heading, suffix, loading=False, capture=False)
    finally:
        page.close()
        if chrome.poll() is None:
            os.killpg(chrome.pid, signal.SIGTERM)
            try:
                chrome.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(chrome.pid, signal.SIGKILL)


def _wait_result(
    page,
    out_dir,
    heading,
    suffix,
    *,
    loading: bool,
    fresh: bool = False,
    shot_name: str = "",
    capture: bool = True,
) -> None:
    deadline = time.time() + 180
    last = ""
    saw_loading = not loading
    replaced = not fresh
    while time.time() < deadline:
        if fresh and not replaced:
            try:
                replaced = _eval(page, "document.documentElement.dataset.shot || ''") != "old"
            except PageError:
                replaced = False
            if not replaced:
                time.sleep(0.05)
                continue
        if loading and not saw_loading:
            try:
                if _loading(page):
                    _hold(page)
                    try:
                        _grab(page, out_dir, f"smoke-{ARCH}-4-loading.png")
                    finally:
                        _release(page)
                    saw_loading = True
            except PageError:
                _release(page)
        try:
            state = _state(page)
        except PageError:
            time.sleep(0.05)
            continue
        last = state.get("text") or ""
        if state.get("failure"):
            if capture:
                _shot(page, out_dir, shot_name or f"smoke-{ARCH}-3-nvda.png")
            raise PageError(state["failure"])
        figures = state.get("figures") or []
        if heading in last and any(figure.endswith(suffix) for figure in figures):
            if loading and not saw_loading:
                raise PageError("the loading steps were not shown")
            time.sleep(0.9)
            try:
                _eval(page, "window.scrollTo(0, 0)")
            except PageError:
                pass
            if capture:
                _shot(page, out_dir, shot_name or f"smoke-{ARCH}-3-nvda.png")
            print(f"result {heading} with a figure ending in {suffix}", flush=True)
            return
        time.sleep(0.05)
    if capture:
        _shot(page, out_dir, shot_name or f"smoke-{ARCH}-3-nvda.png")
    raise PageError(last[:800] or "the result page did not appear")


def launch(binary: str) -> tuple[subprocess.Popen, str, object]:
    """Start the built app. BROWSER records the URL and opens nothing."""
    return _start(binary)


def _start(binary: str) -> tuple[subprocess.Popen, str, object]:
    binary = str(Path(binary).resolve())
    home = Path(tempfile.mkdtemp(prefix="white-cliff-home-"))
    url_file = home / "opened-url"
    recorder = home / "record-url"
    recorder.write_text(
        "#!/bin/sh\n" + 'printf "%s\\n" "$1" > "$URL_FILE"\n',
        encoding="utf-8",
    )
    recorder.chmod(0o755)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["URL_FILE"] = str(url_file)
    env["BROWSER"] = str(recorder)
    log = open(home / "app.log", "wb")
    port_file = home / "Library" / "Application Support" / "White Cliff" / "instance.port"
    proc = subprocess.Popen(
        [binary],
        env=env,
        cwd=str(home),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        if url_file.is_file():
            url = url_file.read_text(encoding="utf-8").strip()
            if url.startswith("http://127.0.0.1:"):
                print(f"app {url}", flush=True)
                return proc, url, log
        if port_file.is_file():
            try:
                port = int(port_file.read_text(encoding="ascii").split()[1])
            except (OSError, ValueError, IndexError):
                port = 0
            if 0 < port <= 65535:
                url = f"http://127.0.0.1:{port}/"
                print(f"app {url}", flush=True)
                return proc, url, log
        if proc.poll() is not None:
            log.flush()
            detail = (home / "app.log").read_text(encoding="utf-8", errors="replace")[:800]
            log.close()
            raise PageError(f"app exited {proc.returncode}: {detail}")
        time.sleep(0.1)
    log.flush()
    detail = (home / "app.log").read_text(encoding="utf-8", errors="replace")[:800]
    stop(proc, log)
    message = "the built app did not record a URL"
    if detail.strip():
        message = f"{message}: {detail}"
    raise PageError(message)


def stop(proc: subprocess.Popen, log) -> None:
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
    log.close()


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: smoke_mac.py BINARY", file=sys.stderr)
        return 2
    binary = sys.argv[1]
    if not Path(binary).is_file():
        print(f"missing binary {binary}", file=sys.stderr)
        return 2
    proc = None
    log = None
    try:
        proc, url, log = launch(binary)
        drive(url, Path.cwd())
    except PageError as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        if proc is not None and log is not None:
            stop(proc, log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
