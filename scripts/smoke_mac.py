"""Drive the built Mac app through the runner's Chrome. No browser window opens."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import select
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

from white_cliff.disclaimer import DISCLAIMER
from white_cliff.lexicon import STRINGS

TEST_NAME = "White Cliff Test"
GERMAN_DISCLAIMER = STRINGS["§1.DISCLAIMER"][1]
ARCH = platform.machine()
_SEC_HOSTS = frozenset({"www.sec.gov", "data.sec.gov", "efts.sec.gov"})


class _SecHold:
    """The smoke stub. The filing download waits until the shot releases it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._release = threading.Event()
        self._release.set()
        self._armed = False
        self._all = False
        self._www = 0

    def arm(self, everything: bool = False) -> None:
        with self._lock:
            self._www = 0
            self._armed = True
            self._all = everything
            self._release.clear()

    def release(self) -> None:
        with self._lock:
            self._armed = False
            self._all = False
        self._release.set()

    def wait(self, host: str) -> None:
        with self._lock:
            armed = self._armed
            block_all = getattr(self, "_all", False)
            if host == "www.sec.gov":
                self._www += 1
                hold = armed and (block_all or self._www >= 2)
            else:
                hold = armed and block_all
        if hold:
            self._release.wait()

    def wait_url(self, url: str) -> None:
        self.wait(urllib.parse.urlsplit(url).hostname or "")


_sec_hold = _SecHold()


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
        self._connect()

    def _connect(self) -> None:
        old = getattr(self, "sock", None)
        if old is not None:
            try:
                old.close()
            except OSError:
                pass
        parsed = urllib.parse.urlsplit(self.ws_url)
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
        self._events: list[dict] = []

    def call(self, method: str, params: dict | None = None, timeout: float = 20):
        try:
            return self._call(method, params, timeout)
        except (BrokenPipeError, ConnectionError, TimeoutError):
            self._connect()
            self._call("Page.enable", {}, timeout)
            self._call("Runtime.enable", {}, timeout)
            return self._call(method, params, timeout)

    def _call(self, method: str, params: dict | None = None, timeout: float = 20):
        self._next += 1
        ident = self._next
        payload = json.dumps({"id": ident, "method": method, "params": params or {}}).encode()
        self._send(0x81, payload)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                message = self._read(deadline)
            except TimeoutError:
                break
            if message is None:
                break
            data = json.loads(message)
            if data.get("id") == ident:
                if "error" in data:
                    raise PageError(data["error"])
                return data.get("result", {})
            self._keep(data)
        raise PageError(method)

    def next_event(self, method: str, timeout: float) -> dict:
        deadline = time.time() + timeout
        while True:
            for index, event in enumerate(self._events):
                if event.get("method") == method:
                    return self._events.pop(index)
            if time.time() >= deadline:
                raise PageError(method)
            try:
                message = self._read(deadline)
            except TimeoutError:
                continue
            if not message:
                continue
            data = json.loads(message)
            self._keep(data)

    def _keep(self, data: dict) -> None:
        """Ack a screencast frame as it arrives, so the next one is not held back."""
        if data.get("method") != "Page.screencastFrame":
            if data.get("method"):
                self._events.append(data)
            return
        params = data.get("params") or {}
        session = params.get("sessionId")
        if session is not None:
            self._next += 1
            payload = json.dumps(
                {
                    "id": self._next,
                    "method": "Page.screencastFrameAck",
                    "params": {"sessionId": session},
                }
            ).encode()
            try:
                self._send(0x81, payload)
            except OSError:
                pass
        self._events.append(data)

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

    def _frame(self, deadline: float) -> tuple[int, bool, bytes]:
        """One websocket frame. A large reply arrives as several frames."""
        while len(self._buf) < 2:
            self._fill(deadline)
        second = self._buf[1]
        opcode = self._buf[0] & 0x0F
        fin = bool(self._buf[0] & 0x80)
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
        return opcode, fin, payload

    def _read(self, deadline: float):
        parts: list[bytes] = []
        kind = 0
        while True:
            opcode, fin, payload = self._frame(deadline)
            if opcode == 0x8:
                raise PageError("devtools closed")
            if opcode == 0x9:
                self._send(0x0A, payload)
                continue
            if opcode == 0x1 or (opcode == 0 and parts):
                if opcode == 0x1:
                    kind = opcode
                parts.append(payload)
                if fin and kind == 0x1:
                    return b"".join(parts).decode("utf-8")
                continue
            if fin and not parts:
                continue


def _paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    if abs(estimate - left) <= abs(estimate - up) and abs(estimate - left) <= abs(estimate - up_left):
        return left
    if abs(estimate - up) <= abs(estimate - up_left):
        return up
    return up_left


def _png_rows(data: bytes) -> tuple[int, int, int, int, list[bytes]]:
    """Decode one screenshot. Chrome writes an 8-bit RGB or RGBA PNG."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise PageError("the picture is not a PNG")
    pos = 8
    width = height = bit_depth = color = 0
    body = b""
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        kind = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        if kind == b"IHDR":
            width, height, bit_depth, color = struct.unpack(">IIBB", chunk[:10])
        elif kind == b"IDAT":
            body += chunk
        elif kind == b"IEND":
            break
        pos += 12 + length
    channels = {0: 1, 2: 3, 6: 4}.get(color)
    if channels is None or bit_depth != 8:
        raise PageError("the picture uses an unexpected PNG layout")
    raw = zlib.decompress(body)
    stride = width * channels
    rows: list[bytes] = []
    index = 0
    previous = bytearray(stride)
    for _ in range(height):
        filter_type = raw[index]
        index += 1
        row = bytearray(raw[index : index + stride])
        index += stride
        if filter_type == 1:
            for column in range(stride):
                left = row[column - channels] if column >= channels else 0
                row[column] = (row[column] + left) & 255
        elif filter_type == 2:
            for column in range(stride):
                row[column] = (row[column] + previous[column]) & 255
        elif filter_type == 3:
            for column in range(stride):
                left = row[column - channels] if column >= channels else 0
                row[column] = (row[column] + ((left + previous[column]) // 2)) & 255
        elif filter_type == 4:
            for column in range(stride):
                left = row[column - channels] if column >= channels else 0
                up_left = previous[column - channels] if column >= channels else 0
                row[column] = (row[column] + _paeth(left, previous[column], up_left)) & 255
        elif filter_type != 0:
            raise PageError("the picture uses an unknown PNG filter")
        rows.append(bytes(row))
        previous = row
    return width, height, color, bit_depth, rows


def _png_bytes(width: int, height: int, color: int, bit_depth: int, rows: list[bytes]) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", width, height, bit_depth, color, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def _crop_png(data: bytes, height: int) -> bytes:
    width, total, color, bit_depth, rows = _png_rows(data)
    if height >= total:
        return data
    return _png_bytes(width, height, color, bit_depth, rows[:height])


def _intel() -> bool:
    """The Intel Mac window is narrower than the layouts this smoke photographs."""
    return sys.platform == "darwin" and ARCH == "x86_64"


_SCREEN_LEFT: int | None = None
_BROWSER: DevTools | None = None
_TARGET_ID = ""
_BOUNDS = ""


def _screen_width(page: DevTools) -> int:
    if _PAUSED:
        return 0
    try:
        raw = _eval(page, "screen.width")
    except (PageError, TimeoutError, OSError):
        return 0
    return int(raw) if isinstance(raw, (int, float)) else 0


def _fit_window(page: DevTools, width: int, height: int) -> None:
    """Put the window on a screen wide enough for the picture.

    The headless screen starts at 800px. A metrics override then reports a wide
    screen while the photographed window stays near 777px.
    """
    if not _intel():
        return
    global _SCREEN_LEFT, _BOUNDS
    # The launch screen is 1400px. A window parked at 2000 is off that screen,
    # and then the cast sends no frame.
    _SCREEN_LEFT = 0
    bounds = {
        "left": 0,
        "top": 0,
        "width": int(width),
        "height": int(min(height, 1400)),
        "windowState": "normal",
    }
    attempts: list[tuple[DevTools, dict]] = [(page, {})]
    if _BROWSER is not None and _BROWSER is not page and _TARGET_ID:
        attempts.insert(0, (_BROWSER, {"targetId": _TARGET_ID}))
    last = ""
    for session, params in attempts:
        try:
            found = session.call("Browser.getWindowForTarget", params)
            window_id = found["windowId"]
            session.call(
                "Browser.setWindowBounds",
                {"windowId": window_id, "bounds": {"windowState": "normal"}},
            )
            session.call(
                "Browser.setWindowBounds",
                {"windowId": window_id, "bounds": bounds},
            )
            seen = session.call("Browser.getWindowForTarget", params).get("bounds") or {}
            _BOUNDS = (
                f"{seen.get('left')},{seen.get('top')} "
                f"{seen.get('width')}x{seen.get('height')}"
            )
            if int(seen.get("width") or 0) >= int(width):
                return
        except (PageError, KeyError, TypeError, ValueError) as exc:
            last = str(exc)
    if last:
        _BOUNDS = f"{_BOUNDS} {last}".strip()


def _window(page: DevTools, width: int = 1100, height: int = 2200, *, reset: bool = False) -> None:
    """Emulate the layout. The real window cannot be wider than the Intel display."""
    height_px = min(int(height), 900)
    metrics = {
        "width": int(width),
        "height": height_px,
        "deviceScaleFactor": 1,
        "mobile": False,
    }
    if _intel():
        # The headless screen starts at 800px. Grow it before the metrics
        # override, which reports a wide screen while the frame stays near 759px.
        # Printing leaves that override stuck near 957px. Clearing it and setting
        # the width alone, as the other Mac path does, reaches the next size.
        if reset:
            try:
                page.call("Emulation.clearDeviceMetricsOverride")
            except PageError:
                pass
            try:
                page.call("Emulation.setDeviceMetricsOverride", metrics)
            except PageError:
                pass
            return
        _fit_window(page, width, height)
        named = dict(metrics)
        named["screenWidth"] = int(width)
        named["screenHeight"] = height_px
        try:
            page.call("Emulation.setDeviceMetricsOverride", named)
        except PageError:
            pass
        _fit_window(page, width, height)
        return
    try:
        page.call("Emulation.clearDeviceMetricsOverride")
    except PageError:
        pass
    try:
        page.call("Emulation.setDeviceMetricsOverride", metrics)
    except PageError:
        pass


def _css_width(page: DevTools) -> int:
    """The layout width in CSS pixels. innerWidth stays at the Intel display size after a full-page shot."""
    try:
        metrics = page.call("Page.getLayoutMetrics")
    except PageError:
        metrics = {}
    if isinstance(metrics, dict):
        for key in ("cssLayoutViewport", "layoutViewport"):
            view = metrics.get(key) or {}
            if isinstance(view, dict):
                raw = view.get("clientWidth")
                if isinstance(raw, (int, float)) and raw:
                    return int(raw)
    if _PAUSED:
        return 0
    try:
        raw = _eval(page, "document.documentElement.clientWidth")
    except (PageError, TimeoutError, OSError):
        return 0
    return int(raw) if isinstance(raw, (int, float)) else 0


def _document_width(page: DevTools) -> int:
    if _PAUSED:
        return 0
    try:
        raw = _eval(page, "document.documentElement.clientWidth")
    except (PageError, TimeoutError, OSError):
        return 0
    return int(raw) if isinstance(raw, (int, float)) else 0


def _wide(page: DevTools, width: int) -> bool:
    if _css_width(page) == width:
        return True
    try:
        return _eval(page, "window.innerWidth") == width
    except PageError:
        return False


_DEBUG_PORT = 0
_CHROME_ERR: Path | None = None


def _document_html(page: DevTools) -> str:
    root = page.call("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
    found = page.call("DOM.querySelector", {"nodeId": root, "selector": "html"})
    node = int(found.get("nodeId") or 0)
    if not node:
        raise PageError("the page had no document")
    return page.call("DOM.getOuterHTML", {"nodeId": node})["outerHTML"]


def _open_tab() -> tuple[DevTools, str]:
    """A new tab. Its screenshot cannot tile the Intel window or stick the next size."""
    last: Exception | None = None
    url = f"http://127.0.0.1:{_DEBUG_PORT}/json/new?about:blank"
    for method in ("PUT", "GET"):
        try:
            request = urllib.request.Request(url, method=method)
            with urllib.request.urlopen(request, timeout=5) as response:
                info = json.loads(response.read().decode("utf-8"))
            if isinstance(info, list):
                info = info[0]
            return DevTools(info["webSocketDebuggerUrl"]), str(info["id"])
        except (OSError, KeyError, json.JSONDecodeError, PageError) as exc:
            last = exc
    raise PageError(last)


def _close_tab(target_id: str) -> None:
    url = f"http://127.0.0.1:{_DEBUG_PORT}/json/close/{target_id}"
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=5).read()
    except OSError:
        pass


def _static_ring(html: str) -> str:
    """The reduced-motion ring, written into the copy so the first paint is already still."""
    html = html.replace(
        '<circle class="arc"',
        '<circle class="arc" style="display:none"',
        1,
    )
    html = html.replace(
        '<circle class="dot"',
        '<circle class="dot" style="display:block"',
        1,
    )
    return html.replace(
        '<circle class="track"',
        '<circle class="track" style="stroke:#0a4b8f;stroke-width:4"',
        1,
    )


def _settled(page: DevTools) -> None:
    """Wait until a card's rise has painted. The next card stays invisible during its delay."""
    _eval(
        page,
        """new Promise((resolve) => {
          const start = Date.now();
          const tick = () => {
            const running = document.getAnimations().some((item) => item.playState === "running");
            if (!running || Date.now() - start > 1500) {
              resolve(true);
              return;
            }
            setTimeout(tick, 50);
          };
          tick();
        })""",
    )


def _frame_png(event: dict | None) -> bytes:
    params = (event or {}).get("params") or {}
    encoded = params.get("data")
    if not isinstance(encoded, str) or not encoded:
        return b""
    return base64.b64decode(encoded)


def _ack_frame(page: DevTools, event: dict | None) -> None:
    params = (event or {}).get("params") or {}
    session = params.get("sessionId")
    if session is None:
        return
    try:
        page.call("Page.screencastFrameAck", {"sessionId": session})
    except (PageError, TimeoutError, OSError):
        pass


_LAST = b""
_SEEN: set[bytes] = set()
_COPY_ERROR = ""


def _activate() -> None:
    """Show the main window again. A copied tab otherwise keeps the cast silent."""
    if _BROWSER is None or not _TARGET_ID:
        return
    try:
        _BROWSER.call("Target.activateTarget", {"targetId": _TARGET_ID})
    except (PageError, TimeoutError, OSError):
        pass


def _copied_png(page: DevTools, width: int) -> bytes:
    """The current document in a new tab.

    A screenshot of this window leaves the next Intel layout near 906px.
    """
    global _COPY_ERROR
    try:
        html = _document_html(page)
        tab, target = _open_tab()
    except (PageError, TimeoutError, OSError) as exc:
        _COPY_ERROR = str(exc)[:180]
        return b""
    try:
        tab.call("Page.enable")
        tab.call("Runtime.enable")
        frame = tab.call("Page.getFrameTree")["frameTree"]["frame"]["id"]
        tab.call("Page.setDocumentContent", {"frameId": frame, "html": html})
        _window(tab, width or 1100, 900)
        result = tab.call(
            "Page.captureScreenshot",
            {"format": "png", "optimizeForSpeed": True},
            timeout=8,
        )
        _COPY_ERROR = ""
        return base64.b64decode(result["data"])
    except (PageError, TimeoutError, OSError, KeyError, ValueError) as exc:
        _COPY_ERROR = str(exc)[:180]
        return b""
    finally:
        try:
            tab.close()
        except (PageError, OSError):
            pass
        _close_tab(target)
        _activate()


def _paint(page: DevTools) -> None:
    """Ask for a frame without waiting. Waiting holds the renderer, so the cast repeats the last picture."""
    try:
        page.call(
            "Runtime.evaluate",
            {
                "expression": "requestAnimationFrame(() => requestAnimationFrame(() => {}))",
                "returnByValue": True,
                "awaitPromise": False,
            },
            1,
        )
    except (PageError, TimeoutError, OSError):
        pass


def _live_frame(page: DevTools, width: int = 0) -> bytes:
    """One frame of this window.

    A surface screenshot repeats the Intel page beside itself and then leaves
    the next layout at the 906px display. The first screencast frame can still
    show the previous scroll. The next frame replaces it when it is as wide.
    """
    page.call("Page.startScreencast", {"format": "png", "everyNthFrame": 1})
    chosen = b""
    try:
        try:
            event = page.next_event("Page.screencastFrame", 0.6)
        except (PageError, TimeoutError):
            event = None
        # An idle page does not paint, so the cast stays silent. Ask for one frame.
        if event is None and not _PAUSED:
            _paint(page)
            try:
                event = page.next_event("Page.screencastFrame", 4)
            except (PageError, TimeoutError):
                event = None
        _ack_frame(page, event)
        chosen = _frame_png(event)
        # The resize paint is missed when it happens before the cast starts.
        # Resize again while the cast is listening. While paused, do not.
        if not _PAUSED and width and (
            not chosen
            or _png_width(chosen) != width
            or chosen in _SEEN
            or chosen == _LAST
        ):
            # The screen-size override can leave the previous picture in place.
            _window(page, width, 900, reset=True)
            later_deadline = time.time() + 2.5
            while time.time() < later_deadline:
                try:
                    later = page.next_event("Page.screencastFrame", 0.4)
                except (PageError, TimeoutError):
                    continue
                _ack_frame(page, later)
                fresh = _frame_png(later)
                if not fresh:
                    continue
                if not chosen or _png_width(fresh) >= _png_width(chosen):
                    chosen = fresh
                if (
                    _png_width(chosen) == width
                    and chosen not in _SEEN
                    and chosen != _LAST
                ):
                    break
    finally:
        try:
            page.call("Page.stopScreencast")
        except (PageError, TimeoutError, OSError):
            pass
    return chosen


def _frame_after_resize(page: DevTools, width: int) -> bytes:
    """A frame painted after the window is already this wide.

    The cast starts after the resize. A frame already queued is the previous
    picture, and pausing first leaves the Intel cast with nothing to send.
    """
    page.call("Page.startScreencast", {"format": "png", "everyNthFrame": 1})

    def take(timeout: float) -> bytes:
        try:
            event = page.next_event("Page.screencastFrame", timeout)
        except (PageError, TimeoutError):
            return b""
        _ack_frame(page, event)
        return _frame_png(event)

    def good(data: bytes) -> bool:
        return bool(
            data
            and _png_width(data) == width
            and data not in _SEEN
            and data != _LAST
        )

    def nudge() -> None:
        # Do not await the paint. Awaiting it holds the renderer, and this
        # loading page then navigates before a frame is sent.
        try:
            page.call(
                "Runtime.evaluate",
                {
                    "expression": "requestAnimationFrame(() => requestAnimationFrame(() => {}))",
                    "returnByValue": True,
                    "awaitPromise": False,
                },
                1,
            )
        except (PageError, TimeoutError, OSError):
            pass

    try:
        # The window is already this wide. Paint after the cast starts, and
        # keep a frame from that paint. Resize again only when it is not.
        nudge()
        fresh = take(0.6)
        if good(fresh):
            return fresh
        _window(page, width, 900)
        nudge()
        deadline = time.time() + 1
        while time.time() < deadline:
            fresh = take(0.3)
            if good(fresh):
                return fresh
        return b""
    finally:
        try:
            page.call("Page.stopScreencast")
        except (PageError, TimeoutError, OSError):
            pass


def _commit_live_frame(
    directory: Path, name: str, data: bytes, wanted: int, height: int
) -> Path:
    """Save one live frame. A missing or repeated frame fails, and is not copied."""
    global _LAST
    got = _png_width(data)
    stale = bool(data) and (data == _LAST or data in _SEEN)
    if not data or stale:
        why = "had no screencast frame" if not data else "repeated a previous screencast frame"
        raise PageError(f"{name} is not a live window picture: it {why}")
    if len(data) < 1000 or got != wanted:
        raise PageError(f"{name} is {got}px wide, wanted {wanted}")
    height_px = min(int(height or 900), 900)
    limit = height or height_px
    png_height = int.from_bytes(data[20:24], "big") if len(data) >= 24 else 0
    saved = _crop_png(data, limit) if png_height > limit else data
    _LAST = data
    _SEEN.add(data)
    path = directory / name
    path.write_bytes(saved)
    print(f"screenshot {path}", flush=True)
    return path


def _png_width(data: bytes) -> int:
    return int.from_bytes(data[16:20], "big") if len(data) >= 24 else 0


def _intel_photo(
    page: DevTools,
    directory: Path,
    name: str,
    width: int,
    height: int,
    *,
    keep_scroll: bool,
    reveal: bool,
    motion: str = "",
) -> Path:
    """Photograph the live window. A copied document hides a paint fault and the typed ticker."""
    global _LAST
    del reveal
    wanted = int(width or _css_width(page) or 1100)
    height_px = min(int(height or 900), 900)
    last: Exception | None = None
    for attempt in range(2):
        # A new connection keeps the search page picture after this page has moved.
        own = False
        fresh = page
        try:
            if own:
                fresh.call("Page.enable")
                fresh.call("Runtime.enable")
            if not _PAUSED:
                _activate()
                _window(fresh, wanted, height_px)
                try:
                    if motion:
                        _motion(fresh, motion)
                    if not keep_scroll:
                        _eval(fresh, "window.scrollTo(0, 0)")
                    _settled(fresh)
                    _paint(fresh)
                except (PageError, TimeoutError, OSError):
                    pass
            # The layout can already say 1100 while the pictured window is still
            # the 800px headless screen. Wait for a frame of the requested width.
            deadline = time.time() + (0 if _PAUSED else 1.5)
            data = b""
            got = 0
            while True:
                data = _live_frame(fresh, wanted)
                got = _png_width(data)
                stale = bool(data) and (data == _LAST or data in _SEEN)
                if len(data) >= 1000 and got == wanted and not stale:
                    break
                if _PAUSED or not data or time.time() >= deadline:
                    # A copied document is not the live window. A missing or repeated
                    # frame must fail here instead of passing as that copy.
                    if not data or stale:
                        why = (
                            "had no screencast frame"
                            if not data
                            else "repeated a previous screencast frame"
                        )
                        raise PageError(f"{name} is not a live window picture: it {why}")
                    # One copy, after the window has had its chance to resize.
                    # Copying the main window sticks the next layout near 906px.
                    alt = _copied_png(fresh, wanted)
                    alt_w = _png_width(alt)
                    if (
                        len(alt) >= 1000
                        and alt_w == wanted
                        and alt != data
                        and alt not in _SEEN
                        and alt != _LAST
                    ):
                        data = alt
                        break
                    if stale or got == wanted:
                        raise PageError(f"{name} repeated the previous picture copy {alt_w} {_COPY_ERROR}")
                    screen = 0 if _PAUSED else _screen_width(fresh)
                    raise PageError(
                        f"{name} is {got}px wide, wanted {wanted}, screen {screen} "
                        f"copy {alt_w} {_COPY_ERROR} {_BOUNDS}"
                    )
                _window(fresh, wanted, height_px)
                time.sleep(0.25)
            limit = height or height_px
            png_height = int.from_bytes(data[20:24], "big") if len(data) >= 24 else 0
            saved = _crop_png(data, limit) if png_height > limit else data
            _LAST = data
            _SEEN.add(data)
            path = directory / name
            path.write_bytes(saved)
            print(f"screenshot {path}", flush=True)
            return path
        except (PageError, TimeoutError, OSError) as exc:
            last = exc
        finally:
            if own:
                fresh.close()
    raise PageError(last)


def _shot(
    page: DevTools,
    directory: Path,
    name: str,
    width: int = 1100,
    height: int = 2200,
    *,
    full: bool = False,
) -> Path:
    if _intel():
        if full:
            try:
                _motion(page, "reduce")
            except PageError:
                pass
        _window(page, width, height)
        return _intel_photo(page, directory, name, width, height, keep_scroll=False, reveal=full)
    last: Exception | None = None
    asked = height
    for _ in range(2):
        fresh = page if full else DevTools(page.ws_url)
        try:
            if not full:
                fresh.call("Page.enable")
                fresh.call("Runtime.enable")
            if full:
                try:
                    _motion(fresh, "reduce")
                except PageError:
                    pass
            _window(fresh, width, asked)
            deadline = time.time() + 2
            while time.time() < deadline:
                if _wide(fresh, width):
                    break
                _window(fresh, width, asked)
                time.sleep(0.1)
            fresh.call(
                "Runtime.evaluate",
                {"expression": "window.scrollTo(0, 0)", "returnByValue": True},
            )
            if full and not _wide(fresh, width):
                seen = _css_width(fresh)
                raise PageError(f"the window stayed at {seen}, wanted {width}")
            result = fresh.call(
                "Page.captureScreenshot",
                {"format": "png", "optimizeForSpeed": True},
                timeout=60 if full else 8,
            )
            data = base64.b64decode(result["data"])
            if full:
                _window(fresh, width, asked)
            else:
                got = int.from_bytes(data[16:20], "big") if len(data) >= 24 else 0
                if not _intel() and (len(data) < 1000 or got != width):
                    result = fresh.call(
                        "Page.captureScreenshot",
                        {
                            "format": "png",
                            "captureBeyondViewport": True,
                            "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": 1},
                        },
                        timeout=20,
                    )
                    data = base64.b64decode(result["data"])
                    _window(fresh, width, asked, reset=True)
                elif _intel() and (len(data) < 1000 or got != width):
                    raise PageError(f"{name} is {got}px wide, wanted {width}")
            path = directory / name
            path.write_bytes(data)
            print(f"screenshot {path}", flush=True)
            return path
        except (PageError, TimeoutError, OSError) as exc:
            last = exc
        finally:
            if fresh is not page:
                fresh.close()
    raise PageError(last)


def _print_preview(page: DevTools, out_dir: Path, html: str = "", *, shot: str | None = None) -> None:
    """Print the open page. The optional shot is the 1280 print preview."""
    tab = page
    target_id = ""
    try:
        if _intel():
            if not html:
                html = _document_html(page)
            tab, target_id = _open_tab()
            tab.call("Page.enable")
            tab.call("Runtime.enable")
            frame = tab.call("Page.getFrameTree")["frameTree"]["frame"]["id"]
            tab.call("Page.setDocumentContent", {"frameId": frame, "html": html})
        _window(tab, 1280, 2200)
        tab.call("Emulation.setEmulatedMedia", {"media": "print"})
        deadline = time.time() + 2
        while time.time() < deadline:
            hidden = _eval(tab, "getComputedStyle(document.querySelector('.top')).display")
            if hidden == "none" and _wide(tab, 1280):
                break
            time.sleep(0.05)
        else:
            raise PageError("print styles were not applied")
        _eval(tab, "window.scrollTo(0, 0)")
        if shot is not None:
            image = tab.call(
                "Page.captureScreenshot",
                {"format": "png", "optimizeForSpeed": True},
                timeout=60,
            )
            data = base64.b64decode(image["data"])
            got = int.from_bytes(data[16:20], "big") if len(data) >= 24 else 0
            if got != 1280:
                raise PageError(f"print preview is {got}px wide")
            path = out_dir / shot
            path.write_bytes(data)
        printed = tab.call(
            "Page.printToPDF",
            {
                "printBackground": True,
                "displayHeaderFooter": False,
                "paperWidth": 8.5,
                "paperHeight": 11,
            },
            timeout=60,
        )
        pdf = base64.b64decode(printed["data"])
        _require_disclaimer_on_every_page(tab, pdf)
    finally:
        try:
            tab.call("Emulation.setEmulatedMedia", {"media": "screen"})
        except PageError:
            pass
        if target_id:
            tab.close()
            _close_tab(target_id)


_WORD = re.compile(r"[A-Za-z]{3,}")
_COMMON = frozenset(
    "the and for was from with million quarter filing this that are not year "
    "rose percent company report".split()
)


def _same_line(text: str) -> str:
    for mark in ("\u00ad", "\u200b", "\ufeff", "\u2060"):
        text = text.replace(mark, "")
    return " ".join(text.split())


def _disclaimer_text(text: str) -> str:
    """The disclaimer compared byte for byte, with whitespace collapsed and nothing else changed."""
    return " ".join(text.split())


def _page_can_be_read(text: str) -> bool:
    """Glyph ids that did not decode are not a page we can read."""
    flat = _same_line(text)
    if sum(char.isalpha() for char in flat) < 40:
        return False
    if "sec.gov" in flat:
        return True
    words = _WORD.findall(flat)
    if len(words) < 6:
        return False
    return sum(word.lower() in _COMMON for word in words) >= 2


def _page_kind(text: str) -> str:
    flat = _same_line(text)
    if sum(char.isalpha() for char in flat) < 40 and "sec.gov" not in flat:
        return "blank"
    if _page_can_be_read(text):
        return "readable"
    return "unreadable"


def _read_disclaimer_pages(texts: list[str], *, german: bool = False) -> str:
    """Empty only when every page can be read and carries the full line.

    A PDF whose pages cannot be read at all is 'unreadable'. A mix of readable
    and unreadable pages is a failure, not a reason to skip the unreadable ones.
    """
    kinds = [_page_kind(text) for text in texts]
    if not any(kind == "readable" for kind in kinds):
        return "unreadable"
    if any(kind == "unreadable" for kind in kinds):
        return "a printed page could not be read"
    pages = [text for text, kind in zip(texts, kinds) if kind == "readable"]
    if len(pages) < 2:
        return "the print summary was one page"
    lines = [DISCLAIMER]
    if german:
        lines.append(GERMAN_DISCLAIMER)
    for text in pages:
        folded = _disclaimer_text(text)
        for line in lines:
            if _disclaimer_text(line) not in folded:
                sample = re.sub(r"\S+@\S+", "", _same_line(text))[:80]
                return f"a printed page does not carry the disclaimer ({sample})"
    return ""


def _require_disclaimer_on_every_page(tab: DevTools, pdf: bytes) -> None:
    """The full disclaimer is on each page. Some PDFs hide that writing in a font map."""
    lang = _eval(tab, "document.documentElement.lang")
    german = lang == "de"
    verdict = _read_disclaimer_pages(_pdf_page_texts(pdf), german=german)
    if verdict == "":
        return
    if verdict != "unreadable":
        raise PageError(verdict)
    page_count = len(re.findall(rb"/Type\s*/Page(?!s)", pdf))
    if page_count < 2:
        raise PageError("the print summary was one page")
    header = _eval(
        tab,
        """(() => {
          const head = document.querySelector("thead.print-head");
          if (!head) return {text: "", display: "", lang: document.documentElement.lang};
          return {
            text: head.innerText,
            display: getComputedStyle(head).display,
            lang: document.documentElement.lang
          };
        })()""",
    )
    if not isinstance(header, dict):
        raise PageError("a printed page does not carry the disclaimer")
    german = header.get("lang") == "de" or german
    text = str(header.get("text") or "")
    lines = [DISCLAIMER]
    if german:
        lines.append(GERMAN_DISCLAIMER)
    if any(_disclaimer_text(line) not in _disclaimer_text(text) for line in lines):
        raise PageError("a printed page does not carry the disclaimer")
    if header.get("display") != "table-header-group":
        raise PageError("the disclaimer does not repeat on each printed page")


def _pdf_objects(data: bytes) -> dict[int, tuple[bytes, bytes | None]]:
    """Object number to (dictionary, decoded stream). A stream stays with the page that draws it."""
    integers = {
        int(match.group(1)): int(match.group(2))
        for match in re.finditer(rb"(\d+)\s+\d+\s+obj\s+(\d+)\s+endobj", data)
    }
    objects: dict[int, tuple[bytes, bytes | None]] = {}
    cursor = 0
    while True:
        match = re.search(rb"(\d+)\s+\d+\s+obj\b", data[cursor:])
        if match is None:
            break
        number = int(match.group(1))
        start = cursor + match.end()
        endobj = data.find(b"endobj", start)
        if endobj < 0:
            break
        window = data[start:endobj]
        stream_at = re.search(rb"stream\r?\n", window)
        if stream_at is None:
            objects[number] = (window, None)
            cursor = endobj + len(b"endobj")
            continue
        dictionary = window[: stream_at.start()]
        raw_at = start + stream_at.end()
        indirect = re.search(rb"/Length\s+(\d+)\s+\d+\s+R", dictionary)
        direct = re.search(rb"/Length\s+(\d+)\b", dictionary)
        if indirect:
            length = integers.get(int(indirect.group(1)), 0)
            raw = data[raw_at : raw_at + length]
            cursor = data.find(b"endobj", raw_at + length)
        elif direct:
            length = int(direct.group(1))
            raw = data[raw_at : raw_at + length]
            cursor = data.find(b"endobj", raw_at + length)
        else:
            endstream = data.find(b"endstream", raw_at)
            raw = data[raw_at:endstream].strip(b"\r\n")
            cursor = data.find(b"endobj", endstream)
        if cursor < 0:
            break
        decoded: bytes | None
        if b"FlateDecode" in dictionary or raw.startswith((b"\x78\x9c", b"\x78\xda", b"\x78\x01")):
            try:
                decoded = zlib.decompress(raw)
            except zlib.error:
                decoded = None
        else:
            decoded = raw
        objects[number] = (dictionary, decoded)
        cursor += len(b"endobj")
    return objects


def _pdf_xobjects(dictionary: bytes, objects: dict[int, tuple[bytes, bytes | None]]) -> dict[str, int]:
    found = re.search(rb"/XObject\s*<<([^>]*)>>", dictionary, re.S)
    if found is None:
        indirect = re.search(rb"/XObject\s+(\d+)\s+\d+\s+R", dictionary)
        if indirect and int(indirect.group(1)) in objects:
            found = re.search(
                rb"<<([^>]*)>>",
                objects[int(indirect.group(1))][0],
                re.S,
            )
    if found is None:
        return {}
    return {
        name.decode(): int(number)
        for name, number in re.findall(rb"/([A-Za-z0-9]+)\s+(\d+)\s+\d+\s+R", found.group(1))
    }


def _pdf_resource_map(dictionary: bytes, objects: dict[int, tuple[bytes, bytes | None]]) -> dict[str, int]:
    """Form names this page can paint, including names inherited from its page tree."""
    mapping = _pdf_xobjects(dictionary, objects)
    resource = re.search(rb"/Resources\s+(\d+)\s+\d+\s+R", dictionary)
    if resource and int(resource.group(1)) in objects:
        mapping = _pdf_xobjects(objects[int(resource.group(1))][0], objects) or mapping
    seen: set[int] = set()
    parent = re.search(rb"/Parent\s+(\d+)\s+\d+\s+R", dictionary)
    while parent and int(parent.group(1)) not in seen and int(parent.group(1)) in objects:
        number = int(parent.group(1))
        seen.add(number)
        parent_dict = objects[number][0]
        mapping = mapping or _pdf_resource_map(parent_dict, objects)
        parent = re.search(rb"/Parent\s+(\d+)\s+\d+\s+R", parent_dict)
    return mapping


def _pdf_page_streams(data: bytes) -> list[bytes]:
    """One blob per page: the page contents plus each form that page paints."""
    objects = _pdf_objects(data)
    pages: list[tuple[int, bytes]] = []
    for number, (dictionary, _stream) in objects.items():
        if re.search(rb"/Type\s*/Page(?!s)", dictionary) is None:
            continue
        array = re.search(rb"/Contents\s*\[([^\]]*)\]", dictionary)
        if array is not None:
            contents = [int(item) for item in re.findall(rb"(\d+)\s+\d+\s+R", array.group(1))]
        else:
            single = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", dictionary)
            contents = [int(single.group(1))] if single else []
        mapping = _pdf_resource_map(dictionary, objects)
        chunks: list[bytes] = []
        seen: set[int] = set()

        def paint(obj_num: int, names: dict[str, int]) -> None:
            if obj_num in seen or obj_num not in objects:
                return
            seen.add(obj_num)
            form_dict, blob = objects[obj_num]
            if b"/Subtype /Image" in form_dict or b"/Subtype/Image" in form_dict:
                return
            local = _pdf_xobjects(form_dict, objects) or names
            if blob:
                chunks.append(blob)
            if not blob:
                return
            for name in re.findall(rb"/([A-Za-z0-9]+)\s+Do\b", blob):
                paint(local.get(name.decode(), -1), local)

        for content in contents:
            paint(content, mapping)
        if chunks:
            pages.append((number, b"\n".join(chunks)))
    if pages:
        return [blob for _number, blob in sorted(pages)]
    streams = [
        blob
        for _dictionary, blob in objects.values()
        if blob and b"792" in blob and (b"Tj" in blob or b"TJ" in blob)
    ]
    return streams


def _pdf_page_texts(data: bytes) -> list[str]:
    """Visible writing on each letter page. Each font keeps its own glyph map."""
    objects = _pdf_objects(data)
    streams = [blob for _dictionary, blob in objects.values() if blob]

    def character(hex_digits: str) -> str:
        if len(hex_digits) > 4:
            return "".join(
                chr(int(hex_digits[index : index + 4], 16))
                for index in range(0, len(hex_digits) - 3, 4)
            )
        code = int(hex_digits, 16)
        return chr(code) if code <= 0x10FFFF else ""

    def font_map(blob: bytes) -> dict[int, str]:
        cmap: dict[int, str] = {}
        for match in re.finditer(rb"beginbfrange\s+(.*?)endbfrange", blob, re.S):
            body = match.group(1)
            for row in re.finditer(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>",
                body,
            ):
                left, right = int(row.group(1), 16), int(row.group(2), 16)
                dest = int(row.group(3), 16)
                for offset, src in enumerate(range(left, right + 1)):
                    code = dest + offset
                    if code <= 0x10FFFF:
                        cmap[src] = chr(code)
            for row in re.finditer(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[([^\]]*)\]",
                body,
            ):
                left = int(row.group(1), 16)
                for offset, dest in enumerate(re.findall(rb"<([0-9A-Fa-f]+)>", row.group(3))):
                    cmap[left + offset] = character(dest.decode())
        for match in re.finditer(rb"beginbfchar\s+(.*?)endbfchar", blob, re.S):
            for row in re.finditer(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", match.group(1)):
                cmap[int(row.group(1), 16)] = character(row.group(2).decode())
        return cmap

    maps = [font_map(stream) for stream in streams if b"beginbfchar" in stream or b"beginbfrange" in stream]
    maps = [cmap for cmap in maps if cmap]

    def literal(body: bytes) -> str:
        chars: list[str] = []
        index = 0
        while index < len(body):
            byte = body[index]
            if byte == 0x5C and index + 1 < len(body):
                index += 1
                nxt = body[index]
                named = {
                    ord("n"): "\n",
                    ord("r"): "\r",
                    ord("t"): "\t",
                    ord("("): "(",
                    ord(")"): ")",
                    ord("\\"): "\\",
                }
                if nxt in named:
                    chars.append(named[nxt])
                elif 48 <= nxt <= 55:
                    digits = bytes([nxt])
                    while index + 1 < len(body) and len(digits) < 3 and 48 <= body[index + 1] <= 55:
                        index += 1
                        digits += bytes([body[index]])
                    chars.append(chr(int(digits, 8)))
                else:
                    chars.append(chr(nxt))
            else:
                chars.append(chr(byte))
            index += 1
        return "".join(chars)

    def glyphs(hex_text: str, cmap: dict[int, str] | None, width: int) -> str:
        raw = bytes.fromhex(hex_text)
        chars = []
        for index in range(0, len(raw) - width + 1, width):
            code = int.from_bytes(raw[index : index + width], "big")
            if cmap is None:
                chars.append(chr(code) if code <= 0x10FFFF else "\ufffd")
            else:
                chars.append(cmap.get(code, "\ufffd"))
        return "".join(chars)

    def page_fonts(dictionary: bytes) -> dict[str, dict[int, str]]:
        found = re.search(rb"/Font\s*<<([^>]*)>>", dictionary, re.S)
        if found is None:
            resource = re.search(rb"/Resources\s+(\d+)\s+\d+\s+R", dictionary)
            if resource and int(resource.group(1)) in objects:
                return page_fonts(objects[int(resource.group(1))][0])
            parent = re.search(rb"/Parent\s+(\d+)\s+\d+\s+R", dictionary)
            if parent and int(parent.group(1)) in objects:
                return page_fonts(objects[int(parent.group(1))][0])
            return {}
        found_maps: dict[str, dict[int, str]] = {}
        for name, number in re.findall(rb"/([A-Za-z0-9]+)\s+(\d+)\s+\d+\s+R", found.group(1)):
            font, _blob = objects[int(number)]
            link = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", font)
            blob = objects[int(link.group(1))][1] if link else None
            found_maps[name.decode()] = font_map(blob or b"")
        return found_maps

    def decode_typed(stream: bytes, fonts: dict[str, dict[int, str]]) -> str:
        """Each glyph uses the font named before it. ActualText is the source writing."""
        parts: list[str] = []
        current: dict[int, str] = {}
        actual: str | None = None
        used = False
        line_y: float | None = None
        tokens = re.compile(
            rb"/([A-Za-z0-9]+)\s+[\d.]+\s+Tf"
            rb"|1 0 0 -1 [\d.]+ ([\d.]+) Tm"
            rb"|/ActualText\s*\(((?:\\.|[^\\)])*)\)"
            rb"|EMC\b"
            rb"|<([0-9A-Fa-f]+)>\s*Tj"
            rb"|\(((?:\\.|[^\\)])*)\)\s*Tj"
        )

        def break_line(y: float) -> None:
            nonlocal line_y
            written = "".join(parts)
            if line_y is not None and y != line_y and written and not written[-1].isspace():
                parts.append(" ")
            line_y = y

        for match in tokens.finditer(stream):
            if match.group(1):
                current = fonts.get(match.group(1).decode(), {})
                continue
            if match.group(2):
                break_line(float(match.group(2)))
                continue
            if match.group(3) is not None:
                actual = literal(match.group(3))
                used = False
                continue
            if match.group(0).startswith(b"EMC"):
                actual = None
                continue
            if actual is not None:
                if not used:
                    parts.append(actual)
                    used = True
                continue
            if match.group(4) is not None:
                raw = bytes.fromhex(match.group(4).decode())
                parts.append(
                    "".join(
                        current.get(int.from_bytes(raw[index : index + 2], "big"), "")
                        for index in range(0, len(raw) - 1, 2)
                    )
                )
                continue
            if match.group(5) is not None:
                parts.append(literal(match.group(5)))
        return "".join(parts)

    shown = re.compile(
        rb"<[0-9A-Fa-f]+>\s*Tj|\((?:\\.|[^\\)])*\)\s*Tj|\[(?:[^\]]*)\]\s*TJ",
        re.S,
    )
    page_dicts = [
        dictionary
        for _number, (dictionary, _stream) in sorted(objects.items())
        if re.search(rb"/Type\s*/Page(?!s)", dictionary)
    ]
    pages = []
    phrase = "This tool explains the numbers"
    for index, stream in enumerate(_pdf_page_streams(data)):
        if index < len(page_dicts) and (b" Tf" in stream or b"/ActualText" in stream):
            typed = decode_typed(stream, page_fonts(page_dicts[index]))
            if phrase in _same_line(typed) or "Dieses Werkzeug" in typed:
                pages.append(typed)
                continue
        plain: list[str] = []
        coded: list[str] = []
        for item in shown.finditer(stream):
            token = item.group(0)
            if token.endswith(b"TJ"):
                for part in re.finditer(rb"<[0-9A-Fa-f]+>|\((?:\\.|[^\\)])*\)", token):
                    raw = part.group(0)
                    if raw.startswith(b"<"):
                        coded.append(raw[1:-1].decode())
                    else:
                        plain.append(literal(raw[1:-1]))
            elif token.lstrip().startswith(b"("):
                plain.append(literal(token[: token.rfind(b"Tj")].strip()[1:-1]))
            else:
                coded.append(token[: token.rfind(b"Tj")].strip()[1:-1].decode())
        base = "".join(plain)
        chosen = base
        candidates = []
        for cmap in maps:
            for width in (2, 1):
                candidates.append(base + "".join(glyphs(item, cmap, width) for item in coded))
        for width in (2, 1):
            candidates.append(base + "".join(glyphs(item, None, width) for item in coded))
        for candidate in candidates:
            if phrase in _same_line(candidate):
                chosen = candidate
                break
            if candidate.count(" ") > chosen.count(" "):
                chosen = candidate
        pages.append(chosen)
    return pages


def _layout(page: DevTools, *, columns: int, width: float | None) -> None:
    """Cards sit in two columns above 900px and one column below. The column is 1160px at 1280."""
    deadline = time.time() + 1
    while True:
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
            # The rise starts the next card a moment later, so its top is still lower.
            stacked = float(second["top"]) + 1 >= float(first["bottom"])
            if stacked or time.time() >= deadline:
                seen = _document_width(page) or _css_width(page)
                raise PageError(f"the cards did not share a row at {seen}px")
            time.sleep(0.05)
            continue
        if columns == 1 and float(second["top"]) + 1 < float(first["bottom"]):
            raise PageError("the cards did not stack")
        if width is not None and abs(float(measured.get("width") or 0) - width) > 1:
            raise PageError(f"result column is {measured.get('width')}px")
        return


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


def _press(page: DevTools, selector: str) -> None:
    """Click through the page's own script, so a corner control is not missed."""
    _wait_node(page, selector, 20)
    shown = json.dumps(selector)
    _eval(
        page,
        "(() => { const node = document.querySelector("
        + shown
        + "); node.scrollIntoView({block: 'center'}); node.click(); return true; })()",
    )


def _wait_ready(page: DevTools, timeout: float) -> None:
    """The submit handler is in a script after the form. Wait until it has run."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if _eval(page, "document.readyState") == "complete":
                return
        except PageError:
            pass
        time.sleep(0.05)
    raise PageError("the page did not finish loading")


def _submit_form(page: DevTools, selector: str) -> None:
    """Start the form through its own submit handler."""
    _wait_node(page, selector + " button", 20)
    shown = json.dumps(selector)
    _eval(
        page,
        "(() => { const form = document.querySelector("
        + shown
        + "); form.requestSubmit(form.querySelector('button')); return true; })()",
    )


def _loading_view(page: DevTools) -> str:
    """Structural facts only. No field values."""
    raw = _eval(
        page,
        """
        (() => {
          const steps = document.getElementById("steps");
          const arc = document.querySelector("li.active .arc");
          return [
            "hidden=" + (steps ? String(steps.hidden) : "missing"),
            "active=" + (steps ? steps.querySelectorAll("li.active").length : 0),
            "arc=" + (arc ? getComputedStyle(arc).display : "missing"),
            "reduce=" + window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ].join(" ");
        })()
        """,
    )
    return str(raw)


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


def _fit(page: DevTools, width: int, height: int) -> None:
    """Set the layout width. A viewport shot can leave the next size on the Intel display."""
    deadline = time.time() + 6
    while time.time() < deadline:
        _window(page, width, height)
        if _wide(page, width):
            return
        time.sleep(0.05)
    _window(page, width, height, reset=True)
    deadline = time.time() + 4
    while time.time() < deadline:
        if _wide(page, width):
            return
        _window(page, width, height, reset=True)
        time.sleep(0.1)
    layout = _css_width(page)
    seen = ""
    try:
        seen = str(_eval(page, "window.innerWidth"))
    except PageError:
        seen = "unknown"
    document = _document_width(page)
    extra = f", document {document}" if document else ""
    raise PageError(f"the window stayed at {layout}, wanted {width}, inner {seen}{extra}")


def _motion(page: DevTools, value: str) -> None:
    page.call(
        "Emulation.setEmulatedMedia",
        {"features": [{"name": "prefers-reduced-motion", "value": value}]},
    )


def _spinning(page: DevTools) -> bool:
    raw = _eval(
        page,
        """
        (() => {
          const arc = document.querySelector("li.active .arc");
          return !!arc && getComputedStyle(arc).display !== "none";
        })()
        """,
    )
    return raw is True


def _grab(
    page: DevTools,
    directory: Path,
    name: str,
    width: int = 0,
    height: int = 0,
    top: int = 0,
    motion: str = "",
) -> Path:
    """Photograph the page as it is. A new connection, and no clip, so a paused page still works."""
    del top
    if _intel():
        return _intel_photo(
            page,
            directory,
            name,
            width,
            height,
            keep_scroll=True,
            reveal=not motion,
            motion=motion,
        )
    last: Exception | None = None
    for _ in range(2):
        fresh = DevTools(page.ws_url)
        try:
            fresh.call("Page.enable")
            fresh.call("Runtime.enable")
            if width:
                _window(fresh, width, max(height, 900))
            result = fresh.call(
                "Page.captureScreenshot",
                {"format": "png", "optimizeForSpeed": True},
                timeout=20,
            )
            data = base64.b64decode(result["data"])
            if len(data) < 1000:
                raise PageError(f"{name} was empty")
            if width:
                got = int.from_bytes(data[16:20], "big") if len(data) >= 24 else 0
                if got != width:
                    raise PageError(f"{name} is {got}px wide, wanted {width}")
            if height:
                png_height = int.from_bytes(data[20:24], "big") if len(data) >= 24 else 0
                if png_height > height:
                    data = _crop_png(data, height)
            path = directory / name
            path.write_bytes(data)
            print(f"screenshot {path}", flush=True)
            return path
        except (PageError, TimeoutError, OSError) as exc:
            last = exc
        finally:
            fresh.close()
    raise PageError(last)


def _blank(data: bytes) -> bool:
    """A picture with almost no ink above the bottom edge. A black bar there does not count."""
    try:
        width, height, color, _depth, rows = _png_rows(data)
    except PageError:
        return True
    channels = {0: 1, 2: 3, 6: 4}.get(color)
    if channels is None or width < 50 or height < 50:
        return True
    limit = max(1, int(height * 0.9))
    dark = sampled = 0
    for row in rows[:limit:8]:
        for column in range(0, width, 8):
            start = column * channels
            pixel = row[start : start + min(3, channels)]
            sampled += 1
            if pixel and min(pixel) < 180:
                dark += 1
    return sampled == 0 or dark * 500 < sampled


def _distinct(directory: Path) -> None:
    """Fail when two smoke pictures are the same file or one of them is blank."""
    seen: dict[str, str] = {}
    shots = sorted(directory.glob("smoke-*.png"))
    if len(shots) < 2:
        raise PageError("the smoke pictures were not written")
    for path in shots:
        data = path.read_bytes()
        if _blank(data):
            raise PageError(f"{path.name} is blank")
        digest = hashlib.sha256(data).hexdigest()
        previous = seen.get(digest)
        if previous:
            raise PageError(f"{path.name} is the same picture as {previous}")
        seen[digest] = path.name


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


def _column_shown(page: DevTools) -> bool:
    """The German column fades in. A frame during that fade is the empty top of the page."""
    raw = _eval(
        page,
        """
        (() => {
          const column = document.querySelector(".column");
          if (!column) return true;
          const opacity = parseFloat(getComputedStyle(column).opacity || "1");
          const running = typeof column.getAnimations === "function"
            && column.getAnimations().some((item) => item.playState === "running");
          return opacity > 0.98 && !running;
        })()
        """,
    )
    return raw is True


def _steps_visible(page: DevTools) -> bool:
    """The steps panel is open. The first step is enough; the filing reply is still held."""
    raw = _eval(
        page,
        """
        (() => {
          const panel = document.getElementById("steps");
          if (!panel || panel.hidden) return false;
          const active = panel.querySelectorAll("li.active").length;
          return active === 1;
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
          return active === 1 && done >= 2 && arcHidden && dotShown;
        })()
        """,
    )
    return raw is True


_PAUSED = False


def _hold(page: DevTools) -> None:
    """Stop the page while the picture is taken, so the result cannot replace the steps."""
    global _PAUSED
    _PAUSED = True
    try:
        page.call("Debugger.enable")
        page.call("Debugger.pause")
    except PageError:
        pass


def _release(page: DevTools) -> None:
    global _PAUSED
    try:
        page.call("Debugger.resume")
    except PageError:
        pass
    try:
        page.call("Debugger.disable")
    except PageError:
        pass
    _PAUSED = False


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


def _widen(page: DevTools, port: int) -> DevTools:
    """A new window at 1100px when the first one stayed on the old 800px screen."""
    if not _intel() or _BROWSER is None:
        return page
    try:
        inner = int(_eval(page, "window.innerWidth") or 0)
    except (PageError, TypeError, ValueError, TimeoutError, OSError):
        return page
    if inner >= 1100:
        return page
    try:
        created = _BROWSER.call(
            "Target.createTarget",
            {
                "url": "about:blank",
                "left": 0,
                "top": 0,
                "width": 1100,
                "height": 900,
                "newWindow": True,
            },
            timeout=4,
        )
    except (PageError, TimeoutError, OSError, TypeError, ValueError):
        return page
    target_id = str(created.get("targetId") or "")
    if not target_id:
        return page
    info = None
    deadline = time.time() + 2
    while time.time() < deadline and info is None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=0.5) as response:
                tabs = json.loads(response.read().decode("utf-8"))
            for tab in tabs:
                if tab.get("id") == target_id and tab.get("webSocketDebuggerUrl"):
                    info = tab
                    break
        except (OSError, json.JSONDecodeError):
            pass
        if info is None:
            time.sleep(0.05)
    if not info:
        return page
    fresh = DevTools(info["webSocketDebuggerUrl"])
    try:
        fresh.call("Page.enable")
        fresh.call("Runtime.enable")
        opened = int(_eval(fresh, "window.innerWidth") or 0)
    except (PageError, TypeError, ValueError, TimeoutError, OSError):
        fresh.close()
        return page
    if opened < 1100:
        fresh.close()
        return page
    global _TARGET_ID
    _TARGET_ID = target_id
    page.close()
    return fresh


def _open_chrome(url: str) -> tuple[subprocess.Popen, DevTools]:
    binary = chrome_binary()
    if binary is None:
        raise PageError("Google Chrome is not installed")
    debug = socket.socket()
    debug.bind(("127.0.0.1", 0))
    port = debug.getsockname()[1]
    debug.close()
    global _DEBUG_PORT, _SCREEN_LEFT, _BROWSER, _TARGET_ID, _BOUNDS, _LAST, _SEEN
    _LAST = b""
    _SEEN = set()
    _DEBUG_PORT = port
    _SCREEN_LEFT = None
    _BROWSER = None
    _TARGET_ID = ""
    _BOUNDS = ""
    profile = Path(tempfile.mkdtemp(prefix="white-cliff-chrome-"))
    stderr_fd, stderr_name = tempfile.mkstemp(prefix="white-cliff-chrome-err-")
    global _CHROME_ERR
    _CHROME_ERR = Path(stderr_name)
    stderr_path = Path(stderr_name)
    stderr_file = os.fdopen(stderr_fd, "wb")
    command = [
        binary,
        "--headless=old",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-gpu-compositing",
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
    if _intel():
        # Headless defaults to an 800x600 screen, so a 1100 window stays near 800.
        command[command.index("--headless=old")] = "--headless=new"
        # Name the screen before the window is created. Later, the window stays
        # near 759px on a 1400px screen and cannot be resized.
        command.insert(1, "--screen-info={1400x2400}")
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
    _TARGET_ID = str(info.get("id") or "")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as response:
            version = json.loads(response.read().decode("utf-8"))
        browser_url = version.get("webSocketDebuggerUrl")
        if browser_url:
            _BROWSER = DevTools(browser_url)
    except (OSError, json.JSONDecodeError, PageError):
        _BROWSER = None
    page.call("Page.enable")
    page.call("Runtime.enable")
    page = _widen(page, port)
    _window(page)
    page.call("Page.navigate", {"url": url})
    try:
        _motion(page, "no-preference")
    except PageError:
        pass
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
        _loading_shot(out_dir, f"smoke-{ARCH}-4-loading.png", 1100, url, query)
        _click(page, 'form[action="/explain"] button')
        _wait_result(page, out_dir, heading, suffix, loading=False)
        loading_shot = out_dir / f"smoke-{ARCH}-4-loading.png"
        result_shot = out_dir / f"smoke-{ARCH}-3-nvda.png"
        if loading_shot.read_bytes() == result_shot.read_bytes():
            raise PageError("the loading picture is the result page")
        _fit(page, 1280, 2200)
        _layout(page, columns=2, width=1160)
        text_left = _eval(
            page,
            """(() => {
              const node = document.querySelector(".disclaimer");
              const range = document.createRange();
              range.selectNodeContents(node);
              return range.getBoundingClientRect().left;
            })()""",
        )
        if abs(float(text_left) - 92) > 4:
            raise PageError(f"the disclaimer text starts at {text_left}")
        _shot(page, out_dir, f"smoke-{ARCH}-9-result-1280.png", width=1280, height=2200, full=True)
        # Printing leaves the Intel layout near 957px, so keep the English page
        # and print it after the other pictures have used the live window.
        english = _document_html(page) if _intel() else ""
        print_shot = f"smoke-{ARCH}-21-print-1280.png"
        if not _intel():
            _print_preview(page, out_dir, shot=print_shot)
        _fit(page, 1100, 2200)
        _layout(page, columns=2, width=None)
        _shot(page, out_dir, f"smoke-{ARCH}-8-result-1100.png", full=True)
        _fit(page, 640, 1600)
        _layout(page, columns=1, width=None)
        _shot(page, out_dir, f"smoke-{ARCH}-6-result-640.png", width=640, height=1600, full=True)
        _shot(page, out_dir, f"smoke-{ARCH}-7-result-420.png", width=420, height=1800, full=True)
        _window(page)
        _reduced_motion(page)
        page.call("Page.navigate", {"url": url})
        _wait_node(page, "#query", 20)
        if _eval(page, "window.matchMedia('(prefers-reduced-motion: reduce)').matches") is not True:
            raise PageError("reduced motion was not emulated")
        _fill(page, "#query", query)
        _loading_shot(
            out_dir, f"smoke-{ARCH}-5-reduced.png", 1100, url, query, reduced=True
        )
        _click(page, 'form[action="/explain"] button')
        _wait_result(page, out_dir, heading, suffix, loading=False, capture=False)
        _german_shots(page, out_dir, url, query, heading)
        if english:
            _print_preview(page, out_dir, english, shot=print_shot)
        _distinct(out_dir)
    finally:
        page.close()
        if chrome.poll() is None:
            os.killpg(chrome.pid, signal.SIGTERM)
            try:
                chrome.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(chrome.pid, signal.SIGKILL)


def _wait_first_run(page: DevTools, timeout: float = 20) -> None:
    """The erase control posts, then the browser opens a new first-run page."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            path = _eval(page, "location.pathname") or ""
            gone = _node(page, 'form[action="/identity/erase"]') is None
            ready = _node(page, "#name") is not None
        except PageError:
            path, gone, ready = "", False, False
        if path in {"/", ""} and gone and ready:
            return
        time.sleep(0.05)
    raise PageError("the first-run page did not replace the saved name")


def _wait_text(page: DevTools, needle: str, timeout: float = 20) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            last = _eval(page, "document.body ? document.body.innerText : ''") or ""
        except PageError:
            last = ""
        if needle in last:
            return
        time.sleep(0.05)
    raise PageError(last[:400] or "the expected text did not appear")


def _share_card(page: DevTools, directory: Path, name: str, width: int, height: int) -> None:
    """One named picture of the German share-count card at this width."""
    deadline = time.time() + 8
    while time.time() < deadline:
        _window(page, width, max(height, 1100))
        if _wide(page, width):
            break
        time.sleep(0.1)
    _eval(page, "window.scrollTo(0, 0)")
    box = _eval(
        page,
        """
        (() => {
          const card = [...document.querySelectorAll("article.card")].find((item) => item.textContent.includes("Aktien"));
          if (!card) return null;
          const found = card.getBoundingClientRect();
          return {top: found.top + window.scrollY, height: Math.ceil(found.height)};
        })()
        """,
    )
    if not isinstance(box, dict):
        labels = _eval(
            page,
            "JSON.stringify([...document.querySelectorAll('h3.label')].map((item) => item.textContent))",
        )
        raise PageError(f"the German share card was not on the page: {labels}")
    _eval(page, f"window.scrollTo(0, {max(int(box['top']) - 8, 0)})")
    _grab(page, directory, name, 0, max(int(box["height"]) + 16, 280))


def _fresh_target(width: int, height: int) -> DevTools:
    """A new window created at this size. Nothing resizes it afterwards."""
    if _BROWSER is None or not _DEBUG_PORT:
        raise PageError("the browser has no debugging socket")
    created = _BROWSER.call(
        "Target.createTarget",
        {
            "url": "about:blank",
            "left": 0,
            "top": 0,
            "width": int(width),
            "height": int(height),
            "newWindow": True,
        },
        timeout=8,
    )
    target_id = str(created.get("targetId") or "")
    if not target_id:
        raise PageError("the loading window was not created")
    info = None
    deadline = time.time() + 4
    while time.time() < deadline and info is None:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{_DEBUG_PORT}/json/list", timeout=0.5
            ) as response:
                tabs = json.loads(response.read().decode("utf-8"))
            for tab in tabs:
                if tab.get("id") == target_id and tab.get("webSocketDebuggerUrl"):
                    info = tab
                    break
        except (OSError, json.JSONDecodeError):
            pass
        if info is None:
            time.sleep(0.05)
    if not info:
        raise PageError("the loading window did not open a debugging socket")
    page = DevTools(info["webSocketDebuggerUrl"])
    page.target_id = target_id
    return page


def _close_loading_target(page: DevTools) -> None:
    try:
        page.call("Page.stopScreencast")
    except (PageError, TimeoutError, OSError):
        pass
    target_id = str(getattr(page, "target_id", "") or "")
    try:
        page.close()
    except (PageError, TimeoutError, OSError):
        pass
    if _BROWSER is not None and target_id:
        try:
            _BROWSER.call("Target.closeTarget", {"targetId": target_id}, timeout=2)
        except (PageError, TimeoutError, OSError):
            pass


def _discard_queued_frames(page: DevTools) -> None:
    """Drop frames already queued. Stop even if a spinning page keeps sending them."""
    deadline = time.time() + 0.15
    while time.time() < deadline:
        try:
            event = page.next_event("Page.screencastFrame", 0.05)
        except (PageError, TimeoutError):
            return
        _ack_frame(page, event)


def _loading_shot(
    directory: Path,
    name: str,
    width: int,
    url: str,
    query: str,
    *,
    german: bool = False,
    reduced: bool = False,
) -> Path:
    """One loading picture from a window born at this width.

    The cast starts before navigation. The filing download stays held until
    the frame is in hand, so the steps cannot be replaced by the result.
    """
    trace: list[str] = []
    started = time.monotonic()

    def mark(step: str) -> None:
        trace.append(f"{int((time.monotonic() - started) * 1000)} {step}")

    def fail(message: str) -> None:
        detail = "\n".join(trace)
        raise PageError(f"{message}\n{detail}" if detail else message) from None

    page = None
    _sec_hold.arm(everything=not reduced)
    mark("hold")
    try:
        page = _fresh_target(width, 900)
        mark(f"Target.createTarget {width}x900")
        page.call("Page.enable")
        mark("Page.enable")
        page.call("Runtime.enable")
        mark("Runtime.enable")
        if width < 500:
            # Mac will not open a browser window narrower than 500. The viewport still can be.
            try:
                page.call(
                    "Emulation.setDeviceMetricsOverride",
                    {
                        "width": int(width),
                        "height": 900,
                        "deviceScaleFactor": 1,
                        "mobile": False,
                    },
                )
            except PageError:
                pass
            mark(f"Emulation.setDeviceMetricsOverride {width}x900")
        page.call("Page.startScreencast", {"format": "png", "everyNthFrame": 1})
        mark("Page.startScreencast")
        # The main window asks for motion before it loads. A new window does too,
        # or a machine that prefers less motion hides the arc and the shot waits forever.
        _motion(page, "reduce" if reduced else "no-preference")
        mark("Emulation.setEmulatedMedia")
        page.call("Page.navigate", {"url": url})
        mark("Page.navigate")
        _wait_node(page, "#query", 30)
        _wait_ready(page, 30)
        if german and _eval(page, "document.documentElement.lang") != "de":
            _press(page, 'button[lang="de"]')
            _wait_node(page, "#query", 20)
            _wait_ready(page, 20)
        _fill(page, "#query", query)
        _submit_form(page, 'form[action="/explain"]')
        mark("click")
        deadline = time.time() + 90
        ready = False
        while time.time() < deadline:
            try:
                ready = _reduced_steps(page) if reduced else _steps_visible(page)
            except PageError:
                ready = False
            if ready and not reduced:
                try:
                    ready = _spinning(page)
                except PageError:
                    ready = False
            if ready:
                try:
                    ready = _column_shown(page)
                except PageError:
                    ready = False
            if ready:
                break
            time.sleep(0.05)
        if not ready:
            try:
                state = _loading_view(page)
            except PageError:
                state = "view failed"
            fail(f"the loading steps were not shown\n{state}")
        mark("steps")
        _discard_queued_frames(page)
        try:
            page.call(
                "Runtime.evaluate",
                {
                    "expression": "requestAnimationFrame(() => {})",
                    "returnByValue": True,
                    "awaitPromise": False,
                },
                1,
            )
        except (PageError, TimeoutError, OSError):
            pass
        mark("paint")
        data = b""
        frame_deadline = time.time() + 4
        while time.time() < frame_deadline and not data:
            try:
                event = page.next_event("Page.screencastFrame", 0.4)
            except (PageError, TimeoutError):
                continue
            _ack_frame(page, event)
            data = _frame_png(event)
        mark(f"frame {_png_width(data)}")
        try:
            return _commit_live_frame(directory, name, data, width, 900)
        except PageError as exc:
            fail(str(exc))
    finally:
        _sec_hold.release()
        if page is not None:
            _close_loading_target(page)


def _grab_steps(
    page: DevTools,
    directory: Path,
    name: str,
    width: int = 0,
    height: int = 0,
    motion: str = "",
) -> Path:
    """Freeze the steps, then photograph them."""
    if _intel():
        # The typed ticker lives on the control, not in the markup a copied
        # document would keep. Write it down, and let it paint, before pausing.
        try:
            # One synchronous write. Waiting for a frame lets the result replace the steps.
            _eval(
                page,
                """(() => {
                  document.querySelectorAll("input, textarea").forEach((node) => {
                    node.setAttribute("value", node.value);
                  });
                  return true;
                })()""",
            )
        except (PageError, TimeoutError, OSError):
            pass
        if motion:
            try:
                _motion(page, motion)
            except PageError:
                pass
        _activate()
        wanted = int(width or 0)
        if wanted <= 0:
            try:
                wanted = int(_css_width(page) or 1100)
            except (PageError, TimeoutError, OSError, TypeError, ValueError):
                wanted = 1100
        _window(page, wanted, int(height or 900))
        data = _frame_after_resize(page, wanted)
        if data:
            _hold(page)
            try:
                return _commit_live_frame(directory, name, data, wanted, int(height or 0))
            finally:
                _release(page)
        # No frame yet. Pausing flushes a picture that was already composited.
    _hold(page)
    try:
        return _grab(page, directory, name, width, height, motion=motion)
    finally:
        _release(page)


def _loading_at(page: DevTools, out_dir: Path, name: str, width: int, height: int) -> None:
    """Photograph the spinning steps after the window is already this wide."""
    try:
        _motion(page, "no-preference")
    except PageError:
        pass
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            loading = _loading(page)
        except PageError:
            loading = False
        if loading:
            if not _spinning(page):
                raise PageError("the loading picture is the reduced-motion ring")
            _grab_steps(page, out_dir, name, width, height)
            return
        time.sleep(0.02)
    raise PageError("the German loading steps were not shown")


def _panel_shot(page: DevTools, directory: Path, name: str, width: int, kind: str) -> None:
    """One German panel at 1280. Scroll the named line into the viewport, then photograph it."""
    _fit(page, width, 900)
    if kind == "explain":
        opened = _eval(
            page,
            """
            (() => {
              const card = [...document.querySelectorAll("article.card")].find((item) =>
                item.textContent.includes("Formel:"));
              if (!card) return false;
              const button = card.querySelector("button.explain");
              if (button) button.click();
              return true;
            })()
            """,
        )
        if opened is not True:
            raise PageError("the German formula line was not on the page")
        _wait_text(page, "Formel:")
    script = {
        "balance": """
            (() => {
              const card = [...document.querySelectorAll("article.card")].find((item) =>
                item.textContent.includes("abzüglich Zahlungsmittel"));
              if (!card) return false;
              const heading = card.querySelector("h3") || card;
              heading.scrollIntoView({block: "start", inline: "nearest"});
              window.scrollBy(0, -24);
              return true;
            })()
        """,
        "checks": """
            (() => {
              const section = document.querySelector('section.check[data-check="C8"]');
              if (!section) return false;
              const hits = [section, ...section.querySelectorAll("*")].filter((item) =>
                (item.textContent || "").includes("Die Ertragsteuer lag"));
              hits.sort((a, b) => a.textContent.length - b.textContent.length);
              (hits[0] || section).scrollIntoView({block: "start", inline: "nearest"});
              window.scrollBy(0, -24);
              return true;
            })()
        """,
        "explain": """
            (() => {
              const hits = [...document.querySelectorAll("body *")].filter((item) =>
                (item.textContent || "").includes("Formel:"));
              if (!hits.length) return false;
              hits.sort((a, b) => a.textContent.length - b.textContent.length);
              hits[0].scrollIntoView({block: "start", inline: "nearest"});
              window.scrollBy(0, -24);
              return true;
            })()
        """,
    }[kind]
    if _eval(page, script) is not True:
        raise PageError(f"the German {kind} picture was not on the page")
    _grab(page, directory, name, 0, 0)


def _german_shots(page: DevTools, out_dir: Path, url: str, query: str, heading: str) -> None:
    """German result, first run, and loading, at 1280 and 420."""
    try:
        _motion(page, "no-preference")
    except PageError:
        pass
    _press(page, 'button[lang="de"]')
    _wait_text(page, "Umsatz")
    if _eval(page, "document.documentElement.lang") != "de":
        raise PageError("the first paint was not German")
    time.sleep(1.0)
    _shot(page, out_dir, f"smoke-{ARCH}-10-de-result-1280.png", width=1280, height=2200, full=True)
    _print_preview(page, out_dir)
    _panel_shot(page, out_dir, f"smoke-{ARCH}-18-de-balance-1280.png", 1280, "balance")
    _panel_shot(page, out_dir, f"smoke-{ARCH}-19-de-checks-1280.png", 1280, "checks")
    _panel_shot(page, out_dir, f"smoke-{ARCH}-20-de-explain-1280.png", 1280, "explain")
    _share_card(page, out_dir, f"smoke-{ARCH}-16-de-shares-1280.png", 1280, 900)
    _shot(page, out_dir, f"smoke-{ARCH}-11-de-result-420.png", width=420, height=1800, full=True)
    _share_card(page, out_dir, f"smoke-{ARCH}-17-de-shares-420.png", 420, 900)
    page.call("Page.navigate", {"url": url})
    _wait_text(page, "Unternehmensname oder Tickersymbol")
    if _eval(page, "document.documentElement.lang") != "de":
        raise PageError("the German choice did not survive a new page")
    _window(page, 1280, 1600)
    page.call("Page.navigate", {"url": url + "identity"})
    _wait_node(page, 'form[action="/identity/erase"] button', 20)
    _click(page, 'form[action="/identity/erase"] button')
    _wait_first_run(page)
    _window(page, 1280, 1600)
    _press(page, 'button[lang="de"]')
    _wait_text(page, "Die SEC verlangt")
    _wait_node(page, "#name", 20)
    time.sleep(0.4)
    _shot(page, out_dir, f"smoke-{ARCH}-12-de-first-1280.png", width=1280, height=1600)
    _shot(page, out_dir, f"smoke-{ARCH}-13-de-first-420.png", width=420, height=1600)
    _window(page, 1280, 1600)
    _fill(page, "#name", TEST_NAME)
    _fill(page, "#email", test_email())
    _click(page, 'form[action="/identity"] button')
    _wait_node(page, "#query", 20)
    _fill(page, "#query", query)
    _loading_shot(
        out_dir, f"smoke-{ARCH}-14-de-loading-1280.png", 1280, url, query, german=True
    )
    _click(page, 'form[action="/explain"] button')
    _wait_result(page, out_dir, heading, "USD", loading=False, capture=False)
    page.call("Page.navigate", {"url": url})
    _wait_text(page, "Unternehmensname oder Tickersymbol")
    _fill(page, "#query", query)
    _loading_shot(
        out_dir, f"smoke-{ARCH}-15-de-loading-420.png", 420, url, query, german=True
    )
    _click(page, 'form[action="/explain"] button')
    _wait_result(page, out_dir, heading, "USD", loading=False, capture=False)


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
                    if not _spinning(page):
                        raise PageError("the loading picture is the reduced-motion ring")
                    _grab_steps(page, out_dir, f"smoke-{ARCH}-4-loading.png")
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


def _proxy_tunnel(left: socket.socket, right: socket.socket) -> None:
    pair = [left, right]
    try:
        while True:
            readable, _, _ = select.select(pair, [], [], 60)
            if not readable:
                return
            for sock in readable:
                other = right if sock is left else left
                chunk = sock.recv(65536)
                if not chunk:
                    return
                other.sendall(chunk)
    except OSError:
        return
    finally:
        for sock in pair:
            try:
                sock.close()
            except OSError:
                pass


def _proxy_client(client: socket.socket) -> None:
    client.settimeout(30)
    upstream = None
    try:
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 8192:
            chunk = client.recv(4096)
            if not chunk:
                return
            data += chunk
        line = data.split(b"\r\n", 1)[0].decode("latin1", "replace")
        parts = line.split(" ")
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n")
            return
        host, _, port_text = parts[1].partition(":")
        if host not in _SEC_HOSTS:
            client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            return
        _sec_hold.wait(host)
        upstream = socket.create_connection((host, int(port_text or "443")), timeout=30)
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        client.settimeout(None)
        upstream.settimeout(None)
        _proxy_tunnel(client, upstream)
        upstream = None
        client = None
    except (OSError, ValueError, TimeoutError):
        return
    finally:
        for sock in (client, upstream):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass


def _proxy_serve(sock: socket.socket) -> None:
    while True:
        try:
            client, _addr = sock.accept()
        except OSError:
            return
        threading.Thread(target=_proxy_client, args=(client,), daemon=True).start()


def _start_sec_proxy() -> int:
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(32)
    port = sock.getsockname()[1]
    threading.Thread(target=_proxy_serve, args=(sock,), daemon=True).start()
    return port


def _start(binary: str, home: Path | None = None) -> tuple[subprocess.Popen, str, object]:
    binary = str(Path(binary).resolve())
    if home is None:
        home = Path(tempfile.mkdtemp(prefix="white-cliff-home-"))
    else:
        for stale in (
            home / "opened-url",
            home / "Library" / "Application Support" / "White Cliff" / "instance.port",
        ):
            if stale.is_file():
                stale.unlink()
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
    proxy_port = _start_sec_proxy()
    env["https_proxy"] = f"http://127.0.0.1:{proxy_port}"
    env["http_proxy"] = env["https_proxy"]
    env["no_proxy"] = "127.0.0.1,localhost"
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


def _confirm_german(url: str) -> None:
    """The saved German choice is still the page language after the app is started again."""
    chrome, page = _open_chrome(url)
    try:
        deadline = time.time() + 20
        lang = ""
        while time.time() < deadline:
            try:
                lang = _eval(page, "document.documentElement.lang") or ""
            except PageError:
                lang = ""
            if lang:
                break
            time.sleep(0.1)
        if lang != "de":
            raise PageError("German did not survive a restart")
    finally:
        page.close()
        if chrome.poll() is None:
            os.killpg(chrome.pid, signal.SIGTERM)


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
        home = Path(log.name).parent
        drive(url, Path.cwd())
        stop(proc, log)
        proc, url, log = _start(binary, home)
        _confirm_german(url)
    except (PageError, OSError) as exc:
        print(exc, file=sys.stderr)
        err = globals().get("_CHROME_ERR")
        if err is not None and Path(err).is_file():
            detail = Path(err).read_text(encoding="utf-8", errors="replace").strip()
            if detail:
                print(detail[-4000:], file=sys.stderr)
        return 1
    finally:
        if proc is not None and log is not None:
            stop(proc, log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
