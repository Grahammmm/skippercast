"""Monterey's producer-coded sediment must not masquerade as rugose reef."""
import json
from pathlib import Path
import unittest

import numpy as np

from skippercast.seafloor.habitat import rough_mask
from skippercast.seafloor.manifest import load_manifest
from skippercast.seafloor.substrate import classify, resolve_bindings
from tests._support import ROOT


class MontereyBatchTests(unittest.TestCase):
    def setUp(self):
        self.rules = json.loads((ROOT/'catalog/habitat-rules.json').read_text())
        self.depth_id = 'bathymetry-2m-offshoremonterey-zip-172dbd1794'
        self.entry = resolve_bindings(self.rules, load_manifest())[self.depth_id]

    def test_depth_and_slope_encoded_sediment_is_excluded_even_on_rough_terrain(self):
        codes = np.array([[1, 4, 11, 14, 51, 54, 61, 64, 101, 111],
                          [2, 3, 12, 13, 52, 53, 62, 63, 102, 113]], dtype='float32')
        good = np.ones(codes.shape, bool)
        classes = classify(codes, good, self.entry['binding'])
        terrain = {'vrm': np.full(codes.shape, .2), 'bpi_fine_m': np.full(codes.shape, 5.)}
        mask = rough_mask(np.full(codes.shape, 50.), good, good, terrain, classes,
                          {'vrm': .1, 'bpi_fine_m': 1.}, self.rules)
        self.assertFalse(mask[0].any())
        self.assertTrue(mask[1].all())
        np.testing.assert_array_equal(classes[1], [2, 3, 2, 3, 2, 3, 2, 3, 2, 3])

    def test_missing_substrate_never_turns_into_a_measured_hard_bottom_class(self):
        values = np.array([[63, 63]], dtype='float32')
        actual = classify(values, np.array([[True, False]]), self.entry['binding'])
        np.testing.assert_array_equal(actual, [[3, 0]])
        with self.assertRaisesRegex(ValueError, 'Unreviewed substrate codes'):
            classify(np.array([[5]]), np.array([[True]]), self.entry['binding'])

    def test_source_qualification_keeps_mixed_dates_and_same_acquisition_evidence(self):
        manifest = load_manifest()
        row = next(x for x in manifest['surveys'] if x['id'] == self.depth_id)
        receipt = json.loads((ROOT/'research/receipts/seafloor-monterey-native-review.json').read_text())
        self.assertEqual(row['status'], 'usable')
        self.assertEqual(row['year'], 'unknown')
        self.assertEqual(row['vertical_datum'], 'NAVD88')
        self.assertEqual(row['sha256'], receipt['bathymetry']['source_sha256'])
        self.assertEqual(row['adapter_review']['requested_bounds_wgs84'],
                         receipt['bathymetry']['reviewed_window_wgs84'])
        self.assertEqual(receipt['bathymetry']['acoustic_years'], [1998, 2012])
        self.assertEqual(receipt['bathymetry']['lidar_years'], [2009, 2010])
        self.assertTrue(self.entry['binding']['same_survey_as_depth'])
        self.assertEqual(self.entry['binding']['metadata_sha256'], receipt['substrate']['sha256'])
