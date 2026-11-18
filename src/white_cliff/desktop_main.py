"""Open White Cliff in the browser on this computer."""

from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from white_cliff.desktop import Desktop, make_server, should_quit
from white_cliff.identity import app_data_dir


class Instance:
    """One running copy. A second launch opens that copy."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._fd: int | None = None

    def start_or_url(self, probe, sleep=time.sleep) -> tuple[bool, str | None]:
        """Return (True, None) to start, or (False, url) to open a live copy."""
        self.directory.mkdir(parents=True, exist_ok=True)
        found = self._live(probe)
        if found:
            return False, found
        lock_path = self.directory / "instance.lock"
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
        os.lseek(fd, 0, os.SEEK_SET)
        if not _lock(fd):
            os.close(fd)
            for _ in range(40):
                found = self._live(probe)
                if found:
                    return False, found
                sleep(0.05)
            return False, self._live(probe)
        self._fd = fd
        found = self._live(probe)
        if found:
            self._release()
            return False, found
        return True, None

    def publish(self, port: int) -> None:
        path = self.directory / "instance.port"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, f"{os.getpid()} {int(port)}\n".encode("ascii"))
        finally:
            os.close(fd)

    def _live(self, probe) -> str | None:
        record = read_instance(self.directory)
        if record is None:
            return None
        pid, port = record
        if not pid_alive(pid) or not probe(port):
            return None
        return "http://127.0.0.1:" + str(port) + "/"

    def _release(self) -> None:
        fd = self._fd
        self._fd = None
        if fd is not None:
            os.close(fd)


def read_instance(directory: Path) -> tuple[int, int] | None:
    path = directory / "instance.port"
    try:
        parts = path.read_text(encoding="ascii").split()
        pid, port = int(parts[0]), int(parts[1])
    except (OSError, ValueError, IndexError):
        return None
    if pid <= 0 or port <= 0 or port > 65535:
        return None
    return pid, port


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _lock(fd: int) -> bool:
    if sys.platform == "win32":
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def probe_port(port: int) -> bool:
    url = f"http://127.0.0.1:{port}/stay"
    try:
        with urllib.request.urlopen(url, timeout=0.4) as response:
            return response.status in {200, 204}
    except (OSError, ValueError):
        return False


def run_until_closed(server, desktop, *, sleep, clock) -> int:
    started = clock()
    try:
        while not should_quit(started, desktop.last_seen, clock()):
            sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        server.shutdown()
        server.server_close()
    return 0


def main() -> int:
    slot = Instance(app_data_dir())
    owner, running = slot.start_or_url(probe_port)
    if running:
        webbrowser.open(running)
        return 0
    if not owner:
        return 0
    desktop = Desktop.create()
    server = make_server(desktop)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    slot.publish(port)
    try:
        webbrowser.open(f"http://127.0.0.1:{port}/")
        return run_until_closed(server, desktop, sleep=time.sleep, clock=time.monotonic)
    except KeyboardInterrupt:
        server.shutdown()
        server.server_close()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
