"""Digit-free stable identifiers."""

from __future__ import annotations

import hashlib

_ALPHABET = "abcdefghijklmnopqrstuvwxyz"


def letter_id(prefix: str, seed: str, length: int = 16) -> str:
    """Return prefix plus letters derived from seed. The result has no digits."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    acc = int.from_bytes(digest, "big")
    chars: list[str] = []
    for _ in range(length):
        acc, rem = divmod(acc, 26)
        chars.append(_ALPHABET[rem])
    return prefix + "".join(chars)
