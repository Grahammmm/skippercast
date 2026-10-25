"""SC137 direct API regressions for classified polygon input shape."""
import copy
import math
import unittest
from unittest.mock import patch

from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon, box, mapping

from skippercast.seafloor import classified_geometry as cg

MESSAGE = 'Invalid classified polygon representation'


def valid_shell_hole():
    return Polygon([(50000, 100000), (50100, 100000), (50100, 100100),
                    (50000, 100100), (50000, 100000)],
                   [[(50020, 100020), (50040, 100020), (50040, 100040),
                     (50020, 100040), (50020, 100020)]])


def point_contact_hole():
    x, y = 50000, 100000
    return Polygon([(x, y), (x + 100, y), (x + 100, y + 100), (x, y + 100)],
                   [[(x, y + 50), (x + 25, y + 100 / 3),
                     (x + 25, y + 200 / 3), (x, y + 50)]])


def assert_typed_refusal(testcase, value):
    with testcase.assertRaisesRegex(ValueError, MESSAGE):
        cg.polygon(value)


class ClassifiedPolygonShapeTests(unittest.TestCase):
    def test_positive_polygon_and_multipolygon_object_identity_and_properties(self):
        for value in (valid_shell_hole(), MultiPolygon([box(0, 0, 2, 3), box(5, 7, 8, 9)])):
            with self.subTest(kind=value.geom_type):
                result = cg.polygon(value)
                self.assertIs(result, value)
                self.assertEqual(result.wkb, value.wkb)
                self.assertEqual(result.bounds, value.bounds)
                self.assertEqual(result.area, value.area)
                self.assertTrue(result.is_valid)
                self.assertFalse(result.is_empty)
                self.assertTrue(math.isfinite(result.area))
                self.assertTrue(all(math.isfinite(v) for v in result.bounds))

    def test_geojson_polygon_and_multipolygon_mappings_decode_without_mutation(self):
        for value in (valid_shell_hole(), MultiPolygon([box(0, 0, 2, 3), box(5, 7, 8, 9)])):
            supplied = mapping(value)
            before = copy.deepcopy(supplied)
            result = cg.polygon(supplied)
            self.assertTrue(value.equals_exact(result, 0))
            self.assertEqual(result.bounds, value.bounds)
            self.assertEqual(result.area, value.area)
            self.assertEqual(supplied, before)

    def test_malformed_values_all_use_named_value_error(self):
        malformed = (
            None, [], 4, 3.25, 'polygon', {}, {'coordinates': []},
            {'type': 'Polygon'}, {'type': 'Polygon', 'coordinates': None},
            {'type': 'Polygon', 'coordinates': []},
            {'type': 'Polygon', 'coordinates': [[0, 1]]},
            {'type': 'Polygon', 'coordinates': 'not coordinates'},
            {'type': 'Feature', 'geometry': mapping(box(0, 0, 1, 1)), 'properties': {}},
            Point(0, 0), LineString([(0, 0), (1, 1)]), GeometryCollection([box(0, 0, 1, 1)]),
            Polygon(), Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]),
        )
        for value in malformed:
            with self.subTest(value=repr(value)):
                assert_typed_refusal(self, value)

    def test_input_mapping_is_unchanged_on_refusal(self):
        supplied = {'type': 'Polygon', 'coordinates': None}
        before = copy.deepcopy(supplied)
        with self.assertRaisesRegex(ValueError, MESSAGE):
            cg.polygon(supplied)
        self.assertEqual(supplied, before)

    def test_compatibility_shell_hole_and_point_contact_direct_api(self):
        for native in (valid_shell_hole(), point_contact_hole()):
            self.assertTrue(native.is_valid)
            self.assertIs(cg.polygon(native), native)
            decoded = cg.polygon(mapping(native))
            self.assertTrue(decoded.equals_exact(native, 0))
            self.assertEqual(decoded.bounds, native.bounds)
            self.assertEqual(decoded.area, native.area)

    def test_old_unchecked_attribute_boundary_is_decided_by_typed_assertion(self):
        def unchecked_old_boundary(value):
            decoded = cg.shape(value) if isinstance(value, dict) else value
            if (decoded.geom_type not in {'Polygon', 'MultiPolygon'} or decoded.is_empty
                    or not decoded.is_valid or not math.isfinite(decoded.area) or decoded.area <= 0
                    or not all(math.isfinite(v) for v in decoded.bounds)):
                raise ValueError(MESSAGE)
            return decoded

        detected = False
        with patch.object(cg, 'polygon', unchecked_old_boundary):
            try:
                assert_typed_refusal(self, None)
            except AttributeError:
                detected = True
        self.assertTrue(detected, 'typed-refusal regression must detect old AttributeError boundary')
        positive = valid_shell_hole()
        self.assertIs(cg.polygon(positive), positive)


if __name__ == '__main__':
    unittest.main()
