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
from white_cliff.render import copy_text, render_html, render_markdown
from white_cliff.tables import parse_tables
from white_cliff.xbrl import ParsedFacts, is_instance_document, parse_inline, parse_instance


@dataclass
class Filing:
    store: FactStore
    filer: str
    form: str
    focus: str | None
    period_end: str | None
    price_metric: bool
    redactions: list[Redaction]
    omissions: list[tuple[int, int, str]]
    text: str
    url: str


@dataclass
class Explained:
    markdown: str
    html: str
    store: FactStore
    reasons: list[str] = field(default_factory=list)

    @property
    def copy(self) -> str:
        return copy_text(self.markdown)


def _parse_text(text: str, document: str, url: str, sha256: str) -> ParsedFacts:
    if is_instance_document(text):
        return parse_instance(text, document, url, sha256)
    parsed = ParsedFacts(facts=[])
    if "nonfraction" in text.lower():
        parsed = parse_inline(text, document, url, sha256)
    table_facts, table_price = parse_tables(text, document, url, sha256)
    covered = {fact.role for fact in parsed.facts if fact.role}
    for fact in table_facts:
        if fact.role and fact.role in covered:
            continue
        parsed.facts.append(fact)
    parsed.price_metric = parsed.price_metric or table_price
    return parsed


def _absorb(store: FactStore, parsed: ParsedFacts) -> None:
    for fact in parsed.facts:
        store.add(fact)


def load_directory(path: Path) -> Filing:
    provenance = json.loads((path / "provenance.json").read_text(encoding="utf-8"))
    store = FactStore()
    filer = provenance.get("filer", "")
    form = provenance.get("form", "")
    focus = None
    period_end = None
    price = False
    redactions: list[Redaction] = []
    omissions: list[tuple[int, int, str]] = []
    texts: list[str] = []
    url = ""
    for item in provenance["files"]:
        blob = (path / item["name"]).read_bytes()
        digest = hashlib.sha256(blob).hexdigest()
        if digest != item["sha256"]:
            raise ValueError(f"sha256 mismatch for {item['name']}")
        text = blob.decode("utf-8")
        texts.append(text)
        url = url or item["url"]
        parsed = _parse_text(text, item["name"], item["url"], digest)
        _absorb(store, parsed)
        filer = parsed.filer or filer
        form = parsed.form or form
        focus = parsed.focus or focus
        period_end = parsed.period_end or period_end
        price = price or parsed.price_metric or is_price_text(text)
        redactions.extend(find_redactions(text, item["name"], item["url"], digest))
        omissions.extend(find_omissions(text))
    return Filing(
        store=store,
        filer=filer,
        form=form,
        focus=focus,
        period_end=period_end,
        price_metric=price,
        redactions=redactions,
        omissions=omissions,
        text="\n".join(texts),
        url=url,
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
    parsed = _parse_text(text, path.name, url, digest)
    store = FactStore()
    _absorb(store, parsed)
    return Filing(
        store=store,
        filer=parsed.filer,
        form=parsed.form,
        focus=parsed.focus,
        period_end=parsed.period_end,
        price_metric=parsed.price_metric or is_price_text(text),
        redactions=find_redactions(text, path.name, url, digest),
        omissions=find_omissions(text),
        text=text,
        url=url,
    )


def explain_filing(filing: Filing) -> Explained:
    blocks = build_blocks(
        store=filing.store,
        filer=filing.filer,
        form=filing.form,
        focus=filing.focus,
        period_end=filing.period_end,
        price_metric=filing.price_metric,
        redactions=filing.redactions,
        omissions=filing.omissions,
        filing_text=filing.text,
        filing_url=filing.url,
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
