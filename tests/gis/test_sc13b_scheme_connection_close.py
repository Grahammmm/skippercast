"""Offline producer-shaped SQLite lifetime tests; no import-time product hooks."""
from contextlib import contextmanager
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch


FIXTURE_ROOT = None  # The standalone runner supplies its exclusive run tree.
REAL_CONNECT = sqlite3.connect


class RetainedConnection(sqlite3.Connection):
    close_calls = 0
    fail_close = False

    def close(self):
        self.close_calls += 1
        super().close()
        if self.fail_close:
            raise OSError('synthetic close failure')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    return {str(p.relative_to(root)): (p.stat().st_ino, digest(p) if p.is_file() else None)
            for p in root.rglob('*')}


def make_scheme(root, kind='valid'):
    """Columns copied from scheme_tiles' row consumers; rollback journal only."""
    cache = root / 'cache'
    cache.mkdir()
    path = cache / 'synthetic-scheme.gpkg'
    db = REAL_CONNECT(path)
    try:
        db.execute('PRAGMA journal_mode=DELETE')
        db.execute('CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT)')
        name = 'Other_Table' if kind == 'invalid-table' else 'BlueTopo_Tile_Scheme_fixture'
        db.execute('INSERT INTO gpkg_contents VALUES (?, ?)', (name, 'features'))
        if kind != 'missing-table':
            db.execute(f'CREATE TABLE "{name}" (geom BLOB, tile TEXT, GeoTIFF_Link TEXT, '
                       'GeoTIFF_SHA256_Checksum TEXT, Delivered_Date TEXT, Resolution TEXT)')
            for tile, x, resolution in [('Z', 0, '4m'), ('A', 1, '8m'), ('outside', 50, '2m')]:
                points = [(x, 0), (x + 1, 0), (x + 1, 1), (x, 1), (x, 0)]
                wkb = struct.pack('<BIII', 1, 3, 1, len(points))
                wkb += b''.join(struct.pack('<dd', *p) for p in points)
                blob = b'GP\x00\x01' + struct.pack('<i', 4326) + wkb
                if kind == 'bad-magic':
                    blob = b'XX' + blob[2:]
                elif kind == 'bad-wkb':
                    blob = blob[:8] + b'broken'
                elif kind == 'bad-header':
                    blob = blob[:3] + b'\x0f' + blob[4:]
                url = 'https://noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com/BlueTopo/fixture.tiff'
                if kind == 'incomplete':
                    url = ''
                if kind == 'bad-resolution':
                    resolution = 'invalid'
                db.execute(f'INSERT INTO "{name}" VALUES (?, ?, ?, ?, ?, ?)',
                           (blob, tile, url, 'a' * 64, '2026-01-01', resolution))
        db.commit()
    finally:
        db.close()
    pin = {'scheme_url': 'https://noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com/BlueTopo/synthetic-scheme.gpkg',
           'scheme_sha256': digest(path)}
    (root / 'pin.json').write_text(json.dumps(pin))
    (root / 'sentinel.txt').write_text('unchanged synthetic sentinel\n')
    config = {'blue_topo_pin': 'pin.json', 'bounds': [0, 0, 3, 2]}
    return config, cache, pin


@contextmanager
def product_context(root):
    """Only scoped patches in ordinary discovery; restore even on import failure."""
    paths = importlib.import_module('skippercast.paths')
    with patch.object(paths, 'repo_root', return_value=root):
        reference = importlib.import_module('skippercast.seafloor.reference')
    yield reference


def context_manager_only(config, root, cache, fetch=False):
    """Named negative control: original algorithm with no explicit close."""
    from skippercast.seafloor import reference as ref
    pin = ref.read_json(root / config['blue_topo_pin'])
    path = cache / Path(pin['scheme_url']).name
    ref.verified_file(pin['scheme_url'], pin['scheme_sha256'], path, fetch, max_bytes=20_000_000)
    selected = []
    with ref.sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        tables = [r[0] for r in db.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'")]
        if len(tables) != 1 or not tables[0].startswith('BlueTopo_Tile_Scheme_'):
            raise ValueError('Expected one official BlueTopo tile scheme')
        name = tables[0].replace('"', '""')
        for row in db.execute(f'SELECT * FROM "{name}"'):
            blob = row['geom']
            if blob[:2] != b'GP':
                raise ValueError('Invalid GeoPackage geometry')
            offset = 8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(blob[3] >> 1) & 7]
            geom = ref.shapely.from_wkb(blob[offset:])
            if not geom.intersects(ref.box(*config['bounds'])):
                continue
            if not row['GeoTIFF_Link'] or not row['GeoTIFF_SHA256_Checksum']:
                raise ValueError(f"Incomplete reference tile: {row['tile']}")
            selected.append({'id': row['tile'], 'url': row['GeoTIFF_Link'],
                             'publisher_sha256': row['GeoTIFF_SHA256_Checksum'],
                             'delivered_date': row['Delivered_Date'],
                             'native_resolution_m': float(str(row['Resolution']).removesuffix('m')),
                             'bounds': list(geom.bounds)})
    if not selected:
        raise ValueError('No reference tiles intersect requested scope')
    return pin, sorted(selected, key=lambda r: r['id'])


class SchemeConnectionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='sc13b-', dir=FIXTURE_ROOT))
        self.held = []
        self.calls = []
        self.before = None
        self.ctx = product_context(self.root)
        self.ref = self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)

    def prepare(self, kind='valid'):
        self.config, self.cache, self.pin = make_scheme(self.root, kind)
        self.before = inventory(self.root)

    def factory(self, database, **kwargs):
        self.calls.append((database, kwargs.copy()))
        self.assertTrue(database.endswith('?mode=ro'))
        self.assertEqual(kwargs, {'uri': True})
        db = REAL_CONNECT(database, factory=RetainedConnection, **kwargs)
        self.held.append(db)
        return db

    def invoke(self):
        with patch.object(self.ref.sqlite3, 'connect', side_effect=self.factory):
            return self.ref.scheme_tiles(self.config, self.root, self.cache, fetch=False)

    def closed_once(self):
        self.assertEqual(len(self.held), 1)
        # This is the deciding real SQLite assertion, before the call counter.
        with self.assertRaisesRegex(sqlite3.ProgrammingError, 'closed database'):
            self.held[0].execute('SELECT 1')
        self.assertEqual(self.held[0].close_calls, 1)

    def valid_output(self, result):
        url = 'https://noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com/BlueTopo/fixture.tiff'
        expected = [{'id': tile, 'url': url, 'publisher_sha256': 'a' * 64,
                     'delivered_date': '2026-01-01', 'native_resolution_m': resolution,
                     'bounds': bounds} for tile, resolution, bounds in
                    [('A', 8.0, [1.0, 0.0, 2.0, 1.0]), ('Z', 4.0, [0.0, 0.0, 1.0, 1.0])]]
        self.assertEqual(result, (self.pin, expected))

    def tearDown(self):
        # Only leaked card-owned synthetic handles are closed during teardown.
        for db in self.held:
            try:
                db.execute('SELECT 1')
            except sqlite3.ProgrammingError:
                pass
            else:
                sqlite3.Connection.close(db)
        if self.before is not None:
            self.assertEqual(inventory(self.root), self.before)

    def test_import_closure(self):
        from skippercast.platform import contracts
        import numpy
        import pyproj
        import rasterio
        import shapefile
        import shapely
        self.assertTrue(callable(self.ref.scheme_tiles))
        self.assertTrue(all(m.__file__ for m in (numpy, pyproj, rasterio, shapefile, shapely)))
        # Standalone redirected before imports; ordinary discovery leaves peers alone.
        if FIXTURE_ROOT is not None:
            self.assertEqual(contracts.REPO, Path(FIXTURE_ROOT).parent)
        self.prepare()
        self.valid_output(self.invoke())

    def test_success_closes_once(self):
        self.prepare()
        self.valid_output(self.invoke())
        self.closed_once()

    def error_case(self, kind, error, message):
        self.prepare(kind)
        with self.assertRaisesRegex(error, message):
            self.invoke()
        self.closed_once()

    def test_invalid_table_closes(self):
        self.error_case('invalid-table', ValueError, 'Expected one official')

    def test_missing_table_closes(self):
        self.error_case('missing-table', sqlite3.OperationalError, 'no such table')

    def test_bad_magic_closes(self):
        self.error_case('bad-magic', ValueError, 'Invalid GeoPackage geometry')

    def test_bad_wkb_closes(self):
        from shapely.errors import GEOSException
        self.error_case('bad-wkb', GEOSException, 'ParseException')

    def test_bad_header_closes(self):
        self.error_case('bad-header', KeyError, '7')

    def test_empty_closes(self):
        self.prepare()
        self.config['bounds'] = [-10, -10, -9, -9]
        with self.assertRaisesRegex(ValueError, 'No reference tiles'):
            self.invoke()
        self.closed_once()

    def test_incomplete_tile_closes(self):
        self.error_case('incomplete', ValueError, 'Incomplete reference tile: Z')

    def test_bad_resolution_closes(self):
        self.error_case('bad-resolution', ValueError, 'could not convert string to float')

    def test_acquisition_failure(self):
        self.prepare()
        failure = sqlite3.OperationalError('synthetic acquisition failure')
        with patch.object(self.ref.sqlite3, 'connect', side_effect=failure) as connect:
            with self.assertRaises(sqlite3.OperationalError) as caught:
                self.ref.scheme_tiles(self.config, self.root, self.cache, fetch=False)
        self.assertIs(caught.exception, failure)
        connect.assert_called_once()
        self.assertEqual(self.held, [])

    def close_failure(self, kind):
        self.prepare(kind)
        original = self.factory

        def failing_factory(*args, **kwargs):
            db = original(*args, **kwargs)
            db.fail_close = True
            return db

        with patch.object(self.ref.sqlite3, 'connect', side_effect=failing_factory):
            with self.assertRaisesRegex(OSError, 'synthetic close failure') as caught:
                self.ref.scheme_tiles(self.config, self.root, self.cache, fetch=False)
        if kind != 'valid':
            self.assertIsInstance(caught.exception.__context__, ValueError)
        self.closed_once()

    def test_close_failure_propagates(self):
        self.close_failure('valid')

    def test_error_and_close_failure(self):
        self.close_failure('invalid-table')

    def test_valid_producer_shape(self):
        self.prepare()
        self.valid_output(self.invoke())
        # Compatibility deliberately independent from the changed lifetime assertion.
        self.assertEqual(len(self.calls), 1)

    def test_cached_hash_failure_before_connect(self):
        self.prepare()
        self.pin['scheme_sha256'] = '0' * 64
        (self.root / 'pin.json').write_text(json.dumps(self.pin))
        self.before = inventory(self.root)
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            self.invoke()
        self.assertEqual(self.calls, [])

    def test_missing_cache_before_connect(self):
        self.prepare()
        self.pin['scheme_url'] += '-missing'
        (self.root / 'pin.json').write_text(json.dumps(self.pin))
        self.before = inventory(self.root)
        with self.assertRaises(FileNotFoundError):
            self.invoke()
        self.assertEqual(self.calls, [])
