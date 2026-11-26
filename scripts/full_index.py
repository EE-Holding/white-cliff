#!/usr/bin/env python3
"""Compare every number the app shows with company facts.

This script is not a test and it is not part of CI. Responses stay in
.full-index-cache, which is gitignored. Pass --limit to stop after a partial pass.
"""

from __future__ import annotations

import argparse
import csv
import gc
import gzip
import hashlib
import html
import io
import json
import os
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

from white_cliff.disclaimer import DISCLAIMER, OutputRefused
from white_cliff.facts import format_decimal
from white_cliff.fetch import EdgarClient, FetchError
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.render import REFUSAL_SENTENCE

ROOT = Path(__file__).resolve().parents[1]
CONSTITUENTS = ROOT / "pinned" / "sp500-constituents.json"
CACHE = ROOT / ".full-index-cache"
SUMMARY = ROOT / "runs" / "full-index-1" / "summary.md"
SEC_SUMMARY = ROOT / "runs" / "full-index-2" / "summary.md"
STATEMENTS = ROOT / "pinned" / "sec-statements"
SCOPE_START = "2020-01-01"
QUARTER_DAYS = Decimal("91.25")
QUARTER_TOLERANCE = Decimal("25")
FORMS = frozenset({"10-K", "10-Q"})
SCALE_STEPS = (3, 6, 9)
_SHOWN_ID = re.compile(r"(fact|calc)=((?:fact|calc)[a-z]+)")
_XBRL_PATH = (
    "The explanation reads inline XBRL. "
    "white_cliff.pipeline.load_directory and white_cliff.pipeline.load_file "
    "call white_cliff.pipeline._parse_text, which calls white_cliff.xbrl.parse_inline. "
    "Each stored fact has origin ixbrl. "
    "The numbers compared here come from that path, so this pass does not count as proof."
)
_PROPOSED_EN = "This filing can't be explained yet."


@dataclass(frozen=True)
class Verdict:
    label: str
    reason: str
    xbrl_value: str


def _quantum(decimals: int | None) -> Decimal | None:
    """XBRL decimals names the last accurate place. -6 is the millions place.

    INF is stored as a million decimal places. That figure is exact, so only
    equal digits match.
    """
    if decimals is None:
        return None
    places = int(decimals)
    if places > 28 or places < -28:
        return None
    return Decimal((0, (1,), -places))


def _near(left: Decimal, right: Decimal, decimals: int | None) -> bool:
    if left == right:
        return True
    quantum = _quantum(decimals)
    if quantum is None:
        return False
    return left.quantize(quantum, rounding=ROUND_HALF_EVEN) == right.quantize(
        quantum, rounding=ROUND_HALF_EVEN
    )


def _scale_factor(left: Decimal, right: Decimal, decimals: int | None) -> bool:
    if left == 0 or right == 0:
        return False
    for step in SCALE_STEPS:
        factor = Decimal(10) ** step
        if _near(left, right * factor, decimals) or _near(right, left * factor, decimals):
            return True
    return False


def classify_value(
    *,
    absolute: Decimal,
    decimals: int | None,
    same: list[Decimal],
    others: list[Decimal],
) -> Verdict:
    """MATCH when the filing absolute equals the accession row.

    A scale factor, or the same period under another accession, is a review.
    The document wins those cases, and they are not MATCH. A missing accession
    row is NOT_COMPARABLE. Any other disagreement is WRONG.
    """
    if not same:
        return Verdict("NOT_COMPARABLE", "", "")
    for value in same:
        if _near(absolute, value, decimals):
            return Verdict("MATCH", "", format_decimal(value))
    for value in same:
        if _scale_factor(absolute, value, decimals):
            return Verdict("REVIEW", "scaling", format_decimal(value))
    for value in others:
        if _near(absolute, value, decimals):
            closest = min(same, key=lambda item: abs(item - absolute))
            return Verdict("REVIEW", "restatement", format_decimal(closest))
    closest = min(same, key=lambda item: abs(item - absolute))
    return Verdict("WRONG", "", format_decimal(closest))


def _month_end(year: int, month: int) -> date:
    if month == 12:
        following = date(year + 1, 1, 1)
    else:
        following = date(year, month + 1, 1)
    return following - timedelta(days=1)


def _nearest_month_end(day: date) -> date:
    """The data set stores ddate rounded to the nearest month end."""
    if day.month == 1:
        previous = _month_end(day.year - 1, 12)
    else:
        previous = _month_end(day.year, day.month - 1)
    current = _month_end(day.year, day.month)
    if day.month == 12:
        following = _month_end(day.year + 1, 1)
    else:
        following = _month_end(day.year, day.month + 1)
    return min(
        (previous, current, following),
        key=lambda item: (abs((item - day).days), -item.toordinal()),
    )


def sec_period(kind: str, start: str | None, end: str | None) -> tuple[str, int] | None:
    """Map a filing period onto the data-set end date and quarter count.

    An instant is quarter count 0. A duration uses the nearest whole number of
    quarters. A span that is not close to that count is left unaligned.
    The end date is the nearest month end, which is how the data set stores it.
    """
    if not end:
        return None
    try:
        end_day = date.fromisoformat(end)
    except ValueError:
        return None
    ddate = _nearest_month_end(end_day).strftime("%Y%m%d")
    if kind == "instant":
        return ddate, 0
    if not start:
        return None
    try:
        start_day = date.fromisoformat(start)
    except ValueError:
        return None
    days = Decimal((end_day - start_day).days)
    if days <= 0:
        return None
    quarters = int((days / QUARTER_DAYS).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))
    if quarters < 1:
        return None
    if abs(days - (Decimal(quarters) * QUARTER_DAYS)) > QUARTER_TOLERANCE:
        return None
    return ddate, quarters


def _dimension(raw: str | None) -> str:
    text = (raw or "").strip()
    if text.upper() == "NULL":
        return ""
    return text


def _qtrs_text(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        number = Decimal(text)
    except Exception:
        return text
    if number == number.to_integral_value():
        return str(int(number))
    return text


def _decimal_text(raw: str) -> Decimal | None:
    text = raw.strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def classify_sec_number(
    *,
    accession: str,
    tag: str,
    kind: str,
    start: str | None,
    end: str | None,
    unit: str,
    absolute: Decimal,
    decimals: int | None,
    rows: list[dict],
) -> tuple[str, dict | None]:
    """MATCH, WRONG, or NOT_COMPARABLE against one SEC source.

    The row must share the tag, the period, the unit, and empty dimensions.
    A scale gap is WRONG. A disagreeing value stays WRONG and is returned for
    the review list. Nothing here reclassifies a disagreement.
    """
    period = sec_period(kind, start, end)
    if period is None:
        return "NOT_COMPARABLE", None
    ddate, quarters = period
    base = _base_unit(unit)
    chosen: list[Decimal] = []
    for row in rows:
        if str(row.get("adsh") or "") != accession:
            continue
        if str(row.get("tag") or "") != tag:
            continue
        if str(row.get("ddate") or "") != ddate:
            continue
        if _qtrs_text(str(row.get("qtrs") or "")) != str(quarters):
            continue
        if str(row.get("uom") or "") != base:
            continue
        if _dimension(row.get("segments")) or _dimension(row.get("coreg")):
            continue
        value = _decimal_text(str(row.get("value") or ""))
        if value is None:
            continue
        chosen.append(value)
    if not chosen:
        return "NOT_COMPARABLE", None
    if all(_near(absolute, value, decimals) for value in chosen):
        return "MATCH", None
    distinct: list[str] = []
    for value in chosen:
        text = format_decimal(value)
        if text not in distinct:
            distinct.append(text)
    return "WRONG", {
        "filing": accession,
        "tag": tag,
        "ours": format_decimal(absolute),
        "sec": "; ".join(distinct),
    }


def rows_from_companyfacts(index: dict, accession: str) -> list[dict]:
    """Companyfacts rows in the same shape as a data-set number row."""
    rows: list[dict] = []
    for (concept, unit, start, end), pairs in index.items():
        for row_accession, value in pairs:
            if row_accession != accession:
                continue
            kind = "instant" if not start else "duration"
            period = sec_period(kind, start or None, end or None)
            if period is None:
                continue
            ddate, quarters = period
            rows.append(
                {
                    "adsh": accession,
                    "tag": concept,
                    "ddate": ddate,
                    "qtrs": str(quarters),
                    "uom": unit,
                    "segments": "",
                    "coreg": "",
                    "value": format_decimal(value),
                }
            )
    return rows


def rows_for_filing(
    accession: str,
    present: set[str],
    statement_rows: list[dict],
    facts_index: dict,
) -> tuple[list[dict], str]:
    """Use the data sets when the filing is in them, otherwise companyfacts."""
    if accession in present:
        rows = [row for row in statement_rows if str(row.get("adsh") or "") == accession]
        return rows, "statements"
    return rows_from_companyfacts(facts_index, accession), "companyfacts"


def _iter_tsv(handle):
    reader = csv.DictReader(handle, delimiter="\t")
    if not reader.fieldnames:
        return
    reader.fieldnames = [(name or "").strip().lower() for name in reader.fieldnames]
    for row in reader:
        if row:
            yield row


def _iter_tsv_bytes(handle):
    text = io.TextIOWrapper(handle, encoding="utf-8-sig", newline="")
    try:
        yield from _iter_tsv(text)
    finally:
        text.detach()


def _zip_member(archive: zipfile.ZipFile, suffix: str) -> str:
    wanted = suffix.lower()
    for name in archive.namelist():
        if name.lower().endswith(wanted) and not name.endswith("/"):
            return name
    raise ValueError(f"missing {suffix}")


def _read_statement_zip(path: Path, allowed: set[str]) -> tuple[set[str], list[dict], list[dict]]:
    kept_adsh: set[str] = set()
    numbers: list[dict] = []
    submissions: list[dict] = []
    with zipfile.ZipFile(path) as archive:
        with archive.open(_zip_member(archive, "sub.txt")) as handle:
            for row in _iter_tsv_bytes(handle):
                adsh = (row.get("adsh") or "").strip()
                if adsh not in allowed:
                    continue
                kept_adsh.add(adsh)
                submissions.append(
                    {
                        "adsh": adsh,
                        "form": (row.get("form") or "").strip(),
                        "period": (row.get("period") or "").strip(),
                        "filed": (row.get("filed") or "").strip(),
                    }
                )
        with archive.open(_zip_member(archive, "num.txt")) as handle:
            for row in _iter_tsv_bytes(handle):
                adsh = (row.get("adsh") or "").strip()
                if adsh not in allowed:
                    continue
                value = (row.get("value") or "").strip()
                if value == "":
                    continue
                numbers.append(
                    {
                        "adsh": adsh,
                        "tag": (row.get("tag") or "").strip(),
                        "ddate": (row.get("ddate") or "").strip(),
                        "qtrs": _qtrs_text(row.get("qtrs")),
                        "uom": (row.get("uom") or "").strip(),
                        "segments": _dimension(row.get("segments")),
                        "coreg": _dimension(row.get("coreg")),
                        "value": value,
                    }
                )
    return kept_adsh, numbers, submissions


def filter_statement_zip(path: Path, allowed: set[str]) -> tuple[set[str], list[dict]]:
    """Keep number rows for the given filings. Submission names stay out."""
    kept_adsh, numbers, _submissions = _read_statement_zip(path, allowed)
    return kept_adsh, numbers


def manifest_entry(url: str, downloaded: str, digest: str) -> dict[str, str]:
    return {"url": url, "downloaded": downloaded, "sha256": digest}


def _fixture_file(directory: Path, name: str) -> Path:
    path = (directory / name).resolve()
    root = directory.resolve()
    if path != root and root not in path.parents:
        raise ValueError("fixture path leaves the directory")
    return path


def load_statements(directory: Path) -> tuple[set[str], dict]:
    """Read the pinned data-set fixture. Dimensional rows stay in the file only."""
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    present: set[str] = set()
    index: dict[str, dict[str, list[tuple[str, str, str, str]]]] = {}
    for item in manifest.get("files") or []:
        with gzip.open(_fixture_file(directory, item["sub"]), "rt", encoding="utf-8", newline="") as handle:
            for row in _iter_tsv(handle):
                adsh = (row.get("adsh") or "").strip()
                if adsh:
                    present.add(adsh)
        with gzip.open(_fixture_file(directory, item["num"]), "rt", encoding="utf-8", newline="") as handle:
            for row in _iter_tsv(handle):
                adsh = (row.get("adsh") or "").strip()
                tag = (row.get("tag") or "").strip()
                if not adsh or not tag:
                    continue
                if _dimension(row.get("segments")) or _dimension(row.get("coreg")):
                    continue
                value = (row.get("value") or "").strip()
                if not value:
                    continue
                bucket = index.setdefault(adsh, {}).setdefault(tag, [])
                bucket.append(
                    (
                        (row.get("ddate") or "").strip(),
                        _qtrs_text(row.get("qtrs")),
                        (row.get("uom") or "").strip(),
                        value,
                    )
                )
    return present, index


def rows_from_index(index: dict, accession: str, tag: str) -> list[dict]:
    found = index.get(accession, {}).get(tag, [])
    return [
        {
            "adsh": accession,
            "tag": tag,
            "ddate": ddate,
            "qtrs": quarters,
            "uom": unit,
            "segments": "",
            "coreg": "",
            "value": value,
        }
        for ddate, quarters, unit, value in found
    ]


def render_sec_summary(report: dict) -> str:
    rows = list(report["review_rows"])
    lines = [
        DISCLAIMER,
        "",
        "# SEC cross-check",
        "",
        "Source: SEC Financial Statement Data Sets (num.txt and sub.txt).",
        f"Snapshot date: {report['snapshot']}.",
        "A filing that is not in those quarterly sets is compared with companyfacts JSON.",
        "These counts are separate from the earlier comparison.",
        "",
        f"Filings in scope: {report['filings_in_scope']}",
        f"Filings read from the data sets: {report['filings_from_statements']}",
        f"Filings read from companyfacts: {report['filings_from_companyfacts']}",
        f"Filings errored: {report.get('filings_errored', 0)}",
        f"Numbers MATCH: {report['sec_match']}",
        f"Numbers WRONG: {report['sec_wrong']}",
        f"Numbers NOT_COMPARABLE: {report['sec_not_comparable']}",
        f"Review list: {len(rows)}",
        "",
        "## Review list",
        "",
        "Each row is a WRONG. The filing, the tag, the value White Cliff shows, and the SEC value.",
        "",
    ]
    if not rows:
        lines.append("None.")
    else:
        lines.append("filing | tag | White Cliff | SEC")
        for row in rows:
            lines.append(" | ".join([row["filing"], row["tag"], row["ours"], row["sec"]]))
    lines.append("")
    return "\n".join(lines)


def check_percent_notes(page: str) -> dict[str, int]:
    """Every change percent must open a note that links both filing inputs."""
    noted = 0
    single = 0
    seen: set[str] = set()
    for match in re.finditer(r'<a class="pct" href="([^"]+)">([^<]*)</a>', page):
        href = html.unescape(match.group(1))
        text = html.unescape(match.group(2))
        folded = text.casefold()
        if "percent" not in folded:
            continue
        if "percentage point" in folded:
            continue
        if not href.startswith("#pct-"):
            start = page.rfind("<p", 0, match.start())
            if start < 0:
                start = max(0, match.start() - 400)
            end = page.find("</p>", match.end())
            window = page[start : end if end >= 0 else match.end()]
            words = re.sub(r"<[^>]+>", " ", window).casefold()
            if not any(token in words for token in ("rose", "fell")):
                continue
            single += 1
            continue
        note_id = href[1:]
        if note_id in seen:
            continue
        seen.add(note_id)
        note = re.search(rf'<p class="pct-note" id="{re.escape(note_id)}">(.*?)</p>', page, re.S)
        if note is None:
            single += 1
            continue
        links = [html.unescape(item) for item in re.findall(r'href="(https://www\.sec\.gov/[^"]*)"', note.group(1))]
        from white_cliff.wording import percent_note_gaps

        if len(links) >= 2 and len(set(links)) >= 2 and not percent_note_gaps(note.group(1)):
            noted += 1
        else:
            single += 1
    return {"noted": noted, "single": single}


def _parse_figure(text: str) -> Decimal | None:
    """The face number in an amount or a percent, without its unit word."""
    cleaned = (
        html.unescape(text)
        .replace("\u00a0", " ")
        .replace("\u2212", "-")
        .replace("$", "")
    )
    match = re.search(r"-?\d[\d.,]*", cleaned)
    if match is None:
        return None
    token = match.group(0).replace(",", "")
    if token in {"", "-", ".", "-."}:
        return None
    return Decimal(token)


def percent_mismatches(page: str) -> list[dict[str, str]]:
    """Recompute each noted percent from its two linked amounts.

    The change from the later amount to the earlier one, divided by the earlier
    amount, has to equal the percent on the page. A different figure is WRONG.
    """
    from white_cliff.compare import percent_change

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in re.finditer(r'<a class="pct" href="([^"]+)">([^<]*)</a>', page):
        href = html.unescape(match.group(1))
        text = html.unescape(match.group(2))
        folded = text.casefold()
        if "percent" not in folded:
            continue
        if "percentage point" in folded:
            continue
        if not href.startswith("#pct-"):
            continue
        note_id = href[1:]
        if note_id in seen:
            continue
        seen.add(note_id)
        note = re.search(
            rf'<p class="pct-note" id="{re.escape(note_id)}">(.*?)</p>', page, re.S
        )
        if note is None:
            continue
        amounts = [
            html.unescape(item)
            for item in re.findall(
                r'<a href="https://www\.sec\.gov/[^"]*"[^>]*>([^<]*)</a>', note.group(1)
            )
        ]
        before = re.sub(r"<[^>]+>", " ", page[max(0, match.start() - 200) : match.start()]).casefold()
        nearest = ""
        nearest_at = -1
        for token in ("rose", "fell"):
            at = before.rfind(token)
            if at > nearest_at:
                nearest_at = at
                nearest = token
        shown = _parse_figure(text)
        current = _parse_figure(amounts[0]) if len(amounts) > 0 else None
        prior = _parse_figure(amounts[1]) if len(amounts) > 1 else None
        recomputed = (
            percent_change(current, prior)
            if current is not None and prior is not None
            else None
        )
        rose = nearest == "rose"
        fell = nearest == "fell"
        agrees = (
            recomputed is not None
            and shown is not None
            and abs(recomputed) == abs(shown)
            and not (rose and recomputed <= 0)
            and not (fell and recomputed >= 0)
        )
        if agrees:
            continue
        plain = re.sub(r"<[^>]+>", " ", html.unescape(note.group(1)))
        plain = re.sub(r"\s+", " ", plain)
        period = ""
        english = re.search(r"from (.+?) to (.+?), divided", plain)
        if english:
            period = f"{english.group(2)} vs {english.group(1)}"
        rows.append(
            {
                "shown": re.sub(r"\s+", " ", text).strip(),
                "recomputed": "" if recomputed is None else format(recomputed, "f"),
                "period": period,
            }
        )
    return rows


def shown_ids(markdown: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for kind, identifier in _SHOWN_ID.findall(markdown):
        if kind == "fact" and not identifier.startswith("fact"):
            continue
        if kind == "calc" and not identifier.startswith("calc"):
            continue
        key = (kind, identifier)
        if key in seen:
            continue
        seen.add(key)
        found.append(key)
    return found


def render_summary(report: dict) -> str:
    coverage = 0
    scope = int(report["filings_in_scope"])
    if scope:
        coverage = (100 * int(report["filings_explained"])) / scope
    lines = [
        DISCLAIMER,
        "",
        "# Full index",
        "",
        _XBRL_PATH,
        "",
        "A filing the app cannot explain correctly should show this sentence, "
        "which is proposed for approval and is not yet on the page:",
        "",
        f"EN: {_PROPOSED_EN}",
        "",
        f"Filings in scope: {report['filings_in_scope']}",
        f"Filings covered: {report['filings_covered']}",
        f"Filings explained: {report['filings_explained']}",
        f"Coverage of scope: {coverage:.1f}%",
        f"Filings refused: {report['filings_refused']}",
        f"Filings not retrieved: {report['filings_not_retrieved']}",
        f"Filings errored: {report.get('filings_errored', 0)}",
        f"Numbers MATCH: {report['match']}",
        f"Numbers WRONG: {report['wrong']}",
        f"Numbers NOT_COMPARABLE: {report['not_comparable']}",
        f"Review list: {report['review']}",
        f"Percents with both inputs: {report.get('percents_noted', 0)}",
        f"Percents removed: {report.get('percents_removed', 0)}",
        f"Percents linked to one input: {report.get('percents_single', 0)}",
        "Percent recomputes that disagree: "
        + str(
            sum(
                1
                for row in report.get("wrong_rows") or []
                if row.get("concept") == "percent"
            )
        ),
        "",
        "## WRONG",
        "",
    ]
    rows = list(report["wrong_rows"])
    if not rows:
        lines.append("None.")
    else:
        lines.append("ticker | accession | concept | period | shown value | XBRL value")
        for row in rows:
            lines.append(
                " | ".join(
                    [
                        row["ticker"],
                        row["accession"],
                        row["concept"],
                        row["period"],
                        row["shown"],
                        row["xbrl"],
                    ]
                )
            )
    lines.append("")
    return "\n".join(lines)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _write_json(path: Path, payload: dict) -> None:
    _write_text(path, json.dumps(payload, indent=2) + "\n")


def _client() -> EdgarClient:
    user_agent = os.environ.get("WHITE_CLIFF_USER_AGENT", "")
    return EdgarClient(user_agent)


def _cached_get(client: EdgarClient, url: str, path: Path) -> dict:
    if path.is_file():
        return _load_json(path)
    payload = json.loads(client.get(url).decode("utf-8"))
    _write_json(path, payload)
    return payload


def _table(payload: dict) -> dict:
    nested = payload.get("filings", {}).get("recent")
    if isinstance(nested, dict) and "form" in nested:
        return nested
    if "form" in payload and "accessionNumber" in payload:
        return payload
    return {}


def _records(table: dict) -> list[dict[str, str]]:
    forms = table.get("form") or []
    count = len(forms)
    rows: list[dict[str, str]] = []
    for index in range(count):
        def cell(name: str, index: int = index) -> str:
            values = table.get(name) or []
            if index >= len(values) or values[index] is None:
                return ""
            return str(values[index])

        rows.append(
            {
                "accession": cell("accessionNumber"),
                "filing_date": cell("filingDate"),
                "form": cell("form"),
                "report_date": cell("reportDate"),
            }
        )
    return rows


def _in_scope(row: dict[str, str]) -> bool:
    return row["form"] in FORMS and row["filing_date"] >= SCOPE_START and bool(row["accession"])


def _oldest(rows: list[dict[str, str]]) -> str:
    dates = [row["filing_date"] for row in rows if row["filing_date"]]
    return min(dates) if dates else "9999-99-99"


def constituent_rows() -> list[dict[str, str]]:
    document = _load_json(CONSTITUENTS)
    return list(document["constituents"])


def _companies() -> list[dict[str, str]]:
    grouped: dict[str, dict[str, str]] = {}
    for row in constituent_rows():
        cik = row["cik"]
        current = grouped.get(cik)
        if current is None:
            grouped[cik] = {"cik": cik, "ticker": row["ticker"], "security": row["security"]}
        else:
            current["ticker"] = current["ticker"] + "," + row["ticker"]
    return list(grouped.values())


def _submission_rows(client: EdgarClient, cik: str) -> list[dict[str, str]]:
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    payload = _cached_get(client, url, CACHE / "submissions" / f"{cik}.json")
    rows = _records(_table(payload))
    extras = []
    if _oldest(rows) > SCOPE_START:
        for item in payload.get("filings", {}).get("files") or []:
            name = str(item.get("name") or "")
            if not name or "/" in name or ".." in name:
                continue
            extra = _cached_get(
                client,
                f"https://data.sec.gov/submissions/{name}",
                CACHE / "submissions" / name,
            )
            older = _records(_table(extra))
            extras.extend(older)
            rows.extend(older)
            if _oldest(older) <= SCOPE_START:
                break
    del extras
    return [row for row in rows if _in_scope(row)]


def build_scope(client: EdgarClient) -> list[dict[str, str]]:
    digest = hashlib.sha256(CONSTITUENTS.read_bytes()).hexdigest()
    scope_path = CACHE / "scope.json"
    if scope_path.is_file():
        saved = _load_json(scope_path)
        if saved.get("constituents_sha256") == digest:
            return list(saved["filings"])
    filings: list[dict[str, str]] = []
    seen: set[str] = set()
    for company in _companies():
        for row in _submission_rows(client, company["cik"]):
            if row["accession"] in seen:
                continue
            seen.add(row["accession"])
            filings.append(
                {
                    "ticker": company["ticker"],
                    "cik": company["cik"],
                    "accession": row["accession"],
                    "form": row["form"],
                    "filing_date": row["filing_date"],
                }
            )
    _write_json(scope_path, {"constituents_sha256": digest, "filings": filings})
    return filings


def facts_payload(raw: str) -> dict:
    """Parse company facts without turning a figure into a binary float."""
    return json.loads(raw, parse_float=Decimal, parse_int=Decimal)


def _facts_index(payload: dict) -> dict[tuple[str, str, str, str], list[tuple[str, Decimal]]]:
    index: dict[tuple[str, str, str, str], list[tuple[str, Decimal]]] = {}
    for concepts in (payload.get("facts") or {}).values():
        if not isinstance(concepts, dict):
            continue
        for concept, body in concepts.items():
            units = (body or {}).get("units") or {}
            for unit, rows in units.items():
                for row in rows or []:
                    if not isinstance(row, dict) or "val" not in row:
                        continue
                    start = str(row.get("start") or "")
                    end = str(row.get("end") or "")
                    accession = str(row.get("accn") or "")
                    value = row["val"]
                    if not isinstance(value, Decimal):
                        value = Decimal(str(value))
                    key = (str(concept), str(unit), start, end)
                    index.setdefault(key, []).append((accession, value))
    return index


def _load_facts(client: EdgarClient, cik: str) -> dict:
    path = CACHE / "facts" / f"{cik}.json"
    if path.is_file():
        raw = path.read_text(encoding="utf-8")
    else:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        raw = client.get(url).decode("utf-8")
        _write_text(path, raw)
    return facts_payload(raw)


def _period_text(kind: str, start: str | None, end: str | None) -> str:
    if kind == "instant":
        return end or ""
    return f"{start or ''}/{end or ''}"


def _base_unit(unit: str) -> str:
    return unit.split(" ", 1)[0]


def _classify_filing(markdown: str, store, accession: str, index: dict) -> tuple[dict[str, int], list[dict], int]:
    counts = {"MATCH": 0, "WRONG": 0, "NOT_COMPARABLE": 0}
    wrong: list[dict] = []
    review = 0
    for kind, identifier in shown_ids(markdown):
        if kind == "calc":
            counts["NOT_COMPARABLE"] += 1
            continue
        fact = store.get(identifier)
        start = fact.period.start or ""
        end = fact.period.end or ""
        unit = _base_unit(fact.unit)
        rows = index.get((fact.concept, unit, start, end), [])
        same = [value for row_accession, value in rows if row_accession == accession]
        others = [value for row_accession, value in rows if row_accession != accession]
        absolute = fact.value * (Decimal(10) ** fact.scale)
        verdict = classify_value(
            absolute=absolute,
            decimals=fact.decimals,
            same=same,
            others=others,
        )
        if verdict.label == "REVIEW":
            review += 1
            continue
        counts[verdict.label] += 1
        if verdict.label == "WRONG":
            wrong.append(
                {
                    "concept": fact.concept,
                    "period": _period_text(fact.period.kind, fact.period.start, fact.period.end),
                    "shown": f"{format_decimal(fact.value)} {fact.unit}",
                    "xbrl": verdict.xbrl_value,
                }
            )
    return counts, wrong, review


def _wait_for_load() -> None:
    """Heavy work waits until the one-minute load average is under 2."""
    while os.getloadavg()[0] >= 2:
        time.sleep(10)


def _result_path(accession: str) -> Path:
    return CACHE / "results" / f"{accession}.json"


def explain_one(client: EdgarClient, item: dict[str, str], index: dict) -> dict:
    accession = item["accession"]
    destination = CACHE / "filings" / accession
    record = {
        "ticker": item["ticker"],
        "cik": item["cik"],
        "accession": accession,
        "form": item["form"],
        "filing_date": item["filing_date"],
        "status": "error",
        "match": 0,
        "wrong": 0,
        "not_comparable": 0,
        "review": 0,
        "wrong_rows": [],
    }
    try:
        if not (destination / "provenance.json").is_file():
            client.fetch_accession(accession, destination, item["cik"])
        filing = load_directory(destination)
        explained = explain_filing(filing)
    except FetchError:
        record["status"] = "not_retrieved"
        return record
    except (OSError, UnicodeError, ValueError, KeyError, OutputRefused):
        record["status"] = "refused"
        return record
    if REFUSAL_SENTENCE in explained.markdown or not shown_ids(explained.markdown):
        record["status"] = "refused"
        return record
    counts, wrong, review = _classify_filing(explained.markdown, filing.store, accession, index)
    record["status"] = "explained"
    record["match"] = counts["MATCH"]
    record["wrong"] = counts["WRONG"]
    record["not_comparable"] = counts["NOT_COMPARABLE"]
    record["review"] = review
    record["wrong_rows"] = wrong
    from white_cliff.present import result_page
    from white_cliff.wording import take_percent_note_counts

    take_percent_note_counts()
    page = result_page(
        explained,
        form=filing.form,
        period=filing.period_end or "",
        filed=item["filing_date"],
        url=filing.url,
        company=filing.filer,
        focus=filing.focus,
        fiscal_year_end=filing.fiscal_year_end,
    )
    checked = check_percent_notes(page)
    noted, removed = take_percent_note_counts()
    record["percents_noted"] = noted
    record["percents_removed"] = removed
    record["percents_single"] = checked["single"]
    for mismatch in percent_mismatches(page):
        record["wrong"] += 1
        record["wrong_rows"].append(
            {
                "concept": "percent",
                "period": mismatch["period"],
                "shown": mismatch["shown"],
                "xbrl": mismatch["recomputed"],
            }
        )
    return record


def _saved_results() -> list[dict]:
    directory = CACHE / "results"
    if not directory.is_dir():
        return []
    rows = []
    for path in sorted(directory.glob("*.json")):
        rows.append(_load_json(path))
    return rows


def _aggregate(scope: list[dict], results: list[dict]) -> dict:
    by_accession = {row["accession"]: row for row in results}
    report = {
        "filings_in_scope": len(scope),
        "filings_covered": 0,
        "filings_explained": 0,
        "filings_refused": 0,
        "filings_not_retrieved": 0,
        "filings_errored": 0,
        "match": 0,
        "wrong": 0,
        "not_comparable": 0,
        "review": 0,
        "wrong_rows": [],
        "percents_noted": 0,
        "percents_removed": 0,
        "percents_single": 0,
    }
    for item in scope:
        row = by_accession.get(item["accession"])
        if row is None:
            continue
        report["filings_covered"] += 1
        status = row["status"]
        if status == "explained":
            report["filings_explained"] += 1
        elif status == "refused":
            report["filings_refused"] += 1
        elif status == "not_retrieved":
            report["filings_not_retrieved"] += 1
        elif status == "error":
            report["filings_errored"] += 1
        report["match"] += int(row.get("match") or 0)
        report["wrong"] += int(row.get("wrong") or 0)
        report["not_comparable"] += int(row.get("not_comparable") or 0)
        report["review"] += int(row.get("review") or 0)
        report["percents_noted"] += int(row.get("percents_noted") or 0)
        report["percents_removed"] += int(row.get("percents_removed") or 0)
        report["percents_single"] += int(row.get("percents_single") or 0)
        for wrong in row.get("wrong_rows") or []:
            report["wrong_rows"].append(
                {
                    "ticker": item["ticker"],
                    "accession": item["accession"],
                    "concept": wrong["concept"],
                    "period": wrong["period"],
                    "shown": wrong["shown"],
                    "xbrl": wrong["xbrl"],
                }
            )
    return report


def write_summary(scope: list[dict]) -> dict:
    report = _aggregate(scope, _saved_results())
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(render_summary(report), encoding="utf-8")
    return report


def select_pending(pending: list[dict[str, str]], tickers: list[str] | None, limit: int | None) -> list[dict[str, str]]:
    chosen = pending
    if tickers:
        wanted = {ticker.upper() for ticker in tickers}
        chosen = [
            item
            for item in chosen
            if wanted.intersection(part.upper() for part in item["ticker"].split(","))
        ]
    if limit is not None:
        return chosen[:limit]
    return chosen


def _empty_record(item: dict[str, str], status: str, error: str = "") -> dict:
    record = {
        "ticker": item["ticker"],
        "cik": item["cik"],
        "accession": item["accession"],
        "form": item["form"],
        "filing_date": item["filing_date"],
        "status": status,
        "match": 0,
        "wrong": 0,
        "not_comparable": 0,
        "review": 0,
        "wrong_rows": [],
    }
    if error:
        record["error"] = error
    return record


def run(limit: int | None, tickers: list[str] | None = None) -> dict:
    client = _client()
    scope = build_scope(client)
    done = {path.stem for path in (CACHE / "results").glob("*.json")} if (CACHE / "results").is_dir() else set()
    pending = select_pending(
        [item for item in scope if item["accession"] not in done],
        tickers,
        limit,
    )
    print(f"scope {len(scope)} pending {len(pending)}", flush=True)
    covered = 0
    current = ""
    index: dict | None = None
    facts_failed = False
    for item in pending:
        _wait_for_load()
        if item["cik"] != current:
            current = item["cik"]
            index = None
            facts_failed = False
            try:
                payload = _load_facts(client, item["cik"])
                index = _facts_index(payload)
                del payload
            except (FetchError, OSError, UnicodeError, ValueError, json.JSONDecodeError):
                facts_failed = True
        if facts_failed or index is None:
            record = _empty_record(item, "not_retrieved")
        else:
            try:
                record = explain_one(client, item, index)
            except Exception as exc:
                record = _empty_record(item, "error", type(exc).__name__)
        _write_json(_result_path(item["accession"]), record)
        covered += 1
        if covered % 100 == 0:
            write_summary(scope)
        print(
            f"covered {covered} {item['ticker']} {item['accession']} {record['status']} "
            f"MATCH {record['match']} WRONG {record['wrong']} "
            f"NOT_COMPARABLE {record['not_comparable']} REVIEW {record['review']}",
            flush=True,
        )
    return write_summary(scope)


def statement_quarters() -> list[str]:
    quarters = []
    for year in range(2020, 2027):
        for quarter in range(1, 5):
            quarters.append(f"{year}q{quarter}")
    return quarters


def statement_url(quarter: str) -> str:
    return f"https://www.sec.gov/files/dera/data/financial-statement-data-sets/{quarter}.zip"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_zip(client: EdgarClient, url: str, path: Path) -> str:
    if path.is_file() and zipfile.is_zipfile(path):
        return _sha256(path)
    temporary = path.with_suffix(".zip.partial")
    blob = client.get(url)
    temporary.write_bytes(blob)
    digest = hashlib.sha256(blob).hexdigest()
    del blob
    temporary.replace(path)
    return digest


def _write_tsv_gz(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    temporary.replace(path)


def _scope_rows(client: EdgarClient | None = None) -> list[dict[str, str]]:
    path = CACHE / "scope.json"
    if path.is_file():
        payload = _load_json(path)
        return list(payload["filings"])
    if client is None:
        client = _client()
    return build_scope(client)


def fetch_statement_sets(client: EdgarClient, downloaded: str | None = None) -> dict:
    """Download each quarterly zip once and pin the in-scope rows."""
    downloaded = downloaded or date.today().isoformat()
    scope = _scope_rows(client)
    allowed = {item["accession"] for item in scope}
    zip_dir = CACHE / "sec-zips"
    zip_dir.mkdir(parents=True, exist_ok=True)
    STATEMENTS.mkdir(parents=True, exist_ok=True)
    entries = []
    for quarter in statement_quarters():
        _wait_for_load()
        url = statement_url(quarter)
        path = zip_dir / f"{quarter}.zip"
        try:
            digest = _ensure_zip(client, url, path)
        except FetchError as exc:
            if "404" in str(exc):
                print(f"skip {quarter} unpublished", flush=True)
                continue
            raise
        with zipfile.ZipFile(path) as archive:
            with archive.open(_zip_member(archive, "num.txt")) as handle:
                text = io.TextIOWrapper(handle, encoding="utf-8-sig", newline="")
                header = text.readline().rstrip("\r\n")
                text.detach()
        print(f"{quarter} columns {header}", flush=True)
        kept_adsh, numbers, submissions = _read_statement_zip(path, allowed)
        num_name = f"{quarter}-num.tsv.gz"
        sub_name = f"{quarter}-sub.tsv.gz"
        _write_tsv_gz(
            STATEMENTS / num_name,
            ["adsh", "tag", "ddate", "qtrs", "uom", "segments", "coreg", "value"],
            [
                [
                    row["adsh"],
                    row["tag"],
                    row["ddate"],
                    row["qtrs"],
                    row["uom"],
                    row["segments"],
                    row["coreg"],
                    row["value"],
                ]
                for row in numbers
            ],
        )
        _write_tsv_gz(
            STATEMENTS / sub_name,
            ["adsh", "form", "period", "filed"],
            [[row["adsh"], row["form"], row["period"], row["filed"]] for row in submissions],
        )
        entry = manifest_entry(url, downloaded, digest)
        entry["quarter"] = quarter
        entry["num"] = num_name
        entry["sub"] = sub_name
        entries.append(entry)
        print(f"{quarter} filings {len(kept_adsh)} rows {len(numbers)}", flush=True)
    manifest = {
        "source": "SEC Financial Statement Data Sets",
        "snapshot": downloaded,
        "files": entries,
    }
    _write_json(STATEMENTS / "manifest.json", manifest)
    return manifest


def classify_shown_sec(markdown: str, store, accession: str, rows_for_tag) -> tuple[dict[str, int], list[dict]]:
    counts = {"MATCH": 0, "WRONG": 0, "NOT_COMPARABLE": 0, "unaligned": 0}
    review: list[dict] = []
    for kind, identifier in shown_ids(markdown):
        if kind == "calc":
            counts["NOT_COMPARABLE"] += 1
            continue
        fact = store.get(identifier)
        absolute = fact.value * (Decimal(10) ** int(fact.scale))
        if sec_period(fact.period.kind, fact.period.start, fact.period.end) is None:
            counts["unaligned"] += 1
        label, row = classify_sec_number(
            accession=accession,
            tag=fact.concept,
            kind=fact.period.kind,
            start=fact.period.start,
            end=fact.period.end,
            unit=fact.unit,
            absolute=absolute,
            decimals=fact.decimals,
            rows=rows_for_tag(fact.concept),
        )
        counts[label] += 1
        if row is not None:
            review.append(row)
    return counts, review


def _sec_result_path(accession: str) -> Path:
    return CACHE / "sec-results" / f"{accession}.json"


def _saved_sec_results() -> list[dict]:
    directory = CACHE / "sec-results"
    if not directory.is_dir():
        return []
    return [_load_json(path) for path in sorted(directory.glob("*.json"))]


def _statement_snapshot() -> str:
    path = STATEMENTS / "manifest.json"
    if not path.is_file():
        return ""
    return str(_load_json(path).get("snapshot") or "")


def _aggregate_sec(scope: list[dict], results: list[dict]) -> dict:
    by_accession = {row["accession"]: row for row in results}
    report = {
        "snapshot": _statement_snapshot(),
        "filings_in_scope": len(scope),
        "filings_from_statements": 0,
        "filings_from_companyfacts": 0,
        "filings_errored": 0,
        "sec_match": 0,
        "sec_wrong": 0,
        "sec_not_comparable": 0,
        "review_rows": [],
    }
    for item in scope:
        row = by_accession.get(item["accession"])
        if row is None:
            continue
        status = row.get("status")
        if status == "error":
            report["filings_errored"] += 1
            continue
        if status != "explained":
            continue
        if row.get("source") == "companyfacts":
            report["filings_from_companyfacts"] += 1
        else:
            report["filings_from_statements"] += 1
        report["sec_match"] += int(row.get("match") or 0)
        report["sec_wrong"] += int(row.get("wrong") or 0)
        report["sec_not_comparable"] += int(row.get("not_comparable") or 0)
        for review in row.get("review_rows") or []:
            report["review_rows"].append(review)
    return report


def write_sec_summary(scope: list[dict] | None = None) -> dict:
    if scope is None:
        scope = _scope_rows()
    earlier = _aggregate(scope, _saved_results())
    sec_report = _aggregate_sec(scope, _saved_sec_results())
    text = render_summary(earlier).rstrip() + "\n\n" + render_sec_summary(sec_report)
    _write_text(SEC_SUMMARY, text)
    return sec_report


def _sec_one(item: dict[str, str], present: set[str], index: dict, facts_index: dict | None) -> dict:
    accession = item["accession"]
    destination = CACHE / "filings" / accession
    source = "statements" if accession in present else "companyfacts"
    record = {
        "accession": accession,
        "status": "error",
        "source": source,
        "match": 0,
        "wrong": 0,
        "not_comparable": 0,
        "unaligned": 0,
        "review_rows": [],
    }
    if not (destination / "provenance.json").is_file():
        record["status"] = "not_retrieved"
        return record
    try:
        filing = load_directory(destination)
        explained = explain_filing(filing)
    except (OSError, UnicodeError, ValueError, KeyError, OutputRefused):
        record["status"] = "refused"
        return record
    if REFUSAL_SENTENCE in explained.markdown or not shown_ids(explained.markdown):
        record["status"] = "refused"
        return record
    if source == "statements":

        def rows_for_tag(tag: str, accession: str = accession) -> list[dict]:
            return rows_from_index(index, accession, tag)

    else:
        if facts_index is None:
            record["status"] = "not_retrieved"
            return record
        built = rows_from_companyfacts(facts_index, accession)

        def rows_for_tag(tag: str, built: list[dict] = built) -> list[dict]:
            return [row for row in built if row["tag"] == tag]

    counts, review = classify_shown_sec(explained.markdown, filing.store, accession, rows_for_tag)
    record["status"] = "explained"
    record["match"] = counts["MATCH"]
    record["wrong"] = counts["WRONG"]
    record["not_comparable"] = counts["NOT_COMPARABLE"]
    record["unaligned"] = counts["unaligned"]
    record["review_rows"] = review
    return record


def run_sec(limit: int | None, tickers: list[str] | None = None) -> dict:
    scope = _scope_rows()
    present, index = load_statements(STATEMENTS)
    done_dir = CACHE / "sec-results"
    done = {path.stem for path in done_dir.glob("*.json")} if done_dir.is_dir() else set()
    pending = select_pending(
        [item for item in scope if item["accession"] not in done],
        tickers,
        limit,
    )
    pending.sort(key=lambda item: (item["cik"], item["filing_date"], item["accession"]))
    print(f"sec scope {len(scope)} pending {len(pending)} statements {len(present)}", flush=True)
    # The statement index is large. Leave it alone while a filing is parsed.
    gc.disable()
    try:
        _run_sec_pending(pending, present, index, scope)
    finally:
        gc.enable()
        gc.collect()
    return write_sec_summary(scope)


def _run_sec_pending(pending, present, index, scope) -> None:
    client: EdgarClient | None = None
    current = ""
    facts_index: dict | None = None
    covered = 0
    for item in pending:
        _wait_for_load()
        facts_for_item = facts_index
        if item["accession"] not in present:
            if item["cik"] != current:
                current = item["cik"]
                if client is None:
                    client = _client()
                try:
                    facts_index = _facts_index(_load_facts(client, item["cik"]))
                except (FetchError, OSError, UnicodeError, ValueError, json.JSONDecodeError):
                    facts_index = None
            facts_for_item = facts_index
        try:
            record = _sec_one(item, present, index, facts_for_item)
        except Exception as exc:
            record = {
                "accession": item["accession"],
                "status": "error",
                "source": "",
                "match": 0,
                "wrong": 0,
                "not_comparable": 0,
                "unaligned": 0,
                "review_rows": [],
                "error": type(exc).__name__,
            }
        _write_json(_sec_result_path(item["accession"]), record)
        covered += 1
        if covered % 50 == 0:
            gc.collect()
        if covered % 100 == 0:
            write_sec_summary(scope)
        print(
            f"sec {covered} {item['ticker']} {item['accession']} {record['status']} "
            f"{record['source']} MATCH {record['match']} WRONG {record['wrong']} "
            f"NOT_COMPARABLE {record['not_comparable']}",
            flush=True,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=DISCLAIMER)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ticker", action="append", default=None)
    parser.add_argument("--fetch-statements", action="store_true")
    parser.add_argument("--sec", action="store_true")
    args = parser.parse_args(argv)
    if args.fetch_statements:
        fetch_statement_sets(_client())
    if args.sec:
        report = run_sec(args.limit, args.ticker)
        print(
            f"sec MATCH {report['sec_match']} WRONG {report['sec_wrong']} "
            f"NOT_COMPARABLE {report['sec_not_comparable']} "
            f"REVIEW {len(report['review_rows'])}",
            flush=True,
        )
        return 0
    if args.fetch_statements:
        return 0
    report = run(args.limit, args.ticker)
    print(
        f"scope {report['filings_in_scope']} covered {report['filings_covered']} "
        f"explained {report['filings_explained']} refused {report['filings_refused']} "
        f"MATCH {report['match']} WRONG {report['wrong']} "
        f"NOT_COMPARABLE {report['not_comparable']} REVIEW {report['review']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
