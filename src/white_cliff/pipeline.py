"""Load a filing, explain it, and render Markdown and HTML."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from white_cliff.disclaimer import OutputRefused
from white_cliff.explain import Block, build_blocks
from white_cliff.review import audit_rendered
from white_cliff.facts import FactStore
from white_cliff.omissions import find_omissions
from white_cliff.prices import is_price_text
from white_cliff.redact import Redaction, contains_personal, find_redactions
from white_cliff.render import copy_text, render_html, render_markdown, render_refusal
from white_cliff.fetch import directory_cik, strip_edgar_script
from white_cliff.xbrl import MONEY_ROLES, ParsedFacts, parse_inline


@dataclass
class Filing:
    store: FactStore
    filer: str
    document_filer: str
    form: str
    focus: str | None
    period_end: str | None
    price_metric: bool
    redactions: list[Redaction]
    omissions: list[tuple[int, int, str]]
    text: str
    url: str
    filer_start: int | None = None
    filer_end: int | None = None
    cik: str = ""
    shares_tagged: bool = False


@dataclass
class Explained:
    markdown: str
    html: str
    store: FactStore
    reasons: list[str] = field(default_factory=list)

    @property
    def copy(self) -> str:
        return copy_text(self.markdown)


_PRIMARY_FORMS = frozenset({"10-K", "10-Q"})


def _parse_text(text: str, document: str, url: str, sha256: str, filer_cik: str) -> ParsedFacts:
    return parse_inline(text, document, url, sha256, filer_cik=filer_cik)


def _verified(path: Path, item: dict) -> bytes:
    blob = (path / item["name"]).read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    if digest != item["sha256"]:
        raise ValueError(f"sha256 mismatch for {item['name']}")
    content = hashlib.sha256(strip_edgar_script(blob)).hexdigest()
    if content != item.get("content_sha256"):
        raise ValueError(f"content hash mismatch for {item['name']}")
    return blob


def _primary_item(files: list[dict], form: str) -> dict | None:
    """The inline 10-K or 10-Q. Exhibits and index files are not read for facts."""
    if form not in _PRIMARY_FORMS:
        return None
    usable: list[dict] = []
    for item in files:
        name = str(item.get("name", ""))
        if "index" in name.lower():
            continue
        document_type = str(item.get("document_type") or "")
        if document_type and document_type not in _PRIMARY_FORMS:
            continue
        usable.append(item)
    matched = [item for item in usable if item.get("document_type") == form]
    untyped = [item for item in usable if not str(item.get("document_type") or "")]
    if len(matched) > 1 or (matched and untyped):
        return None
    if matched:
        return matched[0]
    if len(usable) == 1:
        return usable[0]
    return None


def _cik_text(raw: str) -> str:
    digits = "".join(char for char in raw if char.isdigit())
    if not digits or len(digits) > 10:
        return ""
    return digits.zfill(10)


def _agreed_cik(url: str, provenance: dict) -> str:
    """The filer CIK from the EDGAR directory, when the provenance file agrees."""
    found = directory_cik(url)
    recorded = _cik_text(str(provenance.get("cik", "")))
    if not found or found != recorded:
        return ""
    return found


def _absorb(store: FactStore, parsed: ParsedFacts) -> None:
    for fact in parsed.facts:
        store.add(fact)


def load_directory(path: Path) -> Filing:
    provenance = json.loads((path / "provenance.json").read_text(encoding="utf-8"))
    files = list(provenance["files"])
    blobs = [_verified(path, item) for item in files]
    form = str(provenance.get("form", ""))
    chosen = _primary_item(files, form)
    if chosen is None:
        first = files[0]
        text = blobs[0].decode("utf-8")
        return Filing(
            store=FactStore(),
            filer=str(provenance.get("filer", "")),
            document_filer="",
            form=form,
            focus=None,
            period_end=None,
            price_metric=False,
            redactions=[],
            omissions=[],
            text=text,
            url=str(first.get("url", "")),
            cik=_cik_text(str(provenance.get("cik", ""))),
        )
    index = files.index(chosen)
    blob = blobs[index]
    digest = hashlib.sha256(blob).hexdigest()
    text = blob.decode("utf-8")
    agreed = _agreed_cik(str(chosen["url"]), provenance)
    parsed = _parse_text(text, chosen["name"], chosen["url"], digest, agreed)
    if not agreed or parsed.form != form:
        parsed = ParsedFacts(
            facts=[],
            form=form,
            filer=parsed.filer,
            cik=agreed,
            shares_tagged=parsed.shares_tagged,
        )
    store = FactStore()
    _absorb(store, parsed)
    return Filing(
        store=store,
        filer=parsed.filer or str(provenance.get("filer", "")),
        document_filer=parsed.filer,
        filer_start=parsed.filer_start,
        filer_end=parsed.filer_end,
        form=form,
        focus=parsed.focus,
        period_end=parsed.period_end,
        price_metric=parsed.price_metric or is_price_text(text),
        redactions=find_redactions(text, chosen["name"], chosen["url"], digest),
        omissions=find_omissions(text),
        text=text,
        url=str(chosen["url"]),
        cik=agreed,
        shares_tagged=parsed.shares_tagged,
    )


def load_file(path: Path) -> Filing:
    if path.is_dir():
        return load_directory(path)
    provenance_path = path.parent / "provenance.json"
    if provenance_path.is_file():
        return load_directory(path.parent)
    blob = path.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    text = blob.decode("utf-8")
    url = path.resolve().as_uri()
    parsed = _parse_text(text, path.name, url, digest, directory_cik(url) or "")
    store = FactStore()
    _absorb(store, parsed)
    return Filing(
        store=store,
        filer=parsed.filer,
        document_filer=parsed.filer,
        filer_start=parsed.filer_start,
        filer_end=parsed.filer_end,
        form=parsed.form,
        focus=parsed.focus,
        period_end=parsed.period_end,
        price_metric=parsed.price_metric or is_price_text(text),
        redactions=find_redactions(text, path.name, url, digest),
        omissions=find_omissions(text),
        text=text,
        url=url,
        cik=parsed.cik,
        shares_tagged=parsed.shares_tagged,
    )


def explain_filing(filing: Filing) -> Explained:
    if not any(fact.role in MONEY_ROLES for fact in filing.store.facts()):
        markdown, html_text = render_refusal(filing.url)
        for rendered in (markdown, html_text):
            problem = audit_rendered(rendered)
            if problem:
                raise OutputRefused(problem)
        if contains_personal(markdown) or contains_personal(html_text):
            raise OutputRefused("personal data in output")
        return Explained(markdown=markdown, html=html_text, store=filing.store)
    blocks = build_blocks(
        store=filing.store,
        filer=filing.document_filer,
        filer_start=filing.filer_start,
        filer_end=filing.filer_end,
        form=filing.form,
        focus=filing.focus,
        period_end=filing.period_end,
        price_metric=filing.price_metric,
        redactions=filing.redactions,
        omissions=filing.omissions,
        filing_text=filing.text,
        filing_url=filing.url,
        cik=filing.cik,
        shares_tagged=filing.shares_tagged,
    )
    markdown = render_markdown(blocks, filing.store)
    html_text = render_html(blocks, filing.store)
    for rendered in (markdown, html_text):
        problem = audit_rendered(rendered)
        if problem:
            raise OutputRefused(problem)
    if contains_personal(markdown) or contains_personal(html_text):
        raise OutputRefused("personal data in output")
    reasons = [block.reason for block in blocks if block.reason]
    return Explained(
        markdown=markdown,
        html=html_text,
        store=filing.store,
        reasons=reasons,
    )
