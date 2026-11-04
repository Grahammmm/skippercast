"""GEFS same-cycle reuse is gated on the saved ordered forecast-point coordinates (offline, synthetic)."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skippercast.forecast import ensemble

CYCLE = datetime(2026, 9, 27, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 9, 27, 5, tzinfo=timezone.utc)
NAN, INF = float('nan'), float('inf')


class Collector:
    """Stands in for the GRIB collector: records calls, labels samples with the requested coordinates."""

    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def __call__(self, cycle, points, http=None, workers=32, log=None):
        self.calls.append(list(points))
        if self.fail:
            raise RuntimeError(self.fail)
        samples = [{'latitude': lat, 'longitude': lon, 'grid': [lat, lon], 'distance_km': 0.0,
                    'wind_speed_10m': [[1.0]], 'wind_gusts_10m': [[2.0]]} for lat, lon in points]
        return samples, {'messages': 7, 'missing': []}


class ReuseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(self.tmp, ignore_errors=True))
        self.collector = Collector()
        for target, value in (('latest_cycle', lambda now, **_: CYCLE), ('collect', self.collector),
                              ('STEPS', (0,)), ('MEMBERS', 1)):
            patcher = patch.object(ensemble, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.published = self.tmp / 'published'

    def build(self, regions, out='out', previous=True, force=False):
        return ensemble.build(self.tmp / out, self.published if previous else None, force, now=NOW,
                              regions=regions, log=lambda *_: None)

    def first(self, regions):
        status = self.build(regions, out='published', previous=False)
        self.assertEqual(status['state'], 'built')
        self.collector.calls.clear()

    def region_file(self, root, region_id='a'):
        return Path(self.tmp, root, 'ncep_gefs025', 'regions', f'{region_id}.json')

    def saved(self, root, region_id='a'):
        return [(p['latitude'], p['longitude']) for p in json.loads(self.region_file(root, region_id).read_text())['points']]

    def test_same_cycle_moved_point_rebuilds(self):
        self.first({'a': [(35.5, -121.0), (35.6, -121.1)]})
        status = self.build({'a': [(35.5, -121.0), (35.7, -121.1)]})
        self.assertEqual((status['status'], status['state']), ('ok', 'built'))
        self.assertEqual(len(self.collector.calls), 1)
        self.assertEqual(self.saved('out'), [(35.5, -121.0), (35.7, -121.1)])

    def test_same_cycle_reordered_added_removed_points_rebuild(self):
        base = [(35.5, -121.0), (35.6, -121.1)]
        cases = (('reorder', base, base[::-1]), ('append', base, base + [(35.7, -121.2)]), ('remove', base, base[:1]),
                 ('duplicate added', base, base + [base[0]]), ('duplicate removed', base + [base[0]], base))
        for name, prior, changed in cases:
            with self.subTest(name):
                shutil_rm(self.tmp)
                self.first({'a': prior})
                status = self.build({'a': changed})
                self.assertEqual(status['state'], 'built')
                self.assertEqual(len(self.collector.calls), 1)
                self.assertEqual(self.saved('out'), changed)  # order and multiplicity preserved
                self.collector.calls.clear()

    def test_identical_points_reuse_without_collection(self):
        self.first({'a': [(35.5, -121.0), (35.5, -121.0)], 'b': [(36, -122)]})
        before = self.region_file('published', 'b').read_bytes()
        status = self.build({'b': [(36.0, -122.0)], 'a': [(35.5, -121.0), (35.5, -121.0)]})
        self.assertEqual((status['status'], status['state']), ('ok', 'current'))
        self.assertEqual(self.collector.calls, [])
        self.assertEqual(self.region_file('out', 'b').read_bytes(), before)

    def test_unreadable_or_malformed_prior_points_rebuild(self):
        pt = {'latitude': 35.5, 'longitude': -121.0}
        cases = {
            'absent file': None,
            'broken json': '{not json',
            'not an object': '[]',
            'missing points': {},
            'points not a list': {'points': {'latitude': 35.5}},
            'too few': {'points': []},
            'too many': {'points': [pt, pt]},
            'point not object': {'points': [[35.5, -121.0]]},
            'missing lon': {'points': [{'latitude': 35.5}]},
            'missing lat': {'points': [{'longitude': -121.0}]},
            'string lat': {'points': [{'latitude': '35.5', 'longitude': -121.0}]},
            'string lon': {'points': [{'latitude': 35.5, 'longitude': '-121.0'}]},
            'bool lat': {'points': [{'latitude': True, 'longitude': -121.0}]},
            'bool lon': {'points': [{'latitude': 35.5, 'longitude': False}]},
            'nan': {'points': [{'latitude': NAN, 'longitude': -121.0}]},
            'inf': {'points': [{'latitude': 35.5, 'longitude': INF}]},
            'oversized int lat': {'points': [{'latitude': 10**400, 'longitude': -121.0}]},
            'oversized int lon': {'points': [{'latitude': 35.5, 'longitude': -(10**400)}]},
            'null': {'points': [{'latitude': None, 'longitude': -121.0}]},
        }
        for name, content in cases.items():
            with self.subTest(name):
                shutil_rm(self.tmp)
                self.first({'a': [(35.5, -121.0)]})
                path = self.region_file('published')
                if content is None:
                    path.unlink()
                else:
                    path.write_text(content if isinstance(content, str) else json.dumps(content))
                status = self.build({'a': [(35.5, -121.0)]})
                self.assertEqual((status['status'], status['state']), ('ok', 'built'))
                self.assertEqual(len(self.collector.calls), 1)
                self.assertEqual(self.saved('out'), [(35.5, -121.0)])
                self.collector.calls.clear()

    def test_changed_points_failed_collection_is_failed_with_previous(self):
        self.first({'a': [(35.5, -121.0)]})
        before = self.region_file('published').read_bytes()
        self.collector.fail = 'boom'
        status = self.build({'a': [(35.9, -121.0)]})
        self.assertEqual((status['status'], status['kept_previous']), ('failed', True))
        self.assertIn('boom', status['issue'])
        self.assertNotIn('state', status)
        self.assertEqual(self.region_file('out').read_bytes(), before)
        self.assertEqual(self.saved('out'), [(35.5, -121.0)])  # old labels are not rewritten

    def test_force_rebuilds_identical_points(self):
        self.first({'a': [(35.5, -121.0)]})
        self.assertEqual(self.build({'a': [(35.5, -121.0)]}, force=True)['state'], 'built')
        self.assertEqual(len(self.collector.calls), 1)

    def test_changed_region_ids_still_rebuild(self):
        self.first({'a': [(35.5, -121.0)]})
        self.assertEqual(self.build({'a': [(35.5, -121.0)], 'b': [(36.0, -122.0)]})['state'], 'built')
        self.assertEqual(len(self.collector.calls), 1)


def shutil_rm(root):
    import shutil
    for child in Path(root).iterdir():
        shutil.rmtree(child, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
