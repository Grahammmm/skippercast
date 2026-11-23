"""Synthetic controls for the R5a nearshore raster boundary (no region data)."""
import json
import runpy
import warnings

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


def test_native_paint_stays_inside_mosaic_land_mask(tmp_path):
    # Native water can straddle a coarser mosaic shoreline. Native alpha alone
    # must not let that water paint over mosaic land or missing evidence.
    np = pytest.importorskip('numpy')
    rio = pytest.importorskip('rasterio')
    pytest.importorskip('scipy')
    from rasterio.errors import NotGeoreferencedWarning
    from rasterio.io import MemoryFile
    from rasterio.warp import Resampling, reproject, transform_bounds
    from skippercast.relief import qa
    from skippercast.seafloor.rough_first import read_tiles

    mosaic = np.full((30, 30), -10, dtype='float32')
    mosaic[:, :12] = 5
    bg = _grid(rio, tmp_path / 'mosaic.tif', mosaic, (0, 300), 10)
    native = _grid(rio, tmp_path / 'native.tif', np.full((420, 420), -1, dtype='float32'), (-60, 360), 1)
    row = dict(id='synthetic', resolution_m=1, path=str(native), max_zoom=15)
    bounds = transform_bounds('EPSG:3310', 'EPSG:4326', 5, 5, 295, 295, densify_pts=21)
    tiles._render(bg, tmp_path / 'native.json', [row], bounds, tmp_path, 'synthetic', style.load().view('baked'))

    water_paint = {14: 0, 15: 0}
    land_paint = missing_paint = 0
    archive = read_tiles((tmp_path / 'relief.pmtiles').read_bytes())
    with rio.open(bg) as source:
        for (z, x, y), blob in archive.items():
            if z not in water_paint:
                continue
            with warnings.catch_warnings(), MemoryFile(blob, ext='.png') as memory:
                warnings.simplefilter('ignore', NotGeoreferencedWarning)
                with memory.open(driver='PNG') as image:
                    opaque = image.dataset_mask() != 0
            evidence = np.full(opaque.shape, np.nan, dtype='float32')
            reproject(rio.band(source, 1), evidence, dst_transform=qa._tile_grid(z, x, y),
                      dst_crs='EPSG:3857', dst_nodata=np.nan, resampling=Resampling.nearest, tolerance=0)
            finite = np.isfinite(evidence)
            land_paint += np.count_nonzero(opaque & finite & (evidence > 3))
            missing_paint += np.count_nonzero(opaque & ~finite)
            water_paint[z] += np.count_nonzero(opaque & finite & (evidence <= 3))
    assert land_paint == missing_paint == 0, (land_paint, missing_paint, water_paint)
    assert water_paint[14] > 0 and water_paint[15] > 0, water_paint


def test_morro_bay_mosaic_water_uses_unshaded_depth_ramp(tmp_path):
    # At the render boundary, missing the region switch leaves shaded water;
    # applying it too broadly changes the control or the native PNG payloads.
    import numpy as np
    import rasterio as rio
    from rasterio.errors import NotGeoreferencedWarning
    from rasterio.io import MemoryFile
    from rasterio.warp import Resampling, reproject, transform_bounds
    from skippercast.relief.nearshore import Nearshore, to_bytes
    from skippercast.seafloor.rough_first import read_tiles

    baked = style.load('nearshore-v1.0.0').view('baked')
    elevation = np.full((40, 50), -17., dtype='float32')
    elevation[:, :25] += np.cos(np.arange(25)) * 4
    elevation[:, 40:] = 1.
    elevation[:, 45:] = 5.
    elevation[:2, :] = np.nan
    mosaic = _grid(rio, tmp_path / 'mosaic.tif', elevation, (0, 400), 10)
    fine = np.broadcast_to(-12 + 2 * np.cos(np.arange(620) / 8), (520, 620)).astype('float32')
    native = _grid(rio, tmp_path / 'native.tif', fine, (-60, 460), 1)
    support = _grid(rio, tmp_path / 'support.tif', np.full(fine.shape, 3, dtype='uint8'), (-60, 460), 1)
    rows = [dict(id='synthetic', resolution_m=1, path=str(native), support_path=str(support), max_zoom=17)]
    bounds = transform_bounds('EPSG:3310', 'EPSG:4326', 25, 25, 495, 405)
    clip = transform_bounds('EPSG:4326', 'EPSG:3857', *bounds)
    before = [path.read_bytes() for path in (mosaic, native)]
    archives = []
    for label in ('morro-bay', 'synthetic'):
        out = tmp_path / label
        out.mkdir()
        tiles._render(mosaic, tmp_path / 'native.json', rows, bounds, out, label, baked)
        archives.append(read_tiles((out / 'relief.pmtiles').read_bytes()))
    assert [path.read_bytes() for path in (mosaic, native)] == before
    morro, control = archives
    assert morro.keys() == control.keys()
    for zoom in (14, 15, 16, 17):
        keys = [key for key in morro if key[0] == zoom]
        assert keys, f'fixture must emit native z{zoom}'
        assert all(morro[key] == control[key] for key in keys)

    builder = tiles._builder()
    reference = Nearshore(np.where(elevation <= 3, elevation, np.nan), 10, (0, 0, 500, 400), baked)
    assert not reference.piles_enabled()
    valid = ~reference.nodata
    with rio.open(mosaic) as src:
        profile = dict(driver='GTiff', width=src.width, height=src.height, crs=src.crs,
                       transform=src.transform, count=4, dtype='uint8')
    with MemoryFile() as shaded_mem, MemoryFile() as ramp_mem:
        with shaded_mem.open(**profile) as shaded_ds, ramp_mem.open(**profile) as ramp_ds:
            rgba = np.zeros((4, *elevation.shape), dtype='uint8')
            rgba[3, valid] = 255
            rgba[:3, valid] = to_bytes(reference.base('overview'))[valid].T
            shaded_ds.write(rgba)
            rgba[:3, reference.water] = to_bytes(reference.depth_rgb())[reference.water].T
            ramp_ds.write(rgba)

            def decode(blob):
                with warnings.catch_warnings(), MemoryFile(blob, ext='.png') as memory:
                    warnings.simplefilter('ignore', NotGeoreferencedWarning)
                    with memory.open(driver='PNG') as image:
                        return image.read().transpose(1, 2, 0)

            samples = dict(water=0, land=0, nodata=0, shaded_difference=0, ramp_mismatch=0)
            for key in (key for key in morro if key[0] == 13):
                z, x, y = key
                region = builder.tile_core_region(z, x, y, clip)
                ramp = tiles._tile(ramp_ds, z, x, y, builder)
                shaded = tiles._tile(shaded_ds, z, x, y, builder)
                assert ramp is not None and shaded is not None
                ramp[~region] = shaded[~region] = 0
                actual, other = decode(morro[key]), decode(control[key])
                np.testing.assert_array_equal(other, shaded)
                np.testing.assert_array_equal(actual[..., 3], other[..., 3])
                transform, _ = builder.tile_grid(z, x, y, pad=0)
                for name in ('water', 'land', 'nodata'):
                    # Require zero weight on cells of any other class. The
                    # padding rules out truncated kernels at the raster edge.
                    mask = np.pad(~getattr(reference, name), 2, constant_values=True).astype('float32')
                    fraction = np.ones(region.shape, dtype='float32')
                    reproject(mask, fraction, src_crs=ramp_ds.crs,
                              src_transform=rio.transform.from_origin(-20, 420, 10, 10),
                              dst_crs='EPSG:3857', dst_transform=transform,
                              dst_nodata=1, resampling=Resampling.bilinear, tolerance=0)
                    inside = region & (fraction == 0)
                    samples[name] += np.count_nonzero(inside)
                    if name == 'water':
                        samples['shaded_difference'] += np.count_nonzero(np.any(other[inside, :3] != ramp[inside, :3], axis=1))
                        samples['ramp_mismatch'] += np.count_nonzero(np.any(actual[inside, :3] != ramp[inside, :3], axis=1))
                    else:
                        np.testing.assert_array_equal(actual[inside, :3], other[inside, :3])
    assert all(samples[name] for name in ('water', 'land', 'nodata', 'shaded_difference')), samples
    assert samples['ramp_mismatch'] == 0, f"water RGB differs from the unchanged ramp: {samples}"
