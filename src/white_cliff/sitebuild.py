"""Pre-render pinned filings to static HTML."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

from white_cliff.disclaimer import DISCLAIMER, ISSUE_URL, OutputRefused, ensure_safe_output
from white_cliff.explain import filer_record, shown_registrant
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.review import audit_rendered
from white_cliff.sic import sector_html
from white_cliff.xbrl import MONEY_ROLES


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


_ACCESSION = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")


def _form_words(form: str) -> str:
    return {
        "10-K": "annual report",
        "10-Q": "quarterly report",
        "8-K": "earnings exhibit",
    }.get(form, "filing")


def check_index(text: str) -> str:
    """Refuse an index the rendered-page audit does not accept."""
    ensure_safe_output(text)
    problem = audit_rendered(text)
    if problem:
        raise OutputRefused(problem)
    return text


def build_site(output: Path, pinned: Path | None = None) -> Path:
    source = pinned or pinned_dir()
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    items: list[str] = []
    for entry in manifest["filings"]:
        accession = str(entry.get("accession", ""))
        if _ACCESSION.fullmatch(accession) is None:
            raise OutputRefused("bad accession")
        filing = load_directory(source / "filings" / accession)
        explained = explain_filing(filing)
        page_name = accession + ".html"
        (output / page_name).write_text(explained.html, encoding="utf-8")
        form_words = _form_words(entry["form"])
        edgar = filing.url if filing.url.startswith("https://www.sec.gov/") else ""
        money = any(fact.role in MONEY_ROLES for fact in filing.store.facts())
        chip = (
            shown_registrant(filing.document_filer, filing.text, filing.filer_start, filing.filer_end)
            if money and edgar
            else None
        )
        record = filer_record(filing.cik or str(entry.get("cik", "")))
        if chip:
            shown, start, end = chip
            href = f"{edgar}#registrant={start}&end={end}"
            filer_html = (
                f'<a class="registrant-chip" title="Registrant name in the filing" '
                f'href="{html.escape(href, quote=True)}">{html.escape(shown, quote=False)}</a>'
            )
        elif money and record:
            filer_html = (
                f'<a class="registrant-chip" title="Filer on EDGAR" '
                f'href="{html.escape(record, quote=True)}">the filer</a>'
            )
        else:
            filer_html = "the filer"
        sic = entry.get("sic") if isinstance(entry.get("sic"), dict) else {}
        submissions = str(sic.get("source", "")) if isinstance(sic, dict) else ""
        code = str(sic.get("code", "")) if isinstance(sic, dict) else ""
        cik = re.sub(r"\D", "", str(entry.get("cik", ""))).zfill(10)
        sector = ""
        if len(cik) == 10 and submissions == f"https://data.sec.gov/submissions/CIK{cik}.json":
            sector = sector_html(code, submissions)
        items.append(
            "<li><a href=\"{href}\">{form_words}</a> {filer} {sector}</li>".format(
                href=html.escape(page_name, quote=True),
                form_words=html.escape(form_words),
                filer=filer_html,
                sector=sector,
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
    check_index(index)
    (output / "index.html").write_text(index, encoding="utf-8")
    (output / ".nojekyll").write_text("", encoding="utf-8")
    data = Path(__file__).with_name("data")
    for name in ("how-to-open.md", "how-to-open-de.md"):
        guide = data / name
        (output / name).write_bytes(guide.read_bytes())
    return output
