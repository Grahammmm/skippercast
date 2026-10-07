"""Offline conservative canonical occupied subtraction, never overlap tolerance."""
import unittest
from unittest.mock import patch
from shapely.geometry import box, Polygon
from skippercast.seafloor import bedrock_habitat as bh
from skippercast.seafloor.classified_geometry import MAX_FEATURE_DIFFERENCE_M2


class CanonicalExclusionTests(unittest.TestCase):
    def setUp(self):
        # Synthetic geometry stays in California's Albers domain.
        self.local = box(-200000, 0, -199900, 100)

    def test_no_overlap_preserves_exact_geometry(self):
        result, audit = bh.canonical_occupied_subtraction(self.local, box(-199800, 0, -199700, 100))
        self.assertTrue(result.equals_exact(self.local, 0))
        self.assertEqual(audit['removed_area_m2'], 0)

    def test_small_overlap_is_removed_not_tolerated(self):
        occupied = box(-199900-1e-7, 0, -199800, 100)
        self.assertGreater(self.local.intersection(occupied).area, 0)
        result, audit = bh.canonical_occupied_subtraction(self.local, occupied)
        self.assertEqual(result.intersection(occupied).area, 0)
        self.assertEqual(result.difference(self.local).area, 0)
        self.assertGreater(audit['removed_area_m2'], 0)
        self.assertLess(audit['removed_area_m2'], MAX_FEATURE_DIFFERENCE_M2)
        self.assertEqual(audit['remaining_overlap_m2'], 0)
        self.assertEqual(audit['version'], bh.CANONICAL_EXCLUSION)

    def test_material_overlap_stays_held(self):
        with self.assertRaisesRegex(ValueError, 'conservative representation'):
            bh.canonical_occupied_subtraction(self.local, box(-199950, 0, -199850, 100))

    def test_projected_graded_baseline_is_not_omitted(self):
        from pyproj import Transformer
        from shapely.ops import transform
        from skippercast.seafloor.bedrock_vectors import NativeFragments, assemble_components
        from pyproj import CRS
        native = box(670000, 3950000, 670100, 3950100)
        to_local = Transformer.from_crs(32610, 3310, always_xy=True).transform
        to_depth = Transformer.from_crs(3310, 32610, always_xy=True).transform
        local_original = transform(to_local,native)
        w,s,e,n = local_original.bounds
        occupied = box(w-100,s-100,local_original.centroid.x,n+100)
        initial = assemble_components([NativeFragments(CRS.from_epsg(32610), {'0':native})],
            existing=NativeFragments(CRS.from_epsg(32610), {'graded':transform(to_depth,occupied)}))
        local = transform(to_local,initial[0][1])
        self.assertGreater(local.intersection(occupied).area, MAX_FEATURE_DIFFERENCE_M2)
        with self.assertRaisesRegex(ValueError, 'conservative representation'):
            bh.canonical_occupied_subtraction(local, occupied)

    def test_fully_occupied_stays_held(self):
        with self.assertRaises(ValueError):
            bh.canonical_occupied_subtraction(self.local, self.local)

    def test_invalid_original_is_not_repaired(self):
        invalid = Polygon([(-200000,0),(-199900,100),(-200000,100),(-199900,0),(-200000,0)])
        self.assertFalse(invalid.is_valid)
        with self.assertRaises(ValueError):
            bh.canonical_occupied_subtraction(invalid, box(-199800,0,-199700,100))

    def test_invalid_occupied_is_not_repaired(self):
        invalid = Polygon([(-200000,0),(-199900,100),(-200000,100),(-199900,0),(-200000,0)])
        with self.assertRaises(ValueError):
            bh.canonical_occupied_subtraction(self.local, invalid)

    def test_invalid_geographic_conversion_stays_held(self):
        with patch.object(bh, 'strict_geographic', side_effect=ValueError('invalid projection')):
            with self.assertRaisesRegex(ValueError, 'invalid projection'):
                bh.canonical_occupied_subtraction(self.local, box(-199800,0,-199700,100))

    def test_boundary_contact_preserves_geometry(self):
        result, audit = bh.canonical_occupied_subtraction(self.local, box(-199900,0,-199800,100))
        self.assertTrue(result.equals_exact(self.local,0))
        self.assertEqual(audit['initial_overlap_m2'],0)


if __name__ == '__main__':
    unittest.main()
