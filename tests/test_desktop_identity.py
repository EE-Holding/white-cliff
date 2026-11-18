"""Name and email stay in the per-user app data file."""

import os
from pathlib import Path

from white_cliff.identity import app_data_dir, cache_dir, erase_identity, load_identity, save_identity

NAME = "Example Person"
EMAIL = "person@example.com"


def _home(monkeypatch, tmp_path, platform):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    monkeypatch.setattr("white_cliff.identity.sys.platform", platform)
    return home


def test_darwin_app_data_is_application_support(monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path, "darwin")
    assert app_data_dir() == home / "Library" / "Application Support" / "White Cliff"
    assert cache_dir() == home / "Library" / "Caches" / "White Cliff"


def test_windows_app_data_is_roaming(monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path, "win32")
    assert app_data_dir() == home / "AppData" / "Roaming" / "White Cliff"
    assert cache_dir() == home / "AppData" / "Local" / "White Cliff" / "Cache"


def test_linux_app_data_follows_xdg(monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path, "linux")
    assert app_data_dir() == home / ".local" / "share" / "White Cliff"
    assert cache_dir() == home / ".cache" / "White Cliff"


def test_details_file_lives_only_in_app_data(monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path, "darwin")
    path = app_data_dir() / "identity.json"
    saved = save_identity(path, "  Example   Person ", "  person@example.com  ")
    assert saved.name == NAME
    assert saved.email == EMAIL
    assert saved.user_agent == f"{NAME} {EMAIL}"
    loaded = load_identity(path)
    assert loaded == saved
    found = [
        item
        for item in home.rglob("*")
        if item.is_file() and EMAIL.encode("ascii") in item.read_bytes()
    ]
    assert found == [path]
    assert cache_dir() != app_data_dir()
    assert not cache_dir().exists()


def test_erase_removes_the_file(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path, "linux")
    path = app_data_dir() / "identity.json"
    save_identity(path, NAME, EMAIL)
    erase_identity(path)
    assert not path.exists()
    assert load_identity(path) is None
    erase_identity(path)
    assert load_identity(path) is None


def test_missing_or_broken_file_has_no_identity(tmp_path):
    path = tmp_path / "identity.json"
    assert load_identity(path) is None
    path.write_text("{", encoding="utf-8")
    assert load_identity(path) is None
    path.write_text('{"name": "Only"}', encoding="utf-8")
    assert load_identity(path) is None


def test_identity_temp_file_is_created_owner_only(tmp_path, monkeypatch):
    path = tmp_path / "identity.json"
    modes = []
    real_open = os.open

    def spy(file, flags, mode=0o777, *, dir_fd=None):
        if str(file).endswith(".tmp"):
            modes.append(mode)
        return real_open(file, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr("white_cliff.identity.os.open", spy)
    save_identity(path, NAME, EMAIL)
    assert modes == [0o600]
    assert path.stat().st_mode & 0o777 == 0o600
    assert not path.with_suffix(".tmp").exists()


def test_rejected_details_are_not_written(tmp_path):
    path = tmp_path / "app" / "identity.json"
    for name, email in (("", EMAIL), (NAME, "not-an-email"), ("Bad\nName", EMAIL), (NAME, "a@b")):
        assert save_identity(path, name, email) is None
    assert not path.exists()
