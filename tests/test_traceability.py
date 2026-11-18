import json
import re
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from white_cliff.disclaimer import DISCLAIMER
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.review import review_text

ROOT = Path(__file__).resolve().parents[1]
PINNED = ROOT / "pinned"
LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"([^\"]*)\")?\)")


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _audit_markdown(markdown: str, store) -> None:
    assert markdown.startswith(DISCLAIMER)
    digit = re.search(r"\d", markdown)
    assert digit is None or markdown.find(DISCLAIMER) < digit.start()
    seen = False

    def replace(match: re.Match[str]) -> str:
        nonlocal seen
        label, url = match.group(1), match.group(2)
        number = re.match(r"-?\d+(?:\.\d+)?", label)
        if number:
            seen = True
            fragment = urlsplit(url).fragment
            kind, _, rest = fragment.partition("=")
            identifier = rest.split("&", 1)[0]
            parsed = Decimal(number.group(0))
            if kind == "fact":
                fact = store.get(identifier)
                assert fact.value == parsed
                assert fact.source.document
                assert fact.source.char_start is not None
            elif kind == "calc":
                calc = store.get_calc(identifier)
                assert calc.value == parsed
                assert calc.formula
                assert calc.input_ids
                assert calc.name in markdown
                for input_id in calc.input_ids:
                    assert input_id in markdown
                    assert store.has_fact(input_id)
            else:
                raise AssertionError(fragment)
        return ""

    stripped = LINK.sub(replace, markdown).replace(DISCLAIMER, "")
    assert not re.search(r"\d", stripped)
    assert seen


def _audit_html(document: str, store) -> None:
    assert document.find(DISCLAIMER) < re.search(r"\d", document).start()
    figures = re.findall(r"<data\b([^>]*)>([^<]*)</data>", document)
    assert figures
    for attrs, text in figures:
        identifier = re.search(r'data-id="([^"]+)"', attrs).group(1)
        kind = re.search(r'data-kind="([^"]+)"', attrs).group(1)
        parsed = Decimal(text.split()[0])
        if kind == "fact":
            assert store.get(identifier).value == parsed
        else:
            assert store.get_calc(identifier).value == parsed
        assert f'data-id="{identifier}"' in document
        assert "source-chip" in document
    cleaned = re.sub(r"<data\b[^>]*>[^<]*</data>", "", document)
    cleaned = re.sub(r"<a\b[^>]*>[^<]*</a>", "", cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned).replace(DISCLAIMER, "")
    assert not re.search(r"\d", cleaned)


def test_golden_numbers_resolve_and_match_the_filing():
    manifest = json.loads((PINNED / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["target_count"] == 30
    assert len(manifest["filings"]) >= 5
    sectors = {entry["sic"]["description"] for entry in manifest["filings"]}
    assert len(sectors) >= 5
    assert "technology" not in sectors
    for entry in manifest["filings"]:
        assert "sector" not in entry
        assert entry["sic"]["code"].isdigit()
        assert entry["sic"]["source"].startswith("https://data.sec.gov/submissions/CIK")
    for entry in manifest["filings"]:
        directory = PINNED / "filings" / entry["accession"]
        provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
        expected = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
        filing = load_directory(directory)
        raw_name = provenance["files"][0]["name"]
        raw = (directory / raw_name).read_text(encoding="utf-8")
        recorded = (directory / raw_name).read_bytes()
        assert __import__("hashlib").sha256(recorded).hexdigest() == provenance["files"][0]["sha256"]
        for item in expected["facts"]:
            if item.get("match") == "table":
                found = [
                    fact
                    for fact in filing.store.facts()
                    if item["row"].lower() in fact.label.lower()
                    and fact.value == Decimal(item["value"])
                    and fact.unit == item["unit"]
                ]
            else:
                found = [
                    fact
                    for fact in filing.store.facts()
                    if fact.concept == item["concept"]
                    and fact.value == Decimal(item["value"])
                    and fact.unit == item["unit"]
                    and fact.period.kind == item["kind"]
                    and fact.period.end == item["end"]
                    and (item["start"] is None or fact.period.start == item["start"])
                ]
            assert found, item
            fact = found[0]
            slice_text = raw[fact.source.char_start : fact.source.char_end]
            assert _digits(format(fact.value, "f")) == _digits(slice_text)
        explained = explain_filing(filing)
        _audit_markdown(explained.markdown, filing.store)
        _audit_html(explained.html, filing.store)
        assert "https://github.com/EE-Holding/white-cliff/issues/new?template=filing_error.md" in explained.markdown


def test_every_shown_fact_has_a_hand_checked_expected_entry():
    manifest = json.loads((PINNED / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["filings"]:
        directory = PINNED / "filings" / entry["accession"]
        expected = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
        filing = load_directory(directory)
        explained = explain_filing(filing)
        shown = []
        for match in LINK.finditer(explained.markdown):
            label, url = match.group(1), match.group(2)
            fragment = urlsplit(url).fragment
            if not fragment.startswith("fact="):
                continue
            identifier = fragment.split("=", 1)[1].split("&", 1)[0]
            shown.append(filing.store.get(identifier))
        assert shown, entry["accession"]
        for fact in shown:
            matched = False
            for item in expected["facts"]:
                if Decimal(item["value"]) != fact.value or item["unit"] != fact.unit:
                    continue
                if item.get("match") == "table":
                    matched = item["row"].lower() in fact.label.lower()
                else:
                    matched = (
                        fact.concept == item["concept"]
                        and fact.period.kind == item["kind"]
                        and fact.period.end == item["end"]
                        and (item["start"] is None or fact.period.start == item["start"])
                    )
                if matched:
                    break
            assert matched, (entry["accession"], fact.concept, fact.label, fact.value, fact.unit)


def test_pinned_raw_files_match_provenance_hashes():
    import hashlib

    manifest = json.loads((PINNED / "manifest.json").read_text(encoding="utf-8"))
    checked = 0
    for entry in manifest["filings"]:
        provenance_path = PINNED / "filings" / entry["accession"] / "provenance.json"
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        for item in provenance["files"]:
            raw = (provenance_path.parent / item["name"]).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == item["sha256"]
            checked += 1
    assert checked >= len(manifest["filings"])


def test_bare_digit_fails_review():
    from white_cliff.facts import FactStore

    store = FactStore()
    assert review_text("Revenue was 5. [section:Income statement].", store) == "bare digit"
