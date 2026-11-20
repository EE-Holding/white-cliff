#!/usr/bin/env python3
"""Compare every number the app shows with company facts.

This script is not a test and it is not part of CI. Responses stay in
.full-index-cache, which is gitignored. Pass --limit to stop after a partial pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
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
SCOPE_START = "2020-01-01"
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
_PROPOSED_DE = "Dieser Bericht kann noch nicht erklärt werden."


@dataclass(frozen=True)
class Verdict:
    label: str
    reason: str
    xbrl_value: str


def _quantum(decimals: int | None) -> Decimal | None:
    """XBRL decimals names the last accurate place. -6 is the millions place."""
    if decimals is None:
        return None
    return Decimal((0, (1,), -int(decimals)))


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
        f"DE: {_PROPOSED_DE}",
        "",
        f"Filings in scope: {report['filings_in_scope']}",
        f"Filings covered: {report['filings_covered']}",
        f"Filings explained: {report['filings_explained']}",
        f"Coverage of scope: {coverage:.1f}%",
        f"Filings refused: {report['filings_refused']}",
        f"Filings not retrieved: {report['filings_not_retrieved']}",
        f"Numbers MATCH: {report['match']}",
        f"Numbers WRONG: {report['wrong']}",
        f"Numbers NOT_COMPARABLE: {report['not_comparable']}",
        f"Review list: {report['review']}",
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


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


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
                    value = Decimal(str(row["val"]))
                    key = (str(concept), str(unit), start, end)
                    index.setdefault(key, []).append((accession, value))
    return index


def _load_facts(client: EdgarClient, cik: str) -> dict:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    return _cached_get(client, url, CACHE / "facts" / f"{cik}.json")


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


def _under_load() -> bool:
    for _ in range(60):
        if os.getloadavg()[0] < 2:
            return True
        time.sleep(10)
    return False


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
        "match": 0,
        "wrong": 0,
        "not_comparable": 0,
        "review": 0,
        "wrong_rows": [],
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
        report["match"] += int(row.get("match") or 0)
        report["wrong"] += int(row.get("wrong") or 0)
        report["not_comparable"] += int(row.get("not_comparable") or 0)
        report["review"] += int(row.get("review") or 0)
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


def run(limit: int | None) -> dict:
    client = _client()
    scope = build_scope(client)
    done = {path.stem for path in (CACHE / "results").glob("*.json")} if (CACHE / "results").is_dir() else set()
    pending = [item for item in scope if item["accession"] not in done]
    if limit is not None:
        pending = pending[:limit]
    facts_cache: dict[str, dict] = {}
    covered = 0
    for item in pending:
        if not _under_load():
            break
        index = facts_cache.get(item["cik"])
        if index is None:
            try:
                index = _facts_index(_load_facts(client, item["cik"]))
            except FetchError:
                record = {
                    "ticker": item["ticker"],
                    "cik": item["cik"],
                    "accession": item["accession"],
                    "form": item["form"],
                    "filing_date": item["filing_date"],
                    "status": "not_retrieved",
                    "match": 0,
                    "wrong": 0,
                    "not_comparable": 0,
                    "review": 0,
                    "wrong_rows": [],
                }
                _write_json(_result_path(item["accession"]), record)
                covered += 1
                continue
            facts_cache[item["cik"]] = index
        record = explain_one(client, item, index)
        _write_json(_result_path(item["accession"]), record)
        covered += 1
        print(
            f"covered {covered} {item['ticker']} {item['accession']} {record['status']} "
            f"MATCH {record['match']} WRONG {record['wrong']} "
            f"NOT_COMPARABLE {record['not_comparable']} REVIEW {record['review']}",
            flush=True,
        )
    return write_summary(scope)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=DISCLAIMER)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    report = run(args.limit)
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
