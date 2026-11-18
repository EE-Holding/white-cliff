"""Cover-fact agreement, content hashes, concealed styles, and spelled currency."""

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from white_cliff.fetch import EdgarClient, directory_cik, strip_edgar_script
from white_cliff.pipeline import explain_filing, load_directory
from tests.test_round9 import SEC, SENTENCE, UA, _explain, _page, _revenue, _year

PINNED = Path(__file__).resolve().parents[1] / "pinned" / "filings"
FILER = (
    "Price 150 dollars Inc",
    "Acme 500 Dollars Inc",
    "Acme 5 Euros Inc",
    "Acme 5 Yen Inc",
    "Acme 5 Pounds Inc",
    "Revenue 99999 - - - - USD",
    "99 Cents Only Stores",
    "5 euros",
)
VERBATIM = (
    "Big 5 Sporting Goods",
    "1-800-Flowers.com",
    "Group 1 Automotive",
    "3D Systems",
    "Dollar Tree",
    "Dollar General",
    "3M Company",
    "7-Eleven Inc",
    "21st Century Fox",
    "1st Source",
    "Top 10 Holdings",
    "All 4 One",
    "Pen 2 Paper",
    "Try 3 Corp",
    "Mad 5 Labs",
)


def _both_years() -> str:
    return _year("c-year", "2024-01-01") + _year("c-prior", "2023-01-01", end="2023-12-31")


def test_a_hidden_period_end_that_disagrees_with_the_visible_one_is_refused(tmp_path: Path) -> None:
    lead = (
        '<ix:hidden><ix:nonNumeric name="dei:DocumentPeriodEndDate" '
        'contextRef="c-prior">2023-12-31</ix:nonNumeric></ix:hidden>'
    )
    body = _revenue("5000") + _revenue("1111", contextRef="c-prior")
    explained = _explain(tmp_path, _page(body, contexts=_both_years(), lead=lead))
    rendered = explained.markdown + explained.html
    assert "1111" not in rendered
    assert "5000" not in rendered
    assert SENTENCE in explained.markdown


def test_two_visible_period_ends_that_disagree_are_refused(tmp_path: Path) -> None:
    body = (
        '<ix:nonNumeric name="dei:DocumentPeriodEndDate" contextRef="c-prior">2023-12-31</ix:nonNumeric>'
        + _revenue("5000")
        + _revenue("1111", contextRef="c-prior")
    )
    explained = _explain(tmp_path, _page(body, contexts=_both_years()))
    rendered = explained.markdown + explained.html
    assert "5000" not in rendered
    assert "1111" not in rendered
    assert SENTENCE in explained.markdown


def test_a_period_end_that_differs_from_its_context_is_refused(tmp_path: Path) -> None:
    contexts = _year("c-dei", "2024-01-01", end="2024-12-31") + _year("c-year", "2023-01-01", end="2023-12-31")
    explained = _explain(
        tmp_path,
        _page(_revenue("5000"), contexts=contexts, period_end="2023-12-31", period_context="c-dei"),
    )
    rendered = explained.markdown + explained.html
    assert "5000" not in rendered
    assert SENTENCE in explained.markdown


def test_december_31_2023_on_a_later_context_is_refused(tmp_path: Path) -> None:
    contexts = _year("c-dei", "2024-01-01", end="2024-12-31") + _year("c-year", "2023-01-01", end="2023-12-31")
    explained = _explain(
        tmp_path,
        _page(
            _revenue("5000"),
            contexts=contexts,
            period_end="December 31, 2023",
            period_format="ixt:date-monthname-day-year-en",
            period_context="c-dei",
        ),
    )
    rendered = explained.markdown + explained.html
    assert "5000" not in rendered
    assert SENTENCE in explained.markdown


def test_a_period_end_on_a_prior_year_context_is_refused(tmp_path: Path) -> None:
    contexts = _year("c-dei", "2023-01-01", end="2023-12-31") + _year("c-year", "2024-01-01", end="2024-12-31")
    explained = _explain(
        tmp_path,
        _page(_revenue("5000"), contexts=contexts, period_end="2024-12-31", period_context="c-dei"),
    )
    rendered = explained.markdown + explained.html
    assert "5000" not in rendered
    assert SENTENCE in explained.markdown


@pytest.mark.parametrize(
    "extra",
    (
        '<ix:nonNumeric name="dei:DocumentType" contextRef="c-year">10-Q</ix:nonNumeric>',
        '<ix:nonNumeric name="dei:DocumentFiscalPeriodFocus" contextRef="c-year">Q1</ix:nonNumeric>',
        '<ix:nonNumeric name="dei:EntityRegistrantName" contextRef="c-year">Other Co</ix:nonNumeric>',
    ),
)
def test_two_disagreeing_cover_facts_are_refused(tmp_path: Path, extra: str) -> None:
    explained = _explain(tmp_path, _page(extra + _revenue("5000")))
    rendered = explained.markdown + explained.html
    assert "5000" not in rendered
    assert SENTENCE in explained.markdown


def test_two_agreeing_cover_facts_still_show_the_figure(tmp_path: Path) -> None:
    extra = (
        '<ix:nonNumeric name="dei:DocumentType" contextRef="c-year">10-K</ix:nonNumeric>'
        '<ix:nonNumeric name="dei:DocumentFiscalPeriodFocus" contextRef="c-year">FY</ix:nonNumeric>'
        '<ix:nonNumeric name="dei:EntityRegistrantName" contextRef="c-year">Example Co</ix:nonNumeric>'
        '<ix:nonNumeric name="dei:DocumentPeriodEndDate" contextRef="c-year">2024-12-31</ix:nonNumeric>'
    )
    explained = _explain(tmp_path, _page(extra + _revenue("5000")))
    assert "5000 USD" in explained.markdown
    assert SENTENCE not in explained.markdown


def test_a_fresh_fetch_records_both_hashes_the_url_and_the_time(tmp_path: Path) -> None:
    accession = "0001193125-26-436133"
    body = b"<html><body>primary<script type=\"text/javascript\" src=\"/nWkbdo/x\"></script></body></html>"
    index = """<html><body><table>
<tr><td>10-Q</td><td><a href="msft.htm">msft.htm</a></td><td>10-Q</td></tr>
</table></body></html>""".encode()
    when = datetime(2026, 11, 18, 6, 0, tzinfo=timezone.utc)

    def transport(url, user_agent):
        assert user_agent == UA
        if url.endswith("-index.html"):
            return 200, index, {}
        if url.endswith("/msft.htm"):
            return 200, body, {}
        raise AssertionError(url)

    client = EdgarClient(
        UA,
        transport=transport,
        sleep=lambda _seconds: None,
        clock=lambda: 0.0,
        now=lambda: when,
    )
    dest = tmp_path / "filing"
    client.fetch_accession(accession, dest, "789019")
    provenance = json.loads((dest / "provenance.json").read_text(encoding="utf-8"))
    item = provenance["files"][0]
    assert item["url"] == "https://www.sec.gov/Archives/edgar/data/789019/000119312526436133/msft.htm"
    assert item["sha256"] == sha256(body).hexdigest()
    assert item["content_sha256"] == sha256(strip_edgar_script(body)).hexdigest()
    assert item["content_sha256"] != item["sha256"]
    assert item["retrieved_at"] == "2026-11-18T06:00:00Z"
    load_directory(dest)


def test_a_saved_file_changed_by_one_byte_is_refused(tmp_path: Path) -> None:
    body = b"<html><body>primary</body></html>"
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/primary.htm"
    directory = tmp_path / "saved"
    directory.mkdir()
    (directory / "primary.htm").write_bytes(body)
    changed = bytearray(body)
    changed[12] = changed[12] ^ 1
    (directory / "primary.htm").write_bytes(changed)
    provenance = {
        "cik": "0000000001",
        "form": "10-K",
        "files": [
            {
                "name": "primary.htm",
                "url": url,
                "sha256": sha256(changed).hexdigest(),
                "content_sha256": sha256(strip_edgar_script(body)).hexdigest(),
                "retrieved_at": "2026-11-18T06:00:00Z",
            }
        ],
    }
    (directory / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    with pytest.raises(ValueError):
        load_directory(directory)


def test_pinned_files_recompute_to_the_recorded_content_hash() -> None:
    checked = 0
    for directory in sorted(path for path in PINNED.iterdir() if path.is_dir()):
        load_directory(directory)
        provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
        for item in provenance["files"]:
            raw = (directory / item["name"]).read_bytes()
            assert sha256(strip_edgar_script(raw)).hexdigest() == item["content_sha256"]
            checked += 1
    assert checked >= 9


def test_an_absolute_script_src_is_not_stripped() -> None:
    absolute = b'<html><body>hi<script type="text/javascript" src="https://evil.example/a.js"></script></body></html>'
    dotted = b'<html><body>hi<script type="text/javascript" src="/files/../../a.js"></script></body></html>'
    relative = b'<html><body>hi<script type="text/javascript" src="/nWkbdo/x"></script></body></html>'
    assert strip_edgar_script(absolute) == absolute
    assert strip_edgar_script(dotted) == dotted
    assert strip_edgar_script(relative) == b"<html><body>hi</body></html>"


def test_a_path_with_dot_dot_is_refused() -> None:
    dotted = (
        "https://www.sec.gov/Archives/edgar/data/789019/"
        "000119312526436133/../msft-20260930.htm"
    )
    clean = (
        "https://www.sec.gov/Archives/edgar/data/789019/"
        "000119312526436133/msft-20260930.htm"
    )
    assert directory_cik(dotted) is None
    assert directory_cik(clean) == "0000789019"


@pytest.mark.parametrize(
    ("style", "klass", "sheet"),
    (
        ("visibility:hidden", "", ""),
        ("font-size:0pt", "", ""),
        ("height:0px", "", ""),
        ("", "secret", "<style>.secret { font-size: 0 }</style>"),
    ),
)
def test_a_concealed_only_figure_is_not_shown(tmp_path: Path, style: str, klass: str, sheet: str) -> None:
    attrs = ""
    if style:
        attrs += f' style="{style}"'
    if klass:
        attrs += f' class="{klass}"'
    body = f'{sheet}<div{attrs}>{_revenue("9000")}</div>'
    explained = _explain(tmp_path, _page(body))
    rendered = explained.markdown + explained.html
    assert "9000" not in rendered


@pytest.mark.parametrize(
    ("style", "klass", "sheet"),
    (
        ("visibility:hidden", "", ""),
        ("font-size:0em", "", ""),
        ("height:0%", "", ""),
        ("", "secret", "<style>.secret { display: none }</style>"),
    ),
)
def test_a_concealed_copy_that_disagrees_refuses_the_visible_figure(
    tmp_path: Path, style: str, klass: str, sheet: str
) -> None:
    attrs = ""
    if style:
        attrs += f' style="{style}"'
    if klass:
        attrs += f' class="{klass}"'
    body = f'{sheet}<div{attrs}>{_revenue("9000")}</div>' + _revenue("5000")
    explained = _explain(tmp_path, _page(body))
    rendered = explained.markdown + explained.html
    assert "9000" not in rendered
    assert "5000" not in rendered


@pytest.mark.parametrize("name", FILER)
def test_a_spelled_currency_near_a_digit_becomes_the_filer(tmp_path: Path, name: str) -> None:
    explained = _explain(tmp_path, _page(_revenue("5000"), name=name))
    assert name not in explained.html
    assert ">the filer</a>" in explained.html


@pytest.mark.parametrize("name", VERBATIM)
def test_a_name_without_an_upper_case_code_stays_verbatim(tmp_path: Path, name: str) -> None:
    explained = _explain(tmp_path, _page(_revenue("5000"), name=name))
    assert name in explained.html
    assert 'title="Registrant name in the filing"' in explained.html
    assert 'title="Filer on EDGAR"' not in explained.html
