"""The fleet HTTP session (design section 6).

Wraps ``skippercast.http.Session`` (HTTPS only, public addresses, size caps,
backoff, conditional-GET cache) and adds, for every fleet fetch:

- an allowlist: hosts named in the region's bindings plus operator websites
  added with ``allow_host`` (stored website facts);
- a hard deny of ``catalog/fleet/off-limits.json`` hosts, checked on the first
  URL and on every redirect hop before a connection is made;
- robots.txt per host for the ``SkipperCast`` user agent (``urllib.robotparser``,
  cached 24 h; unreachable or 401/403 robots.txt means disallowed);
- at least ``interval`` seconds between requests to one host;
- a per-run request budget per host (default 600).

A refused URL raises ``Skipped`` and is appended to ``skips`` so the step can
record it in its report; adapters catch ``Skipped`` and move on.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .. import http
from .config import FleetRegion, off_limits_host

ROBOTS_AGENT = "SkipperCast"
ROBOTS_TTL = 24 * 3600


class OffLimits(http.DisallowedHost):
    """The URL (or a redirect target) is on an off-limits host (decision D7)."""


class Skipped(Exception):
    def __init__(self, url: str, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {url}" + (f" ({detail})" if detail else ""))
        self.url, self.reason, self.detail = url, reason, detail

    def as_dict(self) -> dict:
        return {"url": self.url, "reason": self.reason, "detail": self.detail}


class _DenySession(http.Session):
    """A Session whose per-hop URL check also refuses off-limits hosts."""

    def __init__(self, off_limits: Iterable[str], **options: Any):
        super().__init__(**options)
        self.off_limits = tuple(off_limits)

    def check_url(self, url, allowlist=None, allowed_prefixes=None):
        blocked = off_limits_host(url, self.off_limits)
        if blocked:
            raise OffLimits(f"Off-limits host {blocked}: {url}")
        return super().check_url(url, allowlist, allowed_prefixes)


def binding_hosts(region: FleetRegion) -> set[str]:
    hosts = set()
    for binding in region.sources:
        for value in binding.params.values():
            if isinstance(value, str) and value.startswith("https://"):
                hosts.add(urlsplit(value).hostname or "")
    hosts.update(urlsplit(x.website).hostname or "" for x in region.landings if x.website)
    return {h.lower() for h in hosts if h}


class FleetSession:
    def __init__(self, hosts: Iterable[str], off_limits: Iterable[str], *, budget: int = 600,
                 interval: float = 1.0, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic, **session_options: Any):
        self.session = _DenySession(off_limits, allowed_hosts=(), sleep=sleep, clock=clock, **session_options)
        self.hosts = {h.lower() for h in hosts}
        self.budget, self.interval = budget, interval
        self.sleep, self.clock = sleep, clock
        self.used: dict[str, int] = {}
        self.skips: list[dict] = []
        self._next: dict[str, float] = {}
        self._robots: dict[str, tuple[float, RobotFileParser | None]] = {}

    @classmethod
    def for_region(cls, region: FleetRegion, **options: Any) -> "FleetSession":
        return cls(binding_hosts(region), region.off_limits, **options)

    def allow_host(self, host: str) -> None:
        self.hosts.add(host.lower())

    def _skip(self, url: str, reason: str, detail: str = "") -> Skipped:
        error = Skipped(url, reason, detail)
        self.skips.append(error.as_dict())
        return error

    def _wait(self, host: str) -> None:
        now = self.clock()
        ready = self._next.get(host, now)
        if ready > now:
            self.sleep(ready - now)
        self._next[host] = max(now, ready) + self.interval

    def _robots_allows(self, url: str, host: str) -> bool:
        cached = self._robots.get(host)
        if cached is None or self.clock() - cached[0] > ROBOTS_TTL:
            parser: RobotFileParser | None = RobotFileParser()
            self._wait(host)
            try:
                response = self.session.get(f"https://{host}/robots.txt", allowed_hosts=self.hosts,
                                            raise_for_status=False, max_bytes=500_000)
            except (http.SourceError, OSError):
                parser = None  # unreachable robots.txt: fail closed for this run
            else:
                if response.status in (401, 403) or response.status >= 500:
                    parser.disallow_all = True
                elif response.status >= 400:
                    parser.allow_all = True
                else:
                    parser.parse((response.body or b"").decode("utf-8", "replace").splitlines())
            cached = self._robots[host] = (self.clock(), parser)
        return cached[1] is not None and cached[1].can_fetch(ROBOTS_AGENT, url)

    def get(self, url: str, **options: Any) -> http.Response:
        """Fetch ``url`` under the fleet rules; raises Skipped for a refused URL."""
        try:
            host, _port = self.session.check_url(url, http.Allowlist(self.hosts))
        except OffLimits as error:
            raise self._skip(url, "off-limits", str(error)) from None
        except http.DisallowedHost as error:
            raise self._skip(url, "not-allowlisted", str(error)) from None
        if self.used.get(host, 0) >= self.budget:
            raise self._skip(url, "budget", f"{self.budget} requests to {host} this run")
        if not self._robots_allows(url, host):
            raise self._skip(url, "robots", host)
        self.used[host] = self.used.get(host, 0) + 1
        self._wait(host)
        try:
            return self.session.get(url, allowed_hosts=self.hosts, **options)
        except OffLimits as error:  # a redirect pointed at an off-limits host; refused before connecting
            raise self._skip(url, "off-limits-redirect", str(error)) from None
