import json
from pathlib import Path
import unittest

from scripts import audit_point_buchon_ncei_line_index as index


ROOT = Path(__file__).resolve().parents[1]


class PointBuchonLineIndexTest(unittest.TestCase):
    def test_public_index_is_research_only(self):
        result = json.loads((ROOT / "dist/data/point-buchon-2007-ncei-line-index.json").read_text())
        self.assertEqual(result["scope"], "point-buchon-2007-ncei-generated-line-depth-index")
        self.assertFalse(result["fishing_target"])
        self.assertEqual(result["qualified_waypoints"], 0)
        self.assertEqual({row["survey_id"] for row in result["surveys"]}, set(index.SURVEYS))
        self.assertEqual(sum(row["processed_line_count"] for row in result["surveys"]), 186)
        self.assertGreater(sum(row["nominal_200_300ft_unknown_datum_envelope_line_count"]
                               for row in result["surveys"]), 0)
        for row in result["surveys"]:
            self.assertEqual(row["nominal_200_300ft_unknown_datum_envelope_line_count"],
                             len(row["nominal_envelope_candidate_lines"]))
            self.assertTrue(all(item["inf_sha256"] and item["inf_url"]
                                for item in row["nominal_envelope_candidate_lines"]))

    def test_depth_envelope_rejects_bad_or_changed_summary(self):
        self.assertEqual(index.line_range(b"Minimum Depth: 78.64 Maximum Depth: 91.7086"),
                         (78.64, 91.7086))
        with self.assertRaises(ValueError):
            index.line_range(b"Minimum Depth: 90 Maximum Depth: 70")
        with self.assertRaises(ValueError):
            index.line_range(b"no depth summary")


if __name__ == "__main__":
    unittest.main()
