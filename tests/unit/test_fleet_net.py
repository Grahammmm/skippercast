"""Fleet HTTP session: off-limits deny (incl. redirects), allowlist, robots, interval, budget.

Offline: a local plain-HTTP server stands in for every host. The session's
connection factory points each hop at it, and records the host it was asked to
connect to, so a refused URL can be shown to open no connection.
"""
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
import unittest

from skippercast.fleet.net import FleetSession, Skipped, binding_hosts
from skippercast.fleet.config import load_region

OFF_LIMITS = ("fareharbor.com", "instagram.com")
ROBOTS = b"User-agent: SkipperCast\nDisallow: /private\n\nUser-agent: *\nDisallow:\n"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.paths.append(self.path)
        if self.path == "/robots.txt":
            status, body, headers = 200, ROBOTS, {}
        elif self.path == "/redirect":
            status, body, headers = 302, b"", {"Location": "https://www.fareharbor.com/embeds/book/x"}
        elif self.path == "/away":
            status, body, headers = 302, b"", {"Location": "https://unlisted.example.net/x"}
        elif self.path.startswith("/hop"):
            status, body, headers = 302, b"", {"Location": "/b"}
        elif self.path == "/to-private":
            status, body, headers = 302, b"", {"Location": "/private/x"}
        else:
            status, body, headers = 200, b"page " + self.path.encode(), {}
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class FleetSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.server.paths = []
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.server.paths.clear()
        self.connected = []
        self.slept = []
        self.now = [100.0]

        def factory(host, port, addresses, context=None, timeout=None):
            self.connected.append(host)
            return HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=timeout)

        self.resolved = []

        def resolver(host, port, type=None):
            self.resolved.append(host)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

        def sleep(seconds):
            self.slept.append(round(seconds, 3))
            self.now[0] += seconds

        self.net = FleetSession({"www.example-landing.com", "reports.example.org"}, OFF_LIMITS,
                                budget=3, sleep=sleep, clock=lambda: self.now[0],
                                connection_factory=factory, resolver=resolver, attempts=1)

    def test_off_limits_url_refused_before_any_connection(self):
        self.net.allow_host("www.fareharbor.com")  # even an explicitly allowed off-limits host stays denied
        with self.assertRaises(Skipped) as caught:
            self.net.get("https://www.fareharbor.com/embeds/book/x")
        self.assertEqual(caught.exception.reason, "off-limits")
        self.assertEqual(self.connected, [])
        self.assertEqual(self.resolved, [])  # not even a DNS lookup
        self.assertEqual(self.server.paths, [])
        self.assertEqual(self.net.skips[0]["reason"], "off-limits")

    def test_redirect_to_off_limits_host_refused_before_connecting(self):
        self.net.allow_host("www.fareharbor.com")
        with self.assertRaises(Skipped) as caught:
            self.net.get("https://www.example-landing.com/redirect")
        self.assertEqual(caught.exception.reason, "off-limits-redirect")
        self.assertEqual(self.server.paths, ["/robots.txt", "/redirect"])
        self.assertNotIn("www.fareharbor.com", self.connected)

    def test_robots_disallowed_path_is_a_recorded_skip(self):
        with self.assertRaises(Skipped) as caught:
            self.net.get("https://www.example-landing.com/private/boats")
        self.assertEqual(caught.exception.reason, "robots")
        self.assertEqual(self.net.skips, [{"url": "https://www.example-landing.com/private/boats",
                                           "reason": "robots", "detail": "www.example-landing.com"}])
        self.assertEqual(self.net.get("https://www.example-landing.com/fleet.php").body, b"page /fleet.php")
        self.assertEqual(self.server.paths, ["/robots.txt", "/fleet.php"])  # robots.txt fetched once

    def test_host_not_on_allowlist_is_skipped(self):
        with self.assertRaises(Skipped) as caught:
            self.net.get("https://unlisted.example.net/")
        self.assertEqual(caught.exception.reason, "not-allowlisted")
        self.assertEqual(self.connected, [])

    def test_interval_and_budget_per_host(self):
        for path in ("/a", "/b", "/c"):
            self.net.get("https://reports.example.org" + path)
        self.assertEqual(self.slept, [1.0, 1.0, 1.0])  # robots, then /a, /b, /c a second apart
        with self.assertRaises(Skipped) as caught:
            self.net.get("https://reports.example.org/d")
        self.assertEqual(caught.exception.reason, "budget")
        self.assertEqual(self.net.used, {"reports.example.org": 3})

    def test_redirect_off_the_allowlist_is_a_recorded_skip(self):
        with self.assertRaises(Skipped) as caught:
            self.net.get("https://www.example-landing.com/away")
        self.assertEqual(caught.exception.reason, "not-allowlisted-redirect")
        self.assertEqual(self.net.skips[-1]["reason"], "not-allowlisted-redirect")
        self.assertNotIn("unlisted.example.net", self.connected + self.resolved)

    def test_redirect_hops_count_against_interval_budget_and_robots(self):
        self.assertEqual(self.net.get("https://reports.example.org/hop").body, b"page /b")
        self.assertEqual(self.net.used, {"reports.example.org": 2})  # /hop and its redirect to /b
        self.assertEqual(self.slept, [1.0, 1.0])
        with self.assertRaises(Skipped) as caught:
            self.net.get("https://reports.example.org/hop2")  # third request is in budget, its redirect is not
        self.assertEqual(caught.exception.reason, "budget-redirect")
        with self.assertRaises(Skipped) as caught:
            self.net.get("https://www.example-landing.com/to-private")
        self.assertEqual(caught.exception.reason, "robots-redirect")
        self.assertNotIn("/private/x", self.server.paths)

    def test_region_binding_hosts_exclude_off_limits(self):
        region = load_region("CA")
        hosts = binding_hosts(region)
        self.assertIn("www.socalfishreports.com", hosts)
        self.assertFalse([h for h in hosts if any(h == b or h.endswith("." + b) for b in region.off_limits)])


if __name__ == "__main__":
    unittest.main()
