"""C1 fallback uses real support, nearest depths and source-safe hillshading."""
import json
from pathlib import Path
import struct
import zlib
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window
from research.scripts.coast_mvp import coast_c1_preview as preview
from research.tests.test_coast_c1_preview_rights import manifest_fixture


def fixture(tmp_path):
    root = tmp_path / 'input'
    root.mkdir()
    z = -np.arange(64 * 64, dtype='float32').reshape(64, 64) / 10
    c = np.ones((64, 64), dtype='uint16')
    c[16:24, 16:24] = 0
    z[c == 0] = -999999
    transform = from_origin(-100000, -250000, 10, 10)
    for key, data, nodata in [('elevation', z, -999999), ('contributor', c, 0)]:
        with rasterio.open(root / f'{key}.tif', 'w', driver='GTiff', width=64, height=64,
                           count=1, dtype=data.dtype, crs='EPSG:3310', transform=transform, nodata=nodata) as ds:
            ds.write(data, 1)
    manifest = manifest_fixture()
    manifest.update(width=64, height=64, crs='EPSG:3310', resolution_m=10,
                    bounds_projected=[-100000, -250640, -99360, -250000])
    cells = int(np.count_nonzero(c))
    manifest.update(contributor_cells={'1': cells, '2': 0}, stats={'valid_cells': cells})
    manifest['outputs'] = {key: {'path': f'{key}.tif', 'sha256': preview.digest(root / f'{key}.tif')}
                           for key in ('elevation', 'contributor')}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    return root, manifest


def decode_png(path):
    raw = path.read_bytes()
    assert raw[:8] == b'\x89PNG\r\n\x1a\n'
    width, height = struct.unpack('!II', raw[16:24])
    position, compressed = 8, b''
    while position < len(raw):
        length = struct.unpack('!I', raw[position:position+4])[0]
        kind, data = raw[position+4:position+8], raw[position+8:position+8+length]
        assert struct.unpack('!I', raw[position+8+length:position+12+length])[0] == zlib.crc32(kind+data) & 0xffffffff
        if kind == b'IDAT':
            compressed += data
        position += 12 + length
    rows = np.frombuffer(zlib.decompress(compressed), dtype='uint8').reshape(height, 1 + width * 4)
    assert not rows[:, 0].any()
    return rows[:, 1:].reshape(height, width, 4)


def test_verified_hashes_counts_and_grid(tmp_path):
    root, manifest = fixture(tmp_path)
    result = preview.verify_inputs(root, manifest)
    assert result['verified_contributor_cells'] == {1: 4032}
    manifest['width'] += 1
    with pytest.raises(ValueError, match='grid declaration'):
        preview.verify_inputs(root, manifest)
    manifest['width'] -= 1
    manifest['outputs']['elevation']['sha256'] = 'a' * 64
    with pytest.raises(ValueError, match='SHA-256 mismatch'):
        preview.verify_inputs(root, manifest)


def test_count_mismatch_not_accepted(tmp_path):
    root, manifest = fixture(tmp_path)
    manifest['contributor_cells']['1'] -= 1
    manifest['stats']['valid_cells'] -= 1
    with pytest.raises(ValueError, match='actual contributor counts'):
        preview.verify_inputs(root, manifest)


def test_sample_withholds_holes_and_keeps_centre_values(tmp_path):
    root, _ = fixture(tmp_path)
    with rasterio.open(root / 'elevation.tif') as elevation, rasterio.open(root / 'contributor.tif') as contributor:
        values, codes, stride = preview.conservative_sample(elevation, contributor, Window(0, 0, 64, 64), 16)
        assert stride == 4
        assert np.isnan(values[4:6, 4:6]).all()
        assert not codes[4:6, 4:6].any()
        expected = elevation.read(1)[2::4, 2::4]
        np.testing.assert_array_equal(values[codes > 0], expected[codes > 0])


def test_one_hidden_hole_or_mixed_source_withholds_entire_block(tmp_path):
    root, _ = fixture(tmp_path)
    with rasterio.open(root / 'contributor.tif', 'r+') as contributor:
        codes = contributor.read(1)
        codes[0, 0] = 0  # not the nearest sample location
        codes[0, 4] = 2
        contributor.write(codes, 1)
    with rasterio.open(root / 'elevation.tif') as elevation, rasterio.open(root / 'contributor.tif') as contributor:
        values, codes, _ = preview.conservative_sample(elevation, contributor, Window(0, 0, 64, 64), 16)
    assert np.isnan(values[0, 0]) and np.isnan(values[0, 1])
    assert codes[0, 0] == codes[0, 1] == 0


def test_hillshade_has_no_cross_hole_or_cross_source_gradient(tmp_path):
    z = np.full((8, 8), -30, dtype='float32')
    c = np.ones((8, 8), dtype='uint16')
    reference = preview.hillshade(z, c, 10)
    z[:, 4:] = -1000
    c[:, 4:] = 2
    changed = preview.hillshade(z, c, 10)
    np.testing.assert_array_equal(changed[:, :4], reference[:, :4])
    c[:, 4:] = 0
    z[:, 4:] = np.nan
    hole = preview.hillshade(z, c, 10)
    np.testing.assert_array_equal(hole[:, :4], reference[:, :4])
    assert not hole[:, 4:, 3].any()
    path = tmp_path / 'image.png'
    preview.png(path, hole)
    np.testing.assert_array_equal(decode_png(path), hole)


def test_real_cli_contract_without_real_cache_dependency(tmp_path, monkeypatch):
    root, _ = fixture(tmp_path)
    monkeypatch.setattr(preview, 'VIEWS', tuple((key, key, None) for key in ('overview', 'morro-estero', 'buchon-close')))
    output = tmp_path / 'preview'
    result = preview.build(root / 'manifest.json', output)
    assert result['mode'] == 'c1_hillshade_fallback'
    assert len(result['views']) == 3
    for view in result['views']:
        html = (output / f'{view["id"]}.html').read_text()
        assert 'NOT FOR NAVIGATION' in html and 'rights.html' in html
        rgba = decode_png(output / f'{view["id"]}-hillshade.png')
        assert int(np.count_nonzero(rgba[:, :, 3])) == view['supported_display_samples']
    with pytest.raises(FileExistsError):
        preview.build(root / 'manifest.json', output)
    with pytest.raises(ValueError, match='read-only'):
        preview.build(root / 'manifest.json', root / 'not-allowed')
