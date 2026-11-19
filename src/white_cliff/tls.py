"""One verified TLS context for sec.gov, and a short local failure log."""

from __future__ import annotations

import ssl
import sys
import threading
import urllib.parse
import urllib.request
from pathlib import Path

import certifi

from white_cliff.identity import app_data_dir

_MAX_LOG = 1_000_000
_LOCK = threading.Lock()
_CONTEXT: ssl.SSLContext | None = None


def cafile() -> str:
    """The bundled CA file. Frozen apps read it from inside the bundle."""
    return certifi.where()


def cafile_inside_bundle(path: str | None = None) -> bool:
    location = Path(path or cafile()).resolve()
    root = getattr(sys, "_MEIPASS", None)
    if root:
        return location.is_relative_to(Path(root).resolve())
    return location.is_relative_to(Path(certifi.__file__).resolve().parent)


def sec_context() -> ssl.SSLContext:
    """One shared context. Certificate checks stay on."""
    global _CONTEXT
    if _CONTEXT is None:
        context = ssl.create_default_context(cafile=cafile())
        if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
            raise RuntimeError("certificate checks are off")
        _CONTEXT = context
    return _CONTEXT


def https_opener(*handlers):
    return urllib.request.build_opener(
        *handlers,
        urllib.request.HTTPSHandler(context=sec_context()),
    )


def is_tls_error(exc: BaseException) -> bool:
    seen: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in seen:
        seen.append(current)
        if isinstance(current, ssl.SSLError):
            return True
        reason = getattr(current, "reason", None)
        if isinstance(reason, ssl.SSLError):
            return True
        current = current.__cause__ or current.__context__
    return False


def failure_kind(exc: BaseException) -> str:
    """The certificate class when the transport wrapped it, otherwise the class."""
    if isinstance(exc, ssl.SSLError):
        return type(exc).__name__
    reason = getattr(exc, "reason", None)
    if isinstance(reason, ssl.SSLError):
        return type(reason).__name__
    return type(exc).__name__


def log_failure(kind: str, url: str, status: int | None) -> None:
    """Record the class, host, and status. Nothing else."""
    host = urllib.parse.urlparse(url).hostname or "-"
    shown = "-" if status is None else str(int(status))
    line = f"{kind.split()[0]} {host} {shown}\n"
    path = app_data_dir() / "white-cliff.log"
    payload = line.encode("ascii", "replace")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            existing = path.read_bytes() if path.is_file() else b""
            data = existing + payload
            if len(data) > _MAX_LOG:
                data = data[-_MAX_LOG:]
                newline = data.find(b"\n")
                if newline != -1 and newline + 1 < len(data):
                    data = data[newline + 1 :]
            path.write_bytes(data)
    except OSError:
        return
