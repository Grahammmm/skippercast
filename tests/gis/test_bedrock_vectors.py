"""Scientific invariants for a private vector/depth kernel; offline fixtures."""
import unittest
from unittest import mock

from affine import Affine
import numpy as np
from pyproj import CRS
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from skippercast.seafloor import bedrock_vectors
from skippercast.seafloor.bedrock_vectors import (
    NativeFragments, assemble_components, window_fragments,
)

CRS_METRES = CRS.from_epsg(26910)


def extract(records, depth, valid=None, affine=Affine(10,0,0,0,-10,40), crs=CRS_METRES):
    if valid is None:
        valid = np.ones(depth.shape, dtype=bool)
    return window_fragments(records, depth, valid, affine, crs,
                            depth_band_description='depth_m_positive_down')


def union(rows):
    return unary_union([g for _,g in rows])


class BedrockVectorTests(unittest.TestCase):
    def test_native_tile_edge_joins_before_area_filter(self):
        records = {'original7':box(0,0,40,40)}
        depth = np.full((4,4),30.,dtype='float32')
        whole = assemble_components([extract(records,depth)])
        tiles = [extract(records, depth[:,:2]),
                 extract(records, depth[:,2:], affine=Affine(10,0,20,0,-10,40))]
        self.assertEqual(assemble_components(tiles[:1]), []) # 800m² is not final.
        joined = assemble_components(tiles)
        self.assertEqual(len(joined),1)
        self.assertEqual(union(joined).symmetric_difference(union(whole)).area,0)
        self.assertEqual(union(joined).area,1600)

    def test_missing_depth_and_holes_are_never_filled(self):
        rock = Polygon(box(0,0,40,40).exterior.coords,
                       [box(10,10,20,20).exterior.coords])
        depth = np.full((4,4),30.,dtype='float32')
        depth[0,0] = np.nan
        valid = np.ones((4,4),dtype=bool); valid[0,1] = False
        result = union(assemble_components([extract({'r':rock},depth,valid)],min_area_m2=1))
        self.assertEqual(result.area,1300)
        self.assertEqual(result.intersection(box(10,10,20,20)).area,0)
        self.assertEqual(result.intersection(box(0,30,20,40)).area,0)

    def test_nominal_depth_limits_inclusive_and_shallow_retained_elsewhere(self):
        depth=np.array([[7.61,7.62,91.44,91.45],[5.,-20.,np.inf,30.]],dtype='float64')
        result=union(assemble_components([extract({'r':box(0,0,40,40)},depth)],min_area_m2=1))
        self.assertEqual(result.area,300)

    def test_filter_connected_components_not_original_record_total(self):
        parts=unary_union([box(0,0,20,30),box(30,0,50,30)])
        self.assertEqual(parts.area,1200)
        self.assertEqual(assemble_components([NativeFragments(CRS_METRES,{'record1':parts})]),[])

    def test_subtract_native_baseline_before_connected_area_filter(self):
        fragments=NativeFragments(CRS_METRES,{'record':box(0,0,50,40)})
        baseline=NativeFragments(CRS_METRES,{'existing':box(0,0,20,40)})
        result=assemble_components([fragments],existing=baseline)
        self.assertEqual(union(result).area,1200)
        self.assertEqual(union(result).intersection(box(0,0,20,40)).area,0)

    def test_duplicate_tiles_and_original_record_overlap_not_double_counted(self):
        batch=NativeFragments(CRS_METRES,{'a':box(0,0,50,40),'b':box(25,0,75,40)})
        rows=assemble_components([batch,batch])
        self.assertEqual(sum(g.area for _,g in rows),3000)
        self.assertEqual(union(rows).area,3000)

    def test_small_prior_record_stays_occupied(self):
        batch=NativeFragments(CRS_METRES,{'a':box(0,0,20,40),'b':box(0,0,40,40)})
        self.assertEqual(assemble_components([batch]),[])

    def test_invalid_original_polygon_not_repaired(self):
        invalid=Polygon([(0,0),(40,40),(0,40),(40,0),(0,0)])
        with self.assertRaisesRegex(ValueError,'no repair'):
            extract({'r':invalid},np.full((4,4),30.,dtype='float32'))

    def test_require_verified_normalized_depth_convention(self):
        with self.assertRaisesRegex(ValueError,'positive-down'):
            window_fragments({'r':box(0,0,40,40)},np.full((4,4),30.),
                             np.ones((4,4),dtype=bool),Affine.identity(),CRS_METRES,
                             depth_band_description='elevation_m')

    def test_reject_geographic_feet_or_mismatched_crs(self):
        for crs in [4326,2227]:
            with self.subTest(crs=crs),self.assertRaisesRegex(ValueError,'metre CRS'):
                extract({'r':box(0,0,40,40)},np.full((4,4),30.),crs=crs)
        a=NativeFragments(CRS_METRES,{'a':box(0,0,40,40)})
        b=NativeFragments(CRS.from_epsg(32610),{'b':box(0,0,40,40)})
        with self.assertRaisesRegex(ValueError,'tile CRS mismatch'):
            assemble_components([a,b])
        with self.assertRaisesRegex(ValueError,'baseline CRS mismatch'):
            assemble_components([a],existing=b)

    def test_reject_unbounded_shape_bad_mask_or_grid(self):
        for depth,valid,affine in [
            (np.ones((513,1)),np.ones((513,1),dtype=bool),Affine.identity()),
            (np.ones((1,1)),np.ones((1,1),dtype='uint8'),Affine.identity()),
            (np.ones((1,1)),np.ones((1,1),dtype=bool),Affine(0,0,0,0,0,0)),
        ]:
            with self.subTest(shape=depth.shape,mask=valid.dtype),self.assertRaises(ValueError):
                extract({'r':box(0,0,40,40)},depth,valid,affine)

    def test_masked_depth_or_valid_refused_before_polygonization(self):
        plain_d = np.full((4,4),30.,dtype='float32')
        plain_v = np.ones((4,4),dtype=bool)
        one_cell = np.zeros((4,4),dtype=bool); one_cell[1,1] = True
        cases = {
            'all_masked_depth': (np.ma.masked_array(plain_d,mask=True), plain_v),
            'all_masked_valid': (plain_d, np.ma.masked_array(plain_v,mask=True)),
            'partial_depth': (np.ma.masked_array(plain_d,mask=one_cell), plain_v),
            'partial_valid': (plain_d, np.ma.masked_array(plain_v,mask=one_cell)),
            'nomask_depth': (np.ma.masked_array(plain_d,mask=False), plain_v),
            'nomask_valid': (plain_d, np.ma.masked_array(plain_v,mask=False)),
            'both': (np.ma.masked_array(plain_d,mask=one_cell),
                     np.ma.masked_array(plain_v,mask=one_cell)),
        }
        for name,(depth,valid) in cases.items():
            before = (np.ma.getmaskarray(depth).copy(), np.ma.getmaskarray(valid).copy())
            with self.subTest(case=name), mock.patch.object(
                    bedrock_vectors,'shapes',side_effect=AssertionError('polygonized')) as shp:
                with self.assertRaisesRegex(ValueError,'Masked native depth or validity'):
                    extract({'r':box(0,0,40,40)},depth,valid)
                shp.assert_not_called()
            self.assertTrue(np.array_equal(np.ma.getmaskarray(depth),before[0]))
            self.assertTrue(np.array_equal(np.ma.getmaskarray(valid),before[1]))

    def test_plain_arrays_still_admitted_and_masks_resolved_by_caller(self):
        rock = {'r':box(0,0,40,40)}
        depth = np.full((4,4),30.,dtype='float32')
        self.assertEqual(union(assemble_components([extract(rock,depth)])).area,1600)
        self.assertEqual(extract(rock,depth,np.zeros((4,4),dtype=bool)).by_record,{})
        nested = extract(rock,[[30.]*4]*4,[[True]*4]*4)  # lists: old conversion kept
        self.assertEqual(nested.by_record['r'].area,1600)
        masked = np.ma.masked_array(depth,mask=np.zeros((4,4),dtype=bool))
        masked.mask[0,0] = True
        resolved = extract(rock,masked.filled(np.nan),~np.ma.getmaskarray(masked))
        self.assertEqual(resolved.by_record['r'].area,1500)
        self.assertEqual(resolved.by_record['r'].intersection(box(0,30,10,40)).area,0)

    def test_empty_mask_and_empty_batches_are_not_missing_coverage_claims(self):
        result=extract({'r':box(0,0,40,40)},np.full((4,4),30.),np.zeros((4,4),dtype=bool))
        self.assertEqual(result.by_record,{})
        self.assertEqual(assemble_components([result]),[])
        self.assertEqual(assemble_components([]),[])


if __name__ == '__main__':
    unittest.main()
