"""One HTTP client for the pipeline (standard library only).

Every source request in `src/` goes through `Session`, so they all share one
policy instead of a copy per module:

- one User-Agent, `SkipperCast/<version> (+https://skippercast.com)`;
- HTTPS only, to hosts on an allowlist (built from `catalog/sources.json`, the
  region and jurisdiction files, and `EXTRA_HOSTS`; callers may pass their own);
- each hop is resolved once, every resolved address must be public, and the
  connection is made to that checked address while TLS still verifies the
  certificate for the hostname (SNI), so DNS cannot change between the check and
  the connection (engineering audit finding A38);
- redirects are followed only to allowlisted, public HTTPS targets (and, when a
  caller gives `allowed_prefixes`, only inside those URL prefixes);
- a per-call timeout and a maximum body size (checked against Content-Length,
  while reading, and after gzip decoding);
- exponential backoff with full jitter on 429/502/503/504 and connection errors,
  honouring `Retry-After` (seconds or an HTTP date) up to a cap;
- an optional per-host minimum interval between requests;
- an optional conditional-GET cache (ETag / Last-Modified) that returns the
  cached body on 304; it is off unless a cache directory is given or
  `SKIPPERCAST_HTTP_CACHE` is set (`1` means `var/http-cache`);
- a `Receipt` for every call (url, final_url, status, attempts, bytes, sha256,
  elapsed_ms, from_cache, error_class and one history row per attempt) that
  callers record in feeds.

Failures are typed. `DisallowedHost` and `ContractError` (including
`BodyTooLarge`) are `ValueError`s: they describe the request or the response,
are never retried, and keep the fail-closed `except ValueError` paths callers
already have. `TransportError` covers DNS, connection, timeout, TLS and cut
transfers; `HTTPStatusError` carries an unexpected HTTP status. Both are
`OSError`s, like urllib's errors were. Each carries the `receipt` of the call
that raised it.

TLS uses `truststore` (the operating system's trust store) when it is installed
(`pip install ".[tls]"`), else `ssl.create_default_context()`. That replaces the
old `/usr/bin/curl` fallback, which existed because python.org builds on macOS
can carry a stale CA bundle that lacks a root the system store has (the
California agency sites chain to Sectigo Public Server Authentication Root
R46). Certificate checking is never relaxed; a verification failure raises
`TLSVerificationError` and says how to fix the trust store.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import timezone
import email.utils
from functools import lru_cache
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import random
import re
import socket
import ssl
import threading
import time
from typing import Any, BinaryIO, Callable, Iterable, Mapping
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import getproxies, proxy_bypass
import zlib

from . import __version__
from .paths import repo_root
from .util.time import stamp

USER_AGENT = f"SkipperCast/{__version__} (+https://skippercast.com)"
RETRY_STATUSES = frozenset({429, 502, 503, 504})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_BYTES = 5_000_000
DEFAULT_ATTEMPTS = 3
MAX_REDIRECTS = 10  # urllib's limit, which every caller used before
CHUNK = 64 * 1024
TRANSPORT = "skippercast.http; TLS verified"

# Hosts the pipeline code names directly (not in the configuration files the
# default allowlist is built from). Adding a host here is a reviewed change.
EXTRA_HOSTS = frozenset({
    # Daily and live collectors (pipeline/collect.py, live.py, ocean.py, wave_ensemble.py)
    "api.weather.gov", "api.tidesandcurrents.noaa.gov", "www.ndbc.noaa.gov",
    "services2.arcgis.com", "www.socalfishreports.com", "www.ecfr.gov",
    "opendap.co-ops.nos.noaa.gov", "nomads.ncep.noaa.gov",
    # SkipperCast's own published forecast tiles and API (forecast/local.py)
    "skippercast.com", "raw.githubusercontent.com",
    # Morro Bay monitor (monitor/collector.py)
    "forecast.weather.gov", "www.morrobayca.gov", "wildlife.ca.gov", "www.virgslanding.com",
    # Forecast model grids (forecast/models.py, forecast/ensemble.py)
    "noaa-gfs-bdp-pds.s3.amazonaws.com", "noaa-gefs-pds.s3.amazonaws.com",
    "ecmwf-forecasts.s3.eu-central-1.amazonaws.com", "data.ecmwf.int",
    # Seafloor originals and references (seafloor/io.py, fetch.py, reference.py)
    "noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com", "cmgds.marine.usgs.gov",
    "pubs.usgs.gov", "data.ngdc.noaa.gov", "naciscdn.org",
})
# Configuration files whose URLs the collectors fetch.
ALLOWLIST_SOURCES = ("catalog/sources.json", "catalog/coasts.json", "regions/*/region.json",
                     "jurisdictions/*.json")
_URL = re.compile(r"https://[A-Za-z0-9.-]+")


# ---- errors ----------------------------------------------------------------------

class SourceError(Exception):
    """Base class. `error_class` is the name recorded in receipts."""

    receipt: "Receipt | None" = None

    @property
    def error_class(self) -> str:
        return type(self).__name__


class TransportError(SourceError, OSError):
    """DNS, connection, timeout, TLS or a cut transfer. Retried."""


class TLSVerificationError(TransportError):
    """The certificate did not verify. Not retried; the trust store needs fixing."""


class HTTPStatusError(SourceError, OSError):
    """The final response had a status the caller does not accept.

    An OSError, as urllib's HTTPError was, so `except OSError` fail-closed paths
    written for urllib (for example seafloor.screen) still catch it.
    """

    def __init__(self, message: str, status: int, headers: "Headers | None" = None, body: bytes = b""):
        super().__init__(message)
        self.status = status
        self.code = status  # the attribute urllib's HTTPError used
        self.headers = headers or Headers()
        self.body = body


class ContractError(SourceError, ValueError):
    """The response broke the request's contract (encoding, redirect, size). Not retried."""


class BodyTooLarge(ContractError):
    """The body exceeds the call's byte limit."""


class DisallowedHost(SourceError, ValueError):
    """The URL, host, port or resolved address is outside policy. Not retried."""


# ---- receipts and responses -------------------------------------------------------

class Headers(dict):
    """Response headers with case-insensitive `get` (the last value of a repeated header)."""

    def __init__(self, items: Iterable[tuple[str, str]] = ()):
        super().__init__()
        for name, value in items:
            self[name.lower()] = value

    def get(self, name: str, default: Any = None) -> Any:  # type: ignore[override]
        return super().get(name.lower(), default)

    def __getitem__(self, name: str) -> str:
        return super().__getitem__(name.lower())

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and super().__contains__(name.lower())


@dataclass
class Receipt:
    """What one call did. `history` has one row per attempt."""

    url: str
    method: str = "GET"
    final_url: str | None = None
    status: int | None = None
    attempts: int = 0
    bytes: int | None = None
    sha256: str | None = None
    elapsed_ms: int = 0
    from_cache: bool = False
    error_class: str | None = None
    error: str | None = None
    compressed_bytes: int | None = None
    http_date: str | None = None
    content_type: str | None = None
    last_modified: str | None = None
    etag: str | None = None
    truncated: bool = False
    transport: str = TRANSPORT
    history: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        row = {key: value for key, value in self.__dict__.items() if key != "history"}
        row["history"] = [dict(entry) for entry in self.history]
        return row


@dataclass
class Response:
    url: str
    final_url: str
    status: int
    headers: Headers
    body: bytes | None
    receipt: Receipt

    def text(self, encoding: str = "utf-8") -> str:
        return (self.body or b"").decode(encoding)

    def json(self) -> Any:
        return json.loads(self.text())


# ---- TLS, allowlist, addresses ----------------------------------------------------

def tls_context() -> ssl.SSLContext:
    """The OS trust store through `truststore` when installed, else Python's default context."""
    try:
        import truststore
    except ImportError:
        return ssl.create_default_context()
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _normal_host(host: str) -> str:
    return host.lower().rstrip(".")


class Allowlist:
    """Exact hostnames, `*.example.org` for any subdomain of example.org, or `*` for any host.

    `*` is only for documentation probes that never read data (platform.source_audit);
    the address checks still apply to it.
    """

    def __init__(self, hosts: Iterable[str]):
        entries = {_normal_host(h) for h in hosts if h}
        self.any = "*" in entries
        self.exact = frozenset(h for h in entries if not h.startswith("*"))
        self.suffixes = tuple(sorted(h[1:] for h in entries if h.startswith("*.")))

    def allows(self, host: str) -> bool:
        host = _normal_host(host)
        return self.any or host in self.exact or bool(self.suffixes and host.endswith(self.suffixes))

    def __contains__(self, host: object) -> bool:
        return isinstance(host, str) and self.allows(host)

    def __or__(self, other: Iterable[str]) -> "Allowlist":
        return Allowlist([*self.exact, *("*" + s for s in self.suffixes), *(["*"] if self.any else []), *other])


def config_hosts(root: Path | None = None) -> frozenset[str]:
    """HTTPS hosts named in the source catalog, coasts, regions and jurisdictions."""
    root = Path(root) if root is not None else repo_root()
    hosts = set()
    for pattern in ALLOWLIST_SOURCES:
        for path in sorted(root.glob(pattern)):
            for url in _URL.findall(path.read_text(encoding="utf-8")):
                host = urlsplit(url).hostname
                if host:
                    hosts.add(_normal_host(host))
    return frozenset(hosts)


@lru_cache(maxsize=None)
def _default_allowlist(root: str) -> Allowlist:
    return Allowlist(config_hosts(Path(root)) | EXTRA_HOSTS)


def default_allowlist(extra: Iterable[str] = (), root: Path | None = None) -> Allowlist:
    """Configuration hosts plus `EXTRA_HOSTS`, plus any `extra` the caller names."""
    base = _default_allowlist(str(Path(root) if root is not None else repo_root()))
    extra = tuple(extra)
    return base | extra if extra else base


def public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """The default address policy: globally routable only (no private, loopback, link-local...)."""
    return address.is_global


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """Seconds to wait from a Retry-After header (delta-seconds or HTTP date), or None."""
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        moment = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    now = time.time() if now is None else now
    return max(0.0, moment.timestamp() - now)


# ---- connections ------------------------------------------------------------------

class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS to a hostname, connected to addresses that were already checked.

    The TCP connection goes to one of `addresses`, never to a fresh DNS answer;
    TLS still sends SNI for, and verifies the certificate against, `host`.
    """

    def __init__(self, host: str, port: int, addresses: list[tuple[int, tuple]], *,
                 context: ssl.SSLContext, timeout: float):
        super().__init__(host, port, timeout=timeout, context=context)
        self.addresses = addresses
        self.connected_address: tuple | None = None

    def connect(self) -> None:
        error: OSError | None = None
        for family, sockaddr in self.addresses:
            sock = socket.socket(family, socket.SOCK_STREAM)
            try:
                sock.settimeout(self.timeout)
                sock.connect(sockaddr)
            except OSError as failure:
                sock.close()
                error = failure
                continue
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            self.connected_address = sockaddr
            try:
                self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # type: ignore[attr-defined]
            except BaseException:
                sock.close()
                raise
            return
        raise error or OSError(f"No address to connect to for {self.host}")


def _proxy_for(host: str, proxies: Mapping[str, str] | None) -> str | None:
    if proxies is None:
        proxies = getproxies()
        if proxies.get("https") and proxy_bypass(host):
            return None
    return proxies.get("https") or None


def _proxy_connection(proxy: str, host: str, port: int, *, context: ssl.SSLContext,
                      timeout: float, user_agent: str) -> http.client.HTTPSConnection:
    """CONNECT tunnel through an operator-configured proxy (the proxy resolves the host)."""
    parts = urlsplit(proxy if "://" in proxy else "http://" + proxy)
    connection = http.client.HTTPSConnection(parts.hostname, parts.port or 8080, timeout=timeout, context=context)
    headers = {"User-Agent": user_agent}
    if parts.username:
        token = f"{unquote(parts.username)}:{unquote(parts.password or '')}".encode()
        headers["Proxy-Authorization"] = "Basic " + base64.b64encode(token).decode()
    connection.set_tunnel(host, port, headers=headers)
    return connection


# ---- conditional-GET cache --------------------------------------------------------

class HTTPCache:
    """Validators and bodies of earlier 200 responses, keyed by request URL."""

    def __init__(self, directory: Path | str):
        self.directory = Path(directory)
        self._lock = threading.Lock()

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha256(url.encode()).hexdigest()
        return self.directory / f"{key}.json", self.directory / f"{key}.body"

    def lookup(self, url: str) -> dict | None:
        meta_path, _ = self._paths(url)
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, ValueError):
            return None
        return meta if meta.get("url") == url and (meta.get("etag") or meta.get("last_modified")) else None

    def body(self, url: str, meta: dict) -> bytes | None:
        """The cached body, or None when it is missing or no longer matches its hash."""
        _, body_path = self._paths(url)
        try:
            body = body_path.read_bytes()
        except OSError:
            return None
        return body if hashlib.sha256(body).hexdigest() == meta.get("sha256") else None

    def store(self, url: str, body: bytes, headers: Headers) -> None:
        etag, modified = headers.get("ETag"), headers.get("Last-Modified")
        if not etag and not modified:
            return
        meta = {"url": url, "etag": etag, "last_modified": modified, "sha256": hashlib.sha256(body).hexdigest(),
                "bytes": len(body), "content_type": headers.get("Content-Type"), "stored_at": stamp()}
        meta_path, body_path = self._paths(url)
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            for path, data in ((body_path, body), (meta_path, json.dumps(meta).encode())):
                temporary = path.with_name(path.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
                temporary.write_bytes(data)
                temporary.replace(path)

    def forget(self, url: str) -> None:
        for path in self._paths(url):
            path.unlink(missing_ok=True)


def cache_from_environment(environ: Mapping[str, str] | None = None) -> HTTPCache | None:
    """`SKIPPERCAST_HTTP_CACHE`: unset/0 = off, 1 = `var/http-cache`, anything else = that directory."""
    value = ((os.environ if environ is None else environ).get("SKIPPERCAST_HTTP_CACHE") or "").strip()
    if value.lower() in ("", "0", "false", "no", "off"):
        return None
    if value.lower() in ("1", "true", "yes", "on"):
        return HTTPCache(repo_root() / "var/http-cache")
    return HTTPCache(Path(value).expanduser())


# ---- the session ------------------------------------------------------------------

@dataclass
class _Hop:
    status: int
    headers: Headers
    body: bytes | None
    final_url: str
    compressed_bytes: int | None
    size: int
    digest: str | None
    connected_address: tuple | None


def full_jitter(base: float, cap: float, rand: Callable[[], float]) -> Callable[[int], float]:
    """Delay before retry n (1-based): uniform in [0, min(cap, base * 2**(n-1))]."""
    return lambda retry: rand() * min(cap, base * 2 ** (retry - 1))


class Session:
    """Policy-enforcing HTTP client. Thread-safe; share one per job.

    `resolver`, `sleep`, `clock`, `wall_clock`, `rand`, `connection_factory` and
    `address_allowed` exist so tests can run offline and deterministically. `clock` is
    monotonic (per-host spacing); `wall_clock` is epoch seconds, used only to turn an
    HTTP-date `Retry-After` into a delay.
    """

    def __init__(self, *, allowed_hosts: Iterable[str] | Allowlist | None = None,
                 extra_hosts: Iterable[str] = (), user_agent: str = USER_AGENT,
                 timeout: float = DEFAULT_TIMEOUT, max_bytes: int | None = DEFAULT_MAX_BYTES,
                 attempts: int = DEFAULT_ATTEMPTS, retry_statuses: Iterable[int] = RETRY_STATUSES,
                 backoff_base: float = 1.0, backoff_cap: float = 30.0, retry_after_cap: float = 120.0,
                 min_interval: Mapping[str, float] | None = None,
                 cache: HTTPCache | Path | str | None = None,
                 context: ssl.SSLContext | None = None,
                 resolver: Callable[..., list] = socket.getaddrinfo,
                 address_allowed: Callable[[Any], bool] = public_address,
                 proxies: Mapping[str, str] | None = None,
                 ports: Iterable[int] = (443,), max_redirects: int = MAX_REDIRECTS,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time,
                 rand: Callable[[], float] = random.random,
                 connection_factory: Callable[..., http.client.HTTPConnection] | None = None):
        if isinstance(allowed_hosts, Allowlist):
            self.allowlist = allowed_hosts | extra_hosts if extra_hosts else allowed_hosts
        elif allowed_hosts is None:
            self.allowlist = default_allowlist(extra_hosts)
        else:
            self.allowlist = Allowlist([*allowed_hosts, *extra_hosts])
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.attempts = max(1, attempts)
        self.retry_statuses = frozenset(retry_statuses)
        self.backoff = full_jitter(backoff_base, backoff_cap, rand)
        self.retry_after_cap = retry_after_cap
        self.min_interval = {_normal_host(h): float(s) for h, s in (min_interval or {}).items()}
        self.cache = HTTPCache(cache) if isinstance(cache, (str, Path)) else cache
        self._context = context
        self.resolver = resolver
        self.address_allowed = address_allowed
        self.proxies = proxies
        self.ports = frozenset(ports)
        self.max_redirects = max_redirects
        self.sleep, self.clock, self.wall_clock = sleep, clock, wall_clock
        self.connection_factory = connection_factory
        self._lock = threading.Lock()
        self._next_request: dict[str, float] = {}

    @property
    def context(self) -> ssl.SSLContext:
        if self._context is None:
            self._context = tls_context()
        return self._context

    # -- policy checks

    def check_url(self, url: str, allowlist: Allowlist | None = None,
                  allowed_prefixes: tuple[str, ...] | None = None) -> tuple[str, int]:
        """(host, port) of an HTTPS URL this session may fetch, else DisallowedHost."""
        parts = urlsplit(url)
        try:
            port = parts.port or 443
        except ValueError as error:
            raise DisallowedHost(f"Invalid port in {url}") from error
        host = parts.hostname
        if parts.scheme != "https" or not host or parts.username or parts.password:
            raise DisallowedHost(f"Expected a public HTTPS URL: {url}")
        host = _normal_host(host)
        if port not in self.ports:
            raise DisallowedHost(f"Port {port} is not permitted: {url}")
        if host in {"localhost", "metadata.google.internal"} or host.endswith((".local", ".internal", ".localhost")):
            raise DisallowedHost("Internal source URL is not permitted")
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host:
                raise DisallowedHost("Source hostname must be public") from None
        else:
            if not self.address_allowed(literal):
                raise DisallowedHost("Non-public source address is not permitted")
        if not (allowlist or self.allowlist).allows(host):
            raise DisallowedHost(f"Host is not on the source allowlist: {host}")
        if allowed_prefixes is not None and not url.startswith(allowed_prefixes):
            raise DisallowedHost(f"URL is outside the reviewed prefixes: {url}")
        return host, port

    def resolve(self, host: str, port: int) -> list[tuple[int, tuple]]:
        """Resolve once; every address must pass the address policy."""
        try:
            infos = self.resolver(host, port, type=socket.SOCK_STREAM)
        except OSError as error:
            raise TransportError(f"DNS resolution failed for {host}: {error}") from error
        addresses: list[tuple[int, tuple]] = []
        for family, _type, _proto, _name, sockaddr in infos:
            try:
                address = ipaddress.ip_address(str(sockaddr[0]).split("%")[0])
            except ValueError as error:
                raise DisallowedHost(f"{host} resolved to an unparseable address") from error
            if not self.address_allowed(address):
                raise DisallowedHost("Source resolved to a non-public address")
            if (family, sockaddr) not in addresses:
                addresses.append((family, sockaddr))
        if not addresses:
            raise TransportError(f"{host} did not resolve")
        return addresses

    def _throttle(self, host: str) -> None:
        interval = self.min_interval.get(host)
        if not interval:
            return
        with self._lock:
            now = self.clock()
            ready = self._next_request.get(host, now)
            wait = max(0.0, ready - now)
            self._next_request[host] = max(now, ready) + interval
        if wait:
            self.sleep(wait)

    # -- one hop, one attempt

    def _connection(self, host: str, port: int, timeout: float) -> http.client.HTTPConnection:
        proxy = _proxy_for(host, self.proxies)
        if self.connection_factory is not None:
            addresses = [] if proxy else self.resolve(host, port)
            return self.connection_factory(host, port, addresses, context=self.context, timeout=timeout)
        if proxy:
            # The proxy resolves the name; the local check still refuses names that
            # resolve to private addresses here. Pinning applies to direct connections.
            self.resolve(host, port)
            return _proxy_connection(proxy, host, port, context=self.context, timeout=timeout,
                                     user_agent=self.user_agent)
        return PinnedHTTPSConnection(host, port, self.resolve(host, port), context=self.context, timeout=timeout)

    def _read(self, response: http.client.HTTPResponse, limit: int | None, sink: BinaryIO | None,
              digest: Any, truncate: bool = False) -> tuple[bytes | None, int]:
        declared = response.getheader("Content-Length")
        if (limit is not None and not truncate and declared and declared.strip().isdigit()
                and int(declared) > limit):
            raise BodyTooLarge("Response exceeds bounded collection size")
        parts, size = [], 0
        while True:
            chunk = response.read(CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if limit is not None and size > limit:
                if truncate and sink is None:  # a sample: keep limit + 1 bytes so callers see it was cut
                    parts.append(chunk[:len(chunk) - (size - limit - 1)])
                    return b"".join(parts), limit + 1
                raise BodyTooLarge("Response exceeds bounded collection size")
            if sink is None:
                parts.append(chunk)
            else:
                digest.update(chunk)
                sink.write(chunk)
        return (b"".join(parts) if sink is None else None), size

    def _decode(self, body: bytes, headers: Headers, limit: int | None) -> tuple[bytes, int | None]:
        encoding = (headers.get("Content-Encoding") or "identity").strip().lower()
        if encoding in ("", "identity"):
            return body, None
        if encoding not in ("gzip", "x-gzip"):
            raise ContractError("Unsupported response compression")
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            bound = 0 if limit is None else limit + 1
            decoded = decoder.decompress(body, bound)
            if limit is None:
                decoded += decoder.flush()
            elif decoder.unconsumed_tail or len(decoded) > limit:
                raise BodyTooLarge("Response exceeds bounded collection size")
        except zlib.error as error:
            raise ContractError(f"Corrupt gzip response: {error}") from error
        if not decoder.eof:
            raise ContractError("Truncated gzip response")
        return decoded, len(body)

    def _hop(self, method: str, url: str, headers: dict, timeout: float, limit: int | None,
             sink: BinaryIO | None, truncate: bool = False, data: bytes | None = None) -> _Hop:
        parts = urlsplit(url)
        host, port = _normal_host(parts.hostname or ""), parts.port or 443
        self._throttle(host)
        target = (parts.path or "/") + ("?" + parts.query if parts.query else "")
        connection = self._connection(host, port, timeout)
        try:
            try:
                if data is None:
                    connection.request(method, target, headers=headers)
                else:
                    connection.request(method, target, body=data, headers=headers)
                response = connection.getresponse()
                status = response.status
                response_headers = Headers(response.getheaders())
                if method == "HEAD" or status in REDIRECT_STATUSES or status == 304:
                    return _Hop(status, response_headers, b"", url, None, 0, None,
                                getattr(connection, "connected_address", None))
                streaming = sink is not None and 200 <= status < 300
                digest = hashlib.sha256() if streaming else None
                body, size = self._read(response, limit, sink if streaming else None, digest, truncate)
            except ssl.SSLCertVerificationError as error:
                raise TLSVerificationError(
                    f"TLS certificate for {host} did not verify ({error.verify_message}); fix the local trust "
                    "store (install the 'tls' extra for truststore, or update CA certificates)") from error
            except (ssl.SSLError, OSError, http.client.HTTPException) as error:
                if isinstance(error, SourceError):
                    raise
                raise TransportError(f"{type(error).__name__}: {error}") from error
        finally:
            connection.close()
        compressed = None
        if body is not None and not truncate:
            body, compressed = self._decode(body, response_headers, limit)
        return _Hop(status, response_headers, body, url, compressed, size if body is None else len(body),
                    digest.hexdigest() if digest else None, getattr(connection, "connected_address", None))

    def _fetch(self, method: str, url: str, headers: dict, timeout: float, limit: int | None,
               sink: BinaryIO | None, follow: bool | str, allowlist: Allowlist | None,
               prefixes: tuple[str, ...] | None, truncate: bool = False, data: bytes | None = None) -> _Hop:
        current = url
        for _ in range(self.max_redirects + 1):
            self.check_url(current, allowlist, prefixes)
            hop = self._hop(method, current, headers, timeout, limit, sink, truncate, data)
            location = hop.headers.get("Location")
            if hop.status not in REDIRECT_STATUSES or not location:
                return hop
            if follow == "return":  # the caller handles redirects itself
                return hop
            if not follow:
                raise ContractError(f"Redirect refused: {current} -> {location}")
            current = urljoin(current, location)
            if (hop.status == 303 and method != "HEAD") or (hop.status in (301, 302) and method == "POST"):
                method, data = "GET", None  # a form POST is re-requested as a GET without its body
                headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
        raise ContractError(f"More than {self.max_redirects} redirects from {url}")

    # -- public API

    def request(self, method: str, url: str, *, headers: Mapping[str, str] | None = None,
                timeout: float | None = None, max_bytes: int | None | object = ...,
                attempts: int | None = None, retry_statuses: Iterable[int] | None = None,
                ok_statuses: Iterable[int] | None = None, raise_for_status: bool = True,
                follow_redirects: bool | str = True, allowed_hosts: Iterable[str] | None = None,
                allowed_prefixes: Iterable[str] | None = None, use_cache: bool = True,
                backoff: Callable[[int], float] | None = None, sink: BinaryIO | None = None,
                truncate: bool = False, cache: HTTPCache | None | object = ...,
                data: bytes | None = None) -> Response:
        """One logical request with retries. Returns a Response or raises a SourceError.

        `data` is a request body (a form POST). A request with a body is never
        cached. A 301, 302 or 303 redirect re-requests it as a GET without the body;
        a 307 or 308 redirect keeps the method and the body.

        `ok_statuses` defaults to any 2xx; with `raise_for_status=False` any final
        status is returned. `sink` streams a 2xx body to a seekable file instead of
        memory (no decoding, no cache; the file is rewound before each attempt).
        `truncate=True` samples: the body is cut at `max_bytes + 1` bytes instead of
        failing, is not decoded, and the receipt's `truncated` says whether it was cut.
        `follow_redirects="return"` returns a redirect response unfollowed (with
        `raise_for_status=False`), for a caller that checks each hop itself.
        `cache` replaces the session's conditional-GET cache for this request (None: no cache),
        so one session can serve callers that keep their own cache directory.
        """
        store = self.cache if cache is ... else cache
        limit = self.max_bytes if max_bytes is ... else max_bytes
        timeout = self.timeout if timeout is None else timeout
        attempts = self.attempts if attempts is None else max(1, attempts)
        if sink is not None and not getattr(sink, "seekable", lambda: False)():
            attempts = 1
        retry = self.retry_statuses if retry_statuses is None else frozenset(retry_statuses)
        ok = None if ok_statuses is None else frozenset(ok_statuses)
        allowlist = Allowlist(allowed_hosts) if allowed_hosts is not None else None
        prefixes = tuple(allowed_prefixes) if allowed_prefixes is not None else None
        backoff = backoff or self.backoff
        method = method.upper()
        base_headers = {"User-Agent": self.user_agent, "Accept": "*/*", "Connection": "close"}
        for name, value in (headers or {}).items():
            base_headers = {k: v for k, v in base_headers.items() if k.lower() != name.lower()}
            base_headers[name] = value
        cacheable = (store is not None and use_cache and method == "GET" and sink is None and not truncate
                     and data is None
                     and not any(k.lower() == "range" for k in base_headers))
        receipt = Receipt(url=url, method=method)
        started = self.clock()

        def fail(error: SourceError) -> SourceError:
            receipt.error_class = error.error_class
            receipt.error = f"{error.error_class}: {str(error)[:220]}"
            receipt.elapsed_ms = int((self.clock() - started) * 1000)
            error.receipt = receipt
            return error

        # Refuse a URL outside policy before any network activity.
        try:
            self.check_url(url, allowlist, prefixes)
        except DisallowedHost as error:
            raise fail(error)
        for attempt in range(1, attempts + 1):
            row: dict = {"attempt": attempt, "started_at": stamp()}
            receipt.history.append(row)
            receipt.attempts = attempt
            attempt_started = self.clock()
            cached = store.lookup(url) if cacheable and store else None
            request_headers = dict(base_headers)
            if cached:
                if cached.get("etag"):
                    request_headers["If-None-Match"] = cached["etag"]
                if cached.get("last_modified"):
                    request_headers["If-Modified-Since"] = cached["last_modified"]
            delay = None
            try:
                if sink is not None:
                    sink.seek(0)
                    sink.truncate()
                hop = self._fetch(method, url, request_headers, timeout, limit, sink, follow_redirects,
                                  allowlist, prefixes, truncate, data)
                from_cache = False
                if hop.status == 304 and cached and store:
                    body = store.body(url, cached)
                    if body is None:  # cache damaged: refetch without validators
                        store.forget(url)
                        hop = self._fetch(method, url, dict(base_headers), timeout, limit, None,
                                          follow_redirects, allowlist, prefixes)
                    else:
                        hop.body, hop.size, from_cache = body, len(body), True
                row.update(status=hop.status, elapsed_ms=int((self.clock() - attempt_started) * 1000))
                receipt.status, receipt.final_url = hop.status, hop.final_url
                accepted = from_cache or (hop.status in ok if ok is not None else 200 <= hop.status < 300)
                if not accepted and hop.status in retry and attempt < attempts:
                    wait = parse_retry_after(hop.headers.get("Retry-After"), now=self.wall_clock())
                    delay = min(wait, self.retry_after_cap) if wait is not None else backoff(attempt)
                    row.update(error_class="HTTPStatusError", retry_in_s=round(delay, 3))
                elif not accepted and raise_for_status:
                    error = HTTPStatusError(f"HTTP {hop.status} from {urlsplit(hop.final_url).hostname}",
                                            hop.status, hop.headers, hop.body or b"")
                    row["error_class"] = error.error_class
                    raise fail(error)
                else:
                    body = hop.body
                    receipt.from_cache = from_cache
                    receipt.bytes = hop.size
                    receipt.sha256 = hop.digest if body is None else hashlib.sha256(body).hexdigest()
                    receipt.compressed_bytes = hop.compressed_bytes
                    receipt.truncated = bool(truncate and limit is not None and hop.size > limit)
                    receipt.http_date = hop.headers.get("Date")
                    receipt.content_type = hop.headers.get("Content-Type") or (cached or {}).get("content_type")
                    receipt.last_modified = hop.headers.get("Last-Modified") or (cached or {}).get("last_modified")
                    receipt.etag = hop.headers.get("ETag") or (cached or {}).get("etag")
                    if cacheable and store and not from_cache and hop.status == 200 and body is not None:
                        store.store(url, body, hop.headers)
                    receipt.elapsed_ms = int((self.clock() - started) * 1000)
                    return Response(url, hop.final_url, hop.status, hop.headers, body, receipt)
            except HTTPStatusError:
                raise
            except TransportError as error:
                row.update(error_class=error.error_class, error=str(error)[:220],
                           elapsed_ms=int((self.clock() - attempt_started) * 1000))
                if isinstance(error, TLSVerificationError) or attempt == attempts:
                    raise fail(error)
                delay = backoff(attempt)
                row["retry_in_s"] = round(delay, 3)
            except (ContractError, DisallowedHost) as error:
                row.update(error_class=error.error_class, error=str(error)[:220])
                raise fail(error)
            if delay:
                self.sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def get(self, url: str, **options: Any) -> Response:
        return self.request("GET", url, **options)

    def post(self, url: str, data: bytes, **options: Any) -> Response:
        return self.request("POST", url, data=data, **options)

    def head(self, url: str, **options: Any) -> Response:
        return self.request("HEAD", url, **options)

    def download(self, url: str, sink: BinaryIO, **options: Any) -> Response:
        """Stream a 2xx body into `sink` (bounded by `max_bytes`); the receipt has its size and sha256."""
        return self.request("GET", url, sink=sink, **options)


# ---- shared default session and test double ---------------------------------------

_default: Session | None = None
_default_lock = threading.Lock()


def default_session() -> Session:
    """The process-wide Session (default allowlist; cache per SKIPPERCAST_HTTP_CACHE)."""
    global _default
    with _default_lock:
        if _default is None:
            _default = Session(cache=cache_from_environment())
        return _default


def set_default_session(session: Session | None) -> None:
    """Replace (or with None, reset) the process-wide Session."""
    global _default
    with _default_lock:
        _default = session


class FakeSession:
    """Offline stand-in: `routes` maps URL -> bytes, (status, bytes[, headers]), an exception or a callable.

    Records every call in `calls` as (method, url, options). Unknown URLs raise TransportError.
    """

    def __init__(self, routes: Mapping[str, Any] | None = None):
        self.routes = dict(routes or {})
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **options: Any) -> Response:
        self.calls.append((method.upper(), url, options))
        route = self.routes.get(url, TransportError(f"FakeSession has no route for {url}"))
        if callable(route) and not isinstance(route, type):
            route = route(method.upper(), url, options)
        if isinstance(route, BaseException):
            raise route
        status, body, headers = 200, route, {}
        if isinstance(route, tuple):
            status, body, headers = (route + ({},))[:3]
        receipt = Receipt(url=url, method=method.upper(), final_url=url, status=status, attempts=1,
                          bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
        response = Response(url, url, status, Headers(headers.items()), body, receipt)
        if options.get("raise_for_status", True) and not 200 <= status < 300:
            error = HTTPStatusError(f"HTTP {status}", status, response.headers, body)
            error.receipt = receipt
            raise error
        sink = options.get("sink")
        if sink is not None:
            sink.write(body)
            response.body = None
        return response

    def get(self, url: str, **options: Any) -> Response:
        return self.request("GET", url, **options)

    def head(self, url: str, **options: Any) -> Response:
        return self.request("HEAD", url, **options)

    def post(self, url: str, data: bytes, **options: Any) -> Response:
        return self.request("POST", url, data=data, **options)

    def download(self, url: str, sink: BinaryIO, **options: Any) -> Response:
        return self.request("GET", url, sink=sink, **options)
