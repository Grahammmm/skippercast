"""Research priorities must not bypass original-cell or chart-danger gates."""
import copy
import json
from pathlib import Path
import unittest

from scripts.triage_original_habitat_outlines import triage


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT / path).read_text())


class OriginalHabitatTriageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = read("dist/data/cape-mendocino-native-hard-context.geojson")
        cls.depths = read("dist/data/h11975-research-outline-original-depths.json")
        cls.enc = read("dist/data/cape-mendocino-enc-context-review.json")
        cls.profile = read("catalog/original-habitat-triage-profiles.json")["profiles"][0]

    def test_shortlist_is_measured_chart_screened_and_never_fishing(self):
        result = triage(self.context, self.depths, self.enc, self.profile)
        held = {r["context_id"] for r in self.enc["outlines_near_charted_dangers"]}
        self.assertEqual(result["source_context_outlines"], 121)
        self.assertEqual(result["outlines_near_selected_chart_dangers"], 27)
        self.assertEqual(result["research_shortlist_count"], 32)
        for row in result["research_shortlist"]:
            self.assertNotIn(row["context_id"], held)
            self.assertGreaterEqual(row["original_qualified_cells"], 1)
            self.assertFalse(row["fishing_target"])
            self.assertFalse(row["exportable"])
        self.assertFalse(result["fishing_target"])
        self.assertFalse(result["exportable"])

    def test_new_chart_danger_removes_an_outline(self):
        changed = copy.deepcopy(self.enc)
        first = triage(self.context, self.depths, self.enc, self.profile)["research_shortlist"][0]["context_id"]
        changed["outlines_near_charted_dangers"].append({"context_id": first, "survey_id": "H11975",
                                                    "charted_dangers_within_buffer": 1})
        result = triage(self.context, self.depths, changed, self.profile)
        self.assertEqual(result["research_shortlist_count"], 31)
        self.assertNotIn(first, {r["context_id"] for r in result["research_shortlist"]})

    def test_partial_chart_or_mismatched_depth_receipt_fails(self):
        changed = copy.deepcopy(self.enc)
        changed["queried_layers"] = 17
        with self.assertRaisesRegex(ValueError, "Source identity"):
            triage(self.context, self.depths, changed, self.profile)
        changed = copy.deepcopy(self.depths)
        changed["outlines"].pop()
        with self.assertRaisesRegex(ValueError, "complete context"):
            triage(self.context, changed, self.enc, self.profile)


if __name__ == "__main__":
    unittest.main()
