"""Inline facts only, from the live elements of a primary 10-K or 10-Q."""

import html as html_lib
import json
import re
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from white_cliff.disclaimer import DISCLAIMER, ISSUE_URL
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.sitebuild import build_site
from tests.support import write_filing

SEC = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/primary.htm"
EXHIBIT = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/exhibit.htm"
SENTENCE = "This filing has no tagged figures that White Cliff can explain."
NOT_EDGAR = "This filing was not retrieved from EDGAR."
RECORD = "https://data.sec.gov/submissions/CIK0000000001.json"
PINNED = Path(__file__).resolve().parents[1] / "pinned" / "filings"


def _page(body: str, *, contexts: str = "", units: str = "", name: str = "Example Co") -> str:
    unit_xml = units or '<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
    context_xml = contexts or """
<xbrli:context id="c-year">
  <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period>
</xbrli:context>
"""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2026"
      xmlns:dei="http://xbrl.sec.gov/dei/2026">
<body>
{context_xml}
{unit_xml}
<ix:nonNumeric name="dei:DocumentType" contextRef="c-year">10-K</ix:nonNumeric>
<ix:nonNumeric name="dei:EntityRegistrantName" contextRef="c-year">{name}</ix:nonNumeric>
<ix:nonNumeric name="dei:DocumentFiscalPeriodFocus" contextRef="c-year">FY</ix:nonNumeric>
<ix:nonNumeric name="dei:DocumentPeriodEndDate" contextRef="c-year">2024-12-31</ix:nonNumeric>
<ix:nonNumeric name="dei:EntityCentralIndexKey" contextRef="c-year">0000000001</ix:nonNumeric>
{body}
</body>
</html>
"""


def _revenue(text: str, **attrs: str) -> str:
    fields = {"contextRef": "c-year", "unitRef": "usd", "decimals": "0"}
    fields.update(attrs)
    extra = "".join(f' {key}="{value}"' for key, value in fields.items())
    return f'<ix:nonFraction name="us-gaap:Revenues"{extra}>{text}</ix:nonFraction>'


def _load(tmp_path: Path, xml: str, url: str = SEC, form: str = "10-K"):
    directory = write_filing(tmp_path / "case", "primary.htm", xml, url, form=form)
    return explain_filing(load_directory(directory)), xml


def _rendered(explained) -> str:
    return explained.markdown + "\n" + explained.html


def test_a_fact_inside_a_comment_is_ignored(tmp_path: Path) -> None:
    xml = _page(
        "<!-- <ix:nonFraction name=\"us-gaap:Revenues\" contextRef=\"c-year\" "
        "unitRef=\"usd\" decimals=\"0\">9999</ix:nonFraction> -->"
        + _revenue("5000")
    )
    explained, _xml = _load(tmp_path, xml)
    rendered = _rendered(explained)
    assert "9999" not in rendered
    assert "5000 USD" in explained.markdown


def test_a_fact_inside_cdata_is_ignored(tmp_path: Path) -> None:
    xml = _page(
        "<![CDATA[<ix:nonFraction name=\"us-gaap:Revenues\" contextRef=\"c-year\" "
        "unitRef=\"usd\" decimals=\"0\">9999</ix:nonFraction>]]>"
        + _revenue("5000")
    )
    explained, _xml = _load(tmp_path, xml)
    rendered = _rendered(explained)
    assert "9999" not in rendered
    assert "5000 USD" in explained.markdown


def test_a_commented_out_ix_element_is_ignored(tmp_path: Path) -> None:
    xml = _page(
        "<!-- <ix:nonFraction name=\"us-gaap:NetIncomeLoss\" contextRef=\"c-year\" "
        "unitRef=\"usd\" decimals=\"0\" scale=\"6\">9999</ix:nonFraction> -->"
        + _revenue("5000")
    )
    explained, _xml = _load(tmp_path, xml)
    rendered = _rendered(explained)
    assert "9999" not in rendered
    assert "5000 USD" in explained.markdown


def test_format_scale_and_nil_come_from_the_same_element(tmp_path: Path) -> None:
    xml = _page(
        "<!-- <ix:nonFraction name=\"us-gaap:Revenues\" contextRef=\"c-year\" unitRef=\"usd\" "
        "format=\"ixt:num-dot-decimal\" scale=\"6\" decimals=\"-6\">5,000</ix:nonFraction> -->"
        '<ix:nonFraction name="us-gaap:Revenues" contextRef="c-year" unitRef="usd" '
        'format="ixt:num-dot-decimal" scale="6" decimals="-6"/>'
        '<ix:nonFraction name="us-gaap:Revenues" contextRef="c-year" unitRef="usd" '
        'format="ixt:num-comma-decimal" scale="6" decimals="-6">5.000</ix:nonFraction>'
    )
    explained, _xml = _load(tmp_path, xml)
    rendered = _rendered(explained)
    assert "5 USD" not in rendered
    assert "5.000" not in rendered
    assert SENTENCE in explained.markdown


def test_scale_six_is_applied_to_the_printed_digits(tmp_path: Path) -> None:
    explained, _xml = _load(tmp_path, _page(_revenue("5000", scale="6", decimals="-6")))
    assert "5000 USD millions" in explained.markdown
    assert SENTENCE not in explained.markdown


def test_an_off_list_scale_is_refused(tmp_path: Path) -> None:
    explained, _xml = _load(tmp_path, _page(_revenue("5000", scale="4")))
    rendered = _rendered(explained)
    assert "5000" not in rendered
    assert SENTENCE in explained.markdown


def test_a_negative_sign_is_applied(tmp_path: Path) -> None:
    explained, _xml = _load(tmp_path, _page(_revenue("5000", sign="-")))
    assert "-5000 USD" in explained.markdown


def test_nil_with_text_is_refused(tmp_path: Path) -> None:
    xml = _page(
        '<ix:nonFraction name="us-gaap:Revenues" contextRef="c-year" unitRef="usd" '
        'decimals="0" xsi:nil="true">5000</ix:nonFraction>'
    )
    explained, _xml = _load(tmp_path, xml)
    rendered = _rendered(explained)
    assert "5000" not in rendered
    assert SENTENCE in explained.markdown


def test_disagreeing_duplicates_are_refused(tmp_path: Path) -> None:
    xml = _page(
        '<ix:nonFraction name="us-gaap:Revenues" contextRef="c-year" unitRef="usd" decimals="0">4</ix:nonFraction>'
        '<ix:nonFraction name="us-gaap:Revenues" contextRef="c-year" unitRef="usd" decimals="-3">5000</ix:nonFraction>'
    )
    explained, _xml = _load(tmp_path, xml)
    rendered = _rendered(explained)
    assert "4 USD" not in rendered
    assert "5000" not in rendered


def test_disagreeing_scaled_duplicates_are_refused(tmp_path: Path) -> None:
    xml = _page(
        '<ix:nonFraction name="us-gaap:Revenues" contextRef="c-year" unitRef="usd" '
        'scale="3" decimals="-3" format="ixt:num-dot-decimal">9000000</ix:nonFraction>'
        '<ix:nonFraction name="us-gaap:Revenues" contextRef="c-year" unitRef="usd" '
        'scale="6" decimals="-6" format="ixt:num-dot-decimal">5,000</ix:nonFraction>'
    )
    explained, _xml = _load(tmp_path, xml)
    rendered = _rendered(explained)
    assert "9000000" not in rendered
    assert "5000 USD millions" not in rendered


def test_matching_scaled_duplicates_still_render(tmp_path: Path) -> None:
    xml = _page(
        '<ix:nonFraction name="us-gaap:Revenues" contextRef="c-year" unitRef="usd" '
        'scale="6" decimals="-6">5000</ix:nonFraction>'
        '<ix:nonFraction name="us-gaap:Revenues" contextRef="c-year" unitRef="usd" '
        'scale="0" decimals="0">5000000000</ix:nonFraction>'
    )
    explained, _xml = _load(tmp_path, xml)
    rendered = explained.markdown
    assert SENTENCE not in rendered
    assert "5000 USD millions" in rendered or "5000000000 USD" in rendered


def test_a_segment_of_any_kind_refuses_the_context(tmp_path: Path) -> None:
    contexts = """
<xbrli:context id="c-year">
  <xbrli:entity>
    <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
    <xbrli:segment><xbrldi:otherMember>other</xbrldi:otherMember></xbrli:segment>
  </xbrli:entity>
  <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period>
</xbrli:context>
"""
    explained, _xml = _load(tmp_path, _page(_revenue("5000"), contexts=contexts))
    assert "5000" not in _rendered(explained)


def test_a_context_for_another_cik_is_refused(tmp_path: Path) -> None:
    contexts = """
<xbrli:context id="c-year">
  <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:context id="c-other">
  <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000002</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period>
</xbrli:context>
"""
    body = (
        '<ix:nonFraction name="us-gaap:NetIncomeLoss" contextRef="c-other" '
        'unitRef="usd" decimals="0">7777</ix:nonFraction>'
        + _revenue("5000")
    )
    explained, _xml = _load(tmp_path, _page(body, contexts=contexts))
    rendered = _rendered(explained)
    assert "7777" not in rendered
    assert "5000 USD" in explained.markdown


def test_a_duplicate_context_id_refuses_its_facts(tmp_path: Path) -> None:
    contexts = """
<xbrli:context id="c-year">
  <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:context id="c-year">
  <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period>
</xbrli:context>
"""
    explained, _xml = _load(tmp_path, _page(_revenue("5000"), contexts=contexts))
    assert "5000" not in _rendered(explained)


def test_a_duration_that_does_not_move_forward_is_refused(tmp_path: Path) -> None:
    contexts = """
<xbrli:context id="c-year">
  <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2024-12-31</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period>
</xbrli:context>
"""
    explained, _xml = _load(tmp_path, _page(_revenue("5000"), contexts=contexts))
    assert "5000" not in _rendered(explained)


def _index_for(tmp_path: Path, name: str) -> tuple[str, str]:
    xml = _page(_revenue("5000"), name=name)
    pinned = tmp_path / "pinned"
    accession = "0000000001-26-000099"
    directory = pinned / "filings" / accession
    directory.mkdir(parents=True)
    data = xml.encode("utf-8")
    (directory / "primary.htm").write_bytes(data)
    provenance = {
        "filer": name,
        "form": "10-K",
        "cik": "0000000001",
        "files": [
            {
                "name": "primary.htm",
                "url": SEC,
                "sha256": sha256(data).hexdigest(),
                "retrieved_at": "2026-11-18T04:23:53Z",
                "document_type": "10-K",
            }
        ],
    }
    (directory / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    manifest = {
        "filings": [
            {
                "accession": accession,
                "cik": "0000000001",
                "filer": name,
                "form": "10-K",
                "sic": {
                    "code": "3571",
                    "description": "ELECTRONIC COMPUTERS",
                    "source": RECORD,
                },
            }
        ]
    }
    (pinned / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    site = build_site(tmp_path / "site", pinned)
    page = (site / f"{accession}.html").read_text(encoding="utf-8")
    index = (site / "index.html").read_text(encoding="utf-8")
    return page, index


def test_a_digit_in_the_registrant_name_links_the_filer(tmp_path: Path) -> None:
    page, index = _index_for(tmp_path, "Revenue 99999 USD millions")
    for surface in (page, index):
        assert "the filer" in surface
        assert RECORD in surface
        assert "Revenue 99999 USD millions" not in surface
    assert 'class="registrant-chip"' in page
    assert 'title="Filer on EDGAR"' in page
    assert SENTENCE not in page


def test_a_unit_word_in_the_registrant_name_links_the_filer(tmp_path: Path) -> None:
    page, index = _index_for(tmp_path, "Dollar General")
    for surface in (page, index):
        assert "Dollar General" in surface
        assert "the filer" not in surface
    assert 'class="registrant-chip"' in page
    assert 'title="Registrant name in the filing"' in page


def test_file_and_javascript_urls_are_not_filing_links(tmp_path: Path) -> None:
    html = "<html><body><p>No tagged figures.</p></body></html>"
    for url in ("file:///tmp/filing.htm", "javascript:alert(1)"):
        directory = write_filing(tmp_path / "bad", "plain.htm", html, url, form="8-K")
        explained = explain_filing(load_directory(directory))
        rendered = _rendered(explained)
        assert url not in rendered
        assert "https://www.sec.gov/" not in rendered
        assert NOT_EDGAR in explained.markdown
        assert NOT_EDGAR in explained.html
        assert f"[Report an error]({ISSUE_URL})" in explained.markdown
        assert "Report an error: Report an error" not in explained.markdown
        assert f'<a href="{ISSUE_URL}">Report an error</a>' in explained.html


def test_entity_names_render_decoded_and_point_at_the_raw_span(tmp_path: Path) -> None:
    for encoded, shown in (("AT&amp;T Inc.", "AT&T Inc."), ("Johnson &amp; Johnson", "Johnson & Johnson")):
        xml = _page(_revenue("5000"), name=encoded)
        explained, source = _load(tmp_path, xml)
        match = re.search(r'class="registrant-chip"[^>]*href="([^"]+)"[^>]*>([^<]*)</a>', explained.html)
        assert match, explained.html
        assert html_lib.unescape(match.group(2)) == shown
        fragment = urlsplit(html_lib.unescape(match.group(1))).fragment
        parts = dict(piece.split("=", 1) for piece in fragment.split("&"))
        start, end = int(parts["registrant"]), int(parts["end"])
        assert html_lib.unescape(source[start:end]) == shown
        assert source[start:end] == encoded


def test_an_exhibit_is_not_joined_onto_the_primary_document(tmp_path: Path) -> None:
    primary = _page(_revenue("5000"))
    exhibit = _page(
        '<ix:nonFraction name="us-gaap:NetIncomeLoss" contextRef="c-year" unitRef="usd" decimals="0">8888</ix:nonFraction>'
        + _revenue("5000"),
        name="Example Co",
    )
    directory = tmp_path / "multi"
    directory.mkdir()
    primary_bytes = primary.encode("utf-8")
    exhibit_bytes = exhibit.encode("utf-8")
    (directory / "primary.htm").write_bytes(primary_bytes)
    (directory / "exhibit.htm").write_bytes(exhibit_bytes)
    provenance = {
        "filer": "Example Co",
        "form": "10-K",
        "cik": "0000000001",
        "files": [
            {
                "name": "primary.htm",
                "url": SEC,
                "sha256": sha256(primary_bytes).hexdigest(),
                "retrieved_at": "2026-11-18T04:23:53Z",
                "document_type": "10-K",
            },
            {
                "name": "exhibit.htm",
                "url": EXHIBIT,
                "sha256": sha256(exhibit_bytes).hexdigest(),
                "retrieved_at": "2026-11-18T04:23:53Z",
                "document_type": "EX-99.1",
            },
        ],
    }
    (directory / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    filing = load_directory(directory)
    explained = explain_filing(filing)
    rendered = _rendered(explained)
    assert "8888" not in rendered
    assert "5000 USD" in explained.markdown
    hrefs = re.findall(r'href="([^"]+)"', explained.html)
    source_hrefs = [html_lib.unescape(href) for href in hrefs if "fact=" in href or "registrant=" in href]
    assert source_hrefs
    for href in source_hrefs:
        assert href.startswith(SEC)
        assert "exhibit.htm" not in href
    assert filing.url == SEC
    for fact in filing.store.facts():
        assert fact.source.url == SEC
        assert fact.source.document == "primary.htm"


def test_pinned_primary_links_do_not_point_at_the_exhibit() -> None:
    accession = "0000320193-26-000026"
    directory = PINNED / accession
    provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
    primary = next(item for item in provenance["files"] if item.get("document_type") == "10-K")
    exhibit = next(item for item in provenance["files"] if item["name"] != primary["name"])
    filing = load_directory(directory)
    explained = explain_filing(filing)
    hrefs = re.findall(r'href="([^"]+)"', explained.html)
    source_hrefs = [
        html_lib.unescape(href)
        for href in hrefs
        if "fact=" in href or "registrant=" in href or "calc=" in href
    ]
    assert source_hrefs
    for href in source_hrefs:
        assert href.startswith(primary["url"])
        assert exhibit["name"] not in href
        assert "index" not in urlsplit(href).path
    assert filing.url == primary["url"]
