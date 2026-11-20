"""import_cusp refuses gzip tiles whose stream never reaches its end (RF1911-7)."""
from contextlib import redirect_stderr, redirect_stdout
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts.shoreline import import_cusp as cusp
from tests.unit.test_cusp_shoreline import BOX, NOAA, tile

GOOD = tile([(NOAA, [(100, 100), (4000, 4000)])])


class IncompleteGzipTests(unittest.TestCase):
    def test_truncated_trailers_refuse(self):
        for cut in range(1, 9):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                cusp.decode_tile(GOOD[:-cut])

    def test_truncated_header_and_body_refuse(self):
        for data in (GOOD[:2], GOOD[:10], GOOD[:len(GOOD) // 2]):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                cusp.decode_tile(data)

    def test_complete_gzip_and_plain_mvt_are_equal(self):
        plain = gzip.decompress(GOOD)
        self.assertEqual(cusp.decode_tile(GOOD), cusp.decode_tile(plain))
        self.assertEqual(cusp.decode_tile(gzip.compress(b'')), [])

    def test_size_cap_still_refuses(self):
        with self.assertRaisesRegex(ValueError, 'size cap'):
            cusp.decode_tile(gzip.compress(b'\0' * (cusp.MAX_TILE_BYTES * 8 + 1)))

    def test_truncated_tile_preserves_existing_import(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'regions/r').mkdir(parents=True)
            (root / 'regions/r/region.json').write_text(json.dumps({'id': 'r', 'bounds': BOX}))
            out = root / 'catalog/shoreline/r.geojson'
            out.parent.mkdir(parents=True)
            out.write_bytes(b'SENTINEL')
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'incomplete'):
                    cusp.main(['r'], root=root, get=lambda t: GOOD[:-4])
            self.assertEqual(out.read_bytes(), b'SENTINEL')
            self.assertEqual(sorted(p.name for p in out.parent.iterdir()), ['r.geojson'])
