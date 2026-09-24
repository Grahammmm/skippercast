"""Source identity and complete chart response gates for camera/chart leads."""
import hashlib
import unittest

from scripts.audit_original_camera_chart_lead import audit


class OriginalCameraChartLeadTests(unittest.TestCase):
    def test_changed_camera_archive_and_incomplete_chart_receipt_fail_closed(self):
        pair = {'survey_id': 'H11876', 'survey_report_url': 'https://example.test/H11876.pdf',
                'camera_archive_sha256': hashlib.sha256(b'original').hexdigest()}
        report = {'survey_id': 'H11876', 'report_url': pair['survey_report_url'],
                  'report_sha256': hashlib.sha256(b'report').hexdigest()}
        with self.assertRaisesRegex(ValueError, 'camera ZIP'):
            audit(pair, b'changed', {}, {}, report, b'report')
        with self.assertRaisesRegex(ValueError, 'Complete bounded ENC'):
            audit(pair, b'original', {'query_receipts': [{'count': 0}] * 17,
                                      'source_url': 'https://encdirect.noaa.gov/arcgis/rest/services/encdirect',
                                      'features': []}, {}, report, b'report')


if __name__ == '__main__':
    unittest.main()
