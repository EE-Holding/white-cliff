"""The user's name and email, stored only in the per-user app data file."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from white_cliff.config import valid_user_agent

APP_DIR_NAME = "White Cliff"


@dataclass(frozen=True)
class Identity:
    name: str
    email: str

    @property
    def user_agent(self) -> str:
        return f"{self.name} {self.email}"


def app_data_dir() -> Path:
    """The operating system's per-user folder for this program."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME


def cache_dir() -> Path:
    """A cache of sec.gov files. It is not the identity file."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_DIR_NAME / "Cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP_DIR_NAME
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / APP_DIR_NAME


def _checked(name: str, email: str) -> Identity | None:
    raw_name = str(name)
    raw_email = str(email)
    if any(ord(char) < 32 for char in raw_name + raw_email):
        return None
    cleaned_name = " ".join(raw_name.split())
    cleaned_email = raw_email.strip()
    if not cleaned_name or not cleaned_email:
        return None
    if any(char in cleaned_email for char in " <>"):
        return None
    if len(cleaned_name) > 120 or len(cleaned_email) > 120:
        return None
    identity = Identity(cleaned_name, cleaned_email)
    if not valid_user_agent(identity.user_agent):
        return None
    return identity


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def load_identity(path: Path) -> Identity | None:
    data = _read_json(path)
    if not data:
        return None
    return _checked(data.get("name", ""), data.get("email", ""))


def load_language(path: Path) -> str:
    """The saved language. English when the file has none."""
    code = _read_json(path).get("language", "en")
    if code not in {"en", "de"}:
        return "en"
    return code


def _backup_private(path: Path) -> None:
    """Keep an unreadable identity file. The copy is owner-only and is never replaced."""
    backup = path.with_name(path.name + ".bak")
    if backup.exists():
        return
    payload = path.read_bytes()
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.chmod(backup, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            view = view[written:]
    finally:
        os.close(fd)
    os.chmod(backup, 0o600)


def _load_object(path: Path) -> dict:
    """The stored object. A corrupt file is copied aside once, then treated as empty."""
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _backup_private(path)
        return {}
    if not isinstance(loaded, dict):
        _backup_private(path)
        return {}
    return loaded


def save_language(path: Path, code: str) -> None:
    """Store the language beside the name and email. It is not sent anywhere."""
    if code not in {"en", "de"}:
        return
    data = _load_object(path)
    data["language"] = code
    _write_private(path, json.dumps(data, indent=2) + "\n")


def save_identity(path: Path, name: str, email: str) -> Identity | None:
    identity = _checked(name, email)
    if identity is None:
        return None
    data = _load_object(path)
    data["name"] = identity.name
    data["email"] = identity.email
    _write_private(path, json.dumps(data, indent=2) + "\n")
    return identity


def _write_private(path: Path, payload: str) -> None:
    """Create the temp file owner-only, then replace the real file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.chmod(temporary, 0o600)
        data = payload.encode("utf-8")
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
    finally:
        os.close(fd)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def erase_identity(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
