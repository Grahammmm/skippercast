"""RF1930-7: malformed engine result objects fail their own research job, never the collection."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from tests._support import ROOT

spec = importlib.util.spec_from_file_location("recent_intel_results", ROOT / "scripts/collect_recent_intel.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
NOW = datetime(2026, 9, 22, 20, tzinfo=timezone.utc)
GOOD_ROW = {"url": "https://www.reddit.com/r/fishing/comments/abc/morro-bay-lingcod/", "published_at": "2026-09-20T00:00:00+00:00",
            "title": "Morro Bay lingcod report", "summary": "Fishing the reef near Morro Bay this week"}
RETAINED = {"id": "old", "url": "https://example.org/old", "published_at": "2026-09-15T00:00:00+00:00",
            "review_status": "candidate", "status": "ok"}
CONTRACT = "Unexpected last30days agent JSON contract"


def envelope(results, status=None):
    return {"schema_version": "1.3", "results": results, "source_status": {"reddit": "ok"} if status is None else status}


def normalize(raw):
    return module.normalize(raw, "morro-bay", "reef", NOW, 30)


def config():
    data = json.loads((ROOT / "catalog/recent-intel-watchlist.json").read_text())
    data["regions"] = [{"id": "morro-bay", "queries": [{"id": "good", "text": "good"}, {"id": "bad", "text": "bad"}]}]
    data["jobs_per_day"] = 2
    return data


class ResultShapeTests(unittest.TestCase):
    def test_non_object_envelope_is_contract_value_error(self):
        for raw in (None, [], "x", 3, True):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, CONTRACT):
                normalize(raw)
        for raw in ({"schema_version": "2", "results": [], "source_status": {}},
                    {"schema_version": "1", "results": {}, "source_status": {}},
                    {"schema_version": "1", "results": [], "source_status": []}):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, CONTRACT):
                normalize(raw)

    def test_non_object_result_rejects_whole_job(self):
        for bad in (None, 7, "secret-row-text", ["secret-row-text"]):
            with self.subTest(bad=bad), self.assertRaises(ValueError) as caught:
                normalize(envelope([GOOD_ROW, bad]))
            self.assertIn("position 1", str(caught.exception))
            self.assertNotIn("secret", str(caught.exception))

    def test_empty_results_control_remains_ok(self):
        self.assertEqual(normalize(envelope([], {"reddit": "no-results"})), [])
        items = normalize(envelope([{}, GOOD_ROW]))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["published_at"], "2026-09-20T00:00:00+00:00")
        self.assertEqual(items[0]["review_status"], "candidate")


class JobIsolationTests(unittest.TestCase):
    def run_gather(self, bad_payload, bad_first):
        order = []
        cfg = config()
        scheduled = [cfg["regions"][0]["queries"][i]["id"] for i in range(2)]

        def runner(cmd, **kwargs):
            text = cmd[2]
            order.append(text)
            output = Path(next(x.split("=", 1)[1] for x in cmd if x.startswith("--output=")))
            payload = bad_payload if text == "bad" else envelope([GOOD_ROW], {"reddit": "ok", "grounding": "no-results"})
            output.write_text(json.dumps(payload))
            return type("Result", (), {"returncode": 0, "stderr": ""})()

        cfg["regions"][0]["queries"].sort(key=lambda q: q["id"] != ("bad" if bad_first else "good"))
        with tempfile.TemporaryDirectory() as tmp:
            result = module.gather(cfg, Path(__file__), Path(tmp), NOW, {"candidates": [RETAINED]}, runner)
        return result, order, scheduled

    def test_bad_result_keeps_other_jobs_and_previous(self):
        for bad_payload in (None, 5, envelope([GOOD_ROW, None]), envelope([3])):
            for bad_first in (True, False):
                with self.subTest(bad=bad_payload, bad_first=bad_first):
                    result, order, _ = self.run_gather(bad_payload, bad_first)
                    self.assertEqual(sorted(order), ["bad", "good"])
                    checks = result["checks"]
                    self.assertEqual(checks["morro-bay/bad"]["status"], "failed")
                    self.assertEqual(checks["morro-bay/bad"]["result_count"], 0)
                    self.assertEqual(checks["morro-bay/good"]["status"], "ok")
                    self.assertEqual(result["health"]["status"], "degraded")
                    self.assertEqual(result["health"]["jobs_usable"], 1)
                    self.assertEqual(result["health"]["jobs_total"], 2)
                    by_id = {c["id"]: c for c in result["candidates"]}
                    self.assertEqual(len(by_id), 2)
                    self.assertEqual(by_id["old"]["published_at"], RETAINED["published_at"])
                    self.assertTrue(by_id["old"]["retained"])
                    self.assertEqual({c["query_id"] for c in result["candidates"] if "query_id" in c}, {"good"})


if __name__ == "__main__":
    unittest.main()
