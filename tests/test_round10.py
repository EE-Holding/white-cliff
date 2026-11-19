"""Hidden copies, EDGAR index links, name guard, and the second file hash."""

import json
from hashlib import sha256
from pathlib import Path

import pytest

from white_cliff.fetch import FetchError, directory_cik
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.redact import contains_personal
from tests.support import narrative_instance, write_filing
from tests.test_round9 import SEC, SENTENCE, _explain, _page, _revenue, _year

PINNED = Path(__file__).resolve().parents[1] / "pinned" / "filings"
INDEX = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "edgar" / "0001193125-26-436133-index.html"
FILER = (
    "Revenue 99999, USD millions",
    "5 trillion",
    "5 CAD",
    "99 JPY",
    "5 bn",
    "5 mln",
    "500 MM",
    "5 cents",
    "5 per share",
    "10 pct",
    "5USD",
    "USD5",
    "$5k",
)
VERBATIM = (
    "3M Company",
    "7-Eleven Inc",
    "Dollar General Corporation",
    "Thousand Oaks Bancorp",
    "Acme Shares Trust",
    "Revenue Five Hundred Euros Inc",
    "Lowe\u2019s",
    "5k Holdings",
)


def test_a_hidden_copy_that_disagrees_refuses_the_visible_figure(tmp_path: Path) -> None:
    body = (
        '<ix:hidden>' + _revenue("9,000", format="ixt:num-dot-decimal") + "</ix:hidden>"
        + _revenue("5,000", format="ixt:num-dot-decimal")
    )
    explained = _explain(tmp_path, _page(body))
    rendered = explained.markdown + explained.html
    assert "5000" not in rendered
    assert "9000" not in rendered
    assert "9,000" not in rendered


def test_a_display_none_copy_that_disagrees_refuses_the_visible_figure(tmp_path: Path) -> None:
    body = (
        '<div style="display:none">'
        + _revenue("9,000", format="ixt:num-dot-decimal")
        + "</div>"
        + _revenue("5,000", format="ixt:num-dot-decimal")
    )
    explained = _explain(tmp_path, _page(body))
    rendered = explained.markdown + explained.html
    assert "5000" not in rendered
    assert "9000" not in rendered


def test_a_hidden_copy_that_agrees_shows_the_visible_figure(tmp_path: Path) -> None:
    body = (
        '<ix:hidden>' + _revenue("5,000", format="ixt:num-dot-decimal") + "</ix:hidden>"
        + _revenue("5,000", format="ixt:num-dot-decimal")
    )
    explained = _explain(tmp_path, _page(body))
    assert "5000 USD" in explained.markdown
    assert explained.markdown.count("5000 USD") == 1


def test_a_figure_that_exists_only_hidden_is_not_shown(tmp_path: Path) -> None:
    body = '<ix:hidden>' + _revenue("9000") + "</ix:hidden>"
    explained = _explain(tmp_path, _page(body))
    rendered = explained.markdown + explained.html
    assert "9000" not in rendered


def test_a_figure_that_exists_only_in_display_none_is_not_shown(tmp_path: Path) -> None:
    body = '<div style="display: none">' + _revenue("9000") + "</div>"
    explained = _explain(tmp_path, _page(body))
    rendered = explained.markdown + explained.html
    assert "9000" not in rendered


def test_the_real_microsoft_index_link_is_the_primary_document(tmp_path: Path) -> None:
    from white_cliff.fetch import EdgarClient

    index = INDEX.read_bytes()
    accession = "0001193125-26-436133"
    primary = "msft-20260930.htm"
    body = b"<html><body>primary</body></html>"
    seen: list[str] = []

    def transport(url: str, _user_agent: str):
        seen.append(url)
        if url.endswith(f"/{accession}-index.html"):
            return 200, index, {}
        if url.endswith("/" + primary):
            return 200, body, {}
        raise AssertionError(url)

    client = EdgarClient("Example Name name@example.com", transport=transport, sleep=lambda _seconds: None)
    dest = tmp_path / "filing"
    client.fetch_accession(accession, dest, cik="789019")
    assert all("/Archives/edgar/data/789019/" in url for url in seen)
    assert all("/ix?doc=" not in url for url in seen)
    assert (dest / primary).read_bytes() == body
    provenance = json.loads((dest / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["cik"] == "0000789019"
    assert provenance["form"] == "10-Q"
    assert provenance["files"][0]["name"] == primary
    assert provenance["files"][0]["document_type"] == "10-Q"


def test_an_ix_doc_link_for_a_different_filer_is_refused() -> None:
    from white_cliff.fetch import _primary_documents

    html = INDEX.read_text(encoding="utf-8").replace(
        "/Archives/edgar/data/789019/000119312526436133/",
        "/Archives/edgar/data/320193/000119312526436133/",
    )
    with pytest.raises(FetchError):
        _primary_documents(html, cik="789019", accession="0001193125-26-436133")


def test_pinned_files_match_the_raw_hash_and_the_hash_without_the_trailing_script() -> None:
    from white_cliff.fetch import strip_edgar_script

    checked = 0
    for directory in sorted(path for path in PINNED.iterdir() if path.is_dir()):
        provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
        for item in provenance["files"]:
            raw = (directory / item["name"]).read_bytes()
            if item.get("tracked_sha256"):
                assert sha256(raw).hexdigest() == item["tracked_sha256"]
                assert sha256(raw).hexdigest() != item["sha256"]
            else:
                assert sha256(raw).hexdigest() == item["sha256"]
                assert sha256(strip_edgar_script(raw)).hexdigest() == item["content_sha256"]
            assert strip_edgar_script(raw) != raw
            checked += 1
    assert checked == 12


def test_a_cik_only_in_the_query_string_is_refused() -> None:
    query = (
        "https://www.sec.gov/ix?doc=/Archives/edgar/data/789019/"
        "000119312526436133/msft-20260930.htm"
    )
    path = (
        "https://www.sec.gov/Archives/edgar/data/789019/"
        "000119312526436133/msft-20260930.htm"
    )
    assert directory_cik(query) is None
    assert directory_cik(path) == "0000789019"


def test_a_word_date_with_no_format_is_refused(tmp_path: Path) -> None:
    contexts = _year("c-year", "2026-01-01", end="2026-09-30")
    explained = _explain(
        tmp_path,
        _page(_revenue("5000"), contexts=contexts, period_end="September 30, 2026"),
    )
    rendered = explained.markdown + explained.html
    assert "5000" not in rendered
    assert "2026-09-30" not in rendered


def test_the_real_apple_coca_cola_and_microsoft_cover_dates_parse_and_match() -> None:
    cases = (
        ("0000320193-26-000026", "2026-09-26", "478834 USD millions"),
        ("0001628280-26-010047", "2025-12-31", "47941 USD millions"),
        ("0001193125-26-436133", "2026-09-30", "92279 USD millions"),
    )
    for accession, period_end, figure in cases:
        filing = load_directory(PINNED / accession)
        assert filing.period_end == period_end
        explained = explain_filing(filing)
        assert figure in explained.markdown
        assert SENTENCE not in explained.markdown


def test_september_31_2026_is_refused(tmp_path: Path) -> None:
    contexts = _year("c-year", "2026-01-01", end="2026-09-30")
    explained = _explain(
        tmp_path,
        _page(
            _revenue("5000"),
            contexts=contexts,
            period_end="September 31, 2026",
            period_format="ixt:date-monthname-day-year-en",
        ),
    )
    rendered = explained.markdown + explained.html
    assert "5000" not in rendered
    assert "2026-09-30" not in rendered


def test_sept_26_2026_under_monthname_day_year_is_refused(tmp_path: Path) -> None:
    contexts = _year("c-year", "2026-01-01", end="2026-09-26")
    explained = _explain(
        tmp_path,
        _page(
            _revenue("5000"),
            contexts=contexts,
            period_end="Sept. 26 2026",
            period_format="ixt:date-monthname-day-year-en",
        ),
    )
    rendered = explained.markdown + explained.html
    assert "5000" not in rendered
    assert "2026-09-26" not in rendered


def test_a_word_date_one_day_off_the_context_end_is_refused(tmp_path: Path) -> None:
    contexts = _year("c-year", "2026-01-01", end="2026-09-30")
    explained = _explain(
        tmp_path,
        _page(
            _revenue("5000"),
            contexts=contexts,
            period_end="September 29, 2026",
            period_format="ixt:date-monthname-day-year-en",
        ),
    )
    rendered = explained.markdown + explained.html
    assert "5000" not in rendered
    assert "2026-09-30" not in rendered
    assert "2026-09-29" not in rendered


def test_datemonthdayyearen_parses_the_month_name_form(tmp_path: Path) -> None:
    contexts = _year("c-year", "2024-01-01", end="2024-12-31")
    explained = _explain(
        tmp_path,
        _page(
            _revenue("5000"),
            contexts=contexts,
            period_end="December 31, 2024",
            period_format="ixt:datemonthdayyearen",
        ),
    )
    assert "5000 USD" in explained.markdown


def test_a_numeric_us_date_parses_when_it_matches_the_context(tmp_path: Path) -> None:
    contexts = _year("c-year", "2024-01-01", end="2024-12-31")
    explained = _explain(
        tmp_path,
        _page(
            _revenue("5000"),
            contexts=contexts,
            period_end="12/31/2024",
            period_format="ixt:date-month-day-year",
        ),
    )
    assert "5000 USD" in explained.markdown


def test_an_unknown_date_format_is_refused(tmp_path: Path) -> None:
    contexts = _year("c-year", "2026-01-01", end="2026-09-26")
    explained = _explain(
        tmp_path,
        _page(
            _revenue("5000"),
            contexts=contexts,
            period_end="September 26, 2026",
            period_format="ixt:date-day-month-year",
        ),
    )
    rendered = explained.markdown + explained.html
    assert "5000" not in rendered
    assert "2026-09-26" not in rendered


@pytest.mark.parametrize("name", FILER)
def test_a_digit_near_a_money_word_becomes_the_filer(tmp_path: Path, name: str) -> None:
    explained = _explain(tmp_path, _page(_revenue("5000"), name=name))
    assert name not in explained.html
    assert ">the filer</a>" in explained.html
    assert 'title="Filer on EDGAR"' in explained.html


@pytest.mark.parametrize("name", VERBATIM)
def test_a_registrant_name_without_a_money_digit_stays_verbatim(tmp_path: Path, name: str) -> None:
    explained = _explain(tmp_path, _page(_revenue("5000"), name=name))
    assert name in explained.html
    assert 'title="Registrant name in the filing"' in explained.html
    assert 'title="Filer on EDGAR"' not in explained.html


def test_a_decoy_primary_with_an_untyped_real_file_is_refused(tmp_path: Path) -> None:
    directory = tmp_path / "decoy"
    directory.mkdir()
    real = _page(_revenue("5000")).encode()
    decoy = _page(_revenue("9999")).encode()
    (directory / "real.htm").write_bytes(real)
    (directory / "decoy.htm").write_bytes(decoy)
    provenance = {
        "cik": "0000000001",
        "form": "10-K",
        "files": [
            {
                "name": "real.htm",
                "url": SEC,
                "sha256": sha256(real).hexdigest(),
                "content_sha256": sha256(real).hexdigest(),
            },
            {
                "name": "decoy.htm",
                "url": SEC.replace("primary.htm", "decoy.htm"),
                "sha256": sha256(decoy).hexdigest(),
                "content_sha256": sha256(decoy).hexdigest(),
                "document_type": "10-K",
            },
        ],
    }
    (directory / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    explained = explain_filing(load_directory(directory))
    rendered = explained.markdown + explained.html
    assert "9999" not in rendered
    assert "5000" not in rendered
    assert SENTENCE in explained.markdown


def test_a_lower_case_iban_is_personal_data(tmp_path: Path) -> None:
    iban = "gb82west12345698765432"
    note = f"Pay to iban {iban} today."
    assert contains_personal(note)
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/personal.htm"
    directory = write_filing(tmp_path / "iban", "filing.xml", narrative_instance(note), url, form="10-K")
    explained = explain_filing(load_directory(directory))
    rendered = explained.markdown + explained.html
    assert iban not in rendered
    assert "redaction-chip" in explained.html
