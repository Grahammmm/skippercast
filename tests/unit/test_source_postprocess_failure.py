import unittest
from datetime import datetime, timezone

from skippercast.pipeline.collect import source

NOW = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
CLOCKS = ("last_success_at", "data_retrieved_at", "changed_since_previous")
PREVIOUS = {"data": {"sample_at": "2026-09-24T10:00:00Z"},
            "last_success_at": "2026-09-24T10:30:00Z", "data_retrieved_at": "2026-09-24T10:15:00Z"}


def run(kind, loader, previous=None, max_age=6):
    return source("a", "A", kind, "https://example.org", max_age, loader, NOW, previous)


class SourcePostprocessFailureTests(unittest.TestCase):
    def assert_failed_without_clocks(self, result, error_name):
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["data"])
        self.assertTrue(result["issue"].startswith(error_name), result["issue"])
        for key in CLOCKS:
            self.assertNotIn(key, result)
        self.assertEqual(result["requests"], [])

    def test_list_result_fails_with_no_success_clocks(self):
        self.assert_failed_without_clocks(run("observation", lambda c: []), "AttributeError")

    def test_page_watch_without_hash_fails_even_with_no_previous_hash(self):
        for kind in ("page-watch", "pdf-watch"):
            self.assert_failed_without_clocks(run(kind, lambda c: {"title": "x"}), "KeyError")

    def test_failed_refresh_retains_previous_data_and_original_clocks(self):
        result = run("page-watch", lambda c: {"title": "x"}, PREVIOUS)
        self.assertEqual(result["status"], "retained")
        self.assertEqual(result["data"], PREVIOUS["data"])
        self.assertEqual(result["last_success_at"], PREVIOUS["last_success_at"])
        self.assertEqual(result["data_retrieved_at"], PREVIOUS["data_retrieved_at"])
        self.assertNotIn("changed_since_previous", result)
        self.assertTrue(result["issue"].startswith("KeyError"))

    def test_chlorophyll_fallback_serves_only_an_in_window_observation(self):
        # Contract: a failed daily chlorophyll refresh keeps the prior cells only while their
        # observation time is inside max_age_hours. Bug caught: the fallback copied a 337-hour-old
        # grid because it never rechecked age, and a recent retrieval must not make it look fresh.
        def fails(client):
            raise ValueError("Latest NOAA VIIRS chlorophyll file is stale")

        def chlorophyll(previous):
            return source("chlorophyll", "C", "grid", "https://example.org", 96, fails, NOW, previous)

        recent = {"last_success_at": "2026-09-24T11:00:00Z", "data_retrieved_at": "2026-09-24T11:00:00Z"}
        for sample in ("2026-09-10T11:00:00Z", None, "not a time"):  # expired, missing, unreadable
            with self.subTest(sample=sample):
                first = chlorophyll({**recent, "data": {"sample_at": sample, "valid_cells": 673}})
                second = chlorophyll(first)
                for result in (first, second):
                    self.assertEqual((result["status"], result["data"]), ("failed", None))
                    self.assertEqual(result["issue"], "ValueError: Latest NOAA VIIRS chlorophyll file is stale")
                    self.assertEqual(result["last_success_at"], recent["last_success_at"])
                    self.assertNotIn("data_retrieved_at", result)
        in_window = {**recent, "data": {"sample_at": "2026-09-21T00:00:00Z", "valid_cells": 673}}
        kept = chlorophyll(in_window)
        self.assertEqual(kept["status"], "retained")
        self.assertEqual(kept["data"], in_window["data"])
        self.assertEqual((kept["last_success_at"], kept["data_retrieved_at"]),
                         (recent["last_success_at"], recent["data_retrieved_at"]))

    def test_ordinary_results_keep_statuses_and_clocks(self):
        ok = run("observation", lambda c: {"sample_at": "2026-09-24T11:00:00Z"})
        self.assertEqual(ok["status"], "ok")
        self.assertTrue(ok["last_success_at"] and ok["data_retrieved_at"])
        stale = run("observation", lambda c: {"sample_at": "2026-09-20T00:00:00Z"})
        self.assertEqual(stale["status"], "stale")
        self.assertTrue(stale["last_success_at"])
        missing = run("grid", lambda c: {"total_cells": 4, "valid_cells": 0})
        self.assertEqual(missing["status"], "missing")
        self.assertTrue(missing["data_retrieved_at"])
        watch = run("page-watch", lambda c: {"content_sha256": "b"}, {"data": {"content_sha256": "a"}})
        self.assertEqual(watch["status"], "ok")
        self.assertIs(watch["changed_since_previous"], True)
        first = run("page-watch", lambda c: {"content_sha256": "b"})
        self.assertEqual(first["status"], "ok")
        self.assertIsNone(first["changed_since_previous"])


if __name__ == "__main__":
    unittest.main()
