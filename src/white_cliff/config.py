"""User-Agent configuration. The repository ships no contact address and no key."""

from __future__ import annotations

import os
import re
from pathlib import Path

_EMAIL = re.compile(r"\S+@\S+\.\S+")


class MissingUserAgent(Exception):
    """Raised when the operator has not configured a name and contact email."""


def valid_user_agent(value: str) -> bool:
    if not value or len(value.strip()) < 5:
        return False
    if len(value.split()) < 2:
        return False
    return _EMAIL.search(value) is not None


def _read_config(path: Path) -> str:
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("user_agent"):
            _, _, raw = stripped.partition("=")
            return raw.strip().strip('"').strip("'")
    return ""


def load_user_agent(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    configured = env.get("WHITE_CLIFF_USER_AGENT", "").strip()
    if not configured:
        config_value = env.get("WHITE_CLIFF_CONFIG", "").strip()
        if config_value:
            path = Path(config_value)
        else:
            path = Path.home() / ".config" / "white-cliff" / "config.toml"
        configured = _read_config(path).strip()
    if not valid_user_agent(configured):
        raise MissingUserAgent(
            "A User-Agent with a name and a contact email is required."
        )
    return configured
