from pathlib import Path

from white_cliff.pipeline import explain_filing, load_directory

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
