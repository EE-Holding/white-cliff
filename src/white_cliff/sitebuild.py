"""Pre-render pinned filings to static HTML."""

from __future__ import annotations

import html
import json
from pathlib import Path

from white_cliff.disclaimer import DISCLAIMER, ISSUE_URL, ensure_safe_output
from white_cliff.explain import acceptable_name, registrant_span
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.sic import accepted_sector


def pinned_dir() -> Path:
    import os

    override = os.environ.get("WHITE_CLIFF_PINNED", "").strip()
    if override:
        return Path(override)
    cwd = Path.cwd() / "pinned"
    if (cwd / "manifest.json").is_file():
        return cwd
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "pinned" / "manifest.json"
        if candidate.is_file():
            return candidate.parent
    raise FileNotFoundError("pinned filings were not found")


def _form_words(form: str) -> str:
    return {
        "10-K": "annual report",
        "10-Q": "quarterly report",
        "8-K": "earnings exhibit",
    }.get(form, "filing")


def build_site(output: Path, pinned: Path | None = None) -> Path:
    source = pinned or pinned_dir()
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    items: list[str] = []
    for entry in manifest["filings"]:
        filing = load_directory(source / "filings" / entry["accession"])
        explained = explain_filing(filing)
        page_name = entry["accession"] + ".html"
        (output / page_name).write_text(explained.html, encoding="utf-8")
        form_words = _form_words(entry["form"])
        span = registrant_span(filing.document_filer, filing.text)
        edgar = filing.url if filing.url.startswith("https://www.sec.gov/") else ""
        shown = acceptable_name(filing.document_filer) if span else None
        if shown and edgar and span:
            start, end = span
            href = f"{edgar}#registrant={start}&end={end}"
            filer_html = (
                f'<a class="registrant-chip" title="Registrant name in the filing" '
                f'href="{html.escape(href, quote=True)}">{html.escape(shown, quote=False)}</a>'
            )
        else:
            filer_html = "the filer"
        sector = accepted_sector(entry.get("sic"), str(entry.get("cik", "")))
        sector_html = html.escape(sector, quote=False) if sector else ""
        items.append(
            "<li><a href=\"{href}\">{form_words}</a> {filer} {sector}</li>".format(
                href=html.escape(page_name, quote=True),
                form_words=html.escape(form_words),
                filer=filer_html,
                sector=sector_html,
            )
        )
    index = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        "<title>white-cliff</title>\n"
        "</head>\n"
        "<body>\n"
        f'<p class="disclaimer">{DISCLAIMER}</p>\n'
        "<h1>white-cliff</h1>\n"
        "<p>Plain-language explanations of public company filings. "
        "Figures come from EDGAR.</p>\n"
        "<ul>\n"
        + "\n".join(items)
        + "\n</ul>\n"
        f'<p><a href="{ISSUE_URL}">Report an error</a></p>\n'
        "</body>\n"
        "</html>\n"
    )
    ensure_safe_output(index)
    (output / "index.html").write_text(index, encoding="utf-8")
    (output / ".nojekyll").write_text("", encoding="utf-8")
    return output
