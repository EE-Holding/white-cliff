#!/usr/bin/env python3
"""Draw the open-guide pictures that an OS dialog will not give us.

Each picture is a large labelled drawing. It is not a screenshot.
"""

from __future__ import annotations

import struct
import sys
import tempfile
import zlib
from pathlib import Path

from render_guides import shoot

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs"

BANNER = "Drawing, not a screenshot."

STYLE = """
body { font: 32px/1.35 Georgia, serif; color: #1a1a1a; background: #fff; margin: 24px; }
.banner { background: #fff4cc; border: 4px solid #8a6d00; padding: 12px 16px; }
.card { border: 4px solid #222; padding: 20px; margin-top: 16px; max-width: 980px; }
.file { font: 28px/1.4 ui-monospace, monospace; background: #f4f4f4; padding: 8px 12px; margin: 8px 0; }
button, .button { font: inherit; border: 3px solid #222; background: #fff; padding: 8px 16px; margin: 8px 8px 0 0; }
.mark { border-color: #0b5; background: #e9fff4; }
.arrow { color: #0b5; font-weight: bold; }
h2 { font-size: 36px; margin: 0 0 12px; }
"""


def page(body: str) -> str:
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>{STYLE}</style></head><body>"
        f"<p class='banner'>{BANNER}</p>"
        f"<div class='card'>{body}</div>"
        "</body></html>"
    )


PAGES = {
    "how-to-files.png": page(
        "<h2>Which file</h2>"
        "<p class='file'>WhiteCliff-Mac-Apple-silicon.zip</p>"
        "<p>Apple chip</p>"
        "<p class='file'>WhiteCliff-Mac-Intel.zip</p>"
        "<p>Older Intel Mac</p>"
        "<p class='file'>WhiteCliff-Windows.zip</p>"
        "<p>Windows</p>"
    ),
    "how-to-mac-icon.png": page(
        "<h2>White Cliff</h2>"
        "<p class='file'>White Cliff</p>"
        "<p class='arrow'>Double-click this.</p>"
    ),
    "how-to-mac-warning.png": page(
        "<h2>White Cliff</h2>"
        "<p>The Mac cannot check that this program is free of harmful software.</p>"
        "<p><span class='button mark'>Done</span> <span class='button'>Move to Trash</span></p>"
        "<p class='arrow'>Click Done. Do not click Move to Trash.</p>"
    ),
    "how-to-mac-open.png": page(
        "<h2>Right-click White Cliff</h2>"
        "<p class='file'>Open</p>"
        "<p class='arrow'>Click Open.</p>"
    ),
    "how-to-mac-settings.png": page(
        "<h2>System Settings</h2>"
        "<p>Privacy &amp; Security</p>"
        "<p><span class='button mark'>Open Anyway</span></p>"
        "<p class='arrow'>Click Open Anyway.</p>"
    ),
    "how-to-windows-file.png": page(
        "<h2>Windows</h2>"
        "<p class='file'>WhiteCliff-Windows.zip</p>"
        "<p class='arrow'>Double-click this.</p>"
    ),
    "how-to-windows-more-info.png": page(
        "<h2>Windows protected your PC</h2>"
        "<p>The computer blocked this program.</p>"
        "<p><span class='button mark'>More info</span></p>"
        "<p class='arrow'>Click More info.</p>"
    ),
    "how-to-windows-run.png": page(
        "<h2>Windows protected your PC</h2>"
        "<p>The computer blocked this program.</p>"
        "<p><span class='button mark'>Run anyway</span></p>"
        "<p class='arrow'>Click Run anyway.</p>"
    ),
}


def mark_drawing(data: bytes) -> bytes:
    payload = b"Source\x00drawing"
    kind = b"tEXt"
    chunk = struct.pack(">I", len(payload)) + kind + payload
    chunk += struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    end = data.rfind(b"IEND")
    return data[: end - 4] + chunk + data[end - 4 :]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        for name, html in PAGES.items():
            source = folder / (name + ".html")
            source.write_text(html, encoding="utf-8")
            target = OUT / name
            shoot(source, target)
            target.write_bytes(mark_drawing(target.read_bytes()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
