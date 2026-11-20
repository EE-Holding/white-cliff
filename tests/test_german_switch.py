"""German stays hidden until a native-speaker review is recorded."""

from white_cliff.desktop import Desktop
from white_cliff.disclaimer import DISCLAIMER
from white_cliff.identity import load_language, save_identity, save_language
from white_cliff.i18n import german, using
from white_cliff.lexicon import STRINGS
from white_cliff.present import search_page

GERMAN = STRINGS["§1.DISCLAIMER"][1]


def test_the_release_default_leaves_german_off():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src"
        / "white_cliff"
        / "i18n.py"
    ).read_text(encoding="utf-8")
    assert "GERMAN_REVIEWED = False" in source


def test_the_release_build_hides_the_toggle_and_german(monkeypatch):
    import white_cliff.i18n as i18n

    monkeypatch.setattr(i18n, "GERMAN_REVIEWED", False)
    with using("de"):
        assert german() is False
        page = search_page("token")
    assert ">Deutsch<" not in page
    assert 'button lang="de"' not in page
    assert "Language / Sprache" not in page
    assert GERMAN not in page
    assert DISCLAIMER in page
    assert 'lang="en"' in page


def test_a_saved_german_choice_stays_english_before_review(tmp_path, monkeypatch):
    import white_cliff.i18n as i18n

    monkeypatch.setattr(i18n, "GERMAN_REVIEWED", False)
    path = tmp_path / "identity.json"
    save_identity(path, "Example Person", "person@example.com")
    save_language(path, "de")
    clock = lambda: 0
    app = Desktop(path, tmp_path / "cache", None, lambda _seconds: None, clock)
    opened = app.handle("GET", "/", {})
    posted = app.handle("POST", "/language", {"language": "de"})
    for page in (opened, posted):
        assert '<html lang="en"' in page.body
        assert ">Deutsch<" not in page.body
        assert GERMAN not in page.body
        assert "Unternehmensname oder Tickersymbol" not in page.body
    assert load_language(path) == "en"


def test_a_recorded_review_shows_the_toggle_and_german(tmp_path, monkeypatch):
    import white_cliff.i18n as i18n

    monkeypatch.setattr(i18n, "GERMAN_REVIEWED", True)
    with using("de"):
        assert german() is True
        page = search_page("token")
    assert ">Deutsch<" in page
    assert GERMAN in page
    path = tmp_path / "identity.json"
    save_identity(path, "Example Person", "person@example.com")
    clock = lambda: 0
    app = Desktop(path, tmp_path / "cache", None, lambda _seconds: None, clock)
    chosen = app.handle("POST", "/language", {"language": "de"})
    assert '<html lang="de"' in chosen.body
    assert "Unternehmensname oder Tickersymbol" in chosen.body
    assert load_language(path) == "de"
