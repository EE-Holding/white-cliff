#!/usr/bin/env python3
"""Fail when a commit author, committer, or trailer is unexpected."""

from __future__ import annotations

import argparse
import subprocess
import sys

REQUIRED = ("Erik Eicke", "eickeerik@gmail.com", "Erik Eicke", "eickeerik@gmail.com")
ROOT = "6397b468a59a725d727a9b7abf5b3756655fa76f"
MARKERS = (
    "co-authored-by:",
    "made-with:",
    "generated-by:",
    "signed-off-by:",
)


def check_range(expr: str) -> int:
    fmt = "%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%(trailers:only)%x1e"
    try:
        out = subprocess.check_output(
            ["git", "log", "--format=" + fmt, expr],
            text=True,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr or "")
        sys.stderr.write(f"git log failed for {expr}\n")
        return 1
    failed = False
    records = [record for record in out.split("\x1e") if record.strip("\n")]
    if not records:
        print(f"no commits in {expr}")
        return 0
    for record in records:
        parts = record.strip("\n").split("\x1f")
        if len(parts) != 6:
            print("unreadable authorship record")
            failed = True
            continue
        sha, author, author_email, committer, committer_email, trailers = parts
        if sha == ROOT or ROOT.startswith(sha):
            continue
        identity = (author, author_email, committer, committer_email)
        if identity != REQUIRED or trailers.strip():
            shown = trailers.replace("\n", "\\n")
            print(
                "authorship mismatch "
                f"{sha} {author}|{author_email}|{committer}|{committer_email}|{shown}"
            )
            failed = True
    return 1 if failed else 0


def check_message(path: str) -> int:
    lines = []
    for line in open(path, encoding="utf-8").read().splitlines():
        if line.startswith("#"):
            continue
        lines.append(line)
    body = "\n".join(lines).strip() + "\n"
    parsed = subprocess.run(
        ["git", "interpret-trailers", "--parse"],
        input=body,
        text=True,
        capture_output=True,
        check=False,
    )
    lowered = body.lower()
    if parsed.stdout.strip() or any(marker in lowered for marker in MARKERS):
        print("commit message contains a trailer")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check authorship.")
    parser.add_argument("--range", dest="range_expr")
    parser.add_argument("--commit-msg", dest="message")
    args = parser.parse_args(argv)
    if args.message:
        return check_message(args.message)
    if args.range_expr:
        return check_range(args.range_expr)
    parser.error("pass --range or --commit-msg")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
