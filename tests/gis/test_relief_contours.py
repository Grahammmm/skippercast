"""Offline checks for the contour producer's normalised-input boundary."""
import hashlib
import importlib.util
import json
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


def test_normalized_twin_retains_original_identity_and_shelf_lines(builder, geographic_twin, tmp_path):
    # A derivative may not replace the original digest, leak its path or move lines in this planar control.
    from pyproj import Transformer
    from shapely import transform
    from shapely.geometry import shape

    run, _ = builder
    projected, raw, normalized, sidecar = geographic_twin
    expected = run(projected, tmp_path / 'control.geojson')
    output = tmp_path / 'twin.geojson'
    actual = run(normalized, output, sidecar=sidecar, support=write_support(tmp_path / 'support.tif', normalized))
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

    full = native_east(run(normalized, tmp_path / 'full.geojson', sidecar=sidecar,
                           support=write_support(tmp_path / 'measured.tif', normalized)))
    partial_doc = run(normalized, tmp_path / 'partial.geojson', sidecar=sidecar,
                      support=write_support(tmp_path / 'partial.tif', normalized, interpolated_from_col=cut_col))
    partial = native_east(partial_doc)
    cut = 690000 + 2 * cut_col
    assert full > cut + 20
    assert partial <= cut + 2
    # The interpolated side keeps coarse (overview-grade) contours rather than losing its lines.
    assert any(f['properties']['kind'] == 'contour' and f['properties']['minzoom'] < 14
               and max(xs_of.transform(*pt)[0] for line in f['geometry']['coordinates'] for pt in line) > cut + 10
               for f in partial_doc['features'])

    # A support raster that is not cell-for-cell aligned with the grid is refused, not guessed at.
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    shifted = tmp_path / 'shifted.tif'
    with rasterio.open(normalized) as ds, rasterio.open(shifted, 'w', driver='GTiff', count=1, dtype='uint8', height=ds.height,
                                                      width=ds.width, crs=ds.crs, transform=from_origin(690002, 3915000, 2, 2)) as dst:
        dst.write(np.full((ds.height, ds.width), 3, dtype='uint8'), 1)
    with pytest.raises(SystemExit, match='aligned'):
        run(normalized, tmp_path / 'shifted.geojson', sidecar=sidecar, support=shifted)


@pytest.mark.parametrize('downgraded_from_col', [None, 50])
def test_region_stage_preserves_siblings_and_refuses_ineligible_mosaic_cells(tmp_path, monkeypatch, builder, downgraded_from_col):
    # A valid R4 code alone must not admit a denied source, replace native lines, or evict tiles/zone.
    # downgraded_from_col protects: cells the support raster marks interpolated (class 2) in a 2 m normalised
    # grid must not draw z14+ native detail; a bug that ignores support.tif draws it across the whole grid.
    import numpy as np
    import rasterio
    from pyproj import Transformer
    from rasterio.transform import from_origin

    from skippercast.platform import depth_contours as dc
    from skippercast.relief import contours, receipts

    region = {'id': 'morro-bay', 'bounds': [-122, 34, -120, 36], 'source_bindings': {'bathymetry': [SOURCE, 'excluded']}}
    _, source = builder
    sources = {SOURCE: source, 'excluded': {**source, 'rights': {**source['rights'], 'public_display': 'excluded'}},
               'unbound': source, 'coarse': source}
    region['source_bindings']['bathymetry'].append('coarse')
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
    coarse = write_grid(tmp_path / 'coarse.tif', np.tile(np.linspace(-1, -120, 20, dtype='float32'), (40, 1)),
                        crs, from_origin(x + 200, y, 10, 10))

    support = tmp_path / 'support.tif'
    classes = np.full(depths.shape, 3, dtype='uint8')
    if downgraded_from_col is not None:
        classes[:, downgraded_from_col:] = 2
    with rasterio.open(support, 'w', driver='GTiff', count=1, dtype='uint8', height=classes.shape[0],
                       width=classes.shape[1], crs=crs, transform=native_transform) as ds:
        ds.write(classes, 1)

    def row(ident, grid):
        return {'id': f'{ident}-tile', 'source_id': ident, 'path': str(grid),
                'sha256': digest(grid) if grid.exists() else 'f' * 64,
                'rights_class': 'public', 'vertical_offset_m': 0, 'vertical_datum': 'MLLW',
                'value_convention': 'elevation_positive_up'}

    rows = [{**row(SOURCE, native), 'support_path': str(support), 'support_sha256': digest(support)},
            row('coarse', coarse), row('excluded', tmp_path / 'never-open.tif'),
            row('unbound', tmp_path / 'unbound.tif')]

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
    assert {entry['source_id']: entry['reason'] for entry in receipt['params']['refused_sources']} == {
        'excluded': 'not cleared for public display', 'unbound': 'not a static region bathymetry binding'}
    assert receipt['metrics']['mosaic_gap_blocks'] == 12 * 40
    assert all(receipts.check(r, stage, 'public').done for stage in ('tiles', 'zone'))
    assert [row['path'] for row in receipt['outputs']] == [
        'layers/contours/contours-overview.geojson', 'layers/contours/contours.geojson']
    output = r.dir / 'layers/contours/contours.geojson'
    full = json.loads(output.read_bytes())
    dc.check_contours(full, region, sources)
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
