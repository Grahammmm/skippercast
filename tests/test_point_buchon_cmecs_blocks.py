import importlib.util
from pathlib import Path
import unittest
from types import SimpleNamespace

from shapely.geometry import Polygon, box, mapping


SPEC = importlib.util.spec_from_file_location(
    "audit_point_buchon_cmecs_blocks",
    Path(__file__).resolve().parents[1] / "scripts/audit_point_buchon_cmecs_blocks.py",
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class Source:
    def __init__(self, rows):
        self.rows = rows

    def iterShapeRecords(self, bbox):
        return self.rows


def row(geometry, code, induration):
    return SimpleNamespace(shape=SimpleNamespace(__geo_interface__=mapping(geometry)),
                           record={"Substrate": code, "SubInd": induration})


class PointBuchonCMECSReviewTests(unittest.TestCase):
    def test_invalid_source_geometry_is_excluded_and_reported(self):
        valid = row(box(0, 0, 10, 10), "S1.1.1", "Hard")
        invalid = row(Polygon([(20, 0), (30, 10), (20, 10), (30, 0)]), "S1.1.1", "Hard")
        result = audit.group(Source([valid, invalid]),
                             [{"properties": {"lingcod_seen": 1}}], [box(0, 0, 100, 100)])
        self.assertEqual(result["blocks_with_any_mapped_bedrock"], 1)
        self.assertEqual(result["invalid_polygons_with_possible_block_bbox_hit"], 1)
        self.assertEqual(result["valid_polygon_intersected_area_m2_by_cmecs_substrate"]["S1.1.1"], 100.0)

    def test_changed_bedrock_attribution_is_rejected(self):
        changed = row(box(0, 0, 10, 10), "S1.1.1", "Soft")
        with self.assertRaisesRegex(ValueError, "attribution changed"):
            audit.group(Source([changed]), [{"properties": {}}], [box(0, 0, 100, 100)])


if __name__ == "__main__":
    unittest.main()
