import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import unittest

from scripts.triage_regular_habitat_outlines import triage


ROOT = Path(__file__).resolve().parents[1]
PROFILES = {row["id"]: row for row in json.loads(
    (ROOT / "catalog/regular-habitat-triage-profiles.json").read_text())["profiles"]}


def packet(place):
    files = {
        "point-conception": ("point-conception-native-hard-context.geojson",
                             "point-conception-native-hard-review-summary.json",
                             "point-conception-enc-context-review.json"),
        "gaviota": ("gaviota-native-hard-context.geojson",
                    "gaviota-native-hard-review-summary.json",
                    "gaviota-enc-context-review.json"),
    }[place]
    return tuple(json.loads((ROOT / "dist/data" / name).read_text()) for name in files)


def checked_now(enc):
    return datetime.fromisoformat(enc["enc_checked_at"].replace("Z", "+00:00")) + timedelta(hours=1)


class RegularHabitatTriageTests(unittest.TestCase):
    def test_point_conception_shortlist_uses_original_cells_and_full_chart_screen(self):
        context, summary, enc = packet("point-conception")
        result = triage(context, summary, enc, PROFILES["point-conception-original-regular-bag"],
                        now=checked_now(enc))
        self.assertEqual(result["research_shortlist_count"], 4)
        self.assertEqual(result["source_context_outlines"], 21)
        self.assertTrue(all(not row["fishing_target"] and not row["exportable"]
                            for row in result["research_shortlist"]))

    def test_gaviota_small_or_chart_held_outlines_produce_no_shortlist(self):
        context, summary, enc = packet("gaviota")
        result = triage(context, summary, enc, PROFILES["gaviota-original-regular-bag"],
                        now=checked_now(enc))
        self.assertEqual(result["research_shortlist_count"], 0)
        self.assertEqual(result["outlines_near_selected_chart_dangers"], 6)

    def test_source_change_and_incomplete_chart_fail_closed(self):
        context, summary, enc = packet("point-conception")
        changed = copy.deepcopy(context)
        changed["features"][0]["properties"]["noaa_bag_sha256"] = "wrong"
        with self.assertRaises(ValueError):
            triage(changed, summary, enc, PROFILES["point-conception-original-regular-bag"],
                   now=checked_now(enc))
        chart = copy.deepcopy(enc)
        chart["queried_layers"] = 17
        with self.assertRaises(ValueError):
            triage(context, summary, chart, PROFILES["point-conception-original-regular-bag"],
                   now=checked_now(enc))


if __name__ == "__main__":
    unittest.main()
