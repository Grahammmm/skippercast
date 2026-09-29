"""Keep the Bodega rollout from publishing an unreviewed legal claim.

This module used to hold a bare ``test_*`` function, which ``unittest`` never
collected, so it went stale unnoticed when the region moved from draft to a
limited preview with reviewed rules (ef79ca23a). Under pytest it ran and failed.
It now pins the preview's state: the rules a preview shows are reviewed and
hash-approved, and the local salmon boundary still hides salmon near Bodega.
"""
import json
import re
import unittest
from tests._support import ROOT


class BodegaPreviewTest(unittest.TestCase):
    def setUp(self):
        self.region = json.loads((ROOT / 'regions/bodega-point-reyes/region.json').read_text())
        self.rules = json.loads((ROOT / 'dist/data/regulations-san-francisco.json').read_text())

    def test_local_salmon_boundary_hides_salmon(self):
        north = next(area for area in self.region['map']['local_areas'] if area['id'] == 'bodega-north')
        self.assertEqual(north['bounds'][1], 38 + 2 / 60)
        self.assertTrue(any(item['id'] == 'salmon' for item in north['hidden_targets']))

    def test_preview_rules_are_reviewed_and_hash_approved(self):
        self.assertIn(self.region['status'], {'draft', 'preview'})
        self.assertEqual(self.rules['jurisdiction_id'], self.region['jurisdiction_id'])
        self.assertEqual(set(self.rules['species']),
                         {'lingcod', 'rockfish', 'halibut', 'salmon', 'dungeness', 'albacore'})
        if self.region['status'] == 'draft':
            self.assertEqual(self.rules['rules_review_status'], 'pending')
            return
        self.assertEqual(self.rules['rules_review_status'], 'reviewed')
        for name, source in self.rules['sources'].items():
            with self.subTest(source=name):
                self.assertRegex(source['approved_content_sha256'] or '', re.compile(r'^[0-9a-f]{64}$'))

    def test_no_charter_asset_until_reviewed(self):
        self.assertIsNone(self.region['assets']['charters'])
