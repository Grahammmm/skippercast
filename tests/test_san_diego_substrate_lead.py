"""The bounded substrate review must retain source identity and completeness."""
import unittest
from unittest.mock import patch

from scripts.audit_san_diego_substrate_lead import query, review


class SanDiegoSubstrateLeadTests(unittest.TestCase):
    def test_missing_feature_page_fails_closed(self):
        metadata = {'geometryType': 'esriGeometryPolygon',
                    'fields': [{'name': 'OBJECTID'}, {'name': 'descrip'}]}
        with patch('scripts.audit_san_diego_substrate_lead.fetch', side_effect=[
                (metadata, 'a', b'{}'), ({'count': 1}, 'b', b'{}'),
                ({'type': 'FeatureCollection', 'features': []}, 'c', b'{}')]):
            with self.assertRaisesRegex(ValueError, 'Incomplete substrate polygon query'):
                query()

    def test_changed_camera_zip_fails_before_spatial_claim(self):
        pair = {'bag_url': 'https://example.test/H11876_MB_2m_MLLW_2of5.bag',
                'camera_archive_sha256': '0' * 64}
        with self.assertRaisesRegex(ValueError, 'Original camera/BAG identity changed'):
            review([], {}, pair, b'wrong')


if __name__ == '__main__':
    unittest.main()
