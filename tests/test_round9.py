"""Directory CIK, duplicate periods, live facts, and the name rule."""

import json
import shutil
from hashlib import sha256
from pathlib import Path

from white_cliff.disclaimer import ISSUE_URL
from white_cliff.fetch import EdgarClient
from white_cliff.pipeline import explain_filing, load_directory
from tests.support import write_filing

PINNED = Path(__file__).resolve().parents[1] / "pinned" / "filings"
SEC = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/primary.htm"
SENTENCE = "This filing has no tagged figures that White Cliff can explain."
NOT_EDGAR = "This filing was not retrieved from EDGAR."
CANNOT_USE = "The share count is tagged but White Cliff can't use it [section:Equity]."
UNTAGGED = "The filing doesn't tag the share count [section:Equity]."
UA = "Example Name name@example.com"


def _page(
    body: str,
    *,
    contexts: str = "",
    units: str = "",
    name: str | None = "Example Co",
    dei: str | None = "0000000001",
    form: str = "10-K",
    focus: str = "FY",
    period_end: str = "2024-12-31",
) -> str:
    unit_xml = units or '<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
    context_xml = contexts or """
<xbrli:context id="c-year">
  <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period>
</xbrli:context>
"""
    name_xml = ""
    if name is not None:
        name_xml = (
            f'<ix:nonNumeric name="dei:EntityRegistrantName" contextRef="c-year">{name}</ix:nonNumeric>'
        )
    dei_xml = ""
    if dei is not None:
        dei_xml = (
            f'<ix:nonNumeric name="dei:EntityCentralIndexKey" contextRef="c-year">{dei}</ix:nonNumeric>'
        )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:us-gaap="http://fasb.org/us-gaap/2026"
      xmlns:dei="http://xbrl.sec.gov/dei/2026">
<body>
{context_xml}
{unit_xml}
<ix:nonNumeric name="dei:DocumentType" contextRef="c-year">{form}</ix:nonNumeric>
{name_xml}
<ix:nonNumeric name="dei:DocumentFiscalPeriodFocus" contextRef="c-year">{focus}</ix:nonNumeric>
<ix:nonNumeric name="dei:DocumentPeriodEndDate" contextRef="c-year">{period_end}</ix:nonNumeric>
{dei_xml}
{body}
</body>
</html>
"""


def _revenue(text: str, **attrs: str) -> str:
    fields = {"contextRef": "c-year", "unitRef": "usd", "decimals": "0"}
    fields.update(attrs)
    extra = "".join(f' {key}="{value}"' for key, value in fields.items())
    return f'<ix:nonFraction name="us-gaap:Revenues"{extra}>{text}</ix:nonFraction>'


def _explain(tmp_path: Path, xml: str, url: str = SEC, form: str = "10-K", cik: str = "0000000001"):
    directory = write_filing(tmp_path / "case", "primary.htm", xml, url, form=form)
    provenance_path = directory / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["cik"] = cik
    provenance["files"][0]["document_type"] = form
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    return explain_filing(load_directory(directory))


def _year(context_id: str, start: str, end: str = "2024-12-31", cik: str = "0000000001") -> str:
    return f"""
<xbrli:context id="{context_id}">
  <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">{cik}</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period>
</xbrli:context>
"""


def test_same_period_copies_under_different_context_ids_must_agree(tmp_path: Path) -> None:
    contexts = _year("c-year", "2024-01-01") + _year("c-year-b", "2024-01-01")
    body = (
        _revenue("5,000", contextRef="c-year", scale="6", decimals="-6", format="ixt:num-dot-decimal")
        + _revenue(
            "9,000,000",
            contextRef="c-year-b",
            scale="3",
            decimals="-3",
            format="ixt:num-dot-decimal",
        )
    )
    explained = _explain(tmp_path, _page(body, contexts=contexts))
    rendered = explained.markdown + explained.html
    assert "9000000 USD thousands" not in rendered
    assert "5000 USD millions" not in rendered


def test_a_precise_copy_and_a_rounded_copy_of_the_same_fact_still_show(tmp_path: Path) -> None:
    contexts = _year("c-year", "2024-01-01") + _year("c-year-b", "2024-01-01")
    body = (
        _revenue("5,000", contextRef="c-year", scale="6", decimals="-6", format="ixt:num-dot-decimal")
        + _revenue(
            "5,000,400",
            contextRef="c-year-b",
            scale="3",
            decimals="-3",
            format="ixt:num-dot-decimal",
        )
    )
    explained = _explain(tmp_path, _page(body, contexts=contexts))
    assert "5000400 USD thousands" in explained.markdown
    assert SENTENCE not in explained.markdown


def test_a_small_copy_does_not_replace_a_scaled_copy(tmp_path: Path) -> None:
    contexts = _year("c-year", "2024-01-01") + _year("c-year-b", "2024-01-01")
    body = (
        _revenue(
            "5,000",
            contextRef="c-year",
            scale="6",
            decimals="-6",
            format="ixt:num-dot-decimal",
        )
        + _revenue("4", contextRef="c-year-b", decimals="0")
    )
    explained = _explain(tmp_path, _page(body, contexts=contexts))
    rendered = explained.markdown + explained.html
    assert "4 USD" not in rendered
    assert "5000 USD millions" not in rendered


def test_two_fiscal_years_with_the_same_end_are_refused(tmp_path: Path) -> None:
    contexts = _year("c-year", "2024-01-01") + _year("c-year-b", "2023-12-27")
    body = _revenue("5000", contextRef="c-year") + _revenue("5000", contextRef="c-year-b")
    explained = _explain(tmp_path, _page(body, contexts=contexts))
    rendered = explained.markdown + explained.html
    assert "5000 USD" not in rendered


def test_microsoft_uses_the_directory_cik_and_refuses_a_word_period_end() -> None:
    directory = PINNED / "0001193125-26-436133"
    provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
    url = provenance["files"][0]["url"]
    assert "/Archives/edgar/data/789019/000119312526436133/" in url
    assert provenance["cik"] == "0000789019"
    assert provenance["accession"].split("-")[0] != provenance["cik"]
    filing = load_directory(directory)
    assert filing.period_end is None
    explained = explain_filing(filing)
    rendered = explained.markdown + explained.html
    assert "92279" not in rendered
    assert SENTENCE not in explained.markdown
    assert "/Archives/edgar/data/789019/" in rendered
    assert "/Archives/edgar/data/1193125/" not in rendered
    assert "CIK0001193125" not in rendered


def test_pinned_provenance_cik_matches_the_edgar_directory() -> None:
    checked = 0
    for provenance_path in sorted(PINNED.glob("*/provenance.json")):
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        prefix = str(provenance["accession"]).split("-")[0]
        recorded = str(provenance["cik"]).zfill(10)
        for item in provenance["files"]:
            url = item["url"]
            assert "/Archives/edgar/data/" in url
            parts = url.split("/Archives/edgar/data/", 1)[1].split("/")
            assert recorded == parts[0].zfill(10)
            assert parts[1] == str(provenance["accession"]).replace("-", "")
            checked += 1
        if prefix != recorded:
            assert recorded != prefix
    assert checked >= 8


def _mutated_microsoft(tmp_path: Path, new_cik: str):
    source = PINNED / "0001193125-26-436133"
    provenance = json.loads((source / "provenance.json").read_text(encoding="utf-8"))
    directory = tmp_path / new_cik
    directory.mkdir()
    name = provenance["files"][0]["name"]
    text = (source / name).read_text(encoding="utf-8").replace("0000789019", new_cik)
    data = text.encode("utf-8")
    (directory / name).write_bytes(data)
    files = [dict(provenance["files"][0])]
    files[0]["sha256"] = sha256(data).hexdigest()
    rewritten = dict(provenance)
    rewritten["files"] = files
    (directory / "provenance.json").write_text(json.dumps(rewritten), encoding="utf-8")
    return explain_filing(load_directory(directory))


def test_microsoft_contexts_changed_to_the_agent_or_another_filer_are_refused(tmp_path: Path) -> None:
    for new_cik in ("0001193125", "0000320193"):
        explained = _mutated_microsoft(tmp_path, new_cik)
        rendered = explained.markdown + explained.html
        assert SENTENCE in explained.markdown
        assert "92279" not in rendered


def test_contexts_for_cik_99_under_data_1_are_refused(tmp_path: Path) -> None:
    contexts = _year("c-year", "2024-01-01", cik="0000000099")
    xml = _page(_revenue("5000"), contexts=contexts, dei="0000000099", name=None)
    explained = _explain(tmp_path, xml)
    rendered = explained.markdown + explained.html
    assert SENTENCE in explained.markdown
    assert "5000" not in rendered


def test_a_context_without_a_dei_cik_or_a_name_is_refused(tmp_path: Path) -> None:
    contexts = _year("c-year", "2024-01-01", cik="0000000099")
    xml = _page(_revenue("5000"), contexts=contexts, dei=None, name=None)
    explained = _explain(tmp_path, xml)
    assert "5000" not in explained.markdown
    assert SENTENCE in explained.markdown


def test_a_document_with_no_company_id_is_refused(tmp_path: Path) -> None:
    contexts = """
<xbrli:context id="c-year">
  <xbrli:entity></xbrli:entity>
  <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period>
</xbrli:context>
"""
    xml = _page(_revenue("5000"), contexts=contexts, dei=None, name=None)
    explained = _explain(tmp_path, xml)
    assert "5000" not in explained.markdown
    assert SENTENCE in explained.markdown


def test_an_impossible_date_and_an_unpadded_date_refuse_that_context(tmp_path: Path) -> None:
    bad_end = _year("c-bad", "2024-01-01", end="2024-02-30") + _year("c-year", "2023-01-01", end="2023-12-31")
    body = _revenue("1111", contextRef="c-bad") + _revenue("5000")
    explained = _explain(tmp_path, _page(body, contexts=bad_end, period_end="2023-12-31"))
    rendered = explained.markdown + explained.html
    assert "1111" not in rendered
    assert "5000 USD" in explained.markdown

    unpadded = _year("c-year", "2024-1-01", end="2024-12-31")
    explained = _explain(tmp_path, _page(_revenue("2222"), contexts=unpadded))
    assert "2222" not in explained.markdown
    assert SENTENCE in explained.markdown


def test_a_registrant_name_is_kept_unless_a_digit_shares_a_run_with_a_unit_word(tmp_path: Path) -> None:
    shown = (
        "3M Company",
        "7-Eleven Inc",
        "Dollar General Corporation",
        "Thousand Oaks Bancorp",
        "Acme Shares Trust",
        "Lowe\u2019s Companies, Inc.",
    )
    for name in shown:
        explained = _explain(tmp_path, _page(_revenue("5000"), name=name))
        assert name in explained.html
        assert 'title="Registrant name in the filing"' in explained.html
        assert 'title="Filer on EDGAR"' not in explained.html
    refused = (
        "Revenue 99999 USD millions",
        "Acme 500 Million Dollars Inc",
        "Acme 5 EUR Inc",
    )
    record = "https://data.sec.gov/submissions/CIK0000000001.json"
    for name in refused:
        explained = _explain(tmp_path, _page(_revenue("5000"), name=name))
        assert name not in explained.html
        assert ">the filer</a>" in explained.html
        assert 'title="Filer on EDGAR"' in explained.html
        assert record in explained.html


def test_the_refusal_page_says_report_an_error_once(tmp_path: Path) -> None:
    html = "<html><body><p>No figures.</p></body></html>"
    directory = write_filing(tmp_path / "plain", "plain.htm", html, SEC, form="8-K")
    explained = explain_filing(load_directory(directory))
    assert explained.markdown.count("Report an error") == 1
    assert "Report an error: Report an error" not in explained.markdown
    assert f"[Report an error]({ISSUE_URL})" in explained.markdown
    assert explained.html.count("Report an error") == 1


def test_a_filing_address_with_a_space_or_quote_is_not_linked(tmp_path: Path) -> None:
    html = "<html><body><p>No figures.</p></body></html>"
    urls = (
        "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/bad file.htm",
        'https://www.sec.gov/Archives/edgar/data/1/000000000100000001/bad"file.htm',
    )
    for url in urls:
        directory = write_filing(tmp_path / "bad", "plain.htm", html, url, form="8-K")
        explained = explain_filing(load_directory(directory))
        rendered = explained.markdown + explained.html
        assert url not in rendered
        assert NOT_EDGAR in explained.markdown
        assert f'href="{url}"' not in explained.html


def test_fetch_takes_the_primary_document_and_the_directory_cik(tmp_path: Path) -> None:
    accession = "0001193125-26-436133"
    primary = "msft-20260930.htm"
    index = """<html><body><table>
<tr><td>1</td><td>10-Q</td><td><a href="msft-20260930.htm">msft-20260930.htm</a></td><td>10-Q</td><td>10</td></tr>
<tr><td>2</td><td>EX-99.1</td><td><a href="ex99.htm">ex99.htm</a></td><td>EX-99.1</td><td>10</td></tr>
<tr><td>3</td><td>XML</td><td><a href="msft_htm.xml">msft_htm.xml</a></td><td>XML</td><td>10</td></tr>
</table></body></html>""".encode()
    body = b"<html>primary</html>"
    seen: list[str] = []

    def transport(url, user_agent):
        assert user_agent == UA
        seen.append(url)
        if url.endswith("-index.html"):
            return 200, index, {}
        if url.endswith("/" + primary):
            return 200, body, {}
        raise AssertionError(url)

    client = EdgarClient(UA, transport=transport, sleep=lambda _seconds: None, clock=lambda: 0.0)
    dest = tmp_path / "filing"
    client.fetch_accession(accession, dest, "789019")
    assert all("/Archives/edgar/data/789019/" in url for url in seen)
    assert all("/Archives/edgar/data/1193125/" not in url for url in seen)
    assert not any(url.endswith("_htm.xml") or url.endswith("ex99.htm") for url in seen)
    provenance = json.loads((dest / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["cik"] == "0000789019"
    assert provenance["form"] == "10-Q"
    assert provenance["files"][0]["name"] == primary
    assert provenance["files"][0]["document_type"] == "10-Q"
    assert provenance["files"][0]["sha256"] == sha256(body).hexdigest()
    assert "/Archives/edgar/data/789019/" in provenance["files"][0]["url"]


def test_a_nonfraction_inside_ix_hidden_is_refused(tmp_path: Path) -> None:
    body = (
        '<ix:hidden><ix:nonFraction name="us-gaap:Revenues" contextRef="c-year" '
        'unitRef="usd" decimals="0">9999</ix:nonFraction></ix:hidden>'
        + _revenue("5000")
    )
    explained = _explain(tmp_path, _page(body))
    rendered = explained.markdown + explained.html
    assert "9999" not in rendered
    assert "5000" not in rendered


def test_dei_inside_ix_hidden_still_identifies_the_filing(tmp_path: Path) -> None:
    xml = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:us-gaap="http://fasb.org/us-gaap/2026"
      xmlns:dei="http://xbrl.sec.gov/dei/2026">
<body>
<xbrli:context id="c-year">
  <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
<ix:hidden>
  <ix:nonNumeric name="dei:DocumentType" contextRef="c-year">10-K</ix:nonNumeric>
  <ix:nonNumeric name="dei:EntityCentralIndexKey" contextRef="c-year">0000000001</ix:nonNumeric>
  <ix:nonNumeric name="dei:DocumentFiscalPeriodFocus" contextRef="c-year">FY</ix:nonNumeric>
  <ix:nonNumeric name="dei:DocumentPeriodEndDate" contextRef="c-year">2024-12-31</ix:nonNumeric>
  <ix:nonNumeric name="dei:EntityRegistrantName" contextRef="c-year">Example Co</ix:nonNumeric>
</ix:hidden>
<ix:nonFraction name="us-gaap:Revenues" contextRef="c-year" unitRef="usd" decimals="0">5000</ix:nonFraction>
</body>
</html>
"""
    explained = _explain(tmp_path, xml)
    assert "5000 USD" in explained.markdown
    assert "Example Co" in explained.html


def test_a_minus_sign_in_the_fact_text_is_refused(tmp_path: Path) -> None:
    explained = _explain(tmp_path, _page(_revenue("-5000")))
    rendered = explained.markdown + explained.html
    assert "-5000" not in rendered
    assert "5000 USD" not in rendered
    assert SENTENCE in explained.markdown


def test_a_unit_outside_the_xbrli_namespace_is_refused(tmp_path: Path) -> None:
    units = '<foo:unit xmlns:foo="http://example.com" id="usd"><foo:measure>iso4217:USD</foo:measure></foo:unit>'
    explained = _explain(tmp_path, _page(_revenue("5000"), units=units))
    assert "5000" not in explained.markdown
    assert SENTENCE in explained.markdown


def test_two_files_claiming_the_primary_form_are_refused(tmp_path: Path) -> None:
    directory = tmp_path / "two"
    directory.mkdir()
    first = _page(_revenue("5000")).encode()
    second = _page(_revenue("7777")).encode()
    (directory / "one.htm").write_bytes(first)
    (directory / "two.htm").write_bytes(second)
    provenance = {
        "cik": "0000000001",
        "form": "10-K",
        "files": [
            {
                "name": "one.htm",
                "url": SEC,
                "sha256": sha256(first).hexdigest(),
                "document_type": "10-K",
            },
            {
                "name": "two.htm",
                "url": SEC.replace("primary.htm", "other.htm"),
                "sha256": sha256(second).hexdigest(),
                "document_type": "10-K",
            },
        ],
    }
    (directory / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    explained = explain_filing(load_directory(directory))
    rendered = explained.markdown + explained.html
    assert "5000" not in rendered
    assert "7777" not in rendered
    assert SENTENCE in explained.markdown


def test_a_tagged_share_count_that_cannot_be_used_says_so(tmp_path: Path) -> None:
    body = (
        _revenue("5000")
        + '<ix:hidden><ix:nonFraction name="us-gaap:CommonStockSharesOutstanding" '
        'contextRef="c-year" unitRef="usd" decimals="0">4242</ix:nonFraction></ix:hidden>'
    )
    explained = _explain(tmp_path, _page(body))
    assert CANNOT_USE.split(" [section:")[0] in explained.markdown
    assert "doesn't tag the share count" not in explained.markdown
    assert "4242" not in explained.markdown


def test_an_untagged_share_count_still_says_the_filing_does_not_tag_it(tmp_path: Path) -> None:
    explained = _explain(tmp_path, _page(_revenue("5000")))
    assert UNTAGGED.split(" [section:")[0] in explained.markdown
    assert "can't use it" not in explained.markdown


def test_pinned_filings_do_not_add_false_personal_data_notes() -> None:
    notes = 0
    for directory in sorted(path for path in PINNED.iterdir() if path.is_dir()):
        explained = explain_filing(load_directory(directory))
        notes += explained.markdown.count("personal data span")
    assert notes == 0


def test_explain_asks_for_the_filer_cik_and_not_the_accession_prefix(tmp_path, monkeypatch) -> None:
    from white_cliff import cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHITE_CLIFF_USER_AGENT", UA)
    seen: dict[str, str] = {}

    def lookup(self, accession):
        assert accession == "0001193125-26-436133"
        return "0000789019"

    def fetch(self, accession, dest, cik):
        seen["cik"] = cik
        dest.mkdir(parents=True, exist_ok=True)
        contexts = _year("c-year", "2024-01-01", cik="0000789019")
        xml = _page(_revenue("5000"), contexts=contexts, dei="0000789019")
        data = xml.encode()
        (dest / "primary.htm").write_bytes(data)
        url = "https://www.sec.gov/Archives/edgar/data/789019/000119312526436133/primary.htm"
        provenance = {
            "accession": accession,
            "cik": "0000789019",
            "form": "10-K",
            "files": [
                {
                    "name": "primary.htm",
                    "url": url,
                    "sha256": sha256(data).hexdigest(),
                    "document_type": "10-K",
                }
            ],
        }
        (dest / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
        return provenance["files"]

    monkeypatch.setattr(EdgarClient, "cik_for_accession", lookup)
    monkeypatch.setattr(EdgarClient, "fetch_accession", fetch)
    assert cli.main(["explain", "0001193125-26-436133"]) == 0
    assert seen["cik"] == "0000789019"
