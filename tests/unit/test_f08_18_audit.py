"""F08-18: a robots.txt lookup that is still rate-limited (429) is "unavailable", not "no rules".

Contract protected: a final 429 on /robots.txt fails closed (zero content requests, skip reason
``robots-rate-limited``), is retried only after a short cooldown rather than cached allow-all for
24 h, and a genuinely absent robots.txt (404) still means allowed.
Believable bug: the general ``>= 400`` branch treats 429 like 404, so the host's content is fetched
and "allow all" is cached for ROBOTS_TTL while the site is merely throttling us.

Offline and socket-free: reuses the in-memory connection world of test_fleet_net_robots_budget.
"""
import unittest

from skippercast.fleet.net import ROBOTS_LIMITED_TTL, ROBOTS_TTL, Skipped
from tests.unit.test_fleet_net_robots_budget import ALLOW_ALL, HOST, _url, _World

LIMITED = (429, {"Retry-After": "1"}, b"")


class RobotsRateLimitedTests(unittest.TestCase):
    def test_final_429_fails_closed_with_zero_content_requests(self):
        world = _World()
        world.routes[(HOST, "/robots.txt")] = LIMITED
        with self.assertRaises(Skipped) as caught:
            world.net.get(_url("/a"))
        self.assertEqual(caught.exception.reason, "robots-rate-limited")
        self.assertEqual(world.paths(), [("GET", "/robots.txt")])  # the policy lookup only
        self.assertEqual(world.net.skips[-1]["reason"], "robots-rate-limited")
        self.assertEqual(world.net.used, {})  # nothing counted against the content budget
        with self.assertRaises(Skipped):  # POST is gated by the same policy
            world.net.post(_url("/a"), b"q=synthetic")
        self.assertEqual(world.paths(), [("GET", "/robots.txt")])

    def test_retry_is_bounded_by_the_http_attempts_then_stops(self):
        world = _World(attempts=3)
        world.routes[(HOST, "/robots.txt")] = LIMITED
        with self.assertRaises(Skipped):
            world.net.get(_url("/a"))
        self.assertEqual(world.paths(), [("GET", "/robots.txt")] * 3)  # exactly `attempts`, no more
        with self.assertRaises(Skipped):  # inside the cooldown: no further lookup at all
            world.net.get(_url("/b"))
        self.assertEqual(world.paths().count(("GET", "/robots.txt")), 3)
        self.assertNotIn(("GET", "/a"), world.paths())

    def test_lookup_is_retried_after_the_short_cooldown_not_24_hours(self):
        self.assertLess(ROBOTS_LIMITED_TTL, ROBOTS_TTL)
        world = _World()
        world.routes[(HOST, "/robots.txt")] = LIMITED
        with self.assertRaises(Skipped):
            world.net.get(_url("/a"))
        world.routes[(HOST, "/robots.txt")] = (200, {}, ALLOW_ALL)  # the throttle lifts
        world.now[0] += ROBOTS_LIMITED_TTL + 1
        self.assertEqual(world.net.get(_url("/a")).body, b"a")
        self.assertEqual(world.paths(), [("GET", "/robots.txt"), ("GET", "/robots.txt"), ("GET", "/a")])
        self.assertEqual(world.net.get(_url("/b")).body, b"b")  # now cached for the normal 24 h
        self.assertEqual(world.paths().count(("GET", "/robots.txt")), 2)

    def test_429_on_a_followed_robots_redirect_is_also_unavailable(self):
        world = _World(hosts=(HOST, "www." + HOST))
        world.routes[(HOST, "/robots.txt")] = (301, {"Location": _url("/robots.txt", "www." + HOST)}, b"")
        world.routes[("www." + HOST, "/robots.txt")] = LIMITED
        with self.assertRaises(Skipped) as caught:
            world.net.get(_url("/a"))
        self.assertEqual(caught.exception.reason, "robots-rate-limited")
        self.assertNotIn(("GET", "/a"), world.paths())

    def test_absent_robots_file_still_means_allowed(self):  # positive control
        for status in (404, 410):
            with self.subTest(status=status):
                world = _World()
                world.routes[(HOST, "/robots.txt")] = (status, {}, b"")
                self.assertEqual(world.net.get(_url("/a")).body, b"a")
                self.assertEqual(world.net.skips, [])

    def test_401_403_and_5xx_still_fail_closed_with_the_robots_reason(self):
        for status in (401, 403, 500):
            with self.subTest(status=status):
                world = _World()
                world.routes[(HOST, "/robots.txt")] = (status, {}, b"")
                with self.assertRaises(Skipped) as caught:
                    world.net.get(_url("/a"))
                self.assertEqual(caught.exception.reason, "robots")


if __name__ == "__main__":
    unittest.main()
