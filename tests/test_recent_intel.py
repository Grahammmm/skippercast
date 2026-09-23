import importlib.util
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("recent_intel", ROOT / "scripts/collect_recent_intel.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
NOW = datetime(2026, 9, 22, 20, tzinfo=timezone.utc)


class RecentIntelTests(unittest.TestCase):
    def test_rejects_unrelated_and_undated_results(self):
        raw = {"schema_version": "1.3", "source_status": {"reddit": "ok"}, "results": [
            {"title": "Morro Bay lingcod report", "summary": "A trip report", "url": "https://example.org/a?utm_source=x",
             "published_at": "2026-09-21", "source": "reddit", "relevance_score": .8},
            {"title": "Morro Bay lingcod report", "summary": "A trip report", "url": "https://example.org/b",
             "source": "reddit", "relevance_score": .9},
            {"title": "Mossel Bay fishing", "summary": "Unrelated", "url": "https://example.org/c",
             "published_at": "2026-09-21", "source": "reddit", "relevance_score": 0},
        ]}
        found = module.normalize(raw, "morro-bay", "reef", NOW, 30)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["url"], "https://example.org/a")
        self.assertIsNone(found[0]["reported_catch"])
        self.assertIsNone(found[0]["geometry"])
        self.assertIsNone(found[0]["fishing_date"])

    def test_source_failure_is_not_empty_evidence_and_old_date_stays_old(self):
        config = json.loads((ROOT / "catalog/recent-intel-watchlist.json").read_text())
        config["regions"] = [{"id": "morro-bay", "queries": [{"id": "reef", "text": "Morro Bay lingcod"}]}]
        previous = {"candidates": [{"id": "old", "url": "https://example.org/old", "published_at": "2026-09-15T00:00:00+00:00", "review_status": "candidate"}]}

        def runner(cmd, **kwargs):
            self.assertIn("--no-browser-cookies", cmd)
            self.assertIn("--search=reddit,grounding", cmd)
            self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
            output = Path(next(x.split("=", 1)[1] for x in cmd if x.startswith("--output=")))
            output.write_text(json.dumps({"schema_version": "1.3", "results": [], "source_status": {"reddit": "timeout", "grounding": "no-results"}}))
            return type("Result", (), {"returncode": 0})()

        with tempfile.TemporaryDirectory() as tmp:
            result = module.gather(config, Path(__file__), Path(tmp), NOW, previous, runner)
        self.assertEqual(result["checks"]["morro-bay/reef"]["status"], "partial")
        self.assertEqual(result["candidates"][0]["published_at"], previous["candidates"][0]["published_at"])
        self.assertTrue(result["candidates"][0]["retained"])

    def test_regional_forum_is_broad_context_without_position(self):
        raw = {"schema_version": "1.3", "source_status": {"reddit": "ok"}, "results": [
            {"title": "Local yellowtail", "summary": "Recent fishing discussion", "url": "https://www.reddit.com/r/SoCalFishing/comments/abc/report/",
             "published_at": "2026-09-21", "source": "reddit", "relevance_score": 0},
            {"title": "Local yellowtail", "summary": "Recent fishing discussion", "url": "https://www.reddit.com/r/other/comments/xyz/report/",
             "published_at": "2026-09-21", "source": "reddit", "relevance_score": 1},
        ]}
        found = module.normalize(raw, "southern-california", "islands", NOW, 30)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["location_basis"], "regional forum only")
        self.assertIsNone(found[0]["geometry"])


if __name__ == "__main__":
    unittest.main()
