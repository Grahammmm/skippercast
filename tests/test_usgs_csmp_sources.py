"""Original USGS composite-code and duplicate-source protections."""
import unittest

import numpy as np

from scripts.import_usgs_seafloor_character import class_mask
from scripts.audit_usgs_catalog_duplicate_context import audit


class UsgsCsmpSourceTests(unittest.TestCase):
    def test_composite_class_three_uses_reviewed_ones_digit(self):
        codes = np.array([[-128, 1, 3, 13, 53, 63, 103, 113, 14]], dtype='int16')
        source = {'class': 3, 'class_code_rule': 'ones-digit',
                  'valid_codes': [-128, 1, 3, 13, 53, 63, 103, 113, 14]}
        self.assertEqual(class_mask(codes, source).tolist()[0],
                         [False, False, True, True, True, True, True, True, False])
        with self.assertRaisesRegex(ValueError, 'Unreviewed seafloor class code'):
            class_mask(np.array([[23]]), source)

    def test_duplicate_crosswalk_does_not_count_overlap_as_new_ground(self):
        square = {'type': 'Polygon', 'coordinates': [[[0, 0], [.01, 0], [.01, .01], [0, .01], [0, 0]]]}
        candidate = {'scope': 'generalized-statewide-usgs-hard-bottom-context',
                     'source_catalog_url': 'https://cmgds.marine.usgs.gov/data/csmp/',
                     'features': [{'geometry': square, 'properties': {'block_id': 'A',
                         'fishing_target': False, 'exportable': False}}]}
        shard = {'scope': candidate['scope'], 'features': [{'geometry': square,
                 'properties': {'release_id': 'DOI-A', 'fishing_target': False}}]}
        result = audit(candidate, [shard])
        self.assertEqual(result['fully_contained_outlines'], 1)
        self.assertEqual(result['blocks'][0]['doi_release_ids'], ['DOI-A'])


if __name__ == '__main__':
    unittest.main()
