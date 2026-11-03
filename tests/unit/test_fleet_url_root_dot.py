"""RF0720-8: ``clean_url`` folds one trailing root dot on the host; a dot-only host is not a URL.

Synthetic example.com URLs only; no network.
"""
import unittest

from skippercast.fleet.adapters.base import Candidate, Fact
from skippercast.fleet.normalize import clean_url
from skippercast.fleet.resolve import ResolverConfig, _normal_value, fingerprint

NOW = "2026-10-05T09:47:00.000Z"
CONFIG = ResolverConfig("CA", {}, 0.9, 0.6, {}, {})


def fact(url, field="website"):
    return Fact(field, url, "operator-site", url, "page", 0.9, "facts-only", NOW)


class RootDotTests(unittest.TestCase):
    def test_trailing_dot_folded_with_tracking_and_fragment_stripped(self):
        self.assertEqual(clean_url("https://Boat.Example.com./book?utm_source=x&trip=half#top"),
                         "https://boat.example.com/book?trip=half")

    def test_trailing_dot_folded_before_port(self):
        self.assertEqual(clean_url("https://boat.example.com.:8443/"), "https://boat.example.com:8443/")
        self.assertEqual(clean_url("https://BOAT.example.com.:8443/x"), "https://boat.example.com:8443/x")

    def test_dot_only_or_double_dot_host_is_none(self):
        for url in ("https://./", "https://../", "https://boat.example.com../", "https://.:8443/", "https://./book",
                    "https://boat.example.com..:8443/"):
            with self.subTest(url=url):
                self.assertIsNone(clean_url(url))

    def test_ipv6_untouched_port_kept(self):
        self.assertEqual(clean_url("https://[2001:db8::1]:443/path"), "https://[2001:db8::1]:443/path")
        self.assertEqual(clean_url("https://[2001:DB8::1]/"), "https://[2001:db8::1]/")

    def test_not_https_still_none_with_dot(self):
        self.assertIsNone(clean_url("http://boat.example.com./"))
        self.assertIsNone(clean_url("ftp://boat.example.com./"))
        self.assertIsNone(clean_url("https://user@boat.example.com./"))
        self.assertIsNone(clean_url("https://boat.example.com.:bad/"))

    def test_undotted_host_unchanged(self):
        self.assertEqual(clean_url("https://boat.example.com/"), "https://boat.example.com/")
        self.assertEqual(clean_url("https://boat.example.com"), "https://boat.example.com/")
        self.assertEqual(clean_url("https://boat.example.com/a.b./?x=1."), "https://boat.example.com/a.b./?x=1.")

    def test_dot_in_path_or_query_is_not_folded(self):
        self.assertEqual(clean_url("https://boat.example.com./trip."), "https://boat.example.com/trip.")

    def test_dotted_and_undotted_spellings_are_one_source(self):
        dotted, plain = "https://boat.example.com./book", "https://boat.example.com/book"
        self.assertEqual(clean_url(dotted), clean_url(plain))
        both = Candidate("operator-site", "Example Test", "morro-bay", facts=(fact(dotted), fact(plain)))
        one = Candidate("operator-site", "Example Test", "morro-bay", facts=(fact(plain),))
        dot = Candidate("operator-site", "Example Test", "morro-bay", facts=(fact(dotted),))
        self.assertEqual(fingerprint(both), fingerprint(one))
        self.assertEqual(fingerprint(dot), fingerprint(one))
        self.assertTrue(fingerprint(dot).endswith("|" + plain))
        urls = {u for f in both.facts if (u := clean_url(f.source_url))}
        self.assertEqual(urls, {plain})
        self.assertEqual(_normal_value("website", dotted, CONFIG), _normal_value("website", plain, CONFIG))
        self.assertEqual(_normal_value("booking_url", dotted, CONFIG), plain)

    def test_dot_only_host_is_not_a_source(self):
        bare = Candidate("operator-site", "Example Test", "morro-bay", facts=(fact("https://./"),))
        self.assertTrue(fingerprint(bare).endswith("|"))
        self.assertEqual(_normal_value("website", "https://./", CONFIG), "https://./")


if __name__ == "__main__":
    unittest.main()
