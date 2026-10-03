import importlib.util
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests._support import ROOT


spec = importlib.util.spec_from_file_location("recent_intel", ROOT / "scripts/collect_recent_intel.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
NOW = datetime(2026, 9, 22, 20, tzinfo=timezone.utc)


class RecentIntelTests(unittest.TestCase):
    def test_runtime_library_path_survives_but_credentials_do_not(self):
        config = json.loads((ROOT / "catalog/recent-intel-watchlist.json").read_text())
        config["regions"] = [{"id": "morro-bay", "queries": [{"id": "reef", "text": "Morro Bay lingcod"}]}]
        # A real child process simulates an interpreter requiring its host
        # library path before it can emit the upstream JSON contract.
        runtime_path = "/synthetic/python/lib"
        if module.os.environ.get("LD_LIBRARY_PATH"):
            runtime_path += module.os.pathsep + module.os.environ["LD_LIBRARY_PATH"]
        fixture = '''import json, os, sys
if os.environ.get("LD_LIBRARY_PATH") != EXPECTED_LIBRARY_PATH:
    sys.stderr.write("error while loading shared libraries: synthetic-runtime.so")
    sys.exit(127)
assert "OPENAI_API_KEY" not in os.environ
assert "CLOUDFLARE_API_TOKEN" not in os.environ
assert "HOME" not in os.environ
assert os.environ["FROM_BROWSER"] == "off"
assert os.environ["LAST30DAYS_CONFIG_DIR"] == ""
output = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--output="))
with open(output, "w") as f:
    json.dump({"schema_version": "1.3", "results": [], "source_status": {"reddit": "no-results", "grounding": "no-results"}}, f)
'''
        with tempfile.TemporaryDirectory() as tmp:
            engine = Path(tmp) / "engine.py"
            engine.write_text(fixture.replace("EXPECTED_LIBRARY_PATH", repr(runtime_path)))
            with patch.dict(module.os.environ, {"LD_LIBRARY_PATH": runtime_path, "OPENAI_API_KEY": "synthetic-private", "CLOUDFLARE_API_TOKEN": "synthetic-private"}):
                result = module.gather(config, engine, Path(tmp) / "out", NOW)
            self.assertEqual(result["health"]["jobs_usable"], 1)
            self.assertEqual(result["checks"]["morro-bay/reef"]["status"], "ok")

    def test_loader_failure_is_specific_without_publishing_raw_stderr(self):
        config = json.loads((ROOT / "catalog/recent-intel-watchlist.json").read_text())
        config["regions"] = [{"id": "morro-bay", "queries": [{"id": "reef", "text": "Morro Bay lingcod"}]}]
        def runner(*args, **kwargs):
            return type("Result", (), {"returncode": 127, "stderr": "error while loading shared libraries: /private/synthetic-path.so"})()
        with tempfile.TemporaryDirectory() as tmp:
            result = module.gather(config, Path(__file__), Path(tmp), NOW, runner=runner)
        self.assertEqual(result["health"]["jobs_usable"], 0)
        self.assertEqual(result["checks"]["morro-bay/reef"]["issue"], "engine runtime unavailable: shared library loader failed")
        self.assertNotIn("/private", json.dumps(result))

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
