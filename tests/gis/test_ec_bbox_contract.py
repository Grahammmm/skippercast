"""Contract: a bbox written by scripts/ec_detect.py is read by scripts/ec_apply.py with the same meaning.

Both tools follow docs/seafloor-ec.md: `[col0, row0, col1, row1]`, end-exclusive. This test runs the real detect on a
synthetic grid and hands its receipt, unedited, to the real apply, so the two tools cannot drift apart again.
"""
import importlib.util
import json
from pathlib import Path
import tempfile

import numpy as np
import pytest

from tests._support import ROOT

pytestmark = pytest.mark.gis


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tif(path, values):
    import rasterio
    from rasterio.transform import from_origin
    with rasterio.open(path, 'w', driver='GTiff', width=values.shape[1], height=values.shape[0], count=1,
                       dtype='float32', crs='EPSG:32610', transform=from_origin(7e5, 3.9e6, 2.0, 2.0),
                       nodata=-9999.0) as ds:
        ds.write(values.astype('float32'), 1)
    return path


def test_detect_receipt_applies_unedited(tmp_path, capsys):
    detect, apply = _load('ec_detect'), _load('ec_apply')
    v = np.tile(-10.0 - 50.0 * np.arange(64) / 63.0, (64, 1))  # -10 m at column 0 to -60 m at column 63
    holes = {(1, (30, 10)): (slice(30, 31), slice(10, 11)),  # one cell
             (4, (20, 40)): (slice(20, 22), slice(40, 42)),  # 2x2
             (3, (5, 50)): (slice(5, 7), slice(50, 52)),  # an L of three cells inside a 2x2 box
             (16, (40, 20)): (slice(40, 44), slice(20, 24))}  # 4x4: over hole_max_cells(2 m) = 9, never filled
    for rows, cols in holes.values():
        v[rows, cols] = -9999.0
    v[6, 51] = -10.0 - 50.0 * 51 / 63.0  # the L's fourth cell stays valid (its plain slope depth)
    v[10:13, 12:15], v[11, 13] = -20.0, -40.0  # a one-cell pit
    with tempfile.TemporaryDirectory(prefix='ec-contract-', dir='/var/tmp') as spare:
        work = tmp_path / 'grids'
        if detect.ec.FIXTURE_PATH.search(str(work.resolve())):
            work = Path(spare)  # ec_detect refuses fixture-looking paths
        work.mkdir(exist_ok=True)
        grid, receipt = _tif(work / 'grid.tif', v), work / 'EC-DETECT.json'
        assert detect.main([str(grid), '--source-id', 'usgs-test', '--receipt', str(receipt)]) == 0
        det = json.loads(receipt.read_text())
        assert apply.main([str(grid), '--detect', str(receipt), '--out-dir', str(tmp_path / 'out')]) == 0
    capsys.readouterr()
    found = {(h['cells'], (h['bbox'][1], h['bbox'][0])): h for h in det['holes']}
    assert set(found) == set(holes)
    for key, (rows, cols) in holes.items():  # end-exclusive: numpy slices of exactly the hole's rows and columns
        assert found[key]['bbox'] == [cols.start, rows.start, cols.stop, rows.stop], key
    assert [p['bbox'] for p in det['pits']] == [[13, 11, 14, 12]]
    out = json.loads((tmp_path / 'out/EC-APPLY.json').read_text())
    fills = [('hole', h['cells'], h['bbox']) for h in det['holes'] if h['disposition'] == 'fill']
    assert [(f['kind'], f['cells'], f['bbox']) for f in out['fixes']] == fills + [('pit', 1, [13, 11, 14, 12])]
    assert len(fills) == 3
    assert {k: n for k, n in out['counts'].items() if n} == {k: n for k, n in det['counts'].items() if n}
    assert out['counts']['unresolved-hole'] == 16 and out['counts']['filled-hole'] == 1 + 4 + 3
