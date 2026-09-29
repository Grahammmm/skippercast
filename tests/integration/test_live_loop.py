from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts.live_loop import intelligence_due, next_slot
from scripts.report_conditions import summarize
from tests._support import NOW


def utc(h, m, s=0):
    return datetime(2026, 9, 27, h, m, s, tzinfo=timezone.utc)


class LiveLoopTests(unittest.TestCase):
    def test_slots_are_7_and_37_past(self):
        self.assertEqual(next_slot(utc(10, 0)), utc(10, 7))
        self.assertEqual(next_slot(utc(10, 7)), utc(10, 37))
        self.assertEqual(next_slot(utc(10, 36, 59)), utc(10, 37))
        self.assertEqual(next_slot(utc(10, 50)), utc(11, 7))
        self.assertEqual(next_slot(utc(23, 40)), datetime(2026, 9, 28, 0, 7, tzinfo=timezone.utc))

    def test_intelligence_due_by_age_or_absence(self):
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / 'intelligence-health.json'
            now = NOW
            self.assertTrue(intelligence_due(marker, now, 55))
            marker.write_text('{}')
            fresh = (now - timedelta(minutes=54)).timestamp()
            os.utime(marker, (fresh, fresh))
            self.assertFalse(intelligence_due(marker, now, 55))
            old = (now - timedelta(minutes=56)).timestamp()
            os.utime(marker, (old, old))
            self.assertTrue(intelligence_due(marker, now, 55))


class ReportTests(unittest.TestCase):
    def write(self, root, degraded=True):
        (root / 'regions').mkdir()
        (root / 'latest.json').write_text(json.dumps({
            'completed_at': '2026-09-27T23:56:19Z',
            'sources': {'b': {'name': 'Buoy', 'status': 'ok', 'data': {'sample_at': 'now'}}},
            'health': {'issues': ['buoy-46244-spectrum'] if degraded else []}}))
        (root / 'regions/index.json').write_text(json.dumps({'regions': [{'region_id': 'morro-bay', 'status': 'ok', 'issues': []}]}))
        for name in ('intelligence-health.json', 'habitat-health.json'):
            (root / name).write_text(json.dumps({'regions': [
                {'region_id': 'morro-bay', 'status': 'degraded', 'issues': ['sst-analysis'] if degraded else []}]}))

    def test_degraded_sources_warn_but_do_not_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root)
            _, failures, warnings = summarize(root, 'success')
            self.assertEqual(failures, [])
            self.assertEqual(warnings, ['buoy-46244-spectrum', 'sst-analysis'])

    def test_failed_publication_or_missing_product_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, degraded=False)
            self.assertIn('Publication was not confirmed', summarize(root, 'failure')[1])
            (root / 'habitat-health.json').unlink()
            self.assertIn('habitat-health.json was not produced', summarize(root, 'success')[1])


if __name__ == '__main__':
    unittest.main()
