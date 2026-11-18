"""Download from www.sec.gov and data.sec.gov only."""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from white_cliff.config import MissingUserAgent, valid_user_agent
from white_cliff.desktop_copy import BUSY, NO_INTERNET, ONLY_SEC, SEC_ODD

ALLOWED_HOSTS = frozenset({"www.sec.gov", "data.sec.gov"})
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_MAX_WAIT = 30.0


class DisallowedHost(Exception):
    def __init__(self) -> None:
        super().__init__(ONLY_SEC)


class SecBusy(Exception):
    def __init__(self) -> None:
        super().__init__(BUSY)


class SecUnreachable(Exception):
    def __init__(self) -> None:
        super().__init__(NO_INTERNET)


class SecStatus(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(SEC_ODD)
        self.status = status


def host_allowed(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    if parsed.port not in (None, 443):
        return False
    return (parsed.hostname or "") in ALLOWED_HOSTS


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_transport(url: str, user_agent: str) -> tuple[int, bytes, dict[str, str]]:
    if not host_allowed(url):
        raise DisallowedHost()
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json,text/html,application/xml,*/*",
        },
    )
    opener = urllib.request.build_opener(_RefuseRedirect)
    try:
        with opener.open(request, timeout=60) as response:
            return response.status, response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        headers = dict(exc.headers.items()) if exc.headers else {}
        return exc.code, body, headers


class RateLimiter:
    """One shared pace for every request in this process."""

    def __init__(self, rate: float = 10, sleep=time.sleep, clock=time.monotonic) -> None:
        if rate <= 0 or rate > 10:
            raise ValueError("rate exceeds 10 per second")
        self.interval = 1.0 / float(rate)
        self.limit = int(rate)
        self.sleep = sleep
        self.clock = clock
        self._lock = threading.Lock()
        self._next: float | None = None
        self._stamps: list[float] = []

    def run(self, fn):
        """Run fn once this process still has room in the last second."""
        with self._lock:
            while True:
                current = self.clock()
                self._stamps = [stamp for stamp in self._stamps if current - stamp < 1.0]
                wait = 0.0
                if self._next is not None and current < self._next:
                    wait = self._next - current
                if len(self._stamps) >= self.limit:
                    wait = max(wait, 1.0 - (current - self._stamps[0]))
                if wait > 0:
                    self.sleep(wait)
                    continue
                self._stamps.append(current)
                self._next = current + self.interval
                return fn()


def _header(headers: dict[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return ""


class SecClient:
    def __init__(
        self,
        user_agent: str,
        transport=None,
        sleep=time.sleep,
        clock=time.monotonic,
        rate: float = 10,
        limiter: RateLimiter | None = None,
    ) -> None:
        if (
            not isinstance(user_agent, str)
            or any(char in user_agent for char in "\r\n")
            or not valid_user_agent(user_agent)
        ):
            raise MissingUserAgent(
                "A User-Agent with a name and a contact email is required."
            )
        if rate <= 0 or rate > 10:
            raise ValueError("rate exceeds 10 per second")
        self.user_agent = user_agent
        self.transport = transport or _default_transport
        self.sleep = sleep
        self.clock = clock
        self.interval = 1.0 / float(rate)
        self.limiter = limiter
        self._next: float | None = None

    def _acquire(self) -> None:
        current = self.clock()
        if self._next is not None and current < self._next:
            self.sleep(self._next - current)
            current = self.clock()
        self._next = current + self.interval

    def _request(self, url: str):
        def once():
            return self.transport(url, self.user_agent)

        if self.limiter is not None:
            return self.limiter.run(once)
        self._acquire()
        return once()

    def get(self, url: str, hops: int = 0) -> bytes:
        if not host_allowed(url):
            raise DisallowedHost()
        delay = 1.0
        waited = 0.0
        for _ in range(6):
            try:
                status, body, headers = self._request(url)
            except (OSError, TimeoutError):
                raise SecUnreachable() from None
            if status in _REDIRECTS:
                location = _header(headers, "Location")
                target = urllib.parse.urljoin(url, location) if location else ""
                if hops >= 2 or not host_allowed(target):
                    raise DisallowedHost()
                return self.get(target, hops + 1)
            if status in (403, 429):
                pause = delay
                retry_after = _header(headers, "Retry-After")
                if retry_after:
                    try:
                        pause = float(retry_after)
                    except ValueError:
                        pause = delay
                pause = max(0.0, min(pause, _MAX_WAIT - waited))
                self.sleep(pause)
                waited += pause
                delay *= 2
                continue
            if status != 200:
                raise SecStatus(status)
            return body
        raise SecBusy()
