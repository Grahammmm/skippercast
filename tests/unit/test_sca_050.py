"""D1-04: only a complete prior forecast is current or retained."""
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import pytest


MODEL = 'ecmwf_wam'
CYCLE = datetime(2026, 1, 1, tzinfo=timezone.utc)
TILE_KEY = '0_1'
DEFECTS = ('missing tile', 'malformed tile', 'tile model', 'tile cycle', 'tile key',
           'malformed manifest', 'manifest model', 'empty list')


@pytest.mark.gis  # The reserved unit path still needs the GIS tier's numpy.
@unittest.skipUnless(importlib.util.find_spec('numpy'), 'forecast builder requires numpy')
class ForecastGenerationTest(unittest.TestCase):
    def setUp(self):
        import numpy as np
        from skippercast.forecast import build as producer

        self.producer = producer
        root = Path(self.enterContext(TemporaryDirectory()))
        self.previous, self.output = root / 'previous', root / 'output'
        self.latest = self.enterContext(patch.object(producer, 'latest_cycle', return_value=CYCLE))
        self.enterContext(patch.object(producer, 'tile_keys', return_value=[(0, 0), (0, 1)]))
        axes = np.array([0.25, 0.75, 1.25])
        field = producer.MODELS[MODEL].fields[0].name
        cubes = {field: np.ones((1, 3, 3))}
        self.fetch = self.enterContext(patch.object(producer, 'fetch_model', return_value=(
            [int(CYCLE.timestamp())], axes, axes, cubes, np.ones((3, 3), dtype=bool),
        )))
        producer.build(self.previous, models=[MODEL], log=Mock())
        self.fetch.reset_mock()
        self.manifest = self.previous / MODEL / 'manifest.json'
        self.tile = self.previous / MODEL / 'tiles' / f'{TILE_KEY}.json'

    def _set_field(self, path, field, value):
        document = json.loads(path.read_text())
        document[field] = value
        path.write_text(json.dumps(document))

    def _damage(self, defect):
        if defect == 'missing tile':
            self.tile.unlink()
        elif defect == 'malformed tile':
            self.tile.write_text('{')
        elif defect == 'malformed manifest':
            self.manifest.write_text('{')
        else:
            path, field, value = {
                'tile model': (self.tile, 'model', 'gfs_global'),
                'tile cycle': (self.tile, 'cycle', 0),
                'tile key': (self.tile, 'key', '0_0'),
                'manifest model': (self.manifest, 'model', 'gfs_global'),
                'empty list': (self.manifest, 'tiles', []),
            }[defect]
            self._set_field(path, field, value)

    def _build(self, output):
        run = Mock()
        result = self.producer.build(output, self.previous, [MODEL], log=Mock(), run=run)
        self.assertEqual(json.loads((output / 'index.json').read_text()), result)
        run.source.assert_called_once()
        return result['models'][MODEL], run.source.call_args

    def test_invalid_same_cycle_is_rebuilt(self):
        manifest_bytes, tile_bytes = self.manifest.read_bytes(), self.tile.read_bytes()
        for defect in DEFECTS:
            with self.subTest(defect=defect):
                self.manifest.write_bytes(manifest_bytes)
                self.tile.write_bytes(tile_bytes)
                self._damage(defect)
                self.fetch.reset_mock()
                output = self.output / defect
                row, source = self._build(output)
                self.assertEqual((row['status'], row['state'], row['tiles']), ('ok', 'built', 2))
                self.assertEqual(source.args, (MODEL, 'ok'))
                self.assertEqual(source.kwargs['state'], 'built')
                self.fetch.assert_called_once()
                self.assertEqual((output / MODEL / 'tiles' / self.tile.name).read_bytes(), tile_bytes)

    def test_failed_attempt_does_not_keep_invalid_previous(self):
        self.latest.return_value = None
        manifest_bytes, tile_bytes = self.manifest.read_bytes(), self.tile.read_bytes()
        for defect in DEFECTS:
            with self.subTest(defect=defect):
                self.manifest.write_bytes(manifest_bytes)
                self.tile.write_bytes(tile_bytes)
                self._damage(defect)
                output = self.output / defect
                (output / MODEL / 'tiles').mkdir(parents=True)
                (output / MODEL / 'tiles' / 'unverified.json').write_text('{}')
                row, source = self._build(output)
                self.assertEqual(row['status'], 'failed')
                self.assertIn('no complete cycle', row['issue'])
                self.assertFalse(row['kept_previous'])
                self.assertFalse((output / MODEL).exists())
                self.assertEqual(source.args, (MODEL, 'failed'))
                self.assertFalse(source.kwargs['kept_previous'])
                self.fetch.assert_not_called()

    def test_failed_model_with_no_previous_is_removed_when_another_builds(self):
        self.latest.side_effect = lambda model: None if model.id == MODEL else CYCLE
        axes = self.fetch.return_value[1]
        sea = self.fetch.return_value[4]
        cube = next(iter(self.fetch.return_value[3].values()))
        self.fetch.side_effect = lambda model, cycle, log: (
            [int(cycle.timestamp())], axes, axes, {model.fields[0].name: cube}, sea,
        )
        (self.output / MODEL / 'tiles').mkdir(parents=True)
        (self.output / MODEL / 'tiles' / 'unverified.json').write_text('{}')
        result = self.producer.build(self.output, models=[MODEL, 'gfs_global'], log=Mock())
        self.assertFalse(result['models'][MODEL]['kept_previous'])
        self.assertEqual(result['models']['gfs_global']['status'], 'ok')
        self.assertFalse((self.output / MODEL).exists())
        self.assertTrue((self.output / 'gfs_global' / 'manifest.json').is_file())

    def test_complete_same_cycle_is_reused(self):
        row, source = self._build(self.output)
        self.assertEqual((row['status'], row['state'], row['tiles']), ('ok', 'current', 2))
        self.assertEqual(source.kwargs['state'], 'current')
        self.fetch.assert_not_called()
        self._assert_previous_copied()

    def test_failed_attempt_keeps_complete_older_generation(self):
        self.latest.return_value = CYCLE.replace(hour=12)
        self.fetch.side_effect = RuntimeError('synthetic upstream error')
        row, source = self._build(self.output)
        self.fetch.assert_called_once()
        self.assertEqual(row, {'status': 'failed', 'issue': 'synthetic upstream error', 'kept_previous': True})
        self.assertEqual(source.args, (MODEL, 'failed'))
        self.assertTrue(source.kwargs['kept_previous'])
        self._assert_previous_copied()

    def _assert_previous_copied(self):
        for path in (self.manifest, self.tile, self.tile.with_name('0_0.json')):
            self.assertEqual((self.output / path.relative_to(self.previous)).read_bytes(), path.read_bytes())
