"""Fleet session: only the internal robots lookup is uncounted; content /robots.txt requests are budgeted.

Offline and socket-free: the real FleetSession and http.Session run (redirect hops,
robots re-entry, budget and interval), with only the resolver and the connection
factory replaced by in-memory fakes.
"""
import io
import socket
import unittest

from skippercast.fleet.net import ROBOTS_TTL, FleetSession, Skipped

HOST = "reports.example.org"
OFF_LIMITS = ("fareharbor.com",)
ALLOW_ALL = b"User-agent: *\nDisallow:\n"


class _Response:
    def __init__(self, status, headers, body):
        self.status, self._headers, self._body = status, headers, io.BytesIO(body)

    def getheaders(self):
        return list(self._headers.items())

    def getheader(self, name, default=None):
        return {k.lower(): v for k, v in self._headers.items()}.get(name.lower(), default)

    def read(self, size=-1):
        return self._body.read(size)


class _Connection:
    def __init__(self, world, host):
        self.world, self.host, self.sent = world, host, None

    def request(self, method, target, body=None, headers=None):
        self.sent = (method, target, body)
        self.world.calls.append((self.host, method, target, body))

    def getresponse(self):
        method, target, _body = self.sent  # type: ignore[misc]
        route = self.world.routes[(self.host, target.split("?")[0])]
        if isinstance(route, Exception):
            raise route
        return _Response(*route)

    def close(self):
        pass


class _World:
    """Routes map (host, path) to (status, headers, body), or to an exception to raise."""

    def __init__(self, hosts=(HOST,), robots=ALLOW_ALL, **session_options):
        self.calls, self.slept, self.resolved, self.now = [], [], [], [100.0]
        self.routes = {}
        for host in hosts:
            self.routes[(host, "/robots.txt")] = (200, {}, robots)
            self.routes[(host, "/go")] = (302, {"Location": "/robots.txt"}, b"")
            self.routes[(host, "/a")] = (200, {}, b"a")
            self.routes[(host, "/b")] = (200, {}, b"b")
            self.routes[(host, "/c")] = (200, {}, b"c")
        options: dict = dict(budget=3, interval=0, attempts=1, cache=None, proxies={})
        options.update(session_options)
        self.net = FleetSession(set(hosts), OFF_LIMITS, sleep=self._sleep, clock=lambda: self.now[0],
                                connection_factory=lambda host, port, addresses, context=None, timeout=None:
                                _Connection(self, host),
                                resolver=self._resolve, **options)

    def _sleep(self, seconds):
        self.slept.append(round(seconds, 3))
        self.now[0] += seconds

    def _resolve(self, host, port, type=None):
        self.resolved.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    def paths(self):
        return [(method, target) for _host, method, target, _body in self.calls]


def _url(path, host=HOST):
    return f"https://{host}{path}"


class RobotsBudgetTests(unittest.TestCase):
    def test_direct_robots_content_consumes_budget(self):
        world = _World(budget=1)
        self.assertEqual(world.net.get(_url("/robots.txt")).body, ALLOW_ALL)
        self.assertEqual(world.net.used, {HOST: 1})
        self.assertEqual(world.paths(), [("GET", "/robots.txt"), ("GET", "/robots.txt")])  # policy, then content
        before = (list(world.calls), list(world.resolved))
        with self.assertRaises(Skipped) as caught:
            world.net.get(_url("/robots.txt"))
        self.assertEqual(caught.exception.reason, "budget")
        self.assertEqual((world.calls, world.resolved), before)  # no connection, no DNS lookup

    def test_direct_robots_query_variant_consumes_budget(self):
        world = _World(budget=1)
        world.net.get(_url("/robots.txt?variant=1"))
        self.assertEqual(world.net.used, {HOST: 1})
        with self.assertRaises(Skipped) as caught:
            world.net.get(_url("/a"))
        self.assertEqual(caught.exception.reason, "budget")

    def test_redirect_to_robots_cannot_exceed_budget(self):
        world = _World(budget=1)
        with self.assertRaises(Skipped) as caught:
            world.net.get(_url("/go"))
        self.assertEqual(caught.exception.reason, "budget-redirect")
        self.assertEqual(world.paths(), [("GET", "/robots.txt"), ("GET", "/go")])  # target never connected
        self.assertEqual(world.net.used, {HOST: 1})
        self.assertEqual(world.net.skips[-1]["reason"], "budget-redirect")

    def test_redirect_to_robots_counts_both_hops_within_budget(self):
        world = _World(budget=2)
        self.assertEqual(world.net.get(_url("/go")).body, ALLOW_ALL)
        self.assertEqual(world.net.used, {HOST: 2})
        self.assertEqual(world.paths(), [("GET", "/robots.txt"), ("GET", "/go"), ("GET", "/robots.txt")])

    def test_post_robots_is_not_internal(self):
        world = _World(budget=1)
        world.net.post(_url("/robots.txt"), b"q=synthetic")
        self.assertIn((HOST, "POST", "/robots.txt", b"q=synthetic"), world.calls)
        self.assertEqual(world.net.used, {HOST: 1})
        with self.assertRaises(Skipped) as caught:
            world.net.get(_url("/a"))
        self.assertEqual(caught.exception.reason, "budget")

    def test_internal_policy_redirects_remain_exempt(self):
        other = "www." + HOST
        world = _World(hosts=(HOST, other), interval=1.0)
        world.routes[(HOST, "/robots.txt")] = (301, {"Location": _url("/robots.txt", other)}, b"")
        self.assertEqual(world.net.get(_url("/a")).body, b"a")
        self.assertEqual(world.net.used, {HOST: 1})  # the policy chain is uncounted, the content request once
        self.assertEqual(world.calls[:2], [(HOST, "GET", "/robots.txt", None), (other, "GET", "/robots.txt", None)])
        self.assertEqual(world.calls[2], (HOST, "GET", "/a", None))
        self.assertEqual(world.slept, [1.0])  # /a waits out the interval started by the policy hop on HOST

    def test_robots_policy_applies_to_content_redirect(self):
        world = _World(robots=b"User-agent: SkipperCast\nDisallow: /robots.txt\n")
        with self.assertRaises(Skipped) as caught:
            world.net.get(_url("/go"))
        self.assertEqual(caught.exception.reason, "robots-redirect")
        self.assertEqual(world.paths(), [("GET", "/robots.txt"), ("GET", "/go")])  # refused before connecting
        with self.assertRaises(Skipped) as caught:
            world.net.get(_url("/robots.txt"))
        self.assertEqual(caught.exception.reason, "robots")
        self.assertEqual(world.paths().count(("GET", "/robots.txt")), 1)  # policy fetched once, never recursively

    def test_normal_paths_and_host_isolation_unchanged(self):
        other = "other.example.org"
        world = _World(hosts=(HOST, other), interval=1.0)
        for path in ("/a", "/b", "/c"):
            world.net.get(_url(path))
        with self.assertRaises(Skipped) as caught:
            world.net.get(_url("/a"))
        self.assertEqual(caught.exception.reason, "budget")
        self.assertEqual(world.net.get(_url("/a", other)).body, b"a")  # a different host has its own budget
        self.assertEqual(world.net.used, {HOST: 3, other: 1})
        self.assertEqual(world.paths().count(("GET", "/robots.txt")), 2)  # one policy fetch per host
        for url, reason in ((_url("/a", "unlisted.example.net"), "not-allowlisted"),
                            ("https://fareharbor.com/a", "off-limits")):
            with self.assertRaises(Skipped) as caught:
                world.net.get(url)
            self.assertEqual(caught.exception.reason, reason)


class ContextRestoredTests(unittest.TestCase):
    """After any internal policy outcome, a later content /robots.txt request is counted again."""

    def assert_counted_after(self, world):
        world.now[0] += ROBOTS_TTL + 1  # the failed policy ages out; a healthy one is fetched next
        world.routes[(HOST, "/robots.txt")] = (200, {}, ALLOW_ALL)
        before = world.net.used.get(HOST, 0)
        world.net.get(_url("/robots.txt"))
        self.assertEqual(world.net.used.get(HOST, 0), before + 1)

    def test_transport_failure(self):
        world = _World()
        world.routes[(HOST, "/robots.txt")] = OSError("boom")
        with self.assertRaises(Skipped) as caught:
            world.net.get(_url("/a"))
        self.assertEqual(caught.exception.reason, "robots")  # fail closed, unchanged
        self.assertEqual(world.net.used, {})
        self.assert_counted_after(world)

    def test_http_denial(self):
        world = _World()
        world.routes[(HOST, "/robots.txt")] = (403, {}, b"")
        with self.assertRaises(Skipped) as caught:
            world.net.get(_url("/a"))
        self.assertEqual(caught.exception.reason, "robots")
        self.assertEqual(world.net.used, {})
        self.assert_counted_after(world)

    def test_redirect_cap(self):
        world = _World()
        world.routes[(HOST, "/robots.txt")] = (302, {"Location": _url("/robots.txt")}, b"")
        with self.assertRaises(Skipped) as caught:
            world.net.get(_url("/a"))
        self.assertEqual(caught.exception.reason, "robots")
        self.assertEqual(world.paths(), [("GET", "/robots.txt")] * 6)  # ROBOTS_HOPS + 1, all uncounted
        self.assertEqual(world.net.used, {})
        self.assert_counted_after(world)

    def test_unexpected_exception_propagates(self):
        world = _World()
        world.routes[(HOST, "/robots.txt")] = RuntimeError("unexpected")
        with self.assertRaises(RuntimeError):
            world.net.get(_url("/a"))
        self.assertEqual(world.net.used, {})
        world.routes[(HOST, "/robots.txt")] = (200, {}, ALLOW_ALL)
        world.net.get(_url("/robots.txt"))
        self.assertEqual(world.net.used, {HOST: 1})

    def test_ttl_expiry_refetch_does_not_exempt_content(self):
        world = _World()
        world.net.get(_url("/a"))
        world.now[0] += ROBOTS_TTL + 1
        world.net.get(_url("/robots.txt"))  # re-fetches the policy (uncounted), then counts itself
        self.assertEqual(world.net.used, {HOST: 2})
        self.assertEqual(world.paths(), [("GET", "/robots.txt"), ("GET", "/a"),
                                         ("GET", "/robots.txt"), ("GET", "/robots.txt")])


if __name__ == "__main__":
    unittest.main()
