"""Collinear rings cannot stand in for a qualified footprint or closure polygon."""
from copy import deepcopy
import unittest

from skippercast.platform.qualified_scope import _polygons
from tests.integration import test_qualified_scope as historical

REFUSED = "Degenerate polygon ring"
SQUARE = [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]
HOLE = [[1, 1], [1, 2], [2, 2], [2, 1], [1, 1]]
HORIZONTAL = [[-119.125, 34], [-119, 34], [-118.875, 34], [-119.125, 34]]
VERTICAL = [[5, 1], [5, 2], [5, 3], [5, 1]]
DIAGONAL = [[0, 0], [1, 1], [2, 2], [3, 3], [0, 0]]
REPEATED_DIAGONAL = [[0, 0], [0, 0], [1, 1], [1, 1], [2, 2], [0, 0]]


def poly(*rings):
    return {"type": "Polygon", "coordinates": [deepcopy(r) for r in rings]}


class DegenerateRingTests(unittest.TestCase):
    def helper(self):
        case = historical.QualifiedScopeTests("test_reviewed_partial_subset_does_not_claim_current_legal_clearance")
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def test_collinear_outer_ring_cannot_qualify(self):
        with self.assertRaisesRegex(ValueError, REFUSED):
            _polygons(poly(HORIZONTAL))
        case = self.helper()
        self.assertTrue(case.validate()["ready"])  # control
        case.atlas["areas"][0]["geometry"] = poly(HORIZONTAL)
        case.publish()  # genuine rehash: refusal is semantic, not stale integrity
        with self.assertRaisesRegex(ValueError, REFUSED):
            case.validate()

    def test_vertical_and_diagonal_collinear_rings_refuse(self):
        for name, ring in (("vertical", VERTICAL), ("vertical reversed", VERTICAL[::-1]), ("diagonal", DIAGONAL),
                           ("diagonal reversed", DIAGONAL[::-1]), ("repeated adjacent", REPEATED_DIAGONAL)):
            with self.subTest(ring=name), self.assertRaisesRegex(ValueError, REFUSED):
                _polygons(poly(ring))

    def test_degenerate_hole_and_later_component_refuse(self):
        cases = {
            "hole": poly(SQUARE, DIAGONAL),
            "later exterior": {"type": "MultiPolygon", "coordinates": [[SQUARE], [VERTICAL]]},
            "later hole": {"type": "MultiPolygon", "coordinates": [[SQUARE], [SQUARE, HORIZONTAL]]},
        }
        for name, geometry in cases.items():
            with self.subTest(case=name), self.assertRaisesRegex(ValueError, REFUSED):
                _polygons(geometry)

    def test_closure_geometry_uses_same_admission(self):
        case = self.helper()
        path = next(iter(case.closures))
        closure = case.closures[path]
        closure["features"][0]["geometry"] = poly(HORIZONTAL)
        case.quality["closure_receipts"][0]["sha256"] = case.write(path, closure)["sha256"]
        case.publish()
        with self.assertRaisesRegex(ValueError, REFUSED):
            case.validate()

    def test_valid_thin_triangle_and_repeated_vertex_controls(self):
        accepted = [
            poly([[0, 0], [10, 0], [10, 1e-6], [0, 0]]),
            poly([[0, 0], [10, 1e-6], [10, 0], [0, 0]]),
            poly([[0, 0], [0, 0], [4, 0], [4, 4], [4, 4], [0, 4], [0, 0]]),
            poly(SQUARE, HOLE),
            {"type": "MultiPolygon", "coordinates": [[SQUARE, HOLE], [[[10, 10], [12, 10], [12, 12], [10, 10]]]]},
        ]
        for geometry in accepted:
            with self.subTest(geometry=geometry):
                coordinates = deepcopy(geometry["coordinates"])
                result = _polygons(geometry)
                expected = [coordinates] if geometry["type"] == "Polygon" else coordinates
                self.assertEqual(result, expected)

    def test_valid_release_retains_limited_claims(self):
        result = self.helper().validate()
        self.assertTrue(result["ready"])
        self.assertFalse(result["complete_region_coverage"])
        self.assertFalse(result["current_legal_clearance"])
        self.assertTrue(result["runtime_closure_screen_required"])


if __name__ == "__main__":
    unittest.main()
