#!/usr/bin/env python3
"""Print how many times each platform file was downloaded.

The token is read from the environment and is not written down.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

API = "https://api.github.com/repos/EE-Holding/white-cliff/releases?per_page=100"
_PLATFORMS = ("Mac Apple silicon", "Mac Intel", "Windows")


def platform_of(name: str) -> str:
    lowered = name.lower()
    if "apple" in lowered:
        return "Mac Apple silicon"
    if "intel" in lowered:
        return "Mac Intel"
    if "windows" in lowered or lowered.endswith(".exe"):
        return "Windows"
    return ""


def totals(releases: list) -> dict[str, int]:
    counts = {name: 0 for name in _PLATFORMS}
    for release in releases:
        for asset in release.get("assets") or []:
            key = platform_of(str(asset.get("name") or ""))
            if not key:
                continue
            counts[key] += int(asset.get("download_count") or 0)
    return counts


def format_totals(counts: dict[str, int]) -> str:
    return "".join(f"{name}: {counts[name]}\n" for name in _PLATFORMS)


def _token() -> str:
    return os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GH_TOKEN", "").strip()


def main() -> int:
    token = _token()
    if not token:
        print("a token is required in the environment", file=sys.stderr)
        return 2
    request = urllib.request.Request(
        API,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        print("the release list could not be read", file=sys.stderr)
        return 1
    if not isinstance(payload, list):
        print("the release list could not be read", file=sys.stderr)
        return 1
    sys.stdout.write(format_totals(totals(payload)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
