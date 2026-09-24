"""Guard against treating missing camera fields or archive drift as evidence."""

import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from shapely.geometry import Point, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_usgs_video_observations import first_field, load_archive, sector_for
from audit_usgs_native_overlap import hit_counters


class USGSVideoAuditTests(unittest.TestCase):
    def test_missing_species_field_remains_missing(self):
        self.assertIsNone(first_field({"ROCKFISH": 0}, "lingcod", "LINGCOD"))
        self.assertEqual(first_field({"ROCKFISH": 1}, "rockfish", "ROCKFISH"), 1)

    def test_sectors_have_unambiguous_boundary(self):
        sectors = json.loads((Path(__file__).resolve().parents[1] /
                              "catalog/coastal-sectors.json").read_text())["sectors"]
        self.assertEqual(sector_for(40.95, sectors), "crescent-city-humboldt")
        self.assertEqual(sector_for(42.0, sectors), "del-norte")
        self.assertIsNone(sector_for(42.1, sectors))

    def test_original_archive_hash_change_fails_closed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_video_observations.zip").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                load_archive(root, "test", hashlib.sha256(b"original").hexdigest(),
                             "https://pubs.usgs.gov/ds/781/video_observations/data/", False)

    def test_camera_edge_hold_does_not_turn_a_nearby_fish_into_polygon_evidence(self):
        polygon = box(0, 0, 100, 100)
        row = {"MAJOR_GEO": "rock", "rockfish": 1, "Date_": date(2012, 8, 22), "LINE": "106"}
        counts = Counter()
        self.assertTrue(hit_counters(counts, polygon, Point(10, 50), row, "c0212sc"))
        self.assertEqual(counts["near_edge_held"], 1)
        self.assertEqual(counts["interior_windows"], 0)
        self.assertTrue(hit_counters(counts, polygon, Point(50, 50), row, "c0212sc"))
        self.assertTrue(hit_counters(counts, polygon, Point(55, 50), row, "c0212sc"))
        self.assertEqual(counts["interior_windows"], 2)
        self.assertEqual(counts["rockfish_positive_windows"], 2)
        self.assertEqual(len(counts["transects"]), 1)


if __name__ == "__main__":
    unittest.main()
