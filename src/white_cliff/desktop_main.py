"""Open White Cliff in the browser on this computer, and quit when the tab closes."""

from __future__ import annotations

import threading
import time
import webbrowser

from white_cliff.desktop import Desktop, make_server, should_quit


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
    desktop = Desktop.create()
    server = make_server(desktop)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        webbrowser.open(f"http://127.0.0.1:{port}/")
        return run_until_closed(server, desktop, sleep=time.sleep, clock=time.monotonic)
    except KeyboardInterrupt:
        server.shutdown()
        server.server_close()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
