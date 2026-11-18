"""XBRL-only figures, unit binding, and the untagged-filing page."""

import html as html_lib
import json
import re
from decimal import Decimal
from hashlib import sha256
from urllib.parse import urlsplit

from white_cliff.disclaimer import DISCLAIMER
from white_cliff.explain import Block
from white_cliff.facts import Fact, FactStore, Period, SourcePointer
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.render import render_html, render_markdown
from white_cliff.review import audit_rendered
from white_cliff.sitebuild import build_site
from tests.support import write_filing

URL = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/plain.htm"
SENTENCE = "This filing has no tagged figures that White Cliff can explain."
SEC = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/instance.xml"

_CONTEXT = """
  <context id="c-year">
    <entity><identifier scheme="http://www.sec.gov/CIK">0000000001</identifier></entity>
    <period><startDate>2024-01-01</startDate><endDate>2024-12-31</endDate></period>
  </context>
  <context id="c-end">
    <entity><identifier scheme="http://www.sec.gov/CIK">0000000001</identifier></entity>
    <period><instant>2024-12-31</instant></period>
  </context>
"""


def _xbrl(units: str, facts: str, extra_ns: str = "", root: str = "xbrl") -> str:
    open_tag = root if root == "xbrl" else root
    close_tag = root.split()[0]
    return f"""<?xml version="1.0" encoding="utf-8"?>
<{open_tag} xmlns="http://www.xbrl.org/2003/instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2026"
      xmlns:dei="http://xbrl.sec.gov/dei/2026"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"{extra_ns}>
{_CONTEXT}
  {units}
  <dei:EntityRegistrantName contextRef="c-year">Example Co</dei:EntityRegistrantName>
  <dei:DocumentType contextRef="c-year">10-K</dei:DocumentType>
  <dei:DocumentFiscalPeriodFocus contextRef="c-year">FY</dei:DocumentFiscalPeriodFocus>
  <dei:DocumentPeriodEndDate contextRef="c-year">2024-12-31</dei:DocumentPeriodEndDate>
  {facts}
</{close_tag}>
"""


def _load(tmp_path, xml: str, url: str = SEC):
    directory = write_filing(tmp_path / "case", "instance.xml", xml, url)
    return load_directory(directory)


def _roles(filing) -> set[str]:
    return {fact.role for fact in filing.store.facts()}


def test_untagged_filing_page_is_exact(tmp_path) -> None:
    html = "<html><body><p>Total net sales were 5,000.</p></body></html>"
    directory = write_filing(tmp_path / "plain", "plain.htm", html, URL, form="8-K")
    explained = explain_filing(load_directory(directory))
    assert explained.markdown == f"{DISCLAIMER}\n\n{SENTENCE} [the filing]({URL})\n"
    assert explained.html == (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        "<title>Filing explanation</title>\n"
        "</head>\n"
        "<body>\n"
        f'<p class="disclaimer">{DISCLAIMER}</p>\n'
        f"<p>{SENTENCE} "
        f'<a href="{URL}">the filing</a></p>\n'
        "</body>\n"
        "</html>\n"
    )
    assert audit_rendered(explained.markdown) is None
    assert audit_rendered(explained.html) is None
    assert "5,000" not in explained.markdown
    assert "5,000" not in explained.html


def test_revenue_on_a_shares_unit_is_refused(tmp_path) -> None:
    xml = _xbrl(
        '<unit id="sh"><measure>shares</measure></unit>',
        '<us-gaap:Revenues contextRef="c-year" unitRef="sh" decimals="0">5000</us-gaap:Revenues>',
    )
    filing = _load(tmp_path, xml)
    assert "revenue" not in _roles(filing)
    assert "5000" not in explain_filing(filing).markdown


def test_share_count_on_a_usd_unit_is_refused(tmp_path) -> None:
    xml = _xbrl(
        '<unit id="usd"><measure>iso4217:USD</measure></unit>',
        '<us-gaap:Revenues contextRef="c-year" unitRef="usd" decimals="0">5000</us-gaap:Revenues>'
        '<us-gaap:CommonStockSharesOutstanding contextRef="c-end" unitRef="usd" decimals="0">4242</us-gaap:CommonStockSharesOutstanding>',
    )
    filing = _load(tmp_path, xml)
    assert "shares" not in _roles(filing)
    assert "revenue" in _roles(filing)
    rendered = explain_filing(filing).markdown
    assert "4242" not in rendered
    assert "doesn't tag the share count" in rendered


def test_a_two_measure_unit_is_refused(tmp_path) -> None:
    xml = _xbrl(
        '<unit id="usd"><measure>iso4217:USD</measure><measure>xbrli:pure</measure></unit>',
        '<us-gaap:Revenues contextRef="c-year" unitRef="usd" decimals="0">5000</us-gaap:Revenues>',
        extra_ns=' xmlns:xbrli="http://www.xbrl.org/2003/instance"',
    )
    assert "revenue" not in _roles(_load(tmp_path, xml))


def test_usd_and_eur_together_are_refused(tmp_path) -> None:
    xml = _xbrl(
        '<unit id="usd"><measure>iso4217:USD</measure><measure>iso4217:EUR</measure></unit>',
        '<us-gaap:Revenues contextRef="c-year" unitRef="usd" decimals="0">5000</us-gaap:Revenues>',
    )
    assert "revenue" not in _roles(_load(tmp_path, xml))


def test_a_divide_unit_is_refused(tmp_path) -> None:
    xml = _xbrl(
        """<unit id="usd"><divide>
             <unitNumerator><measure>iso4217:USD</measure></unitNumerator>
             <unitDenominator><measure>shares</measure></unitDenominator>
           </divide></unit>""",
        '<us-gaap:Revenues contextRef="c-year" unitRef="usd" decimals="0">5000</us-gaap:Revenues>',
    )
    assert "revenue" not in _roles(_load(tmp_path, xml))


def test_iso4217_prefix_bound_to_another_namespace_is_refused(tmp_path) -> None:
    xml = _xbrl(
        '<unit id="usd"><measure>iso4217:USD</measure></unit>',
        '<us-gaap:Revenues contextRef="c-year" unitRef="usd" decimals="0">5000</us-gaap:Revenues>',
        extra_ns="",
    ).replace(
        'xmlns:iso4217="http://www.xbrl.org/2003/iso4217"',
        'xmlns:iso4217="http://example.com/not-iso4217"',
    )
    assert "revenue" not in _roles(_load(tmp_path, xml))


def test_bare_usd_is_refused(tmp_path) -> None:
    xml = _xbrl(
        '<unit id="usd"><measure>USD</measure></unit>',
        '<us-gaap:Revenues contextRef="c-year" unitRef="usd" decimals="0">5000</us-gaap:Revenues>',
    )
    assert "revenue" not in _roles(_load(tmp_path, xml))


def test_foo_usd_outside_iso4217_is_refused(tmp_path) -> None:
    xml = _xbrl(
        '<unit id="usd"><measure>foo:USD</measure></unit>',
        '<us-gaap:Revenues contextRef="c-year" unitRef="usd" decimals="0">5000</us-gaap:Revenues>',
        extra_ns=' xmlns:foo="http://example.com/currency"',
    )
    assert "revenue" not in _roles(_load(tmp_path, xml))


def test_a_duplicate_unit_id_refuses_every_fact_that_uses_it(tmp_path) -> None:
    xml = _xbrl(
        '<unit id="usd"><measure>iso4217:USD</measure></unit>'
        '<unit id="usd"><measure>iso4217:USD</measure></unit>'
        '<unit id="cash"><measure>iso4217:USD</measure></unit>',
        '<us-gaap:Revenues contextRef="c-year" unitRef="usd" decimals="0">5000</us-gaap:Revenues>'
        '<us-gaap:NetIncomeLoss contextRef="c-year" unitRef="usd" decimals="0">800</us-gaap:NetIncomeLoss>'
        '<us-gaap:CashAndCashEquivalentsAtCarryingValue contextRef="c-end" unitRef="cash" decimals="0">300</us-gaap:CashAndCashEquivalentsAtCarryingValue>',
    )
    filing = _load(tmp_path, xml)
    concepts = {fact.concept for fact in filing.store.facts()}
    assert "Revenues" not in concepts
    assert "NetIncomeLoss" not in concepts
    assert "CashAndCashEquivalentsAtCarryingValue" in concepts


def test_a_format_prefix_outside_an_ixt_namespace_is_refused(tmp_path) -> None:
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:foo="http://example.com/not-ixt"
      xmlns:us-gaap="http://fasb.org/us-gaap/2026">
<body>
<xbrli:context id="c">
  <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
<ix:nonFraction name="us-gaap:Revenues" contextRef="c" unitRef="usd" format="foo:num-dot-decimal" scale="6" decimals="-6">5,000</ix:nonFraction>
</body></html>
"""
    filing = _load(tmp_path, xml)
    assert "revenue" not in _roles(filing)


def test_a_concept_outside_the_money_and_share_lists_is_refused(tmp_path) -> None:
    xml = _xbrl(
        '<unit id="usd"><measure>iso4217:USD</measure></unit>',
        '<us-gaap:Assets contextRef="c-end" unitRef="usd" decimals="0">5000</us-gaap:Assets>',
    )
    filing = _load(tmp_path, xml)
    assert filing.store.facts() == []


def test_unicode_digits_are_refused(tmp_path) -> None:
    for digit in ("５", "٥"):
        xml = _xbrl(
            '<unit id="usd"><measure>iso4217:USD</measure></unit>',
            f'<us-gaap:Revenues contextRef="c-year" unitRef="usd" decimals="0">{digit}000</us-gaap:Revenues>',
        )
        filing = _load(tmp_path, xml)
        assert filing.store.facts() == []
        rendered = explain_filing(filing).markdown + explain_filing(filing).html
        assert digit not in rendered
        assert SENTENCE in rendered


def test_prefixed_instance_root_reads_concept_unit_and_scale(tmp_path) -> None:
    xml = _xbrl(
        '<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>',
        '<us-gaap:Revenues contextRef="c-year" unitRef="usd" decimals="0" scale="6">5000</us-gaap:Revenues>',
        root='xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"',
    )
    filing = _load(tmp_path, xml)
    revenue = [fact for fact in filing.store.facts() if fact.concept == "Revenues"]
    assert revenue and revenue[0].value == Decimal("5000")
    assert revenue[0].unit == "USD millions"
    rendered = explain_filing(filing).markdown
    assert "5000 USD millions" in rendered
    assert "nonFraction" not in rendered


def test_a_dropped_figure_drops_its_sentence() -> None:
    fact = Fact(
        id="factrevenue",
        concept="Revenues",
        label="Revenue",
        value=Decimal("5000"),
        unit="USD millions",
        period=Period("duration", "2024-01-01", "2024-12-31"),
        source=SourcePointer("filing.htm", "Income statement", "https://example.com/filing.htm", "abc", 10, 20),
        role="revenue",
    )
    store = FactStore()
    store.add(fact)
    blocks = [Block("Revenue for the fiscal year was {fact:factrevenue} [section:Income statement].")]
    html = render_html(blocks, store)
    markdown = render_markdown(blocks, store)
    for rendered in (html, markdown):
        assert "5000" not in rendered
        assert "Revenue for the fiscal year was" not in rendered
        assert "Section:" not in rendered
        assert "<p></p>" not in rendered
        for line in rendered.splitlines():
            assert "  " not in line
            assert "{fact:" not in line


def test_registrant_chip_points_at_the_xbrl_fact(tmp_path) -> None:
    xml = """<?xml version="1.0" encoding="utf-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2026"
      xmlns:dei="http://xbrl.sec.gov/dei/2026"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
  <context id="c-year">
    <entity><identifier scheme="http://www.sec.gov/CIK">0000000001</identifier></entity>
    <period><startDate>2024-01-01</startDate><endDate>2024-12-31</endDate></period>
  </context>
  <unit id="usd"><measure>iso4217:USD</measure></unit>
  <dei:DocumentType contextRef="c-year">Example Co</dei:DocumentType>
  <dei:EntityRegistrantName contextRef="c-year">Example Co</dei:EntityRegistrantName>
  <dei:DocumentFiscalPeriodFocus contextRef="c-year">FY</dei:DocumentFiscalPeriodFocus>
  <dei:DocumentPeriodEndDate contextRef="c-year">2024-12-31</dei:DocumentPeriodEndDate>
  <us-gaap:Revenues contextRef="c-year" unitRef="usd" decimals="0">5000</us-gaap:Revenues>
</xbrl>
"""
    filing = _load(tmp_path, xml)
    explained = explain_filing(filing)
    match = re.search(r'class="registrant-chip"[^>]*href="([^"]+)"', explained.html)
    assert match, explained.html
    fragment = urlsplit(html_lib.unescape(match.group(1))).fragment
    parts = dict(piece.split("=", 1) for piece in fragment.split("&"))
    start, end = int(parts["registrant"]), int(parts["end"])
    assert xml[start:end] == "Example Co"
    assert start > xml.index("EntityRegistrantName")
    assert xml.rfind("Example Co", 0, start) > 0


def test_registrant_shape_rule_still_chooses_the_chip_or_the_filer(tmp_path) -> None:
    def rendered(name: str) -> str:
        xml = _xbrl(
            '<unit id="usd"><measure>iso4217:USD</measure></unit>',
            "<us-gaap:Revenues contextRef=\"c-year\" unitRef=\"usd\" decimals=\"0\">5000</us-gaap:Revenues>",
        ).replace(
            "<dei:EntityRegistrantName contextRef=\"c-year\">Example Co</dei:EntityRegistrantName>",
            f"<dei:EntityRegistrantName contextRef=\"c-year\">{name}</dei:EntityRegistrantName>",
        )
        explained = explain_filing(_load(tmp_path, xml))
        return explained.markdown + explained.html

    shown = rendered("Best Buy Co., Inc.")
    assert "Best Buy Co., Inc." in shown
    assert "registrant-chip" in shown
    assert "PEG Inc" in rendered("PEG Inc")
    assert "Twelve Inc" in rendered("Twelve Inc")
    lowes = rendered("Lowe's Companies")
    assert "Lowe's" in lowes
    assert "&#x27;" not in lowes

    for name in ("Best **Buy**", "Best\nBuy", "A" * 101, "Buy [now](https://example.com)"):
        page = rendered(name)
        assert "the filer" in page
        assert name not in page
        assert "example.com" not in page


def test_index_registrant_matches_the_filing_page(tmp_path) -> None:
    pinned = tmp_path / "pinned"
    filings = pinned / "filings"

    def add(accession: str, xml: str) -> None:
        directory = filings / accession
        directory.mkdir(parents=True)
        data = xml.encode("utf-8")
        (directory / "instance.xml").write_bytes(data)
        provenance = {
            "filer": "Manifest Only Name",
            "form": "10-K",
            "files": [
                {
                    "name": "instance.xml",
                    "url": SEC,
                    "sha256": sha256(data).hexdigest(),
                    "retrieved_at": "2026-11-18T00:13:08Z",
                }
            ],
        }
        (directory / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")

    named = _xbrl(
        '<unit id="usd"><measure>iso4217:USD</measure></unit>',
        '<us-gaap:Revenues contextRef="c-year" unitRef="usd" decimals="0">5000</us-gaap:Revenues>',
    )
    hidden = named.replace(">Example Co<", ">" + ("A" * 101) + "<")
    refused = _xbrl(
        '<unit id="usd"><measure>iso4217:USD</measure></unit>',
        '<dei:EntityRegistrantName contextRef="c-year">Example Co</dei:EntityRegistrantName>',
    )
    add("0000000001-26-000011", named)
    add("0000000001-26-000012", hidden)
    add("0000000001-26-000013", refused)
    manifest = {
        "filings": [
            {"accession": "0000000001-26-000011", "cik": "0000000001", "filer": "Manifest Only Name", "form": "10-K"},
            {"accession": "0000000001-26-000012", "cik": "0000000001", "filer": "Manifest Only Name", "form": "10-K"},
            {"accession": "0000000001-26-000013", "cik": "0000000001", "filer": "Manifest Only Name", "form": "10-K"},
        ]
    }
    (pinned / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    site = build_site(tmp_path / "site", pinned)
    index = (site / "index.html").read_text(encoding="utf-8")
    named_page = (site / "0000000001-26-000011.html").read_text(encoding="utf-8")
    hidden_page = (site / "0000000001-26-000012.html").read_text(encoding="utf-8")
    refused_page = (site / "0000000001-26-000013.html").read_text(encoding="utf-8")
    assert "Example Co" in named_page and "Example Co" in index
    assert "Manifest Only Name" not in index
    assert "the filer" in hidden_page
    assert "A" * 101 not in hidden_page
    assert "A" * 101 not in index
    assert SENTENCE in refused_page
    assert "Example Co" not in refused_page
    items = re.findall(r"<li>.*?</li>", index)
    assert len(items) == 3
    assert "Example Co" in items[0]
    assert "the filer" in items[1]
    assert "Example Co" not in items[1]
    assert "the filer" in items[2]
    assert "Example Co" not in items[2]
