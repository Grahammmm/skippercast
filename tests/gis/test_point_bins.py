"""Synthetic tests for private no-fill lidar/point-density diagnostics."""
import unittest

import numpy as np

from research.scripts.inspect_point_bins import bin_points, supported_bins, verify_reference


class PointBinTests(unittest.TestCase):
    def test_complete_mixed_depth_sparse_missing_and_nominal_boundary(self):
        a = np.array([[1,1,d] for d in (-1,10,12)]
                     + [[6,1,d] for d in (91.44,91.44,91.44)]
                     + [[11,1,d] for d in (60,70,91.441)]
                     + [[16,1,d] for d in (8,9)]
                     + [[21,1,d] for d in (0,1,2)])
        g = bin_points(a, bounds=(0,0,30,5))
        self.assertEqual(supported_bins(g).tolist(), [[False,True,False,False,False,False]])
        self.assertTrue(np.isnan(g['median_depth'][0,5]))
        self.assertEqual(verify_reference(a,g)['mismatches'],0)
        # Depth prefiltering would falsely credit the first and third bins.
        filtered = a[(a[:,2]>0)&(a[:,2]<=91.44)]
        self.assertLess(len(filtered),g['inside_count'])

    def test_lattice_tile_edges_match_full_grid_without_clamping(self):
        a = np.array([[-.001,1,4],[0,0,1],[4.999,4.999,2],[5,5,3],
                      [9.999,9.999,4],[10,1,5],[1,10,6],[5,0,7],[0,5,8]])
        full = bin_points(a,bounds=(0,0,10,10))
        mosaic = {k: np.empty_like(full[k]) for k in ('count','median_depth','min_depth','max_depth','median_residual_rms')}
        for bottom in range(2):
            for col in range(2):
                tile = bin_points(a,bounds=(col*5,bottom*5,(col+1)*5,(bottom+1)*5))
                verify_reference(a,tile)
                for k in mosaic:mosaic[k][1-bottom,col]=tile[k][0,0]
        self.assertEqual(full['inside_count'],6)
        for k in mosaic:np.testing.assert_equal(full[k],mosaic[k])
        verify_reference(a,full)

    def test_even_upper_median_residual_rms_and_negative_coordinates(self):
        a = np.array([[-9,-9,d] for d in (1,2,3,8)])
        g=bin_points(a)
        self.assertEqual(g['bounds'],[-10,-10,-5,-5])
        self.assertEqual(g['median_depth'][0,0],3)
        self.assertAlmostEqual(g['median_residual_rms'][0,0],np.sqrt(30/3))
        verify_reference(a,g)

    def test_large_metric_coordinates_tile_parity(self):
        a=np.array([[-200005.+dx,-200000.+dy,depth]
                    for dx,dy,depth in ((0,0,2),(4.99,4.99,4),(5,5,7),(9.99,9.99,9))])
        g=bin_points(a,bounds=(-200005,-200000,-199995,-199990))
        verify_reference(a,g)
        for bounds,row,col in (((-200005,-200000,-200000,-199995),1,0),
                               ((-200000,-199995,-199995,-199990),0,1)):
            tile=bin_points(a,bounds=bounds);verify_reference(a,tile)
            for field in ('count','median_depth','min_depth','max_depth','median_residual_rms'):
                self.assertEqual(tile[field][0,0],g[field][row,col])

    def test_empty_grid_no_fill_and_invalid_resource_inputs(self):
        a=np.empty((0,3)); g=bin_points(a,bounds=(0,0,10,10))
        self.assertFalse(supported_bins(g).any());verify_reference(a,g)
        for args in ({},{'spacing':0},{'spacing':float('nan')},
                     {'spacing':1e-300,'bounds':(0,0,10,10)}, {'bounds':(0,0,1e6,1e6)},
                     {'bounds':(0,0,9,10)},{'bounds':(0,0,0,5)}):
            with self.subTest(args=args),self.assertRaises(ValueError):bin_points(a,**args)
        with self.assertRaises(ValueError):bin_points([[0,0,float('nan')]])
        with self.assertRaises(ValueError):supported_bins(g,minimum_returns=True)

    def test_reference_detects_changed_contributors_statistics_and_fake_fill(self):
        a=np.array([[1,1,5],[2,2,6],[3,3,7]])
        for field in ('count','median_depth','min_depth','max_depth','median_residual_rms'):
            g=bin_points(a,bounds=(0,0,10,5));g[field][0,0]+=1
            with self.subTest(field=field),self.assertRaises(ValueError):verify_reference(a,g)
        g=bin_points(a,bounds=(0,0,10,5));g['median_depth'][0,1]=5
        with self.assertRaisesRegex(ValueError,'Missing bins'):verify_reference(a,g)


if __name__=='__main__':unittest.main()
