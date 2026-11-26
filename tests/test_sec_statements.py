"""The SEC cross-check reads pinned fixtures. It does not contact EDGAR."""

import gzip
import hashlib
import json
import zipfile
from decimal import Decimal
from pathlib import Path

from white_cliff.disclaimer import DISCLAIMER

from tests.test_full_index import _harness

ROOT = Path(__file__).resolve().parents[1]


def _row(**kwargs):
    base = {
        "adsh": "0000320193-26-000026",
        "tag": "Assets",
        "ddate": "20260930",
        "qtrs": "0",
        "uom": "USD",
        "segments": "",
        "coreg": "",
        "value": "100",
    }
    base.update(kwargs)
    return base


def test_an_equal_sec_number_matches():
    harness = _harness()
    label, review = harness.classify_sec_number(
        accession="0000320193-26-000026",
        tag="Assets",
        kind="instant",
        start=None,
        end="2026-09-26",
        unit="USD million",
        absolute=Decimal("100"),
        decimals=0,
        rows=[_row()],
    )
    assert label == "MATCH"
    assert review is None


def test_a_different_sec_number_is_wrong_and_stays_on_the_review_list():
    harness = _harness()
    label, review = harness.classify_sec_number(
        accession="0000320193-26-000026",
        tag="Assets",
        kind="instant",
        start=None,
        end="2026-09-26",
        unit="USD",
        absolute=Decimal("90"),
        decimals=0,
        rows=[_row(value="100")],
    )
    assert label == "WRONG"
    assert review == {
        "filing": "0000320193-26-000026",
        "tag": "Assets",
        "ours": "90",
        "sec": "100",
    }


def test_a_scale_difference_is_wrong():
    harness = _harness()
    label, review = harness.classify_sec_number(
        accession="0000320193-26-000026",
        tag="Assets",
        kind="instant",
        start=None,
        end="2026-09-26",
        unit="USD",
        absolute=Decimal("100"),
        decimals=0,
        rows=[_row(value="100000")],
    )
    assert label == "WRONG"
    assert review["sec"] == "100000"
    assert review["ours"] == "100"


def test_a_missing_sec_row_is_not_comparable():
    harness = _harness()
    label, review = harness.classify_sec_number(
        accession="0000320193-26-000026",
        tag="Assets",
        kind="instant",
        start=None,
        end="2026-09-26",
        unit="USD",
        absolute=Decimal("100"),
        decimals=0,
        rows=[_row(tag="Liabilities")],
    )
    assert label == "NOT_COMPARABLE"
    assert review is None


def test_a_segment_row_does_not_stand_in_for_the_consolidated_number():
    harness = _harness()
    label, review = harness.classify_sec_number(
        accession="0000320193-26-000026",
        tag="Assets",
        kind="instant",
        start=None,
        end="2026-09-26",
        unit="USD",
        absolute=Decimal("100"),
        decimals=0,
        rows=[_row(segments="StatementBusinessSegmentsAxis=ProductMember")],
    )
    assert label == "NOT_COMPARABLE"
    assert review is None


def test_one_matching_version_does_not_hide_a_disagreeing_sec_value():
    harness = _harness()
    label, review = harness.classify_sec_number(
        accession="0000320193-26-000026",
        tag="Assets",
        kind="instant",
        start=None,
        end="2026-09-26",
        unit="USD",
        absolute=Decimal("100"),
        decimals=0,
        rows=[_row(value="100"), _row(value="250")],
    )
    assert label == "WRONG"
    assert review["ours"] == "100"
    assert "100" in review["sec"]
    assert "250" in review["sec"]


def test_a_coregistrant_row_is_not_the_consolidated_number():
    harness = _harness()
    label, review = harness.classify_sec_number(
        accession="0000320193-26-000026",
        tag="Assets",
        kind="instant",
        start=None,
        end="2026-09-26",
        unit="USD",
        absolute=Decimal("100"),
        decimals=0,
        rows=[_row(coreg="0000320193")],
    )
    assert label == "NOT_COMPARABLE"
    assert review is None


def test_a_span_that_is_not_a_quarter_count_is_not_comparable():
    harness = _harness()
    label, review = harness.classify_sec_number(
        accession="0000320193-26-000026",
        tag="Revenues",
        kind="duration",
        start="2026-01-01",
        end="2026-02-15",
        unit="USD",
        absolute=Decimal("100"),
        decimals=0,
        rows=[_row(tag="Revenues", ddate="20260215", qtrs="1", value="100")],
    )
    assert label == "NOT_COMPARABLE"
    assert review is None


def test_a_fiscal_period_end_matches_the_sec_month_end():
    harness = _harness()
    label, review = harness.classify_sec_number(
        accession="0000320193-20-000052",
        tag="Revenues",
        kind="duration",
        start="2019-12-29",
        end="2020-03-28",
        unit="USD",
        absolute=Decimal("58313000000"),
        decimals=-6,
        rows=[_row(
            adsh="0000320193-20-000052",
            tag="Revenues",
            ddate="20200331",
            qtrs="1",
            value="58313000000.0000",
        )],
    )
    assert label == "MATCH"
    assert review is None


def test_a_month_end_row_with_a_different_value_is_still_wrong():
    harness = _harness()
    label, review = harness.classify_sec_number(
        accession="0000320193-20-000052",
        tag="Revenues",
        kind="duration",
        start="2019-12-29",
        end="2020-03-28",
        unit="USD",
        absolute=Decimal("1000000"),
        decimals=-6,
        rows=[_row(
            adsh="0000320193-20-000052",
            tag="Revenues",
            ddate="20200331",
            qtrs="1",
            value="58313000000",
        )],
    )
    assert label == "WRONG"
    assert review["ours"] == "1000000"
    assert review["sec"] == "58313000000"
    assert review["filing"] == "0000320193-20-000052"
    assert review["tag"] == "Revenues"


def test_a_year_matches_four_quarters():
    harness = _harness()
    label, review = harness.classify_sec_number(
        accession="0000320193-26-000026",
        tag="Revenues",
        kind="duration",
        start="2025-09-28",
        end="2026-09-26",
        unit="USD",
        absolute=Decimal("400"),
        decimals=0,
        rows=[_row(tag="Revenues", ddate="20260930", qtrs="4", value="400")],
    )
    assert label == "MATCH"
    assert review is None


def test_a_filing_missing_from_the_sets_uses_companyfacts():
    harness = _harness()
    accession = "0000320193-26-000099"
    index = {
        ("Assets", "USD", "", "2026-09-26"): [(accession, Decimal("50"))],
    }
    rows, source = harness.rows_for_filing(accession, set(), [], index)
    assert source == "companyfacts"
    label, review = harness.classify_sec_number(
        accession=accession,
        tag="Assets",
        kind="instant",
        start=None,
        end="2026-09-26",
        unit="USD",
        absolute=Decimal("50"),
        decimals=0,
        rows=rows,
    )
    assert label == "MATCH"
    assert review is None
    present = {accession}
    used, source = harness.rows_for_filing(accession, present, [_row(adsh=accession)], index)
    assert source == "statements"
    assert used[0]["value"] == "100"


def test_a_local_zip_keeps_only_in_scope_rows(tmp_path):
    harness = _harness()
    inside = "0000320193-26-000026"
    outside = "0000000000-26-000001"
    sub = (
        "adsh\tform\tperiod\tfiled\tname\n"
        f"{inside}\t10-K\t20260926\t20261101\tExample Filer\n"
        f"{outside}\t10-Q\t20260627\t20260801\tOther Filer\n"
    )
    num = (
        "adsh\ttag\tversion\tddate\tqtrs\tuom\tsegments\tcoreg\tvalue\tfootnote\n"
        f"{inside}\tAssets\tus-gaap/2026\t20260926\t0\tUSD\t\t\t100\t\n"
        f"{outside}\tAssets\tus-gaap/2026\t20260627\t0\tUSD\t\t\t9\t\n"
    )
    blob = tmp_path / "2026q3.zip"
    with zipfile.ZipFile(blob, "w") as archive:
        archive.writestr("sub.txt", sub)
        archive.writestr("num.txt", num)
    kept_adsh, kept_rows = harness.filter_statement_zip(blob, {inside})
    assert kept_adsh == {inside}
    assert [row["adsh"] for row in kept_rows] == [inside]
    assert "Example" not in str(kept_rows)
    assert "Other" not in str(kept_rows)
    digest = hashlib.sha256(blob.read_bytes()).hexdigest()
    entry = harness.manifest_entry(
        "https://www.sec.gov/files/dera/data/financial-statement-data-sets/2026q3.zip",
        "2026-11-26",
        digest,
    )
    assert entry == {
        "url": "https://www.sec.gov/files/dera/data/financial-statement-data-sets/2026q3.zip",
        "downloaded": "2026-11-26",
        "sha256": digest,
    }


def test_the_fixture_keeps_a_segment_row_and_the_index_does_not_use_it(tmp_path):
    harness = _harness()
    num = tmp_path / "2026q3-num.tsv.gz"
    with gzip.open(num, "wt", encoding="utf-8", newline="") as handle:
        handle.write(
            "adsh\ttag\tddate\tqtrs\tuom\tsegments\tcoreg\tvalue\n"
            "0000320193-26-000026\tAssets\t20260926\t0\tUSD\t\t\t100\n"
            "0000320193-26-000026\tAssets\t20260926\t0\tUSD\tAxis=Member\t\t80\n"
        )
    sub = tmp_path / "2026q3-sub.tsv.gz"
    with gzip.open(sub, "wt", encoding="utf-8", newline="") as handle:
        handle.write(
            "adsh\tform\tperiod\tfiled\n"
            "0000320193-26-000026\t10-K\t20260926\t20261101\n"
        )
    manifest = {
        "source": "SEC Financial Statement Data Sets",
        "snapshot": "2026-11-26",
        "files": [
            {
                "quarter": "2026q3",
                "url": "https://www.sec.gov/files/dera/data/financial-statement-data-sets/2026q3.zip",
                "downloaded": "2026-11-26",
                "sha256": "ab" * 32,
                "num": "2026q3-num.tsv.gz",
                "sub": "2026q3-sub.tsv.gz",
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    present, index = harness.load_statements(tmp_path)
    assert present == {"0000320193-26-000026"}
    rows = harness.rows_from_index(index, "0000320193-26-000026", "Assets")
    assert len(rows) == 1
    assert rows[0]["value"] == "100"
    assert rows[0]["segments"] == ""
    stored = gzip.open(num, "rt", encoding="utf-8").read()
    assert "Axis=Member" in stored
    assert "80" in stored


def test_the_pinned_fixture_records_each_source_file():
    harness = _harness()
    directory = ROOT / "pinned" / "sec-statements"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    text = (directory / "manifest.json").read_text(encoding="utf-8")
    assert "@" not in text
    assert manifest["source"] == "SEC Financial Statement Data Sets"
    assert manifest["snapshot"] == "2026-11-26"
    quarters = [item["quarter"] for item in manifest["files"]]
    expected = [f"{year}q{quarter}" for year in range(2020, 2026) for quarter in range(1, 5)]
    expected += ["2026q1", "2026q2", "2026q3"]
    assert quarters == expected
    for item in manifest["files"]:
        entry = harness.manifest_entry(item["url"], item["downloaded"], item["sha256"])
        assert entry["url"] == (
            "https://www.sec.gov/files/dera/data/financial-statement-data-sets/"
            + item["quarter"]
            + ".zip"
        )
        assert entry["downloaded"] == "2026-11-26"
        assert len(entry["sha256"]) == 64
        assert int(entry["sha256"], 16) >= 0
        sub_path = directory / item["sub"]
        num_path = directory / item["num"]
        present = set()
        with gzip.open(sub_path, "rt", encoding="utf-8", newline="") as handle:
            header = handle.readline().rstrip("\n")
            assert header == "adsh\tform\tperiod\tfiled"
            for line in handle:
                assert "@" not in line
                adsh, form, _period, _filed = line.rstrip("\n").split("\t")
                assert form in {"10-K", "10-Q"}
                present.add(adsh)
        with gzip.open(num_path, "rt", encoding="utf-8", newline="") as handle:
            header = handle.readline().rstrip("\n")
            assert header == "adsh\ttag\tddate\tqtrs\tuom\tsegments\tcoreg\tvalue"
            for line in handle:
                assert "@" not in line
                adsh = line.split("\t", 1)[0]
                assert adsh in present


def test_the_sec_summary_names_the_source_and_lists_every_wrong():
    harness = _harness()
    text = harness.render_sec_summary(
        {
            "snapshot": "2026-11-26",
            "filings_in_scope": 13548,
            "filings_from_statements": 13000,
            "filings_from_companyfacts": 548,
            "sec_match": 10,
            "sec_wrong": 1,
            "sec_not_comparable": 2,
            "review_rows": [
                {
                    "filing": "0000320193-26-000026",
                    "tag": "Assets",
                    "ours": "90",
                    "sec": "100",
                }
            ],
        }
    )
    assert text.startswith(DISCLAIMER)
    assert "SEC Financial Statement Data Sets" in text
    assert "2026-11-26" in text
    assert "companyfacts" in text
    assert "Numbers MATCH: 10" in text
    assert "Numbers WRONG: 1" in text
    assert "Numbers NOT_COMPARABLE: 2" in text
    assert "0000320193-26-000026" in text
    assert "Assets" in text
    assert "90" in text
    assert "100" in text
    assert "@" not in text
    assert "num.txt" in text
    assert "sub.txt" in text
