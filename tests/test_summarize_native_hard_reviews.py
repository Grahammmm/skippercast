import json
from pathlib import Path
import tempfile
import unittest

from scripts.summarize_native_hard_reviews import summarize


class SummaryPrivacyTest(unittest.TestCase):
    def test_summary_keeps_provenance_but_never_candidate_coordinates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'review.geojson'
            path.write_text(json.dumps({
                'scope': 'native-noaa-usgs-hard-bottom-review', 'survey_id': 'H1',
                'survey_dates': ['2007-01-01', '2007-02-01'], 'compiled_at': '2026-09-23T00:00:00Z',
                'noaa_bag_url': 'https://example.test/source.bag', 'noaa_bag_sha256': 'a',
                'survey_report_url': 'https://example.test/report.pdf', 'survey_report_sha256': 'b',
                'usgs_sources': [], 'cdfw_mpa_retrieved_at': '2026-09-23T00:00:00Z',
                'noaa_federal_areas_retrieved_at': '2026-09-23T00:00:00Z',
                'native_resolution_m': [2, 2], 'maximum_planning_depth_ft': 200,
                'bag_tracking_history': {}, 'counts': {'retained_components': 1},
                'features': [{'geometry': {'type': 'Point', 'coordinates': [-123.1, 38.1]},
                              'properties': {'area_m2': 5000, 'fishing_target': False, 'exportable': False}}]}))
            summary = summarize([path])
            self.assertNotIn('coordinates', json.dumps(summary))
            self.assertEqual(summary['surveys'][0]['retained_component_area_m2'], 5000)
            review = json.loads(path.read_text())
            review['features'][0]['properties']['exportable'] = True
            path.write_text(json.dumps(review))
            with self.assertRaisesRegex(ValueError, 'must remain unpublished'):
                summarize([path])


if __name__ == '__main__':
    unittest.main()
