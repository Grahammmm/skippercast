"""A malformed prior GEFS manifest is a reuse cache miss, and force never decodes it (offline, synthetic)."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from skippercast.forecast import ensemble

CYCLE = datetime(2026, 9, 27, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 9, 27, 5, tzinfo=timezone.utc)
REGIONS = {'a': [(35.5, -121.0), (35.5, -121.0)], 'b': [(36.0, -122.0)]}


class Collector:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def __call__(self, cycle, points, http=None, workers=32, log=None):
        self.calls.append(list(points))
        if self.fail:
            raise RuntimeError(self.fail)
        samples = [{'latitude': lat, 'longitude': lon, 'grid': [lat, lon], 'distance_km': 0.0,
                    'wind_speed_10m': [[1.0]], 'wind_gusts_10m': [[2.0]]} for lat, lon in points]
        return samples, {'messages': 7, 'missing': []}


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.collector = Collector()
        for target, value in (('latest_cycle', lambda now, **_: CYCLE), ('collect', self.collector),
                              ('STEPS', (0,)), ('MEMBERS', 1)):
            patcher = patch.object(ensemble, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.published = self.tmp / 'published'
        self.assertEqual(ensemble.build(self.published, None, now=NOW, regions=REGIONS, log=lambda *_: None)['state'], 'built')
        self.collector.calls.clear()
        self.manifest = self.published / 'ncep_gefs025' / 'manifest.json'
        self.good = json.loads(self.manifest.read_text())

    def build(self, out='out', force=False, regions=None):
        return ensemble.build(self.tmp / out, self.published, force, now=NOW,
                              regions=REGIONS if regions is None else regions, log=lambda *_: None)

    def snapshot(self, root):
        base = self.tmp / root / 'ncep_gefs025'
        return {str(p.relative_to(base)): p.read_bytes() for p in sorted(base.rglob('*')) if p.is_file()}

    def assert_rebuilt(self, status, out='out'):
        self.assertEqual((status['status'], status['state']), ('ok', 'built'))
        self.assertEqual(len(self.collector.calls), 1)
        rebuilt = json.loads((self.tmp / out / 'ncep_gefs025' / 'manifest.json').read_text())
        self.assertEqual((rebuilt['cycle'], rebuilt['regions']), (self.good['cycle'], ['a', 'b']))
        points = json.loads((self.tmp / out / 'ncep_gefs025' / 'regions' / 'a.json').read_text())['points']
        self.assertEqual([(p['latitude'], p['longitude']) for p in points], REGIONS['a'])

    def test_corrupt_json_cache_rebuilds_instead_of_recopied_failure(self):
        self.manifest.write_text('{not json')
        before = self.snapshot('published')
        self.assert_rebuilt(self.build())
        self.assertEqual(self.snapshot('published'), before)

    def test_nonobject_and_bad_reuse_fields_are_cache_misses(self):
        good = self.good
        cases = {'array': [1], 'string': 'x', 'number': 3, 'true': True, 'null': None, 'empty': {},
                 'empty array': [], 'no cycle': {**good, 'cycle': None}, 'string cycle': {**good, 'cycle': str(good['cycle'])},
                 'bool cycle': {**good, 'cycle': True}, 'float cycle': {**good, 'cycle': float(good['cycle']) + 0.5},
                 'no regions': {k: v for k, v in good.items() if k != 'regions'}, 'int regions': {**good, 'regions': 2},
                 'dict regions': {**good, 'regions': {'a': 1, 'b': 2}}, 'mixed regions': {**good, 'regions': ['a', 2]},
                 'no cycle_iso': {k: v for k, v in good.items() if k != 'cycle_iso'}, 'empty cycle_iso': {**good, 'cycle_iso': ''},
                 'int cycle_iso': {**good, 'cycle_iso': 5}, 'no built_at': {k: v for k, v in good.items() if k != 'built_at'},
                 'empty built_at': {**good, 'built_at': ''}, 'null built_at': {**good, 'built_at': None},
                 'older cycle': {**good, 'cycle': good['cycle'] - 21600}, 'other regions': {**good, 'regions': ['a', 'z']}}
        for name, content in cases.items():
            with self.subTest(name):
                self.manifest.write_text(json.dumps(content))
                self.assert_rebuilt(self.build())
                self.collector.calls.clear()

    def test_force_never_reads_the_corrupt_reuse_manifest(self):
        self.manifest.write_text('{not json')
        real, reads = Path.read_text, []

        def spy(path, *args, **kwargs):
            reads.append(path)
            return real(path, *args, **kwargs)

        with patch.object(Path, 'read_text', spy):
            status = self.build(force=True)
        self.assertNotIn(self.manifest, reads)
        self.assert_rebuilt(status)

    def test_force_with_valid_prior_still_rebuilds(self):
        self.assert_rebuilt(self.build(force=True))

    def test_unreadable_manifest_and_invalid_utf8_are_misses(self):
        real = Path.read_text

        def deny(path, *args, **kwargs):
            if path == self.manifest:
                raise PermissionError('denied')
            return real(path, *args, **kwargs)

        with patch.object(Path, 'read_text', deny):
            self.assert_rebuilt(self.build())
        self.collector.calls.clear()
        self.manifest.write_bytes(b'{"cycle": "\xff\xfe"}')
        self.assert_rebuilt(self.build('out2'), 'out2')

    def test_eligible_same_cycle_ordered_points_still_reuse(self):
        reversed_regions = dict(reversed(list(REGIONS.items())))
        before = self.snapshot('published')
        status = self.build(regions=reversed_regions)
        self.assertEqual((status['status'], status['state']), ('ok', 'current'))
        self.assertEqual((status['cycle'], status['built_at']), (self.good['cycle_iso'], self.good['built_at']))
        self.assertEqual(self.collector.calls, [])
        self.assertEqual(self.snapshot('out'), before)

    def test_rebuild_failure_still_reports_failure_and_preserves_prior(self):
        self.collector.fail = 'boom'
        for name, forced, corrupt in (('corrupt manifest', False, True), ('valid forced', True, False)):
            with self.subTest(name):
                self.manifest.write_text('{not json' if corrupt else json.dumps(self.good))
                before = self.snapshot('published')
                status = self.build(out='out-' + name.split()[0], force=forced)
                self.assertEqual((status['status'], status['kept_previous']), ('failed', True))
                self.assertIn('boom', status['issue'])
                self.assertNotIn('state', status)
                self.assertEqual(self.snapshot('out-' + name.split()[0]), before)

    def test_same_directory_recovery_and_input_preservation(self):
        self.manifest.write_text('{not json')
        regions = {k: list(v) for k, v in REGIONS.items()}
        status = ensemble.build(self.published, self.published, now=NOW, regions=regions, log=lambda *_: None)
        self.assertEqual((status['status'], status['state']), ('ok', 'built'))
        self.assertEqual(json.loads(self.manifest.read_text())['cycle'], self.good['cycle'])
        self.assertEqual(regions, {k: list(v) for k, v in REGIONS.items()})


if __name__ == '__main__':
    unittest.main()
