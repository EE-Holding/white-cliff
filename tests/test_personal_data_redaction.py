from pathlib import Path

from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.redact import contains_personal
from tests.support import write_filing

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = (
    "123-45-6789",
    "123456789012",
    "742 Evergreen Terrace",
    "Springfield, IL 62704",
)


def test_personal_data_is_replaced_by_chips():
    filing = load_directory(ROOT / "tests" / "fixtures" / "personal")
    explained = explain_filing(filing)
    rendered = explained.markdown + "\n" + explained.html
    for secret in FORBIDDEN:
        assert secret not in rendered
    assert rendered.count("redaction=") >= 3 or rendered.count("redaction-chip") >= 3
    assert explained.html.count("redaction-chip") >= 3
    assert "5000" in explained.markdown


def test_more_personal_shapes_are_chips_and_a_street_in_words_is_refused(tmp_path):
    from tests.support import narrative_instance

    note = (
        "SSN 123456789. The other form is 123.45.6789. "
        "Account No. 12345678. Pay to IBAN GB82WEST12345698765432. "
        "Mail to PO Box 123. Deliver to Apt 4B, 77 Main St. "
        "The plant is at 77 main street. The office is at 10 Downing Street, London."
    )
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/personal.htm"
    directory = write_filing(tmp_path / "personal", "filing.xml", narrative_instance(note), url, form="10-K")
    filing = load_directory(directory)
    sentence = "The officer lives at Elm Street in Springfield [section:Notes]."
    assert contains_personal(sentence)
    explained = explain_filing(filing)
    rendered = explained.markdown + "\n" + explained.html
    for secret in (
        "123456789",
        "123.45.6789",
        "12345678",
        "GB82WEST12345698765432",
        "PO Box 123",
        "77 Main St",
        "77 main street",
        "10 Downing Street",
        "Elm Street",
        "Springfield",
    ):
        assert secret not in rendered
    assert explained.html.count("redaction-chip") >= 7
