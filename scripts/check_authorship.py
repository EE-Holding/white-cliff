#!/usr/bin/env python3
"""Fail when a commit author, committer, or trailer is unexpected."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

ROOT = "6397b468a59a725d727a9b7abf5b3756655fa76f"
REQUIRED_NAME = "Erik Eicke"
MARKERS = (
    "co-authored-by:",
    "made-with:",
    "generated-by:",
    "signed-off-by:",
)
_BY_LINE = re.compile(r"(?im)^[ \t]*[A-Za-z-]+-by:")


def _git_config(key: str) -> str:
    completed = subprocess.run(
        ["git", "config", "--get", key],
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.stdout.strip()


def _in_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS", "").strip().lower() == "true"


def _expected_email() -> str:
    """Local checks read the address from the environment, then git config."""
    email = os.environ.get("AUTHOR_EMAIL", "").strip()
    if email:
        return email
    return _git_config("user.email")


def _recorded_email(which: str) -> str:
    return os.environ.get(f"GIT_{which}_EMAIL", "").strip() or _git_config("user.email")


def check_range(expr: str) -> int:
    in_ci = _in_ci()
    email = ""
    if not in_ci:
        email = _expected_email()
        if not email:
            print("AUTHOR_EMAIL is unset and git config has no user.email")
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
        email_mismatch = (not in_ci) and (
            author_email != email or committer_email != email
        )
        if author != REQUIRED_NAME or committer != REQUIRED_NAME or trailers.strip() or email_mismatch:
            shown = trailers.replace("\n", "\\n")
            print(
                "authorship mismatch "
                f"{sha} {author}|{author_email}|{committer}|{committer_email}|{shown}"
            )
            failed = True
    bodies = subprocess.check_output(
        ["git", "log", "--format=%B", expr],
        text=True,
        stderr=subprocess.PIPE,
    )
    matched = subprocess.run(
        ["grep", "-iE", r"^[[:space:]]*[A-Za-z-]+-by:"],
        input=bodies,
        text=True,
        capture_output=True,
        check=False,
    )
    if matched.returncode == 0:
        print("commit message contains a trailer")
        failed = True
    elif matched.returncode != 1:
        sys.stderr.write(matched.stderr or "")
        return 1
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
    if parsed.stdout.strip() or any(marker in lowered for marker in MARKERS) or _BY_LINE.search(body):
        print("commit message contains a trailer")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check authorship.")
    parser.add_argument("--range", dest="range_expr")
    parser.add_argument("--commit-msg", dest="message")
    args = parser.parse_args(argv)
    if args.message:
        if not _in_ci():
            expected = _expected_email()
            if not expected:
                print("AUTHOR_EMAIL is unset and git config has no user.email")
                return 1
            if _recorded_email("AUTHOR") != expected or _recorded_email("COMMITTER") != expected:
                print("author email does not match")
                return 1
        return check_message(args.message)
    if args.range_expr:
        return check_range(args.range_expr)
    parser.error("pass --range or --commit-msg")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
