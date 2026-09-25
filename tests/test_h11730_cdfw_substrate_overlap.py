import unittest

from scripts.audit_h11730_cdfw_substrate_overlap import pixel_location, review
from scripts.audit_cdfw_substrate_tiles import BASE, RESOLUTION_M


class CameraSubstrateCrosscheckTests(unittest.TestCase):
    def test_known_point_arena_camera_position_maps_to_expected_source_tile(self):
        row, col, py, px = pixel_location(-123.715688, 38.89704)
        self.assertEqual((row, col, py, px), (34, 11, 187, 50))

    def test_missing_cdfw_tile_audit_fails_before_camera_sampling(self):
        with self.assertRaisesRegex(ValueError, 'Incomplete or changed CDFW'):
            review({'pair_reviews': []}, {}, {}, {'service_url': 'wrong', 'resolution_m': RESOLUTION_M}, None, {})

    def test_changed_original_camera_archive_fails_closed(self):
        pairs = {'pair_reviews': [{'survey_id': 'H11730', 'camera_archive_url': 'f208nc', 'transects': []}]}
        audit = {'service_url': BASE, 'resolution_m': RESOLUTION_M, 'failures': [], 'tiles': []}
        with self.assertRaisesRegex(ValueError, 'Original USGS camera archive changed'):
            review(pairs, {'f208nc': b'changed', 'c210nc': b'changed'},
                   {'f208nc': 'wrong', 'c210nc': 'wrong'}, audit, None, {})


if __name__ == '__main__':
    unittest.main()
