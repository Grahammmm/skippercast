"""Offline checks for the contour producer's normalised-input boundary."""
import hashlib
import importlib.util
import json
import shutil
import sys

import pytest

from tests._support import ROOT

pytestmark = pytest.mark.gis
SOURCE = 'usgs-point-estero'


@pytest.fixture
def builder(monkeypatch):
    pytest.importorskip('rasterio')
    spec = importlib.util.spec_from_file_location('build_depth_contours', ROOT / 'scripts/build_depth_contours.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = {'name': 'Synthetic CSUMB survey', 'review_status': 'approved', 'needs': ['bathymetry'],
              'documentation_url': 'https://example.org/survey', 'survey_year': 2008,
              'native_resolution_m': 2, 'vertical_datum': 'MLLW',
              'rights': {'public_display': 'allowed', 'attribution': 'USGS; CSUMB',
                         'owner_public_display': {'decision': 'allowed',
                                                  'basis': 'G decision 2026-11-18 (owner-accepted risk; revisit when paid)'}}}
    region = {'id': 'morro-bay', 'bounds': [-122, 34, -120, 36], 'source_bindings': {'bathymetry': [SOURCE]}}
    monkeypatch.setattr(module, 'load_catalogs', lambda: ({}, {SOURCE: source}))
    monkeypatch.setattr(module, 'load_region', lambda _: region)

    def run(grid, out, *, sidecar=None, support=None):
        argv = ['build_depth_contours.py', '--region', region['id'], '--set', 'v2',
                '--grid', f'{SOURCE}={grid}', '--output', str(out)]
        if sidecar is not None:
            argv.extend(('--normalized-sidecar', f'{SOURCE}={sidecar}'))
        if support is not None:
            argv.extend(('--normalized-support', f'{SOURCE}={support}'))
        monkeypatch.setattr(sys, 'argv', argv)
        module.main()
        return json.loads(out.read_bytes())

    return run, source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_grid(path, values, crs, transform):
    import rasterio

    with rasterio.open(path, 'w', driver='GTiff', count=1, dtype='float32', nodata=-9999,
                       height=values.shape[0], width=values.shape[1], crs=crs, transform=transform) as ds:
        ds.write(values, 1)
    return path


@pytest.mark.parametrize('admission', ['allowed', 'cell-cap', 'memory-low', 'memory-unknown'])
def test_region_trace_admission(tmp_path, monkeypatch, builder, admission):
    # The native guard must not stop a region trace, and refusals must precede mosaic reads.
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    from skippercast.relief import contours, receipts

    tool = contours.producer()
    _, source = builder
    values = np.tile(np.linspace(-1, -100, 20, dtype='float32'), (20, 1))
    crs, transform = 'EPSG:32610', from_origin(690000, 3915000, 10, 10)
    elevation = write_grid(tmp_path / 'elevation.tif', values, crs, transform)
    with rasterio.open(elevation) as grid:
        profile = grid.profile
    with rasterio.open(tmp_path / 'contributor.tif', 'w', **(profile | {'dtype': 'uint16', 'nodata': 0})) as ds:
        ds.write(np.ones(values.shape, dtype='uint16'), 1)
    region = {'id': 'morro-bay', 'bounds': [-122, 34, -120, 36], 'source_bindings': {'bathymetry': [SOURCE]}}
    row = {'id': SOURCE, 'source_id': SOURCE, 'sha256': digest(elevation), 'vertical_datum': 'MLLW'}
    manifest = {'seam_feather': {'feather_m': 0}, 'sources': [{'id': SOURCE, 'code': 1}]}
    job = tool, region, {SOURCE: source}, [(row, elevation, None, None, None)], set(), manifest, tmp_path
    monkeypatch.setattr(tool.preflight, 'MAX_PIXELS', 100)
    monkeypatch.setattr(contours, 'CONTOUR_MAX_CELLS', values.size - (admission == 'cell-cap'))
    monkeypatch.setattr(contours, 'TRACE_BYTES_PER_CELL', 10)
    # Exactly half available is allowed; one byte less must hold rather than consume all available RAM.
    available = None if admission == 'memory-unknown' else 2 * values.size * 10 - (admission == 'memory-low')
    monkeypatch.setattr(contours, '_mem_available', lambda: available)
    if admission == 'allowed':
        collection, _ = contours.trace(job)
        assert {f['properties']['source_id'] for f in collection['features']} == {SOURCE}
        return
    monkeypatch.setattr(contours, 'mosaic_samples', lambda *_: pytest.fail('read mosaic before admission'))
    error, reason = {
        'cell-cap': (ValueError, 'contour mosaic exceeds the cell budget'),
        'memory-low': (receipts.Held, 'contour trace needs'),
        'memory-unknown': (receipts.Held, 'cannot determine MemAvailable'),
    }[admission]
    with pytest.raises(error, match=reason):
        contours.trace(job)


def test_native_detail_keeps_native_window_cap(geographic_twin, monkeypatch):
    # Raising the region cap must not permit a larger native window read.
    import numpy as np

    from skippercast.relief import contours

    tool = contours.producer()
    projected, *_ = geographic_twin
    monkeypatch.setattr(tool.preflight, 'MAX_PIXELS', 99)
    with tool.open_geotiff(projected, normalized=True) as grid:
        with pytest.raises(SystemExit, match='v2 native window exceeds 99 pixels'):
            tool.v2_native(grid, (0, 0, 5), np.ones((2, 2), dtype=bool), None)


@pytest.fixture
def geographic_twin(tmp_path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import reproject

    crs, transform = 'EPSG:32610', from_origin(690000, 3915000, 2, 2)
    values = np.tile(np.linspace(-1, -120, 100, dtype='float32'), (80, 1))
    projected = write_grid(tmp_path / 'projected.tif', values, crs, transform)
    with rasterio.open(projected) as ds:
        geographic, geo_transform = reproject(ds.read(1), src_transform=ds.transform, src_crs=crs,
                                               src_nodata=-9999, dst_crs='EPSG:4326', dst_nodata=-9999,
                                               dst_resolution=0.000004)
    raw = write_grid(tmp_path / 'original-geographic.tif', geographic[0], 'EPSG:4326', geo_transform)
    twin, _ = reproject(geographic[0], destination=np.empty_like(values), src_transform=geo_transform,
                        src_crs='EPSG:4326', src_nodata=-9999, dst_crs=crs, dst_transform=transform,
                        dst_nodata=-9999)
    normalized = write_grid(tmp_path / 'grid.tif', twin, crs, transform)
    sidecar = tmp_path / 'sidecar.json'
    sidecar.write_text(json.dumps({'schema': 'sc-relief-normalized/1', 'original_sha256': digest(raw),
                                   'original_path': str(raw), 'outputs': {'grid.tif': digest(normalized)},
                                   'units': 'm', 'value_convention': 'elevation_positive_up', 'vertical_datum': 'MLLW',
                                   'crs': crs, 'shape': list(values.shape), 'transform': list(transform)[:6],
                                   'resolution_m': 2}))
    return projected, raw, normalized, sidecar


def write_support(path, grid, interpolated_from_col=None):
    import numpy as np
    import rasterio

    with rasterio.open(grid) as ds:
        classes = np.full((ds.height, ds.width), 3, dtype='uint8')
        if interpolated_from_col is not None:
            classes[:, interpolated_from_col:] = 2
        with rasterio.open(path, 'w', driver='GTiff', count=1, dtype='uint8', height=ds.height, width=ds.width,
                           crs=ds.crs, transform=ds.transform) as out:
            out.write(classes, 1)
    return path


def pin_support(sidecar, support, name='pinned-sidecar.json'):
    """A copy of the normalised sidecar whose receipt pins `support` as outputs['support.tif']."""
    doc = json.loads(sidecar.read_bytes())
    doc['outputs']['support.tif'] = digest(support)
    pinned = sidecar.with_name(name)
    pinned.write_text(json.dumps(doc))
    return pinned


@pytest.mark.parametrize('cell,native,certified', [(2, 2, True), (4, 4, False), (1, 4, True), (1, 1, False), (1, 1, True)])
def test_v3_native_tiers_and_pier(tmp_path, cell, native, certified):
    # Interpolated or merely fine-looking cells cannot acquire fine or pier contours.
    import numpy as np
    from pyproj import Transformer
    from rasterio.transform import from_origin
    from skippercast import style
    from skippercast.relief import contours

    tool = contours.producer()
    view = style.load().view('contours')
    region = {'bounds': [-122, 34, -120, 36]}
    values = np.tile(np.linspace(-0.2, -100, 100, dtype='float32'), (50, 1))
    values[20:30, :] = -9999
    proj = 'EPSG:32610'
    grid = write_grid(tmp_path / 'native.tif', values, proj, from_origin(690000, 3915000, cell, cell))
    mask = write_support(tmp_path / 'support.tif', grid)
    with tool.open_geotiff(grid, normalized=True) as ds, tool.open_geotiff(mask, normalized=True) as support:
        lines = list(tool.v3_grid(ds, region, view, {'source_id': 'synthetic'}, native,
                                  support=support if certified else None, certified=certified))
    if native > cell:
        assert not lines
        return
    props = [f['properties'] for f in lines]
    assert {p['tier'] for p in props} == ({'z8', 'z11', 'z13'} | ({'z15'} if cell <= 2 else set())
                                           | ({'pier'} if cell == 1 and certified else set()))
    for tier, step, indices in [('z8', 60, {60, 150, 300}), ('z11', 30, {60, 150, 300}),
                                ('z13', 10, set(range(50, 301, 50))), ('z15', 5, set(range(10, 301, 10)))]:
        rows = [p for p in props if p['tier'] == tier]
        if rows:
            assert {p['depth_ft'] for p in rows} == set(range(step, 301, step)) | indices
            assert {p['depth_ft'] for p in rows if p['index']} == indices
    xy = Transformer.from_crs('EPSG:4326', proj, always_xy=True)
    for f in lines:
        for line in f['geometry']['coordinates']:
            ys = [xy.transform(*point)[1] for point in line]
            assert min(ys) > 3915000 - 20 * cell or max(ys) < 3915000 - 30 * cell


def test_normalized_twin_retains_original_identity_and_shelf_lines(builder, geographic_twin, tmp_path):
    # A derivative may not replace the original digest, leak its path or move lines in this planar control.
    from pyproj import Transformer
    from shapely import transform
    from shapely.geometry import shape

    run, _ = builder
    projected, raw, normalized, sidecar = geographic_twin
    expected = run(projected, tmp_path / 'control.geojson')
    output = tmp_path / 'twin.geojson'
    support = write_support(tmp_path / 'support.tif', normalized)
    actual = run(normalized, output, sidecar=pin_support(sidecar, support), support=support)
    assert actual['provenance']['sources'][0]['sha256'] == digest(raw)
    assert str(tmp_path) not in output.read_text()
    assert actual['provenance']['set'] == 'ft-v2'
    xy = Transformer.from_crs('EPSG:4326', 'EPSG:32610', always_xy=True).transform

    def lines(doc):
        return {f['id']: transform(shape(f['geometry']), xy, interleaved=False)
                for f in doc['features'] if f['properties']['kind'] == 'contour'}

    ref, got = lines(expected), lines(actual)
    assert ref and ref.keys() == got.keys()
    assert max(geom.hausdorff_distance(got[ident]) for ident, geom in ref.items()) <= 0.5
    contours = [f['properties'] for f in actual['features'] if f['properties']['kind'] == 'contour']
    assert max(p['depth_ft'] for p in contours) == 300
    assert all(p['source_id'] == SOURCE and p['estimated'] is True and 'name' not in p for p in contours)


@pytest.mark.parametrize('failure', ['registry-excluded', 'different-normalized-bytes'])
def test_derivative_fails_closed(builder, geographic_twin, tmp_path, failure):
    # Neither an owner-basis declaration nor a correct-looking sidecar may override an explicit denial or pin.
    run, source = builder
    _, _, grid, sidecar = geographic_twin
    if failure == 'registry-excluded':
        source['rights']['public_display'] = 'excluded'
        grid = tmp_path / 'must-not-open.tif'
        reason = 'not cleared for public display'
    else:
        doc = json.loads(sidecar.read_bytes())
        doc['outputs']['grid.tif'] = 'b' * 64
        sidecar.write_text(json.dumps(doc))
        reason = 'normalised grid hash mismatch'
    out = tmp_path / 'refused.geojson'
    with pytest.raises(SystemExit, match=reason):
        run(grid, out, sidecar=sidecar)
    assert not out.exists()


def test_original_grid_needs_an_affirmative_public_display_before_any_read(builder, geographic_twin, tmp_path, monkeypatch):
    # Contract: a non-held build of an ORIGINAL (un-normalised) grid publishes only a source whose registry row
    # says public_display 'allowed'. Believable bug: treating a missing public_display as clearance for original
    # grids (only normalised ones were gated), or opening the raster before refusing.
    import rasterio

    run, source = builder
    projected = geographic_twin[0]
    del source['rights']['public_display']
    calls = []
    monkeypatch.setattr(rasterio, 'open', lambda *a, **k: calls.append(a))
    out = tmp_path / 'refused.geojson'
    with pytest.raises(SystemExit, match=f'{SOURCE} is not cleared for public display'):
        run(projected, out)
    assert calls == [] and not out.exists()


def test_standalone_normalized_native_detail_only_over_measured_support(builder, geographic_twin, tmp_path):
    # Protects: the standalone --set v2 --normalized-sidecar path must apply the grid's support.tif like the region
    # stage does. A bug that omits the support raster traces z14+ native detail across cells marked interpolated
    # (class 2); a bug that lets the support be optional silently does the same when the flag is forgotten.
    from pyproj import Transformer

    run, _ = builder
    _, _, normalized, sidecar = geographic_twin
    out = tmp_path / 'unsupported.geojson'
    with pytest.raises(SystemExit, match='needs --normalized-support'):
        run(normalized, out, sidecar=sidecar)
    assert not out.exists()

    cut_col = 50
    xs_of = Transformer.from_crs('EPSG:4326', 'EPSG:32610', always_xy=True)

    def native_east(doc):
        return max(xs_of.transform(*pt)[0] for f in doc['features'] if f['properties']['kind'] == 'contour'
                   and f['properties']['minzoom'] >= 14 for line in f['geometry']['coordinates'] for pt in line)

    measured = write_support(tmp_path / 'measured.tif', normalized)
    partial_support = write_support(tmp_path / 'partial.tif', normalized, interpolated_from_col=cut_col)
    full = native_east(run(normalized, tmp_path / 'full.geojson', sidecar=pin_support(sidecar, measured, 'full.json'),
                           support=measured))
    partial_sidecar = pin_support(sidecar, partial_support, 'partial.json')
    partial_doc = run(normalized, tmp_path / 'partial.geojson', sidecar=partial_sidecar, support=partial_support)
    partial = native_east(partial_doc)
    cut = 690000 + 2 * cut_col
    assert full > cut + 20
    assert partial <= cut + 2
    # The interpolated side keeps coarse (overview-grade) contours rather than losing its lines.
    assert any(f['properties']['kind'] == 'contour' and f['properties']['minzoom'] < 14
               and max(xs_of.transform(*pt)[0] for line in f['geometry']['coordinates'] for pt in line) > cut + 10
               for f in partial_doc['features'])

    # The support bytes must be the ones the receipt pins. The receipt pins the half-interpolated raster, so an aligned
    # all-measured substitute (which would restore z14+ detail over interpolated cells), a tampered copy of the pinned
    # raster and a receipt with no pin at all are each refused before anything is traced.
    import rasterio

    tampered = tmp_path / 'tampered.tif'
    tampered.write_bytes(partial_support.read_bytes())
    with rasterio.open(tampered, 'r+') as ds:
        classes = ds.read(1)
        classes[:, cut_col:] = 3
        ds.write(classes, 1)
    unpinned = tmp_path / 'unpinned.json'
    doc = json.loads(sidecar.read_bytes())
    doc['outputs'].pop('support.tif', None)
    unpinned.write_text(json.dumps(doc))
    for label, side, support, reason in (('substituted', partial_sidecar, measured, 'differs from the support.tif'),
                                         ('tampered', partial_sidecar, tampered, 'differs from the support.tif'),
                                         ('unpinned', unpinned, measured, 'does not pin')):
        refused = tmp_path / f'{label}.geojson'
        with pytest.raises(SystemExit, match=reason):
            run(normalized, refused, sidecar=side, support=support)
        assert not refused.exists()

    # A support raster that is not cell-for-cell aligned with the grid is refused, not guessed at.
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    shifted = tmp_path / 'shifted.tif'
    with rasterio.open(normalized) as ds, rasterio.open(shifted, 'w', driver='GTiff', count=1, dtype='uint8', height=ds.height,
                                                      width=ds.width, crs=ds.crs, transform=from_origin(690002, 3915000, 2, 2)) as dst:
        dst.write(np.full((ds.height, ds.width), 3, dtype='uint8'), 1)
    with pytest.raises(SystemExit, match='aligned'):
        run(normalized, tmp_path / 'shifted.geojson', sidecar=pin_support(sidecar, shifted, 'shifted.json'), support=shifted)


@pytest.mark.parametrize('downgraded_from_col', [None, 50, 'kit'])
def test_region_stage_preserves_siblings_and_refuses_ineligible_mosaic_cells(tmp_path, monkeypatch, builder, downgraded_from_col):
    # A valid R4 code alone must not admit a denied source, replace native lines, or evict tiles/zone.
    # downgraded_from_col protects: cells the support raster marks interpolated (class 2) in a 2 m normalised
    # grid must not draw z14+ native detail; a bug that ignores support.tif draws it across the whole grid.
    import numpy as np
    import rasterio
    from pyproj import Transformer
    from rasterio.transform import from_origin

    from skippercast.platform import depth_contours as dc
    from skippercast.relief import contours, receipts, render_config

    region = {'id': 'morro-bay', 'bounds': [-122, 34, -120, 36], 'source_bindings': {'bathymetry': ['coarse', 'excluded']}}
    _, source = builder
    source['rights']['license'] = 'public-domain'
    not_cleared = {k: v for k, v in source['rights'].items() if k != 'owner_public_display'}
    sources = {SOURCE: {**source, 'review_status': 'candidate', 'publication_allowed': False},
               'excluded': {**source, 'rights': {**source['rights'], 'public_display': 'excluded'}},
               'unreviewed': {**source, 'publication_allowed': False, 'rights': not_cleared},
               'mbari-lineage': {**source, 'provider': 'Monterey Bay Aquarium Research Institute'},
               'missing-licence': {**source, 'rights': {**source['rights'], 'license': '  '}},
               'unknown-licence': {**source, 'rights': {**not_cleared, 'license': 'Unknown'}},
               'nonpublic': source, 'coarse': {**source, 'rights': not_cleared}}
    monkeypatch.setattr(contours, 'load_region', lambda *_: region)
    monkeypatch.setattr(contours, 'load_catalogs', lambda *_: ({}, sources))
    root = tmp_path / 'repo'
    config = root / 'regions/morro-bay/region.json'
    config.parent.mkdir(parents=True)
    config.write_bytes(receipts.canonical(region))
    (root / 'catalog').mkdir()
    (root / 'catalog/sources.json').write_bytes(receipts.canonical(sources))
    # The CLI uses the checkout for its code digest; only the synthetic registry root is substituted.
    real_producer = contours.producer()
    monkeypatch.setattr(contours, 'producer', lambda: real_producer)
    monkeypatch.setattr(contours, 'repo_root', lambda: root)
    monkeypatch.setattr(render_config, 'repo_root', lambda: root)
    shutil.copytree(ROOT / 'style', root / 'style')
    index_path = root / 'style/index.json'
    index = json.loads(index_path.read_bytes())
    kit = downgraded_from_col == 'kit'
    base_version = index['default']
    if not kit:
        index['default'] = render_config.LEGACY
        index_path.write_bytes(receipts.canonical(index))
    r = receipts.Region(tmp_path / 'out', region['id'])
    crs, x, y = 'EPSG:32610', 690000, 3915000
    native_transform = from_origin(x, y, 2, 2)
    depths = np.tile(np.linspace(-1, -120, 100, dtype='float32'), (200, 1))
    original = write_grid(tmp_path / 'original.tif', depths, crs, native_transform)
    native = write_grid(tmp_path / 'grid.tif', depths + 0.01, crs, native_transform)
    sidecar = tmp_path / 'sidecar.json'
    sidecar.write_bytes(receipts.canonical({'schema': 'sc-relief-normalized/1', 'original_sha256': digest(original),
                                            'outputs': {'grid.tif': digest(native)}, 'units': 'm',
                                            'value_convention': 'elevation_positive_up', 'vertical_datum': 'MLLW',
                                            'crs': crs, 'shape': list(depths.shape), 'resolution_m': 2,
                                            'transform': list(native_transform)[:6]}))
    coarse_cell = 4 if kit else 10
    coarse_count = 200 // coarse_cell
    coarse = write_grid(tmp_path / 'coarse.tif', np.tile(np.linspace(-1, -120, coarse_count, dtype='float32'), (2 * coarse_count, 1)),
                        crs, from_origin(x + 200, y, coarse_cell, coarse_cell))

    support = tmp_path / 'support.tif'
    classes = np.full(depths.shape, 3, dtype='uint8')
    if downgraded_from_col == 50:
        classes[:, downgraded_from_col:] = 2
    with rasterio.open(support, 'w', driver='GTiff', count=1, dtype='uint8', height=classes.shape[0],
                       width=classes.shape[1], crs=crs, transform=native_transform) as ds:
        ds.write(classes, 1)

    if kit:
        normalized = json.loads(sidecar.read_bytes())
        normalized['outputs']['support.tif'] = digest(support)
        sidecar.write_bytes(receipts.canonical(normalized))

    def row(ident, grid):
        return {'id': f'{ident}-tile', 'source_id': ident, 'path': str(grid),
                'sha256': digest(grid) if grid.exists() else 'f' * 64,
                'rights_class': 'public', 'vertical_offset_m': 0, 'vertical_datum': 'MLLW',
                'value_convention': 'elevation_positive_up'}

    rows = [{**row(SOURCE, native), 'support_path': str(support), 'support_sha256': digest(support)},
            row('coarse', coarse), row('excluded', tmp_path / 'never-open.tif'),
            row('unreviewed', tmp_path / 'unreviewed.tif'), row('mbari-lineage', tmp_path / 'mbari.tif'),
            row('missing-licence', tmp_path / 'unlicensed.tif'), row('unknown-licence', tmp_path / 'unknown.tif'),
            {**row('nonpublic', tmp_path / 'nonpublic.tif'), 'rights_class': 'private'}]

    def select(out):
        (out / 'native.json').write_bytes(receipts.canonical(rows[:1]))
        (out / 'sources.json').write_bytes(receipts.canonical({'schema_version': 1, 'scope': 'public', 'sources': rows}))

    def mosaic(out):
        data = np.tile(np.linspace(-1, -120, 20, dtype='float32'), (40, 1))
        block = from_origin(x, y, 10, 10)
        # R4's admitted native strip is deliberately flat here; its actual contour must come from R3.
        depth = write_grid(out / 'elevation.tif', np.hstack((data * 0 - 1, data, data)), crs, block)
        contributor = out / 'contributor.tif'
        with rasterio.open(contributor, 'w', driver='GTiff', width=60, height=40, count=1, dtype='uint16',
                           nodata=0, crs=crs, transform=block) as ds:
            ds.write(np.repeat(np.tile(np.arange(1, 4, dtype='uint16'), (40, 1)), 20, axis=1), 1)
        manifest = {'segment': r.id, 'region_sha256': digest(config),
                    'source_table_sha256': digest(r.dir / 'select/sources.json'), 'units': 'm',
                    'value_convention': 'elevation_positive_up', 'seam_feather': {'feather_m': 40},
                    'sources': [{**value, 'code': i} for i, value in enumerate(rows, 1)],
                    'outputs': {'elevation': {'sha256': digest(depth)}, 'contributor': {'sha256': digest(contributor)}}}
        (out / 'manifest.json').write_bytes(receipts.canonical(manifest))

    select_plan = receipts.Plan([receipts.Input(sidecar, 'normalized-sidecar.json')])
    assert receipts.run_stage(receipts.StageRun(r, 'select', select, 'a' * 64, plan=select_plan)).state == 'ok'
    assert receipts.run_stage(receipts.StageRun(r, 'mosaic', mosaic, 'b' * 64, scope='public',
                                               upstream=[receipts.Ref('select')])).state == 'ok'
    for name in ('tiles', 'zone'):
        def sibling(out):
            (out / 'sentinel').write_text('must survive')
        assert receipts.run_stage(receipts.StageRun(r, name, sibling, 'c' * 64, scope='public',
                                                   target=f'layers/public/{name}')).state == 'ok'
    spec = importlib.util.spec_from_file_location('region_cli', ROOT / 'scripts/relief/region.py')
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    args = ['contours', '--out', str(tmp_path / 'out'), '--region', r.id]
    assert cli.main(args) == 0
    path = r.receipt_path('contours')
    first = path.read_bytes()
    assert cli.main(args) == 0 and path.read_bytes() == first
    receipt = json.loads(first)
    assert receipt['status'] == 'ok' and receipt['attempt'] == 1 and receipts.check(r, 'contours').done
    if kit:
        # Non-contour tokens and style IDs must not invalidate the real StageRun.
        from scripts.style.gen_style import group_digests
        from tests.unit.test_relief_package import inputs as package_inputs, run_package
        from skippercast.relief import package, qa
        default = index['versions'][base_version]
        tokens = json.loads((root / 'style' / default['file']).read_bytes())
        rules = json.loads((root / 'style/groups.json').read_bytes())
        c = default['digests']['contours']
        assert receipt['params'].keys() == {'set', 'refused_sources', 'contours'}
        assert receipt['params']['contours'] == c and receipt['params']['set'] == 'ft-v3'
        assert receipt['metrics']['style'] == {'built_with': base_version, 'sha256': default['sha256'], 'contours': c}
        assert all('style/' not in item['path'] for item in receipt['inputs'])
        v3 = json.loads((r.dir / 'layers/contours/contours.geojson').read_bytes())
        props = [f['properties'] for f in v3['features']]
        assert {p['source_id'] for p in props if p['tier'] == 'z13' and p['depth_ft'] == 10} == {SOURCE, 'coarse'}
        assert {p['source_id'] for p in props if p['tier'] == 'z15' and p['depth_ft'] == 5} == {SOURCE}
        assert set(qa._contour_counts(r.dir, r.id)) == {'5', '10', '30', '60'}
        package_root = tmp_path / 'package-root'
        shutil.copytree(root, package_root)
        (package_root / 'catalog/relief').mkdir()
        shutil.copyfile(ROOT / 'catalog/relief/pointer.schema.json', package_root / 'catalog/relief/pointer.schema.json')
        catalog = package_root / 'catalog/sources.json'
        catalog.write_bytes(receipts.canonical({'sources': [{'id': 'synthetic-grid', 'review_status': 'approved',
                                                             'rights': {'public_display': 'allowed', 'license': 'public-domain'}}]}))
        monkeypatch.setattr(package, 'repo_root', lambda: package_root)
        _, manifest = package_inputs(r.out_root, style={'built_with': base_version, 'baked': default['digests']['baked']})
        assert run_package(r, manifest) == 0
        before_package = receipts.check(r, 'package').receipt
        assert before_package is not None
        prior = before_package['generation']
        for name in ('paint', 'id', 'baked', 'contours'):
            changed = json.loads(json.dumps(tokens))
            if name == 'paint':
                changed['overlays']['field_opacity_by_zoom'][0][1] += 0.01
            elif name == 'baked':
                changed['shading']['hillshade']['ve_min'] += 0.01
            elif name == 'contours':
                changed['contours']['tiers'][0]['sigma_m'] += 0.01
            version = f'nearshore-{name}'
            file = root / 'style' / f'{version}.json'
            file.write_bytes(receipts.canonical(changed))
            new_entry = {**default, 'file': file.name, 'sha256': digest(file), 'digests': group_digests(changed, rules)}
            index['versions'][version] = new_entry
            index['default'] = version
            index_path.write_bytes(receipts.canonical(index))
            assert cli.main(args) == 0
            if name != 'contours':
                assert path.read_bytes() == first
            else:
                rebuilt = json.loads(path.read_bytes())
                assert rebuilt['generation'] != receipt['generation']
                assert rebuilt['metrics']['style']['contours'] == new_entry['digests']['contours'] != c
                assert run_package(r, manifest) == 0
                after_package = receipts.check(r, 'package').receipt
                assert after_package is not None
                gen = after_package['generation']
                assert gen != prior
                release = json.loads((r.dir / 'release' / gen / 'release.json').read_bytes())
                assert release['style']['contours'] == new_entry['digests']['contours']
        return
    # Selection may bind the owner-cleared original, but neither a valid mosaic nor an owner marker
    # grants clearance to nonpublic, MBARI, excluded or unlicensed rows.
    assert {entry['source_id']: entry['reason'] for entry in receipt['params']['refused_sources']} == {
        'excluded': 'not cleared for public display', 'unreviewed': 'publication_allowed is false',
        'mbari-lineage': 'MBARI lineage', 'missing-licence': 'licence mismatch',
        'unknown-licence': 'licence mismatch', 'nonpublic': 'not a public selector row'}
    assert receipt['metrics']['mosaic_gap_blocks'] == 12 * 40
    assert all(receipts.check(r, stage, 'public').done for stage in ('tiles', 'zone'))
    assert [row['path'] for row in receipt['outputs']] == [
        'layers/contours/contours-overview.geojson', 'layers/contours/contours.geojson']
    output = r.dir / 'layers/contours/contours.geojson'
    full = json.loads(output.read_bytes())
    dc.check_selected_contours(full, region, sources, {SOURCE, 'coarse'})
    assert full['provenance']['sources_omitted'] == []
    assert {s['source_id']: s['sha256'] for s in full['provenance']['sources']} == {
        SOURCE: digest(original), 'coarse': digest(coarse)}
    assert str(tmp_path) not in output.read_text()
    assert {f['properties']['source_id'] for f in full['features']} == {SOURCE, 'coarse'}
    assert any(f['properties']['source_id'] == SOURCE and f['properties']['minzoom'] >= 14 for f in full['features'])
    inverse = Transformer.from_crs('EPSG:4326', crs, always_xy=True)
    for f in full['features']:
        p = f['properties']
        assert p['estimated'] and p['depth_ft'] <= 300 and 'name' not in p
        if p['source_id'] == 'coarse':
            assert p['minzoom'] < 14
            assert all(x + 239 <= inverse.transform(*pt)[0] <= x + 361
                       for line in f['geometry']['coordinates'] for pt in line)
    if downgraded_from_col is not None:
        cut = x + 2 * downgraded_from_col

        def xs(f):
            return [inverse.transform(*pt)[0] for line in f['geometry']['coordinates'] for pt in line]

        mine = [f for f in full['features'] if f['properties']['source_id'] == SOURCE]
        native_lines = [f for f in mine if f['properties']['minzoom'] >= 14]
        # Measured west cells keep z14+ detail; none appears over interpolated cells (a 2 m cell of tolerance).
        assert native_lines and all(max(xs(f)) <= cut + 2 for f in native_lines)
        # The interpolated east keeps its coarse (overview-grade) lines instead of losing them.
        assert any(f['properties']['minzoom'] < 14 and max(xs(f)) > cut + 10 for f in mine)


@pytest.mark.parametrize('license_id', ['unknown', 'Unlicensed', ' unresolved ', 'metadata-review-needed'])
def test_unreviewed_licence_term_needs_the_owner_display_decision(license_id):
    # Protects: the contour gate keeps the release policy's known-licence rule (relief.package._UNKNOWN_LICENSE).
    # A bug that rejects only blank licences lets an approved source with licence `unknown` and no owner
    # clearance feed public contours; the owner's recorded display decision is the only override.
    pytest.importorskip('rasterio')
    from skippercast.relief import contours

    owner = {'decision': 'allowed', 'basis': 'G decision 2026-11-18 (owner-accepted risk; revisit when paid)'}
    plain = {'rights': {'license': license_id}}
    cleared = {'rights': {'license': license_id, 'owner_public_display': owner}}
    assert contours._metadata_refusal(plain) == 'licence mismatch'
    assert contours._metadata_refusal(cleared) is None
    assert contours._metadata_refusal({'rights': {'license': 'public-domain'}}) is None
