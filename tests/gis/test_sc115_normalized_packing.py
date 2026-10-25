"""SC115: real normalized API, portable native fixtures, reversible test scopes."""
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / 'tests/fixtures/sc115-normalized-packing'
RUN_ROOT = None
EVENTS = []


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackingTests(unittest.TestCase):
    def setUp(self):
        self.scope = ExitStack()
        self.addCleanup(self.scope.close)
        self.scope.enter_context(patch.object(sys, 'dont_write_bytecode', True))
        old_path = sys.path[:]
        sys.path.insert(0, str(REPO / 'src'))
        self.scope.callback(lambda: sys.path.__setitem__(slice(None), old_path))
        self.fixtures = load_file('sc115_constructors', FIXTURES / 'constructors.py')
        self.scope.enter_context(self.fixtures.offline_scope())
        import numpy as np
        import rasterio
        from skippercast.seafloor import normalized
        self.np, self.rio, self.api = np, rasterio, normalized
        self.assertEqual(Path(normalized.__file__).resolve(),
                         REPO / 'src/skippercast/seafloor/normalized.py')
        parent = Path(RUN_ROOT) if RUN_ROOT else REPO.parent / 'out/sc115-ordinary'
        parent.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='case-', dir=parent))
        self.sentinel = self.root / 'sentinel.txt'
        self.sentinel.write_text('SC115 retained synthetic sentinel\n')
        self.before_sentinel = self.fixtures.hashes(self.root)
        self.addCleanup(self.record_preservation)

    def record_preservation(self):
        after = self.fixtures.hashes(self.root)
        self.assertEqual(after['sentinel.txt'], self.before_sentinel['sentinel.txt'])
        EVENTS.append({'id': self.id(), 'root': str(self.root),
                       'sentinel_before': self.before_sentinel, 'fixture_after': after})

    def make(self, name, **kwargs):
        return self.fixtures.make_raster(self.root / (name + '.tif'), **kwargs)

    def identity(self, path):
        before = self.fixtures.hashes(self.root)
        result = self.api.raster_identity(path)
        self.assertEqual(before, self.fixtures.hashes(self.root))
        EVENTS.append({'id': self.id(), 'raster': path.name, 'identity': result,
                       'fixture_before': before, 'fixture_after': self.fixtures.hashes(self.root)})
        return result

    def refusal(self, path):
        before = self.fixtures.hashes(self.root)
        with self.assertRaisesRegex(ValueError, self.fixtures.MESSAGE):
            self.api.raster_identity(path)
        after = self.fixtures.hashes(self.root)
        self.assertEqual(before, after)
        EVENTS.append({'id': self.id(), 'rejected_raster': path.name,
                       'fixture_before': before, 'fixture_after': after})

    def test_regression_equal_samples_nonunit_scale_rejected(self):
        plain = self.make('plain')
        packed = self.make('packed', scales=(2, 1))
        with self.rio.open(plain) as a, self.rio.open(packed) as b:
            self.np.testing.assert_array_equal(a.read(), b.read())
            self.assertEqual(b.scales, (2, 1))
            self.assertEqual(a.offsets, b.offsets)
            self.assertEqual(a.crs, b.crs)
        self.identity(plain)
        self.refusal(packed)

    def test_regression_unpacked_lossless_positive(self):
        default = self.make('default')
        explicit = self.make('explicit', scales=(1, 1), offsets=(0, 0), compress='DEFLATE')
        self.assertNotEqual(default.read_bytes(), explicit.read_bytes())
        self.assertEqual(self.identity(default), self.identity(explicit))

    def test_regression_every_band_real_packing(self):
        for field, values in (('scales', (0, -1, 2, self.np.nextafter(1., 2.),
                                        float('nan'), float('inf'), -float('inf'))),
                              ('offsets', (1, -1, self.np.nextafter(0., 1.),
                                           float('nan'), float('inf'), -float('inf')))):
            for band in (0, 1):
                for i, value in enumerate(values):
                    with self.subTest(field=field, band=band + 1, value=str(value)):
                        metadata = [1, 1] if field == 'scales' else [0, 0]
                        metadata[band] = value
                        path = self.make(f'{field}-{band}-{i}', **{field: tuple(metadata)})
                        with self.rio.open(path) as ds:
                            actual = getattr(ds, field)[band]
                        representable = (self.np.isnan(actual) if self.np.isnan(value)
                                         else actual == value)
                        EVENTS.append({'native_metadata': field, 'band': band + 1,
                                       'requested': str(value), 'observed': str(actual),
                                       'representable': bool(representable)})
                        if representable:
                            self.refusal(path)
                        else:
                            # Not a skip: the exact header is exercised by the seam below.
                            self.check_header(tuple(metadata) if field == 'scales' else (1, 1),
                                              tuple(metadata) if field == 'offsets' else (0, 0))

    def check_header(self, scales, offsets):
        path = self.make('header-base-' + str(len(list(self.root.glob('*.tif')))))
        before = self.fixtures.hashes(self.root)
        with self.rio.open(path) as real:
            reads = []
            class Header:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    return False
                def __getattr__(self, name):
                    return getattr(real, name)
                def read(self, *args, **kwargs):
                    reads.append(True)
                    raise AssertionError('pixels read after invalid packing header')
            header = Header()
            header.scales, header.offsets = scales, offsets
            with patch.object(self.api.rasterio, 'open', return_value=header):
                self.refusal(path)
            self.assertEqual(reads, [])
        self.assertEqual(before, self.fixtures.hashes(self.root))
        EVENTS.append({'synthetic_header': True, 'scales': str(scales),
                       'offsets': str(offsets), 'read_count': len(reads)})

    def test_regression_synthetic_headers_reject_before_read(self):
        for band in (0, 1):
            for value in (0, 2, float('nan'), float('inf'), -float('inf'), None, '1'):
                with self.subTest(field='scales', band=band, value=str(value)):
                    scales = [1, 1]; scales[band] = value
                    self.check_header(tuple(scales), (0, 0))
            for value in (1, float('nan'), float('inf'), -float('inf'), None, '0'):
                with self.subTest(field='offsets', band=band, value=str(value)):
                    offsets = [0, 0]; offsets[band] = value
                    self.check_header((1, 1), tuple(offsets))
        for scales, offsets in (((), (0, 0)), ((1,), (0, 0)),
                                ((1, 1, 1), (0, 0)), ((1, 1), ()),
                                ((1, 1), (0,)), ((1, 1), (0, 0, 0)),
                                (None, (0, 0)), ((1, 1), None)):
            with self.subTest(scales=str(scales), offsets=str(offsets)):
                self.check_header(scales, offsets)

    def test_compatibility_baseline_digest(self):
        expected = json.loads((FIXTURES / 'baseline_identity.json').read_text())
        self.assertEqual(self.identity(self.make('default')), expected['identity'])
        self.assertEqual(self.api.VERSION, 'normalized-raster-content-v1')

    def test_compatibility_existing_metadata_masks_and_errors(self):
        base = self.identity(self.make('base'))
        for name, kwargs in (('mask', {'mask': False}), ('datum', {'datum': 'NAVD88'}),
                             ('bands', {'count': 1})):
            self.assertNotEqual(base, self.identity(self.make(name, **kwargs)))
        for name, kwargs, message in (('dtype', {'dtype': 'int16'}, 'exact float32'),
                                       ('crs', {'crs': None}, 'identified CRS')):
            with self.assertRaisesRegex(ValueError, message):
                self.api.raster_identity(self.make(name, **kwargs))
        infinite = self.make('infinite')
        with self.rio.open(infinite, 'r+') as ds:
            values = ds.read(1); values[0, 0] = float('inf'); ds.write(values, 1)
        with self.assertRaisesRegex(ValueError, 'Infinite normalized raster value'):
            self.api.raster_identity(infinite)

    def test_compatibility_complete_log_binding(self):
        runner = load_file('sc115_runner_for_binding', REPO / 'tools/run_sc115_normalized_packing.py')
        log = self.root / 'inert-log.txt'
        log.write_text('complete\n')
        binding = runner.bind_logs([log])
        runner.verify_logs(binding)
        missing = self.root / 'never-created.txt'
        with self.assertRaises(FileNotFoundError):
            runner.bind_logs([missing])
        log.write_text('changed\n')
        with self.assertRaisesRegex(ValueError, 'log changed'):
            runner.verify_logs(binding)
        late = self.root / 'late.txt'
        late.write_text('completed writer\n')
        late_binding = runner.bind_logs([late])
        with late.open('a') as stream:
            stream.write('late append\n')
        with self.assertRaisesRegex(ValueError, 'log changed'):
            runner.verify_logs(late_binding)
        with self.assertRaises(FileNotFoundError):
            runner.verify_logs({str(missing): {'sha256': '0' * 64, 'bytes': 0}})


if __name__ == '__main__':
    unittest.main()
