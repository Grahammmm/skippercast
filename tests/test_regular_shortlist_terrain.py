import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from scripts.audit_regular_shortlist_terrain import audit
from scripts.fetch_shortlist_original_bags import selected_sources


ROOT = Path(__file__).resolve().parents[1]


class OriginalRegularShortlistTerrainTests(unittest.TestCase):
    def data(self):
        paths = ["point-conception-regular-site-review-queue.json",
                 "point-conception-native-hard-context.geojson",
                 "point-conception-fresh-closure-audit.json"]
        return [json.loads((ROOT / "dist/data" / path).read_text()) for path in paths]

    def test_shortlist_fetches_only_exact_pinned_original_bags(self):
        queue, context, _ = self.data()
        rows = selected_sources(queue, context)
        self.assertEqual([row["survey_id"] for row in rows], ["H11952", "H11953"])
        self.assertTrue(all(len(row["sha256"]) == 64 for row in rows))

    def test_changed_closure_and_stale_source_fail_before_terrain(self):
        queue, context, closures = self.data()
        now = datetime.fromisoformat(queue["enc_checked_at"]) + timedelta(hours=1)
        with tempfile.TemporaryDirectory() as folder:
            changed = copy.deepcopy(closures)
            changed["held_count"] = 1
            with self.assertRaises(ValueError):
                audit(queue, context, changed, Path(folder), now=now)
            with self.assertRaises(ValueError):
                audit(queue, context, closures, Path(folder), now=now + timedelta(days=3))

    def test_conflicting_source_identity_fails(self):
        queue, context, _ = self.data()
        changed = copy.deepcopy(context)
        target = queue["research_shortlist"][0]["context_id"]
        for feature in changed["features"]:
            if feature["properties"]["id"] == target:
                feature["properties"]["noaa_bag_sha256"] = "bad"
        with self.assertRaises(ValueError):
            selected_sources(queue, changed)


if __name__ == "__main__":
    unittest.main()
