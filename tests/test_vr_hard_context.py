import json
from pathlib import Path
import unittest

from affine import Affine
import numpy as np

from scripts.build_vr_hard_context import DisplayMask


ROOT=Path(__file__).resolve().parents[1]


class VRHardContextTests(unittest.TestCase):
    def test_native_cell_display_alignment_preserves_north_up_position(self):
        mask=DisplayMask((0,0,50,50))
        source=np.zeros((3,3),dtype=bool)
        source[0,0]=True
        depth=np.full((3,3),-20.0)
        mask.add(source,depth,Affine(5,0,10,0,-5,40),'EPSG:26910')
        self.assertEqual(mask.array.sum(),1)
        self.assertEqual(mask.array[2,2],1)
        self.assertEqual(mask.array[4,4],0)
        self.assertEqual(mask.sample_depth[2,2],-20)
        self.assertTrue(np.isnan(mask.sample_depth[4,4]))

    def test_published_context_keeps_depth_policy_separate_from_local_depth(self):
        layer=json.loads((ROOT/'dist/data/cape-mendocino-native-hard-context.geojson').read_text())
        screen=json.loads((ROOT/'dist/data/noaa-h11975-cape-mendocino-hard-depth-screen.json').read_text())
        self.assertEqual(layer['source_screen_counts'],screen['counts'])
        self.assertGreater(len(layer['features']),100)
        for feature in layer['features']:
            p=feature['properties']
            self.assertEqual(p['depth_range_kind'],'screened-policy-not-local-depth-range')
            self.assertNotIn('depth_ft_range',p)
            self.assertGreaterEqual(p['sampled_relief_5_95_m'],0)
            self.assertGreaterEqual(p['display_depth_samples'],20)
            self.assertIs(p['fishing_target'],False)
            self.assertIs(p['exportable'],False)


if __name__=='__main__':unittest.main()
