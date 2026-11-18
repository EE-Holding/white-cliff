"""Show the old opener failing once the runner's CA files are gone.

The f0b792e transport builds an opener with no CA file. This step does that
and prints the exception class. A completed request means the runner still
has a usable bundle.
"""

from __future__ import annotations

import os
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HIDDEN = Path("/tmp/white-cliff-hidden-certs")
TARGET = "https://www.sec.gov/"


def _remembered(argv: list[str]) -> list[str]:
    return [item for item in argv[1:] if item]


def _candidates(extra: list[str]) -> list[Path]:
    found: list[Path] = []
    paths = ssl.get_default_verify_paths()
    named = [
        paths.cafile,
        paths.capath,
        paths.openssl_cafile,
        paths.openssl_capath,
        *extra,
    ]
    roots = [
        Path("/Library/Frameworks/Python.framework"),
        Path("/Users/runner/hostedtoolcache/Python"),
        Path.home() / "hostedtoolcache" / "Python",
        Path("/usr/local/etc"),
        Path("/opt/homebrew/etc"),
        Path("/etc/ssl"),
        Path("/private/etc/ssl"),
    ]
    for item in named:
        if item:
            found.append(Path(item))
    for root in roots:
        if not root.exists():
            continue
        for openssl in root.glob("Versions/*/etc/openssl"):
            found.append(openssl)
        for openssl in root.glob("**/etc/openssl"):
            found.append(openssl)
        if root.name == "Python":
            for cert in root.glob("**/cert.pem"):
                found.append(cert)
            for cert in root.glob("**/cacert.pem"):
                found.append(cert)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in found:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _move(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    HIDDEN.mkdir(parents=True, exist_ok=True)
    dest = HIDDEN / path.name
    number = 0
    while dest.exists() or dest.is_symlink():
        number += 1
        dest = HIDDEN / f"{path.name}-{number}"
    print(f"moved {path} -> {dest}", flush=True)
    try:
        shutil.move(str(path), str(dest))
    except PermissionError:
        subprocess.check_call(["sudo", "mv", str(path), str(dest)])


def _try_open():
    request = urllib.request.Request(TARGET)
    opener = urllib.request.build_opener()
    with opener.open(request, timeout=20) as response:
        return response.status


def main(argv: list[str]) -> int:
    for name in ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        os.environ.pop(name, None)
    print(ssl.get_default_verify_paths(), flush=True)
    for path in _candidates(_remembered(argv)):
        try:
            _move(path)
        except OSError as exc:
            print(f"could not move {path}: {type(exc).__name__}", flush=True)
    try:
        status = _try_open()
    except Exception as exc:
        reason = getattr(exc, "reason", None)
        print(f"exception class: {type(exc).__name__}", flush=True)
        if reason is not None:
            print(f"reason class: {type(reason).__name__}", flush=True)
            print(f"reason: {reason}", flush=True)
        else:
            print(f"message: {exc}", flush=True)
        if isinstance(exc, ssl.SSLError) or isinstance(reason, ssl.SSLError):
            print("old opener failed with a certificate error", flush=True)
            return 0
        if isinstance(exc, urllib.error.HTTPError):
            print(f"old opener completed TLS and got HTTP {exc.code}", flush=True)
            return 1
        print("old opener failed, but not with a certificate error", flush=True)
        return 1
    print(f"old opener completed TLS and got HTTP {status}", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
