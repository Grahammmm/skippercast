"""Point Buchon's resampled deep grid and soft bottom must not create fine reefs."""
import json
import unittest

import numpy as np

from skippercast.seafloor.habitat import rough_mask
from skippercast.seafloor.manifest import load_manifest
from skippercast.seafloor.resolution_profile import fine_detail_valid
from skippercast.seafloor.substrate import classify, resolve_bindings
from tests._support import ROOT


class BuchonBatchTests(unittest.TestCase):
    def setUp(self):
        self.manifest = load_manifest()
        self.rules = json.loads((ROOT/'catalog/habitat-rules.json').read_text())
        self.ident = 'bathymetry-offshorepointbuchon-zip-fcc90bde5c'
        self.row = next(r for r in self.manifest['surveys'] if r['id'] == self.ident)
        self.entry = resolve_bindings(self.rules, self.manifest)[self.ident]

    def test_qualified_source_excludes_upsampled_deep_pixels_and_missing_data(self):
        depth = np.array([[79.99, 80, 85, 91.44, 79]], dtype='float32')
        valid = np.array([[True, True, True, True, False]])
        np.testing.assert_array_equal(fine_detail_valid(depth, valid, self.row),
                                      [[True, False, False, False, False]])
        receipt = json.loads((ROOT/'research/receipts/seafloor-point-buchon-native-review.json').read_text())
        self.assertEqual(self.row['resolution_profile'], receipt['bathymetry']['effective_resolution_profile'])
        self.assertEqual(self.row['sha256'], receipt['bathymetry']['source_sha256'])
        self.assertEqual(self.row['vertical_datum'], 'unknown')
        self.assertTrue(self.entry['binding']['same_survey_as_depth'])
        self.assertEqual(self.entry['binding']['metadata_sha256'], receipt['substrate']['metadata_sha256'])
        self.assertEqual(self.entry['row']['archive_member'], receipt['substrate']['archive_member'])

    def test_soft_sediment_is_excluded_even_with_rugose_terrain(self):
        codes = np.array([[1, 2, 3]], dtype='float32')
        valid = np.ones(codes.shape, bool)
        classes = classify(codes, valid, self.entry['binding'])
        terrain = {'vrm': np.full(codes.shape, .2), 'bpi_fine_m': np.full(codes.shape, 5.)}
        actual = rough_mask(np.full(codes.shape, 50.), valid, valid, terrain, classes,
                            {'vrm': .1, 'bpi_fine_m': 1.}, self.rules)
        np.testing.assert_array_equal(actual, [[False, True, True]])
        np.testing.assert_array_equal(classify(codes, np.array([[True, True, False]]),
                                              self.entry['binding']), [[1, 2, 0]])
