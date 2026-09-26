import json
from pathlib import Path
import unittest

from scripts.audit_point_conception_launch_hazard import audit, parse_window


ROOT = Path(__file__).resolve().parents[1]
NOTICE = '''SEC LALB BNM 0239-26
1. HAZARDOUS WINDOW - 1
VANDENBERG SFB HAZARD AREA - 1
34° 24' 0" N 120° 42' 0" W
34° 42' 0" N 120° 42' 0" W
34° 42' 0" N 120° 18' 0" W
34° 24' 0" N 120° 18' 0" W
TO BEGINNING
261156Z SEP TO 261521Z SEP 2026---- (PRIMARY)
2. HAZARDOUS WINDOW - 2
VANDENBERG SFB HAZARD AREA - 1
29° 00' 0" N 118° 00' 0" W
29° 12' 0" N 118° 00' 0" W
29° 12' 0" N 117° 48' 0" W
TO BEGINNING
261156Z SEP TO 261539Z SEP 2026---- (PRIMARY)
3. SURFACE VESSELS ARE STRONGLY ADVISED TO AVOID
'''


class LaunchHazardTests(unittest.TestCase):
    def test_dates_and_actual_candidate_geometry_are_screened(self):
        polygon, times = parse_window(NOTICE, 1)
        self.assertTrue(polygon.is_valid)
        self.assertEqual(times[0]["start_utc"], "2026-09-26T11:56:00+00:00")
        context = json.loads((ROOT / "dist/data/point-conception-native-hard-context.geojson").read_text())
        queue = json.loads((ROOT / "dist/data/point-conception-regular-site-review-queue.json").read_text())
        report = audit(NOTICE.encode(), context, queue)
        self.assertEqual(len(report["research_shortlist"]), 4)
        self.assertTrue(all(row["hazard_window_ids_with_100m_margin"] == [1]
                            for row in report["research_shortlist"]))
        self.assertFalse(report["exportable"])

    def test_missing_window_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_window(NOTICE.replace("2. HAZARDOUS WINDOW - 2", ""), 2)


if __name__ == "__main__":
    unittest.main()
