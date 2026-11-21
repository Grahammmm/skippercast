"""Synthetic controls for the R5a nearshore raster boundary (no region data)."""
import json
import runpy

import pytest

from skippercast import style
from skippercast.relief import tiles
from tests._support import ROOT
from tests.gis.test_relief_stage_adapters import pmtiles_metadata

pytestmark = pytest.mark.gis


def _grid(rio, path, values, origin, cell):
    with rio.open(path, 'w', driver='GTiff', width=values.shape[1], height=values.shape[0],
                  count=1, dtype=values.dtype, crs='EPSG:3310',
                  transform=rio.transform.from_origin(*origin, cell, cell)) as ds:
        ds.write(values, 1)
    return path


def test_render_chunk_size_and_1m_2m_seam_preserve_support(tmp_path):
    # A repartition must not change shading of a real pile or erase holes. Where
    # the 1m footprint ends, the 40m feather should meet the 2m tier without a step.
    np = pytest.importorskip('numpy')
    rio = pytest.importorskip('rasterio')
    pytest.importorskip('scipy')
    from skippercast.relief.nearshore import Nearshore

    baked = style.load().view('baked')
    builder = tiles._builder()
    gold = runpy.run_path(str(ROOT / 'scripts/style/make_synthetic_goldens.py'))
    fine, *_ = gold['surface_1m'](11)
    fine = np.asarray(fine, dtype='float32')
    h, w = fine.shape
    engine = Nearshore(fine, 1, (0, 0, w, h), baked)
    assert engine.piles()[1], 'the chunk control must exercise the pile compositor'
    fine[:, :12] = np.nan
    finepath = _grid(rio, tmp_path / 'fine.tif', fine, (0, h), 1)
    coarse = np.full((h // 2 + 100, w // 2 + 100), -30, dtype='float32')
    coarsepath = _grid(rio, tmp_path / 'coarse.tif', coarse, (-100, h + 100), 2)
    with rio.open(finepath) as src, rio.open(coarsepath) as base:
        profile = dict(src.profile, dtype='uint8', count=4)
        paths = [tmp_path / f'bake{chunk}.tif' for chunk in (83, 512)]
        for path, chunk in zip(paths, (83, 512)):
            with rio.open(path, 'w', **profile) as dst:
                tiles._bake(src, [(base, True)], baked, {'closeup': dst}, builder, native=True, chunk=chunk)
        with rio.open(paths[0]) as a, rio.open(paths[1]) as b:
            first, second = a.read(), b.read()
        np.testing.assert_array_equal(first[3] != 0, np.isfinite(fine) & (fine <= 0) & (fine >= -builder.SHALLOW_M))
        assert np.max(np.abs(first.astype(int) - second.astype(int))) <= 1

    # Check the seam on the same 2m depth ramp, not on a hand-picked equal RGB row.
    coarse_rgb = Nearshore(coarse, 2, (-100, h + 100 - 2 * coarse.shape[0],
                                     -100 + 2 * coarse.shape[1], h + 100), baked).base('closeup')[50, 50]

    def lightness(rgb):
        linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        return 116 * np.cbrt(linear @ np.array([0.2126, 0.7152, 0.0722])) - 16

    seam = first[:, h // 4:3 * h // 4, 12]
    seam = seam[:3, seam[3] == 255].T / 255
    assert len(seam) > 0
    step = np.max(np.abs(lightness(seam) - lightness(coarse_rgb)))
    assert step <= 3, f'1 m/2 m seam step ΔL* {step:.3f} exceeds 3'


def test_render_certified_zoom_requires_every_core_cell_and_never_opens_substrate(tmp_path, monkeypatch):
    # Same certified survey with one interpolated island must lose at least one
    # detail tile; a cap alone cannot certify it. A forbidden class raster cannot
    # silently become an input (native support_class is evidence, not substrate).
    np = pytest.importorskip('numpy')
    rio = pytest.importorskip('rasterio')
    pytest.importorskip('scipy')
    from rasterio.warp import transform_bounds

    bg = _grid(rio, tmp_path / 'mosaic.tif', np.full((30, 30), -10, dtype='float32'), (0, 300), 10)
    native = _grid(rio, tmp_path / 'native.tif', np.full((420, 420), -10, dtype='float32'), (-60, 360), 1)
    cert = tmp_path / 'support.tif'
    substrate = tmp_path / 'substrate.tif'
    substrate.touch()
    manifest = tmp_path / 'native.json'
    row = dict(id='synthetic', resolution_m=1, path=str(native), support_path=str(cert),
               max_zoom=17, substrate_path=str(substrate))
    bounds = transform_bounds('EPSG:3310', 'EPSG:4326', 5, 5, 295, 295, densify_pts=21)
    original = rio.open

    def guarded(path, *args, **kwargs):
        assert 'substrate' not in str(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(rio, 'open', guarded)
    metadata = []
    for degraded in (False, True):
        support = np.full((420, 420), 3, dtype='uint8')
        if degraded:
            support[135:285, 135:285] = 2
        _grid(rio, cert, support, (-60, 360), 1)
        out = tmp_path / str(degraded)
        out.mkdir()
        tiles._render(bg, manifest, [row], bounds, out, 'synthetic', style.load().view('baked'))
        sidecar = json.loads((out / 'coverage.json').read_bytes())
        assert sidecar['native'][0]['id'] == 'synthetic'
        meta = pmtiles_metadata(out / 'relief.pmtiles')
        assert meta['bounds'] == list(bounds)
        metadata.append(meta['native_support_by_zoom'])
    for zoom in ('16', '17'):
        assert metadata[0][zoom]['tiles'] > 0 and metadata[0][zoom]['omitted_uncertified'] == 0
        assert metadata[1][zoom]['tiles'] < metadata[0][zoom]['tiles']
        assert metadata[1][zoom]['omitted_uncertified'] > 0
