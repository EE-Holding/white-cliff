"""Unit, currency, scale, and path allow-lists refuse by default."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from white_cliff.disclaimer import OutputRefused
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.sic import accepted_sector, sic_title
from white_cliff.xbrl import parse_inline
from tests.support import write_filing

URL = "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/inline.htm"
_USD = '<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'


def _inline(
    amount: str,
    fmt: str,
    *,
    unit_xml: str = _USD,
    unit_ref: str = "usd",
    scale: str = "6",
    decimals: str = "-6",
    pad: bool = False,
) -> str:
    gap = "<!-- " + ("x" * 900) + " -->" if pad else ""
    scale_attr = f' scale="{scale}"' if scale else ""
    decimal_attr = f' decimals="{decimals}"' if decimals else ""
    format_attr = f' format="{fmt}"' if fmt else ""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"
      xmlns:ixt-sec="http://www.sec.gov/inlineXBRL/transformation/2015-08-31"
      xmlns:us-gaap="http://fasb.org/us-gaap/2026">
<body>
<xbrli:context id="c">
  <xbrli:entity>
    <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
  </xbrli:entity>
  <xbrli:period>
    <xbrli:startDate>2024-01-01</xbrli:startDate>
    <xbrli:endDate>2024-12-31</xbrli:endDate>
  </xbrli:period>
</xbrli:context>
<ix:nonNumeric name="dei:DocumentPeriodEndDate" contextRef="c">2024-12-31</ix:nonNumeric>
<ix:nonNumeric name="dei:DocumentFiscalPeriodFocus" contextRef="c">FY</ix:nonNumeric>
<ix:nonNumeric name="dei:EntityRegistrantName" contextRef="c">Example Co</ix:nonNumeric>
<ix:nonNumeric name="dei:DocumentType" contextRef="c">10-Q</ix:nonNumeric>
{unit_xml}
{gap}
<ix:nonFraction name="us-gaap:Revenues" contextRef="c" unitRef="{unit_ref}"{format_attr}{scale_attr}{decimal_attr}>{amount}</ix:nonFraction>
</body>
</html>
"""


def _revenues(text: str):
    parsed = parse_inline(text, "inline.htm", URL, "abc", filer_cik="0000000001")
    return [fact for fact in parsed.facts if fact.role == "revenue"]


def test_num_comma_decimal_five_thousand_is_refused() -> None:
    assert _revenues(_inline("5.000", "ixt:num-comma-decimal")) == []


def test_num_comma_decimal_five_comma_five_is_refused() -> None:
    assert _revenues(_inline("5,5", "ixt:num-comma-decimal")) == []


def test_an_unknown_inline_format_is_refused() -> None:
    assert _revenues(_inline("5", "ixt:num-words")) == []


def test_num_dot_decimal_with_thousands_commas_is_accepted() -> None:
    found = _revenues(_inline("5,000", "ixt:num-dot-decimal"))
    assert found and found[0].value == Decimal("5000")
    assert found[0].unit == "USD millions"


def test_num_dot_decimal_without_hyphens_is_accepted() -> None:
    found = _revenues(_inline("5,000", "ixt-sec:numdotdecimal"))
    assert found and found[0].value == Decimal("5000")


def test_a_badly_grouped_dot_decimal_is_refused() -> None:
    assert _revenues(_inline("12,34", "ixt:num-dot-decimal")) == []
    assert _revenues(_inline("5,5", "ixt:num-dot-decimal")) == []


def test_an_undefined_unit_ref_is_refused() -> None:
    text = _inline("5", "", unit_xml="", unit_ref="usd", scale="")
    assert _revenues(text) == []
    instance = """<?xml version="1.0" encoding="utf-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:us-gaap="http://fasb.org/us-gaap/2026">
  <context id="c">
    <entity><identifier scheme="http://www.sec.gov/CIK">0000000001</identifier></entity>
    <period><startDate>2024-01-01</startDate><endDate>2024-12-31</endDate></period>
  </context>
  <us-gaap:Revenues contextRef="c" unitRef="usd" decimals="0">5</us-gaap:Revenues>
</xbrl>
"""
    parsed = parse_inline(instance, "instance.xml", URL, "abc")
    assert [fact for fact in parsed.facts if fact.role == "revenue"] == []


def test_sic_code_must_be_ascii_digits() -> None:
    assert sic_title("3571") == "ELECTRONIC COMPUTERS"
    assert sic_title("３５７１") is None
    assert sic_title("٣٥٧١") is None
    source = "https://data.sec.gov/submissions/CIK0000000001.json"
    assert accepted_sector({"code": "3571", "source": source}, "1") is not None
    assert accepted_sector({"code": "３５７１", "source": source}, "1") is None
    assert accepted_sector({"code": "٣٥٧١", "source": source}, "1") is None


def test_inline_document_with_an_early_xbrli_tag_keeps_the_comma_fact(tmp_path: Path) -> None:
    text = _inline("5,000", "ixt:num-dot-decimal", pad=True)
    assert "<xbrli:" in text[:800]
    assert "nonfraction" not in text[:800].lower()
    directory = write_filing(tmp_path / "inline", "inline.htm", text, URL, form="10-Q")
    explained = explain_filing(load_directory(directory))
    assert "5000 USD millions" in explained.markdown
    assert "Revenue" in explained.markdown


def test_inline_dot_decimal_keeps_the_decimal_point(tmp_path: Path) -> None:
    text = _inline("5.000", "ixt:num-dot-decimal", pad=True)
    directory = write_filing(tmp_path / "dots", "inline.htm", text, URL, form="10-Q")
    explained = explain_filing(load_directory(directory))
    assert "5 USD millions" in explained.markdown
    assert "5000 USD millions" not in explained.markdown


def test_a_traversal_accession_is_refused(tmp_path: Path) -> None:
    from white_cliff.sitebuild import build_site

    pinned = tmp_path / "pinned"
    (pinned / "filings").mkdir(parents=True)
    manifest = {
        "filings": [
            {
                "accession": "../outside",
                "cik": "0000000001",
                "form": "10-K",
            }
        ]
    }
    (pinned / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(OutputRefused):
        build_site(tmp_path / "site", pinned)
    assert not (tmp_path / "outside").exists()
    site = tmp_path / "site"
    if site.exists():
        assert list(site.rglob("*")) == []
