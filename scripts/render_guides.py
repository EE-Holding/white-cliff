#!/usr/bin/env python3
"""Render the open guides as large-type pages and save a picture of each."""

from __future__ import annotations

import html
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDES = (
    (ROOT / "docs" / "how-to-open.md", "how-to-open-en.png"),
    (ROOT / "guides" / "how-to-open-de.md", "how-to-open-de.png"),
)

STYLE = """
html { background: #ffffff; }
body {
  font-family: Georgia, "Iowan Old Style", Palatino, "Palatino Linotype", serif;
  font-size: 32px;
  line-height: 1.45;
  color: #1a1a1a;
  max-width: 900px;
  margin: 48px auto;
  padding: 0 24px 64px;
}
h1 { font-size: 44px; line-height: 1.2; margin: 0 0 24px; }
h2 { font-size: 36px; line-height: 1.25; margin: 36px 0 12px; }
p { margin: 0 0 18px; }
ol { margin: 0 0 18px; padding-left: 1.4em; }
li { margin: 0.35em 0; }
.review {
  background: #fff4cc;
  border: 3px solid #8a6d00;
  padding: 16px 20px;
}
"""


def html_page(text: str) -> str:
    """Turn one guide into one large-type page."""
    lang = "de" if "Muttersprache" in text else "en"
    title = "How to open White Cliff"
    for kind, body in _blocks(text):
        if kind == "h1":
            title = str(body)
            break
    parts = [
        "<!DOCTYPE html>",
        f'<html lang="{lang}">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{html.escape(title)}</title>",
        f"<style>{STYLE}</style>",
        "</head>",
        "<body>",
    ]
    for kind, body in _blocks(text):
        if kind == "h1":
            parts.append(f"<h1>{html.escape(str(body))}</h1>")
        elif kind == "h2":
            parts.append(f"<h2>{html.escape(str(body))}</h2>")
        elif kind == "ol":
            items = "".join(f"<li>{html.escape(item)}</li>" for item in body)
            parts.append(f"<ol>{items}</ol>")
        else:
            marker = ' class="review"' if _review(str(body)) else ""
            parts.append(f"<p{marker}>{html.escape(str(body))}</p>")
    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts) + "\n"


def _review(body: str) -> bool:
    return "native review" in body or "Muttersprache" in body


def _blocks(text: str) -> list[tuple[str, object]]:
    blocks: list[tuple[str, object]] = []
    paragraph: list[str] = []
    items: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(("p", " ".join(paragraph)))
            paragraph.clear()

    def flush_items() -> None:
        if items:
            blocks.append(("ol", list(items)))
            items.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush_paragraph()
            flush_items()
            continue
        if line.startswith("# "):
            flush_paragraph()
            flush_items()
            blocks.append(("h1", line[2:].strip()))
            continue
        if line.startswith("## "):
            flush_paragraph()
            flush_items()
            blocks.append(("h2", line[3:].strip()))
            continue
        number, _, rest = line.partition(". ")
        if number.isdigit() and rest:
            flush_paragraph()
            items.append(rest)
            continue
        flush_items()
        paragraph.append(line)
    flush_paragraph()
    flush_items()
    return blocks


def chrome_binary() -> str | None:
    for candidate in (
        os.environ.get("CHROME", ""),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/opt/google/chrome/chrome",
        shutil.which("google-chrome") or "",
        shutil.which("google-chrome-stable") or "",
        shutil.which("chromium") or "",
        shutil.which("chromium-browser") or "",
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def shoot(page_path: Path, png_path: Path) -> None:
    binary = chrome_binary()
    if binary is None:
        raise SystemExit("Google Chrome is not installed")
    png_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as profile:
        completed = subprocess.run(
            [
                binary,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--hide-scrollbars",
                "--force-device-scale-factor=1",
                "--window-size=1100,5600",
                f"--user-data-dir={profile}",
                f"--screenshot={png_path}",
                page_path.as_uri(),
            ],
            capture_output=True,
            timeout=90,
        )
        if completed.returncode != 0:
            sys.stderr.buffer.write(completed.stderr)
            raise SystemExit(completed.returncode)
    png_path.write_bytes(crop_bottom(png_path.read_bytes()))


def crop_bottom(data: bytes) -> bytes:
    """Drop the blank rows under the last line of the page."""
    try:
        width, height, color, rows = _read_png(data)
    except ValueError:
        return data
    channels = 4 if color == 6 else 3
    last = 0
    for index, row in enumerate(rows):
        if not _white(row, channels):
            last = index
    keep = min(height, last + 49)
    if keep >= height:
        return data
    return _write_png(width, keep, color, rows[:keep])


def _white(row: bytearray, channels: int) -> bool:
    for index in range(0, len(row), channels):
        if row[index] < 250 or row[index + 1] < 250 or row[index + 2] < 250:
            return False
    return True


def _read_png(data: bytes) -> tuple[int, int, int, list[bytearray]]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a png")
    pos = 8
    width = height = color = 0
    idat = bytearray()
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        kind = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, color, _comp, _filt, inter = struct.unpack(">IIBBBBB", chunk)
            if depth != 8 or inter != 0 or color not in (2, 6):
                raise ValueError("unsupported png")
        elif kind == b"IDAT":
            idat.extend(chunk)
        elif kind == b"IEND":
            break
    channels = 4 if color == 6 else 3
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    rows: list[bytearray] = []
    cursor = 0
    prev = bytearray(stride)
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        scan = bytearray(raw[cursor : cursor + stride])
        cursor += stride
        row = _unfilter(filter_type, scan, prev, channels)
        rows.append(row)
        prev = row
    return width, height, color, rows


def _unfilter(filter_type: int, scan: bytearray, prev: bytearray, channels: int) -> bytearray:
    row = bytearray(len(scan))
    for index, value in enumerate(scan):
        left = row[index - channels] if index >= channels else 0
        up = prev[index]
        upper_left = prev[index - channels] if index >= channels else 0
        if filter_type == 0:
            row[index] = value
        elif filter_type == 1:
            row[index] = (value + left) & 255
        elif filter_type == 2:
            row[index] = (value + up) & 255
        elif filter_type == 3:
            row[index] = (value + ((left + up) // 2)) & 255
        elif filter_type == 4:
            row[index] = (value + _paeth(left, up, upper_left)) & 255
        else:
            raise ValueError("bad filter")
    return row


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    upper_distance = abs(estimate - upper_left)
    if left_distance <= up_distance and left_distance <= upper_distance:
        return left
    if up_distance <= upper_distance:
        return up
    return upper_left


def _write_png(width: int, height: int, color: int, rows: list[bytearray]) -> bytes:
    raw = bytearray()
    for row in rows:
        raw.append(0)
        raw.extend(row)
    compressed = zlib.compress(bytes(raw), 9)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        head = struct.pack(">I", len(payload)) + kind + payload
        return head + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0)
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", ihdr),
            chunk(b"IDAT", compressed),
            chunk(b"IEND", b""),
        )
    )


def main(argv: list[str] | None = None) -> int:
    out = Path(argv[0]) if argv else Path.cwd()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        for source, name in GUIDES:
            page = folder / (name + ".html")
            page.write_text(html_page(source.read_text(encoding="utf-8")), encoding="utf-8")
            shoot(page, out / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
