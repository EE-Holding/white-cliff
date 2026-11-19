"""Drive the built Mac app through the runner's Chrome. No browser window opens."""

from __future__ import annotations

import base64
import hashlib
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
import zlib
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
        self._events: list[dict] = []

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
            if data.get("method"):
                self._events.append(data)
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
            if data.get("method"):
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


def _window(page: DevTools, width: int = 1100, height: int = 2200, *, reset: bool = False) -> None:
    """Emulate the layout. The real window cannot be wider than the Intel display."""
    del reset
    try:
        page.call("Emulation.clearDeviceMetricsOverride")
    except PageError:
        pass
    try:
        page.call(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": int(width),
                "height": min(int(height), 900),
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )
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


def _ack_frame(page: DevTools, event: dict | None) -> None:
    params = (event or {}).get("params") or {}
    session = params.get("sessionId")
    if session is None:
        return
    try:
        page.call("Page.screencastFrameAck", {"sessionId": session})
    except (PageError, TimeoutError, OSError):
        pass


def _live_frame(page: DevTools) -> bytes:
    """One frame of this window.

    A surface screenshot repeats the Intel page beside itself and then leaves
    the next layout at the 906px display. The first screencast frame can be the
    one from before the latest paint, so a later frame replaces it.
    """
    page.call("Page.startScreencast", {"format": "png", "everyNthFrame": 1})
    event: dict | None = None
    try:
        event = page.next_event("Page.screencastFrame", 5)
        _ack_frame(page, event)
        if not _PAUSED:
            try:
                event = page.next_event("Page.screencastFrame", 0.6)
                _ack_frame(page, event)
            except (PageError, TimeoutError):
                pass
    finally:
        try:
            page.call("Page.stopScreencast")
        except (PageError, TimeoutError, OSError):
            pass
    params = (event or {}).get("params") or {}
    encoded = params.get("data")
    if not isinstance(encoded, str) or not encoded:
        raise PageError("the window had no frame")
    return base64.b64decode(encoded)


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
    del reveal
    wanted = int(width or _css_width(page) or 1100)
    height_px = min(int(height or 900), 900)
    last: Exception | None = None
    for attempt in range(2):
        fresh = DevTools(page.ws_url)
        try:
            fresh.call("Page.enable")
            fresh.call("Runtime.enable")
            if not _PAUSED:
                _window(fresh, wanted, height_px)
                deadline = time.time() + 2
                while time.time() < deadline and not _wide(fresh, wanted):
                    time.sleep(0.05)
                if not _wide(fresh, wanted):
                    raise PageError(f"the window stayed at {_css_width(fresh)}, wanted {wanted}")
                if motion:
                    _motion(fresh, motion)
                if not keep_scroll:
                    _eval(fresh, "window.scrollTo(0, 0)")
                _settled(fresh)
                _eval(
                    fresh,
                    "new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))",
                )
            data = _live_frame(fresh)
            if not _PAUSED:
                _window(fresh, wanted, height_px)
            got = int.from_bytes(data[16:20], "big") if len(data) >= 24 else 0
            if len(data) < 1000 or got != wanted:
                raise PageError(f"{name} is {got}px wide, wanted {wanted}")
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
        _click(page, 'form[action="/explain"] button')
        _wait_result(page, out_dir, heading, suffix, loading=True)
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
        _click(page, 'form[action="/explain"] button')
        reduced_deadline = time.time() + 60
        while time.time() < reduced_deadline:
            try:
                if _reduced_steps(page):
                    _hold(page)
                    try:
                        _grab(page, out_dir, f"smoke-{ARCH}-5-reduced.png", motion="reduce")
                    finally:
                        _release(page)
                    break
            except PageError:
                _release(page)
            time.sleep(0.02)
        else:
            raise PageError("the reduced-motion steps were not shown")
        _wait_result(page, out_dir, heading, suffix, loading=False, capture=False)
        _german_shots(page, out_dir, url, query, heading)
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
            _hold(page)
            try:
                _grab(page, out_dir, name, width, height)
            finally:
                _release(page)
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
    _fit(page, 1280, 1800)
    _click(page, 'form[action="/explain"] button')
    _loading_at(page, out_dir, f"smoke-{ARCH}-14-de-loading-1280.png", 1280, 1800)
    _wait_result(page, out_dir, heading, "USD", loading=False, capture=False)
    page.call("Page.navigate", {"url": url})
    _wait_text(page, "Unternehmensname oder Tickersymbol")
    _fill(page, "#query", query)
    _fit(page, 420, 1800)
    _click(page, 'form[action="/explain"] button')
    _loading_at(page, out_dir, f"smoke-{ARCH}-15-de-loading-420.png", 420, 1800)
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
    except PageError as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        if proc is not None and log is not None:
            stop(proc, log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
