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
        self.sock.close()

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


def _shot(page: DevTools, directory: Path, name: str) -> Path:
    metrics = page.call("Page.getLayoutMetrics")
    size = metrics.get("cssContentSize") or metrics["contentSize"]
    width = max(1, float(size["width"]))
    height = max(1, float(size["height"]))
    result = page.call(
        "Page.captureScreenshot",
        {
            "format": "png",
            "captureBeyondViewport": True,
            "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": 1},
        },
        timeout=30,
    )
    path = directory / name
    path.write_bytes(base64.b64decode(result["data"]))
    print(f"screenshot {path}", flush=True)
    return path


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
    box = page.call("DOM.getBoxModel", {"nodeId": node})["model"]["content"]
    x = (box[0] + box[4]) / 2
    y = (box[1] + box[5]) / 2
    for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
        page.call(
            "Input.dispatchMouseEvent",
            {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1},
        )


def _fill(page: DevTools, selector: str, text: str) -> None:
    _click(page, selector)
    page.call("Input.insertText", {"text": text})
    value = _eval(page, f"document.querySelector({json.dumps(selector)}).value")
    if value != text:
        raise PageError(f"{selector} showed {value!r}")


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
    chrome = subprocess.Popen(
        [
            binary,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={profile}",
            "--window-size=1100,1400",
            "about:blank",
        ],
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
        deadline = time.time() + 180
        last = ""
        while time.time() < deadline:
            try:
                state = _state(page)
            except PageError:
                time.sleep(0.2)
                continue
            last = state.get("text") or ""
            if state.get("failure"):
                _shot(page, out_dir, f"smoke-{ARCH}-3-nvda.png")
                raise PageError(state["failure"])
            figures = state.get("figures") or []
            if heading in last and any(figure.endswith(suffix) for figure in figures):
                _shot(page, out_dir, f"smoke-{ARCH}-3-nvda.png")
                print(f"result {heading} with a figure ending in {suffix}", flush=True)
                return
            time.sleep(0.4)
        _shot(page, out_dir, f"smoke-{ARCH}-3-nvda.png")
        raise PageError(last[:800] or "the result page did not appear")
    finally:
        page.close()
        if chrome.poll() is None:
            os.killpg(chrome.pid, signal.SIGTERM)
            try:
                chrome.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(chrome.pid, signal.SIGKILL)


def launch(binary: str) -> tuple[subprocess.Popen, str, object]:
    """Start the built app. BROWSER records the URL and opens nothing."""
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
    proc = subprocess.Popen(
        [binary],
        env=env,
        cwd=str(home),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        if url_file.is_file():
            url = url_file.read_text(encoding="utf-8").strip()
            if url.startswith("http://127.0.0.1:"):
                print(f"app {url}", flush=True)
                return proc, url, log
        if proc.poll() is not None:
            log.flush()
            detail = (home / "app.log").read_text(encoding="utf-8", errors="replace")[:800]
            log.close()
            raise PageError(f"app exited {proc.returncode}: {detail}")
        time.sleep(0.1)
    stop(proc, log)
    raise PageError("the built app did not record a URL")


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
