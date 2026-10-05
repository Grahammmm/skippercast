"""Private classification proof retains tile-edge area and conservative masks."""
import unittest
import numpy as np
from affine import Affine
from shapely.ops import unary_union

from research.scripts.probe_classified_habitat import candidate_mask, polygons, components


class ClassifiedHabitatProbeTests(unittest.TestCase):
    def test_exact_depth_band_and_unknown_missing_soft_mixed_excluded(self):
        depth = np.array([[7.619,7.62,91.44,91.441,np.nan,30,30,30,30,30]])
        classes = np.array([[3,3,3,3,3,3,1,2,0,3]])
        valid = np.ones(depth.shape,dtype=bool); valid[0,5] = False
        inside = np.ones(depth.shape,dtype=bool); inside[0,9] = False
        self.assertEqual(candidate_mask(depth,valid,classes,inside).tolist(),
                         [[False,True,True,False,False,False,False,False,False,False]])

    def test_dissolve_tiles_before_minimum_area_and_keep_missing_data_holes(self):
        mask = np.ones((20,20),dtype=bool); mask[4:6,4:6] = False
        affine = Affine(2,0,0,0,-2,40)
        full = unary_union(polygons(mask,affine))
        tiled = unary_union(polygons(mask[:,:10],affine)
                            +polygons(mask[:,10:],affine*Affine.translation(10,0)))
        self.assertTrue(full.equals(tiled))
        self.assertEqual(full.area,1584)
        self.assertEqual(len(components(tiled)),1)
        self.assertEqual(len(tiled.interiors),1)
        self.assertTrue(all(p.area <1000 for p in polygons(mask[:,:10],affine)))
        self.assertEqual(len([p for p in components(tiled) if p.area >=1000]),1)

    def test_difference_keeps_only_new_area_without_buffering(self):
        from shapely.geometry import box
        classified = box(0,0,40,40)
        baseline = box(0,0,10,40)
        additional = classified.difference(baseline)
        self.assertEqual(additional.area,1200)
        self.assertEqual(additional.intersection(baseline).area,0)
        self.assertTrue(classified.covers(additional))

    def test_nested_polygon_components_and_processing_limits(self):
        from shapely.geometry import box, MultiPolygon, GeometryCollection
        from research.scripts.probe_classified_habitat import probe
        one,two = box(0,0,1,1),box(2,2,3,3)
        self.assertEqual(len(components(GeometryCollection([MultiPolygon([one,two])]))),2)
        for edge,pixels in [(0,100),(2048,100),(512,0),(512,25_000_001)]:
            with self.subTest(edge=edge,pixels=pixels), self.assertRaisesRegex(ValueError,'bounded'):
                probe('.', 'unused', 'unused', 'unused', edge=edge, max_pixels=pixels)
