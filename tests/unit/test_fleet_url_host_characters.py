"""clean_url refuses hostnames containing whitespace or control characters (synthetic strings only)."""

from __future__ import annotations

import unittest

from skippercast.fleet.normalize import clean_url


class HostCharacterTests(unittest.TestCase):
    def test_hostname_whitespace_refuses(self) -> None:
        for url in (
            "https://boat .example.com/",
            "https://boat\xa0.example.com/",
            "https://boat\u2003.example.com:8443/book",
            "https://boat .example.com./",
        ):
            with self.subTest(url=url):
                self.assertIsNone(clean_url(url))

    def test_hostname_surviving_controls_refuse(self) -> None:
        for url in (
            "https://boat\x00.example.com/",
            "https://boat\x1f.example.com/",
            "https://boat\x7f.example.com:443/",
        ):
            with self.subTest(url=url):
                self.assertIsNone(clean_url(url))

    def test_hostname_check_does_not_scan_path_or_query(self) -> None:
        self.assertEqual(
            clean_url("  https://boat.example.com/a%20b?q=x+y&utm_source=z#top  "),
            "https://boat.example.com/a%20b?q=x+y",
        )

    def test_valid_host_and_port_controls(self) -> None:
        self.assertEqual(clean_url("https://BOAT.example.com.:8443/book"), "https://boat.example.com:8443/book")
        self.assertEqual(clean_url("https://[::1]:0"), "https://[::1]:0/")
        self.assertEqual(clean_url("https://boat.example.com:65535?b=&a=1&a=2"), "https://boat.example.com:65535/?b=&a=1&a=2")
        for url in (
            "http://boat.example.com/",
            "https://user@boat.example.com/",
            "https://boat.example.com:99999/",
        ):
            with self.subTest(url=url):
                self.assertIsNone(clean_url(url))


if __name__ == "__main__":
    unittest.main()
