"""Offline parity and refusal controls for the opt-in native-grid C4 path."""
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from research.scripts.coast_mvp import coast_qa as reference
from research.scripts.coast_mvp import coast_qa_regional as regional
from tests._support import ROOT


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(regional, 'STRIP_ROWS', 2)
    monkeypatch.setattr(regional, 'RESERVE_BYTES', 0)
    a = np.full((8, 9), np.nan)
    b = a.copy()
    a[:, :5] = -10
    b[:, 4:] = -13
    for grid in (a, b):
        grid[0, 0] = np.nan
        grid[1, 1] = np.nan  # diagonals are not connected
        grid[3:6, 4] = np.nan  # spans multiple strips
    mosaic = np.where(np.isfinite(a), a, b)
    contributor = np.where(np.isfinite(a), 1, np.where(np.isfinite(b), 2, 0))
    support = np.isfinite(a).astype('uint16') + np.isfinite(b).astype('uint16')
    arrays = dict(a=a, b=np.where(np.isfinite(b), -b+2, np.nan),
                  elevation=mosaic, contributor=contributor, support_count=support)
    for label, grid in arrays.items():
        dtype = 'uint16' if label in {'contributor', 'support_count'} else 'float32'
        nodata = 0 if dtype == 'uint16' else -9999
        with rasterio.open(tmp_path/f'{label}.tif', 'w', driver='GTiff', width=9, height=8,
                           count=1, dtype=dtype, crs='EPSG:3310',
                           transform=from_origin(0, 80, 10, 10), nodata=nodata) as ds:
            ds.write(np.where(np.isfinite(grid), grid.astype('float64'), nodata).astype(dtype), 1)
    sources = [dict(id=s, code=i+1, path=f'{s}.tif', sha256=reference.digest(tmp_path/f'{s}.tif'),
                    units='m', value_convention='depth_positive_down' if s == 'b' else 'elevation_positive_up',
                    vertical_offset_m=2 if s == 'b' else 0, vertical_datum='test-datum' if s == 'b' else 'unstated',
                    datum_unresolved=s == 'a') for i, s in enumerate(('a', 'b'))]
    manifest = dict(schema_version=1, units='m', value_convention='elevation_positive_up', sources=sources,
                    outputs={s: dict(path=f'{s}.tif', sha256=reference.digest(tmp_path/f'{s}.tif'))
                             for s in ('elevation', 'contributor', 'support_count')},
                    stats=dict(grid_cells=mosaic.size, valid_cells=int(np.isfinite(mosaic).sum()),
                               hole_cells=int((~np.isfinite(mosaic)).sum()), overlap_cells=int((support > 1).sum())),
                    contributor_cells={str(i): int((contributor == i).sum()) for i in (1, 2)})
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    config = tmp_path/'config.json'
    config.write_text(json.dumps(dict(region='test', segments=[dict(id='test', manifest='manifest.json')])))
    return tmp_path, config, mosaic, manifest


def rows(array):
    return [[float(z) if np.isfinite(z) else None for z in line] for line in array]


def pixels(path_or_bytes):
    if isinstance(path_or_bytes, bytes):
        with MemoryFile(path_or_bytes) as file, file.open() as ds:
            return ds.read()
    with rasterio.open(path_or_bytes) as ds:
        return ds.read()


def test_regional_matches_reference_stats_holes_overlap_and_png(inputs):
    path, config, mosaic, _ = inputs
    ref = reference.packet(config, path/'reference')['segments'][0]
    result = regional.packet(config, path/'regional')['segments'][0]
    for key, value in ref['stats'].items():
        assert result['stats'][key] == pytest.approx(value)
    assert result['holes'] == reference.holes(rows(mosaic)) == ref['holes']
    assert result['seam_rms'][0]['rms_m'] == ref['seam_rms'][0]['rms_m'] == 3
    assert result['seam_rms'][0]['mean_delta_m'] == 3
    assert result['consistency']['passed']
    assert sum(s['contributor_cells'] for s in result['sources']) == result['stats']['valid_cells']
    assert result['sources'][0]['datum_unresolved']
    assert result['seam_rms'][0]['datum_unresolved']
    assert result['sources'][1]['vertical_offset_m'] == 2
    np.testing.assert_array_equal(pixels(path/'regional/test-hillshade.png'),
                                  pixels(reference.hillshade(rows(mosaic), 10)))
    np.testing.assert_array_equal(pixels(path/'regional/test-hillshade.png')[1] > 0, np.isfinite(mosaic))


def test_hillshade_crop_uses_halo_and_has_no_strip_edge_artifacts(inputs):
    path, _, mosaic, _ = inputs
    with rasterio.open(path/'elevation.tif') as ds:
        regional.hillshade_png(ds, path/'crop.png', [2, 1, 8, 7])
    np.testing.assert_array_equal(pixels(path/'crop.png'),
        pixels(reference.hillshade(rows(mosaic), 10))[:, 1:7, 2:8])


@pytest.mark.parametrize('role', ['a', 'b', 'elevation', 'contributor', 'support_count'])
def test_hash_mismatch_refuses_without_packet(inputs, role):
    path, config, _, _ = inputs
    with (path/f'{role}.tif').open('ab') as file:
        file.write(b'changed')
    with pytest.raises(ValueError, match='hash mismatch'):
        regional.packet(config, path/'packet')
    assert not (path/'packet').exists()


def test_cap_and_no_overwrite_remain_enforced(inputs, monkeypatch):
    path, config, _, _ = inputs
    with monkeypatch.context() as small:
        small.setattr(regional, 'MAX_CELLS', 10)
        with pytest.raises(ValueError, match='cap'):
            regional.packet(config, path/'packet')
    assert not (path/'packet').exists()
    regional.packet(config, path/'packet')
    before = (path/'packet/qa.json').read_bytes()
    with pytest.raises(FileExistsError):
        regional.packet(config, path/'packet')
    assert (path/'packet/qa.json').read_bytes() == before


def test_no_overlap_is_unavailable_and_inconsistent_support_is_flagged(inputs):
    path, config, _, manifest = inputs
    with rasterio.open(path/'b.tif', 'r+') as ds:
        grid = ds.read(1)
        grid[:, :5] = -9999
        ds.write(grid, 1)
    manifest['sources'][1]['sha256'] = reference.digest(path/'b.tif')
    (path/'manifest.json').write_text(json.dumps(manifest))
    result = regional.packet(config, path/'packet')['segments'][0]
    seam = result['seam_rms'][0]
    assert seam['status'] == 'unavailable'
    assert seam['rms_m'] is None
    assert seam['mean_delta_m'] is None
    assert seam['overlap_cells'] == 0
    assert result['consistency']['source_support_count_mismatches'] > 0
    assert not result['consistency']['passed']


def test_independent_native_sampling_verifier(inputs):
    from research.scripts.coast_mvp.verify_c4_real import verify
    path, config, _, _ = inputs
    regional.packet(config, path/'packet')
    result = verify(path/'packet', path/'manifest.json')
    assert result['status'] == 'PASS'
    assert result['native_hillshade_alpha_mismatches'] == 0
    assert result['pairwise'][0]['rms_m'] == 3


def test_holes_empty_and_single_pixel():
    assert regional.hole_components(np.zeros((3, 3), dtype=bool)) == []
    assert regional.hole_components(np.ones((1, 1), dtype=bool)) == [
        dict(cells=1, pixel_bbox=[0, 0, 1, 1], touches_boundary=True)]


def tamper_valid_cells(packet):
    report = json.loads((packet/'qa.json').read_text())
    report['segments'][0]['stats']['valid_cells'] += 1
    (packet/'qa.json').write_text(json.dumps(report))


def test_verifier_refuses_tampered_packet_with_explicit_exception(inputs):
    from research.scripts.coast_mvp.verify_c4_real import VerificationError, verify
    path, config, _, _ = inputs
    regional.packet(config, path/'packet')
    tamper_valid_cells(path/'packet')
    with pytest.raises(VerificationError, match='valid_cells mismatch'):
        verify(path/'packet', path/'manifest.json')


def test_verifier_refusal_survives_python_optimize(inputs):
    # Under `python -O` an assert-based check would be stripped and report PASS.
    path, config, _, _ = inputs
    regional.packet(config, path/'packet')
    tamper_valid_cells(path/'packet')
    code = ('import sys; from research.scripts.coast_mvp.verify_c4_real import verify; '
            'verify(sys.argv[1], sys.argv[2])')
    run = subprocess.run([sys.executable, '-O', '-c', code, str(path/'packet'), str(path/'manifest.json')],
                         cwd=ROOT, capture_output=True, text=True)
    assert run.returncode != 0
    assert 'VerificationError: valid_cells mismatch' in run.stderr


def test_regional_flag_imports_when_run_as_package(inputs, monkeypatch, capsys):
    path, config, _, _ = inputs
    monkeypatch.setattr(sys, 'argv', ['coast_qa', '--regional', '--region-config', str(config),
                                      '--output', str(path/'packet')])
    reference.main()
    assert json.loads(capsys.readouterr().out)['processing'] == 'bounded-regional-v1'
    assert (path/'packet/qa.json').exists()
