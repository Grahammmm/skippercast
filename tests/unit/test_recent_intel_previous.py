"""RF2310-4: an unusable previous snapshot or a malformed retained lead never loses the run."""
from contextlib import redirect_stderr
from datetime import datetime, timezone
import functools
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from tests._support import ROOT

spec = importlib.util.spec_from_file_location("recent_intel_previous", ROOT / "scripts/collect_recent_intel.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
NOW = datetime(2026, 9, 22, 20, tzinfo=timezone.utc)
LEAD = {"id": "old", "url": "https://example.org/old", "published_at": "2026-09-15T00:00:00+00:00", "review_status": "candidate"}


class Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def config():
    data = json.loads((ROOT / "catalog/recent-intel-watchlist.json").read_text())
    data["regions"] = [{"id": "morro-bay", "queries": [{"id": "reef", "text": "Morro Bay lingcod"}]}]
    data["jobs_per_day"] = 1
    return data


def runner(cmd, **kwargs):
    output = Path(next(x.split("=", 1)[1] for x in cmd if x.startswith("--output=")))
    output.write_text(json.dumps({"schema_version": "1.3", "results": [], "source_status": {"reddit": "no-results"}}))
    return type("Result", (), {"returncode": 0, "stderr": ""})()


class PreviousSnapshotTests(unittest.TestCase):
    def run_main(self, previous_bytes=None, directory=False):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "config.json").write_text(json.dumps(config()))
            prev = tmp / "prev"
            if directory:
                prev.mkdir()
            elif previous_bytes is not None:
                prev.write_bytes(previous_bytes)
            argv = ["collect", "--engine", __file__, "--output", str(tmp / "out"), "--previous", str(prev),
                    "--config", str(tmp / "config.json")]
            err = io.StringIO()
            gather = functools.partial(module.gather, runner=runner)
            with patch.object(sys, "argv", argv), patch.object(module, "gather", gather), \
                    patch.object(module, "datetime", Frozen), redirect_stderr(err), patch("sys.stdout", io.StringIO()):
                module.main()
            return json.loads((tmp / "out/recent-intel.json").read_text()), err.getvalue()

    def gather(self, previous):
        with tempfile.TemporaryDirectory() as tmp:
            return module.gather(config(), Path(__file__), Path(tmp), NOW, previous, runner)

    def test_unusable_previous_file_prints_one_line_and_snapshot_is_written(self):
        cases = {b'{"candidates": [': "unreadable JSON", b"\xff\xfe{}": "unreadable JSON",
                 b"[]": "not an object", b'"x"': "not an object"}
        for raw, reason in cases.items():
            with self.subTest(raw=raw):
                data, err = self.run_main(raw)
                self.assertEqual(err, "recent-intel: previous snapshot ignored: " + reason + "\n")
                self.assertEqual(data["candidates"], [])
                self.assertEqual(data["health"]["jobs_usable"], 1)
                self.assertNotIn("previous_skipped", data["health"])

    def test_directory_or_missing_previous_is_absent_without_a_line(self):
        for kwargs in ({"directory": True}, {}):
            with self.subTest(**kwargs):
                data, err = self.run_main(**kwargs)
                self.assertEqual(err, "")
                self.assertEqual(data["candidates"], [])

    def test_valid_previous_file_through_main_keeps_lead_without_line(self):
        data, err = self.run_main(json.dumps({"candidates": [LEAD]}).encode())
        self.assertEqual(err, "")
        self.assertEqual([c["id"] for c in data["candidates"]], ["old"])

    def test_candidates_not_a_list_retains_nothing(self):
        for value in ("old", {"id": "old"}, None):
            with self.subTest(candidates=value):
                result = self.gather({"candidates": value})
                self.assertEqual(result["candidates"], [])
                self.assertNotIn("previous_skipped", result["health"])

    def test_malformed_entries_are_skipped_and_counted(self):
        result = self.gather({"candidates": [1, {}, {"id": ""}, {"id": 5}, LEAD]})
        self.assertEqual([c["id"] for c in result["candidates"]], ["old"])
        self.assertTrue(result["candidates"][0]["retained"])
        self.assertEqual(result["health"]["previous_skipped"], 4)

    def test_valid_previous_output_is_unchanged(self):
        stale = dict(LEAD, id="stale", published_at="2026-01-01T00:00:00+00:00")
        result = self.gather({"candidates": [LEAD, stale]})
        self.assertEqual(result["health"], {"status": "ok", "jobs_usable": 1, "jobs_total": 1, "watchlist_queries": 1})
        self.assertEqual(result["candidates"], [{**LEAD, "retained": True}])
        self.assertEqual(list(result), ["schema_version", "generated_at", "upstream", "lookback_days", "checks",
                                        "candidates", "health", "limitations"])


if __name__ == "__main__":
    unittest.main()
