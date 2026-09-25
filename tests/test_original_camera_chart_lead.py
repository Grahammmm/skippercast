"""Source identity and complete chart response gates for camera/chart leads."""
import hashlib
import json
import unittest
from pathlib import Path

from scripts.audit_original_camera_chart_lead import audit
from scripts.summarize_original_camera_chart_lead import summarize


class OriginalCameraChartLeadTests(unittest.TestCase):
    def test_public_summary_removes_camera_positions_and_requires_complete_hold(self):
        published = json.loads((Path(__file__).resolve().parents[1] /
                                'dist/data/h11971-bear-landing-research-review.json').read_text())
        full = dict(published)
        full['transects'] = [dict(row, camera_position_bounds=[-124.03, 39.93, -124.02, 39.94])
                             for row in published['transects']]
        summary = summarize(full)
        self.assertEqual(summary['historical_camera_windows'], 13)
        self.assertFalse(summary['fishing_target'])
        self.assertNotIn('camera_position_bounds', json.dumps(summary))
        full['enc_danger_queried_layers'] = 17
        with self.assertRaisesRegex(ValueError, 'complete research review'):
            summarize(full)
        full['enc_danger_queried_layers'] = 18
        full['fishing_target'] = True
        with self.assertRaisesRegex(ValueError, 'complete research review'):
            summarize(full)

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

    def test_unheld_arena_bodega_review_preserves_mpa_proximity(self):
        root = Path(__file__).resolve().parents[1]
        for year, count in ((2008, 40), (2010, 14)):
            report = json.loads((root / f'dist/data/h11730-arena-bodega-{year}-research-review.json').read_text())
            self.assertIsNone(report['survey_fishing_promotion_hold'])
            self.assertEqual(report['historical_camera_windows'], count)
            self.assertFalse(report['fishing_target'])
            self.assertFalse(report['exportable'])
            self.assertNotIn('camera_position_bounds', json.dumps(report))
            self.assertNotIn('"latitude"', json.dumps(report))
        self.assertEqual(report['transects'][0]['within_100m_mpa_review_buffer'], 4)


if __name__ == '__main__':
    unittest.main()
