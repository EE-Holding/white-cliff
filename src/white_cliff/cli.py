"""Command line for white-cliff."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from white_cliff.config import MissingUserAgent, load_user_agent
from white_cliff.disclaimer import DISCLAIMER
from white_cliff.fetch import ACCESSION_RE, EdgarClient, FetchError, host_allowed
from white_cliff.model import model_text_from_env
from white_cliff.pipeline import explain_filing, load_directory, load_file
from white_cliff.sitebuild import build_site


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="white-cliff",
        description=DISCLAIMER,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    explain = sub.add_parser(
        "explain",
        description=DISCLAIMER,
        help="Explain a filing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    explain.add_argument("target", help="Accession number or a local filing path")
    explain.add_argument("--format", choices=("md", "html", "both"), default="md")
    explain.add_argument("--output", help="File or directory for the export")
    explain.add_argument(
        "--copy",
        action="store_true",
        help="Print the copyable export",
    )
    explain.add_argument(
        "--model-text",
        default=None,
        help=argparse.SUPPRESS,
    )

    site = sub.add_parser(
        "site",
        description=DISCLAIMER,
        help="Write static pages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    site.add_argument("--output", default="docs")
    site.add_argument("--pinned", default=None)
    return parser


def _require_user_agent() -> str:
    try:
        return load_user_agent()
    except MissingUserAgent:
        print(
            "A User-Agent with a name and a contact email is required.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _explain(args, user_agent: str) -> int:
    target = args.target
    if target.startswith("http://") or target.startswith("https://"):
        if not host_allowed(target):
            print("That host is not an EDGAR host.", file=sys.stderr)
            return 2
        print("Pass an accession number or a local filing path.", file=sys.stderr)
        return 2
    path = Path(target)
    if ACCESSION_RE.fullmatch(target):
        cache = Path(".white-cliff-cache") / target
        if not (cache / "provenance.json").is_file():
            client = EdgarClient(user_agent)
            cik = str(int(target.split("-")[0]))
            try:
                client.fetch_accession(target, cache, cik=cik)
            except FetchError:
                client.fetch_accession(target, cache, cik=client.cik_for_accession(target))
        filing = load_directory(cache)
    elif path.exists():
        filing = load_file(path)
    else:
        print("Filing not found.", file=sys.stderr)
        return 2
    model_text = args.model_text
    if model_text is None:
        model_text = model_text_from_env(filing)
    explained = explain_filing(filing, model_text=model_text)
    rendered = explained.html if args.format == "html" else explained.markdown
    if args.copy:
        rendered = explained.copy
    sys.stdout.write(rendered if rendered.endswith("\n") else rendered + "\n")
    if args.output:
        destination = Path(args.output)
        if args.format == "both":
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "explanation.md").write_text(explained.markdown, encoding="utf-8")
            (destination / "explanation.html").write_text(explained.html, encoding="utf-8")
        elif destination.exists() and destination.is_dir():
            name = "explanation.html" if args.format == "html" else "explanation.md"
            (destination / name).write_text(rendered, encoding="utf-8")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(rendered, encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "explain":
        user_agent = _require_user_agent()
        return _explain(args, user_agent)
    if args.command == "site":
        _require_user_agent()
        pinned = Path(args.pinned) if args.pinned else None
        build_site(Path(args.output), pinned)
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
