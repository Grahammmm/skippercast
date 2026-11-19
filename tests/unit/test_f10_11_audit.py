"""A receipt-write interruption must not strand a private multibeam cache."""
import json
from pathlib import Path

import pytest

from skippercast.seafloor.adapters import multibeam_grid
from skippercast.seafloor.io import sha256


def _preparation(source):
    receipt = {
        'scope': 'private-multibeam-grid-parity', 'output_sha256': sha256(source),
        'derived_bin_spacing_m': 5, 'vertical_datum': 'unknown', 'horizontal_crs': 'EPSG:3857',
        'native_resolution': 'irregular soundings', 'uncertainty': 'unknown',
        'count_support_mismatches': 0, 'source_qualified': False, 'fishing_target': False,
        'exportable': False, 'new_measured_km2': 0, 'new_physical_candidates': 0,
        'new_public_locations': 0, 'originals': {'synthetic.mb57': 'a' * 64},
        'beam_table_sha256': ['b' * 64], 'grid_sha256': ['c' * 64, 'd' * 64, 'e' * 64],
        'grid_receipt_sha256': 'f' * 64,
    }
    sidecar = source.with_suffix('.json')
    sidecar.write_text(json.dumps(receipt))
    row = {
        'id': 'synthetic', 'format': multibeam_grid.FORMAT, 'kind': 'bathymetry',
        'status': 'candidate', 'license': 'unknown', 'archive_member': 'unknown',
        'sha256': sha256(source), 'bytes': source.stat().st_size, 'resolution_m': 5,
        'vertical_datum': 'unknown', 'grid_preparation': {
            'profile': multibeam_grid.VERSION, 'preparation_receipt_sha256': sha256(sidecar),
            'preparation_code_sha256': '1' * 64, 'native_sampling': 'irregular-original-soundings',
            'grid_spacing_m': 5, 'minimum_good_soundings': 3,
        },
    }
    return row, sidecar, receipt


def _interrupt_receipt_install(patch, installed_payload):
    replace, link = Path.replace, Path.hardlink_to

    def replace_file(path, dest):
        interrupt(dest)
        return replace(path, dest)

    def link_file(path, staged):
        interrupt(path)
        return link(path, staged)

    def interrupt(receipt):
        payload = installed_payload(receipt)
        if payload is not None:
            assert payload.is_file()
            raise OSError('simulated receipt install interruption')

    # The same fault injection works on main's replace and the candidate's link.
    patch.setattr(Path, 'replace', replace_file)
    patch.setattr(Path, 'hardlink_to', link_file)


def test_multibeam_import_resumes_only_with_the_exact_local_pair(tmp_path, monkeypatch):
    # An installed source without its sidecar used to make every retry fail.
    local = tmp_path / 'grid.tif'
    local.write_bytes(b'synthetic grid bytes')
    row, sidecar, preparation = _preparation(local)
    cache = tmp_path / 'cache'
    source = cache / row['sha256'] / 'source.tif'
    receipt = source.with_name('preparation.json')
    with monkeypatch.context() as patch:
        _interrupt_receipt_install(patch, lambda path: source if path == receipt else None)
        with pytest.raises(OSError, match='simulated receipt install interruption'):
            multibeam_grid.source_files(row, cache, local)
    original, original_receipt = local.read_bytes(), sidecar.read_bytes()
    assert source.read_bytes() == original and not receipt.exists()
    with pytest.raises(ValueError):
        multibeam_grid.source_files(row, cache, None)
    sidecar.write_text(json.dumps({**preparation, 'exportable': True}))
    with pytest.raises(ValueError):
        multibeam_grid.source_files(row, cache, local)
    unreviewed = {**row, 'grid_preparation': {
        **row['grid_preparation'], 'preparation_receipt_sha256': sha256(sidecar),
    }}
    with pytest.raises(ValueError):
        multibeam_grid.source_files(unreviewed, cache, local)
    assert source.read_bytes() == original and not receipt.exists()
    sidecar.write_bytes(original_receipt)
    local.write_bytes(b'!' * len(original))
    with pytest.raises(ValueError):
        multibeam_grid.source_files(row, cache, local)
    assert source.read_bytes() == original and not receipt.exists()
    local.write_bytes(original)
    source.write_bytes(b'?' * len(original))
    with pytest.raises(ValueError):
        multibeam_grid.source_files(row, cache, local)
    assert source.read_bytes() == b'?' * len(original) and not receipt.exists()
    source.write_bytes(original)
    inode = source.stat().st_ino
    assert multibeam_grid.source_files(row, cache, local) == (source, preparation)
    assert source.stat().st_ino == inode and receipt.read_bytes() == original_receipt
    assert multibeam_grid.source_files(row, cache, None) == (source, preparation)


@pytest.mark.gis
def test_multibeam_normalization_recovers_only_a_reproducible_private_raster(tmp_path, monkeypatch):
    # A normalized orphan must match a fresh render, not just a readable TIFF.
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    local = tmp_path / 'grid.tif'
    with rasterio.open(local, 'w', driver='GTiff', width=4, height=4, count=5,
                       dtype='float32', crs='EPSG:3857', transform=from_origin(0, 20, 5, 5)) as ds:
        ds.write(np.broadcast_to(np.array([50, 4, .5, 49, 51], dtype='float32')[:, None, None], (5, 4, 4)))
        ds.descriptions = multibeam_grid.DESCRIPTIONS
        ds.update_tags(interpolation='none', depth_basis='nominal', vertical_datum='unknown')
    row, _, _ = _preparation(local)
    bounds = (0, 0, .001, .001)
    folder = tmp_path / 'var/seafloor/cache' / row['sha256']

    def normalized_payload(path):
        if path.parent == folder and path.suffix == '.json' and path.name != 'preparation.json':
            return path.with_suffix('.tif')

    with monkeypatch.context() as patch:
        _interrupt_receipt_install(patch, normalized_payload)
        with pytest.raises(OSError, match='simulated receipt install interruption'):
            multibeam_grid.ingest(row, bounds, root=tmp_path, local=local)
    output, = (p for p in folder.glob('*.tif') if p.name != 'source.tif')
    receipt = output.with_suffix('.json')
    original = output.read_bytes()
    assert not receipt.exists()
    damaged = original[:-1] + bytes([original[-1] ^ 1])
    output.write_bytes(damaged)
    with pytest.raises(ValueError):
        multibeam_grid.ingest(row, bounds, root=tmp_path)
    assert output.read_bytes() == damaged and not receipt.exists()
    output.write_bytes(original)
    inode = output.stat().st_ino
    saved, fetched, reused = multibeam_grid.ingest(row, bounds, root=tmp_path)
    assert not fetched and not reused
    assert output.read_bytes() == original and output.stat().st_ino == inode
    assert saved['cog_sha256'] == sha256(output) and saved['valid_pixels_in_requested_bounds'] == 16
    with rasterio.open(output) as ds:
        assert ds.tags()['source_qualification'] == 'private-physical-only'
        assert ds.tags()['fishing_export'] == 'prohibited'
    assert multibeam_grid.ingest(row, bounds, root=tmp_path) == (saved, False, True)
