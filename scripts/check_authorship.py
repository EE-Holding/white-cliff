#!/usr/bin/env python3
"""Fail when a commit author, committer, or trailer is unexpected."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = "6397b468a59a725d727a9b7abf5b3756655fa76f"
MARKERS = (
    "co-authored-by:",
    "made-with:",
    "generated-by:",
    "signed-off-by:",
)


def _git_config(key: str) -> str:
    completed = subprocess.run(
        ["git", "config", "--get", key],
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.stdout.strip()


def resolve_expected() -> tuple[tuple[str, str, str, str] | None, str | None]:
    """Name and address come from the environment, then from git config."""
    in_ci = os.environ.get("GITHUB_ACTIONS", "").strip().lower() == "true"
    name = os.environ.get("AUTHOR_NAME", "").strip()
    email = os.environ.get("AUTHOR_EMAIL", "").strip()
    if in_ci:
        missing = [
            item
            for item, value in (("AUTHOR_NAME", name), ("AUTHOR_EMAIL", email))
            if not value
        ]
        if missing:
            return None, "\n".join(f"repository variable {item} is missing" for item in missing)
        return (name, email, name, email), None
    if not name:
        name = _git_config("user.name")
    if not email:
        email = _git_config("user.email")
    if not name or not email:
        return None, "AUTHOR_NAME and AUTHOR_EMAIL are unset and git config has no user name or email"
    return (name, email, name, email), None


def check_range(expr: str) -> int:
    required, problem = resolve_expected()
    if problem or required is None:
        print(problem or "repository variable AUTHOR_EMAIL is missing")
        return 1
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
        if identity != required or trailers.strip():
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
        _expected, problem = resolve_expected()
        if problem:
            print(problem)
            return 1
        return check_message(args.message)
    if args.range_expr:
        return check_range(args.range_expr)
    parser.error("pass --range or --commit-msg")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
