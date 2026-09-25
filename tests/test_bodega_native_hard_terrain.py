"""Public Bodega terrain receipt must remain a research queue, not waypoints."""
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BodegaNativeHardTerrainTests(unittest.TestCase):
    def test_public_review_has_no_promoted_spots(self):
        review = json.loads((ROOT / 'dist/data/bodega-native-hard-terrain-review.json').read_text())
        chart = json.loads((ROOT / 'dist/data/bodega-native-enc-scope-review.json').read_text())
        atlas = json.loads((ROOT / 'dist/regions/bodega-point-reyes/atlas.json').read_text())
        self.assertEqual(review['status'], 'research-ranking-only')
        self.assertEqual(review['reviewed_outlines'], 74)
        self.assertEqual(review['charted_danger_proximity_holds'], 1)
        self.assertEqual(review['source_context_sha256'], chart['source_context_sha256'])
        self.assertEqual(len(review['rows']), review['reviewed_outlines'])
        self.assertEqual(len({row['context_id'] for row in review['rows']}), 74)
        self.assertEqual(sum(review['grades'].values()) + review['unranked_outlines'], 74)
        for row in review['rows']:
            self.assertNotIn('latitude', row)
            self.assertNotIn('longitude', row)
            self.assertNotIn('geometry', row)
            self.assertNotIn('fishing_export', row)
            if row['terrain'] is not None:
                self.assertGreaterEqual(row['display_area_m2'], 2500)
                self.assertGreater(row['qualified_native_cells'], 0)
                self.assertIsNone(row['terrain']['catch_probability'])
                depths = row['sampled_original_depth_ft']
                self.assertLessEqual(25, depths['minimum'])
                self.assertLessEqual(depths['minimum'], depths['p05'])
                self.assertLessEqual(depths['p05'], depths['median'])
                self.assertLessEqual(depths['median'], depths['p95'])
                self.assertLessEqual(depths['p95'], depths['maximum'])
                self.assertLessEqual(depths['maximum'], 200)
            else:
                self.assertIsNone(row['sampled_original_depth_ft'])
        self.assertEqual(atlas['targets'], [])
        self.assertEqual(atlas['areas'], [])


if __name__ == '__main__':
    unittest.main()
