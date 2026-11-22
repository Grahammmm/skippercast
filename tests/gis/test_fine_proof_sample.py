"""Sample a synthetic GeoTIFF through the CLI and real proof reader."""
import json

import numpy as np
import pytest

from scripts.relief.fine_proof_sample import main
from skippercast.relief import fine_proof


@pytest.fixture(scope='module')
def proof_path(tmp_path_factory):
    path = tmp_path_factory.mktemp('fine-proof-sample') / 'proof.tif'
    bands = np.full((3, 512, 512), fine_proof.NODATA)
    # Put all three samples in tile 16/6/10, away from the proof's 16/5/9 origin.
    # The class-3 pixel is at the inclusive southeast corner of the proof.
    bands[:, 511, 511] = (3, -12.5, 0.75)
    bands[:, 511, 510] = (2, -8, 0.5)
    # The sample immediately north of class 3 remains nodata.
    fine_proof.write(path, 16, 5, 9, 6, 10, *bands)
    return path


@pytest.mark.parametrize(('coords', 'status', 'reason', 'evidence'), [
    # A lost tile offset or exclusive endpoint misses the last pixel's evidence.
    pytest.param((16, 6, 10, 255, 255), 'proven', 'Class 3',
                 {'class': 3, 'depth_m': 12.5, 'spacing_m': 0.75}, id='class-3-at-last-pixel'),
    # Reporting every observed sample as qualified or as nodata erases class 2.
    pytest.param((16, 6, 10, 254, 255), 'observed_noncertified', 'not class 3',
                 {'class': 2}, id='class-2-observed'),
    # Using the decoded class without the proven mask misreports nodata as class 0.
    pytest.param((16, 6, 10, 255, 254), 'unproven', 'nodata', {}, id='nodata-is-unproven'),
    # One tile west of the extent can wrap into the class-3 column in NumPy.
    pytest.param((16, 4, 10, 255, 255), 'out_of_extent', 'XYZ tile', {}, id='adjacent-outside-tile'),
    # A negative local index can land in the previous tile instead of being refused.
    pytest.param((16, 6, 10, -1, 255), 'out_of_extent', 'Local pixel', {}, id='negative-local-column'),
    # Ignoring the requested zoom reuses valid evidence from the wrong lattice.
    pytest.param((17, 6, 10, 255, 255), 'out_of_extent', 'zoom', {}, id='wrong-zoom'),
])
def test_sample_cli(proof_path, capsys, coords, status, reason, evidence):
    assert main([str(proof_path), *map(str, coords)]) == 0
    captured = capsys.readouterr()
    assert not captured.err
    report = json.loads(captured.out)
    assert reason in report.pop('reason')
    assert report == {'tile': list(coords[:3]), 'pixel': list(coords[3:]), 'status': status, **evidence}
