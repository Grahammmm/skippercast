"""F21-11: a missing previously served tile must not erase prior shoreline."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.shoreline import import_cusp as cusp
from tests.unit.test_cusp_shoreline import NOAA, tile


class TileCoverageTests(unittest.TestCase):
    def test_partial_refresh_preserves_prior_and_complete_revision_is_allowed(self):
        # Contract: a failed tile is not a source deletion; a served revised tile is.
        # Before the fix, the second run replaced two features with one and returned success.
        cells = [(12, 2048, 2048), (12, 2049, 2048)]
        box = [cusp.tile_lon(2048, 12), cusp.tile_lat(2049, 12),
               cusp.tile_lon(2050, 12), cusp.tile_lat(2048, 12)]
        good = tile([(NOAA, [(100, 100), (4000, 4000)])])
        held = tile([({**NOAA, 'DAT_SET_CR': 'Other'}, [(100, 100), (4000, 4000)])])
        with tempfile.TemporaryDirectory() as directory, patch.object(cusp, 'tiles_for', return_value=cells):
            root = Path(directory)
            region = root / 'regions' / 'test-region'
            region.mkdir(parents=True)
            (region / 'region.json').write_text(json.dumps({'bounds': box}))
            path = root / 'catalog' / 'shoreline' / 'test-region.geojson'

            def run(bodies, *args):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    result = cusp.main(['test-region', *args], root=root, get=lambda t: bodies.get(t))
                return result, out.getvalue(), err.getvalue()

            self.assertEqual(run({cells[0]: good, cells[1]: good})[0], 0)
            before = path.read_bytes()
            self.assertEqual(len(json.loads(before)['features']), 2)
            code, out, err = run({cells[0]: good}, '--allow-empty')
            self.assertEqual((code, out, path.read_bytes()), (1, '', before))
            self.assertIn('previously covered tiles unavailable: 12/2049/2048', err)
            code, _, err = run({cells[0]: good, cells[1]: held})
            self.assertEqual((code, err), (0, ''))
            revised = json.loads(path.read_text())
            self.assertEqual(len(revised['features']), 1)
            self.assertEqual(revised['provenance']['held_creators'], {'Other': 1})
            self.assertEqual(len(revised['provenance']['tile_receipts']), 2)

    def test_unavailable_previously_unserved_tile_allows_refresh(self):
        # Existing omissions are not newly lost coverage; receipts distinguish them.
        cells = [(12, 2048, 2048), (12, 2049, 2048)]
        box = [cusp.tile_lon(2048, 12), cusp.tile_lat(2049, 12),
               cusp.tile_lon(2050, 12), cusp.tile_lat(2048, 12)]
        good = tile([(NOAA, [(100, 100), (4000, 4000)])])
        with tempfile.TemporaryDirectory() as directory, patch.object(cusp, 'tiles_for', return_value=cells):
            root = Path(directory)
            region = root / 'regions' / 'test-region'
            region.mkdir(parents=True)
            (region / 'region.json').write_text(json.dumps({'bounds': box}))
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(cusp.main(['test-region'], root=root, get=lambda t: good if t == cells[0] else None), 0)
                self.assertEqual(cusp.main(['test-region'], root=root, get=lambda t: good if t == cells[0] else None), 0)


if __name__ == '__main__':
    unittest.main()
