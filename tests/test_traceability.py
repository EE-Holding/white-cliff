import json
import re
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from white_cliff.disclaimer import DISCLAIMER
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.review import audit_rendered, review_text

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
            assert url.startswith("https://www.sec.gov/")
            fragment = urlsplit(url).fragment
            assert fragment
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
    figures = re.findall(
        r'<data\b([^>]*)>([^<]*)</data>\s*'
        r'<a class="source-chip"[^>]*href="(https://www\.sec\.gov/[^"]+)"',
        document,
    )
    assert figures
    assert len(figures) == len(re.findall(r"<data\b", document))
    for attrs, text, href in figures:
        identifier = re.search(r'data-id="([^"]+)"', attrs).group(1)
        kind = re.search(r'data-kind="([^"]+)"', attrs).group(1)
        parsed = Decimal(text.split()[0])
        if kind == "fact":
            assert store.get(identifier).value == parsed
        else:
            assert store.get_calc(identifier).value == parsed
        assert "fact=" in href or "calc=" in href
        assert f'data-id="{identifier}"' in document
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
            raw = (directory / fact.source.document).read_text(encoding="utf-8")
            slice_text = raw[fact.source.char_start : fact.source.char_end]
            assert _digits(format(fact.value, "f")) == _digits(slice_text)
        explained = explain_filing(filing)
        if not expected["facts"]:
            assert "This filing has no tagged figures that White Cliff can explain." in explained.markdown
            assert "<data" not in explained.html
            assert explained.markdown.startswith(DISCLAIMER)
            assert audit_rendered(explained.markdown) is None
            continue
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
        if not expected["facts"]:
            assert "This filing has no tagged figures that White Cliff can explain." in explained.markdown
            continue
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


def test_johnson_chip_points_at_the_name_in_the_filing():
    import html as html_lib

    accession = "0000200406-26-000016"
    directory = PINNED / "filings" / accession
    filing = load_directory(directory)
    explained = explain_filing(filing)
    match = re.search(r'class="registrant-chip"[^>]*href="([^"]+)"', explained.html)
    assert match, explained.html[:500]
    href = html_lib.unescape(match.group(1))
    fragment = urlsplit(href).fragment
    parts = dict(piece.split("=", 1) for piece in fragment.split("&"))
    start, end = int(parts["registrant"]), int(parts["end"])
    raw_name = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))["files"][0]["name"]
    raw = (directory / raw_name).read_text(encoding="utf-8")
    assert html_lib.unescape(raw[start:end]) == "Johnson & Johnson"
    assert "the filer" not in explained.html.split("registrant-chip", 1)[0]


def test_index_uses_the_filing_name_and_only_a_real_sic(tmp_path: Path):
    import json as json_lib
    from hashlib import sha256

    from tests.support import MINI_XML
    from white_cliff.sitebuild import build_site

    pinned = tmp_path / "pinned"
    filings = pinned / "filings"

    def add(accession: str, filer: str, sic: dict) -> None:
        directory = filings / accession
        directory.mkdir(parents=True)
        data = MINI_XML.encode("utf-8")
        (directory / "instance.xml").write_bytes(data)
        provenance = {
            "filer": filer,
            "form": "10-K",
            "cik": "0000000001",
            "files": [
                {
                    "name": "instance.xml",
                    "url": "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/instance.xml",
                    "sha256": sha256(data).hexdigest(),
                    "retrieved_at": "2026-11-18T00:13:08Z",
                }
            ],
        }
        (directory / "provenance.json").write_text(json_lib.dumps(provenance), encoding="utf-8")
        return {
            "accession": accession,
            "cik": "0000000001",
            "filer": filer,
            "form": "10-K",
            "sic": sic,
        }

    manifest = {
        "target_count": 30,
        "filings": [
            add(
                "0000000001-26-000001",
                "Manifest Only Name",
                {
                    "code": "3571",
                    "description": "Electronic Computers",
                    "source": "https://data.sec.gov/submissions/CIK0000000001.json",
                    "retrieved_at": "2026-11-18T00:13:08Z",
                },
            ),
            add(
                "0000000001-26-000002",
                "Manifest Only Name",
                {
                    "code": "6211",
                    "description": "Strong Buy Recommendations",
                    "source": "https://data.sec.gov/submissions/CIK0000000001.json",
                    "retrieved_at": "2026-11-18T00:13:08Z",
                },
            ),
            add(
                "0000000001-26-000004",
                "Manifest Only Name",
                {
                    "code": "6282",
                    "description": "Investment Advice",
                    "source": "https://data.sec.gov/submissions/CIK0000000001.json",
                    "retrieved_at": "2026-11-18T00:13:08Z",
                },
            ),
            add(
                "0000000001-26-000003",
                "Manifest Only Name",
                {
                    "code": "3571",
                    "description": "Market-Cap Leaders",
                    "source": "https://example.com/sectors.json",
                    "retrieved_at": "2026-11-18T00:13:08Z",
                },
            ),
        ],
    }
    (pinned / "manifest.json").write_text(json_lib.dumps(manifest), encoding="utf-8")
    site = build_site(tmp_path / "site", pinned)
    index = (site / "index.html").read_text(encoding="utf-8")
    assert "Example Co" in index
    assert "Manifest Only Name" not in index
    assert "SEC industry (SIC 3571): ELECTRONIC COMPUTERS" in index
    assert "Electronic Computers" not in index
    assert "SEC industry (SIC 6211): SECURITY BROKERS, DEALERS &amp; FLOTATION COMPANIES" in index
    assert "Strong Buy Recommendations" not in index
    assert "SEC industry (SIC 6282): INVESTMENT ADVICE" in index
    assert "Investment Advice" not in index
    assert "Market-Cap Leaders" not in index
    assert "example.com" not in index
    assert "https://data.sec.gov/submissions/CIK0000000001.json" in index
    assert 'class="registrant-chip"' in index
    assert "#registrant=" in index


def test_apple_exhibit_has_no_tagged_figures():
    directory = PINNED / "filings" / "0000320193-26-000024"
    filing = load_directory(directory)
    explained = explain_filing(filing)
    assert "This filing has no tagged figures that White Cliff can explain." in explained.markdown
    assert "132175" not in explained.markdown
    assert "<data" not in explained.html


def test_sector_label_is_exempt_only_in_its_form():
    import pytest

    from white_cliff.disclaimer import DISCLAIMER, OutputRefused
    from white_cliff.review import audit_rendered
    from white_cliff.sic import sector_html
    from white_cliff.sitebuild import check_index

    assert sector_html("6282", "https://data.sec.gov/submissions/CIK0000000001.json", labelled=False) == ""
    labelled = sector_html("6282", "https://data.sec.gov/submissions/CIK0000000001.json")
    assert labelled.startswith('<a class="sector-chip"')
    assert "SEC industry (SIC 6282): INVESTMENT ADVICE" in labelled
    assert audit_rendered(DISCLAIMER + labelled) is None
    altered = labelled.replace("INVESTMENT ADVICE", "Investment Advice")
    assert audit_rendered(DISCLAIMER + altered) is not None
    assert audit_rendered(DISCLAIMER + " Investment Advice") == "advice"
    assert audit_rendered(DISCLAIMER + ' <a href="https://example.com/note">Investment Advice</a>') == "advice"
    with pytest.raises(OutputRefused):
        check_index(DISCLAIMER + "\n<p>You should buy this stock.</p>\n")


def test_bare_digit_fails_review():
    from white_cliff.facts import FactStore

    store = FactStore()
    assert review_text("Revenue was 5. [section:Income statement].", store) == "bare digit"
