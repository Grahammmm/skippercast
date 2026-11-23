"""C1–C3: exercise the CLI with writer-produced synthetic GeoTIFFs."""
import hashlib
import json
import subprocess
import sys

import pytest

from tests._support import ROOT

pytestmark = pytest.mark.gis
SCRIPT = ROOT / 'scripts' / 'relief' / 'fine_proof_report.py'


def _run(*paths, json_output=True):
    flags = ['--json'] if json_output else []
    result = subprocess.run([sys.executable, SCRIPT, *paths, *flags], cwd=paths[0].parent,
                            capture_output=True, text=True, timeout=30)
    return result.returncode, result.stdout, result.stderr


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def proofs(tmp_path):
    import numpy as np

    from skippercast.relief.fine_proof import write

    path16, path17 = tmp_path / 'sixteen.tif', tmp_path / 'seventeen.tif'
    bands = np.full((3, 512, 512), -9999.0)
    for row, col in [(slice(0, 256), slice(256, 512)), (slice(256, 512), slice(0, 256))]:
        bands[:, row, col] = np.array([3, -10, 1])[:, None, None]
    bands[:, 0, 0] = (0, -10, 1)  # A proven class-zero pixel, not an empty tile.
    write(path16, 16, 9, 9, 10, 10, *bands)
    sparse = np.full((3, 256, 512), -9999.0)
    sparse[:, 0, 256] = (3, -10, 1)  # One qualifying pixel cannot certify a tile.
    write(path17, 17, 21, 24, 22, 24, *sparse)
    return path16, path17


@pytest.mark.parametrize('json_output', [
    pytest.param(True, id='C1: exact zoom-ordered JSON, including XYZ IDs and source hashes'),
    pytest.param(False, id='C1: exact text rows and counts'),
])
def test_reports(proofs, json_output):
    # Row-major raster traversal would transpose or misorder the diagonal IDs;
    # using class truthiness rather than the proven mask would lose class zero.
    path16, path17 = proofs
    digest16, digest17 = _digest(path16), _digest(path17)
    rc, stdout, stderr = _run(path17, path16, json_output=json_output)
    if json_output:
        assert (rc, json.loads(stdout), stderr) == (0, [
            {'zoom': 16, 'raster_sha256': digest16,
             'tile_range': {'x0': 9, 'y0': 9, 'x1': 10, 'y1': 10},
             'certified': 2, 'uncertified': 1, 'unproven': 1,
             'certified_tiles': ['16/9/10', '16/10/9']},
            {'zoom': 17, 'raster_sha256': digest17,
             'tile_range': {'x0': 21, 'y0': 24, 'x1': 22, 'y1': 24},
             'certified': 0, 'uncertified': 1, 'unproven': 1, 'certified_tiles': []},
        ], '')
    else:
        assert (rc, stdout, stderr) == (0,
            f'z16 sha256={digest16} tiles=9/9..10/10 certified=2 uncertified=1 unproven=1\n'
            f'z17 sha256={digest17} tiles=21/24..22/24 certified=0 uncertified=1 unproven=1\n', '')


@pytest.mark.parametrize(('tags', 'expected'), [
    pytest.param({'sc_fine_proof': '2'}, 'invalid sc_fine_proof tag must be 1\n',
                 id='C2: unsupported proof version reports the reader check'),
    pytest.param({'zoom': '15'}, 'invalid zoom tag must be 16 or 17\n',
                 id='C2: invalid zoom reports the reader check'),
])
def test_invalid_reader_check(proofs, tags, expected):
    import rasterio

    # A late invalid file must not leak the earlier valid report as evidence.
    valid, invalid = proofs
    with rasterio.open(invalid, 'r+') as dataset:
        dataset.update_tags(**tags)
    assert _run(valid, invalid) == (1, '', expected)


@pytest.mark.parametrize('json_output', [
    pytest.param(True, id='C2: duplicate zoom refuses the entire batch'),
])
def test_duplicate_zoom(proofs, json_output):
    import shutil

    original = proofs[0]
    another = original.with_name('same-zoom.tif')
    shutil.copyfile(original, another)
    # Comparing path names instead of decoded zooms would miss this duplicate.
    assert _run(original, another, json_output=json_output) == (1, '', 'duplicate zoom\n')


@pytest.mark.parametrize('json_output', [
    pytest.param(True, id='C3: neither reports nor raster sidecars are written'),
])
def test_read_only(proofs, json_output):
    directory = proofs[0].parent

    def snapshot():
        return directory.stat().st_mtime_ns, {
            path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in directory.iterdir()
        }

    # A byte comparison alone misses a rewrite with identical bytes or a sidecar.
    before = snapshot()
    assert _run(*proofs, json_output=json_output)[::2] == (0, '')
    assert _run(proofs[0], proofs[0], json_output=json_output) == (1, '', 'duplicate zoom\n')
    assert snapshot() == before
