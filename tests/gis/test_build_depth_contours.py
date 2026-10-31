"""scripts/build_depth_contours.py on tiny synthetic GeoTIFFs; nothing is written outside tmp_path."""
import importlib.util
import sys

import pytest

from tests._support import ROOT

pytestmark = pytest.mark.gis


def _load_builder():
    spec = importlib.util.spec_from_file_location('build_depth_contours', ROOT / 'scripts/build_depth_contours.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tif(path, values, x0, y0, cell=2.0, crs='EPSG:32610', dtype='float32', nodata=-9999.0):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    with rasterio.open(path, 'w', driver='GTiff', width=values.shape[1], height=values.shape[0], count=1, dtype=dtype,
                       crs=crs, transform=from_origin(x0, y0, cell, cell), nodata=nodata) as ds:
        ds.write(np.asarray(values, dtype=dtype), 1)
    return path


def _sources(*ids, native=2):
    return {i: {'id': i, 'review_status': 'approved', 'needs': ['bathymetry'], 'name': f'Synthetic {i}',
                'documentation_url': 'https://example.invalid/doc', 'rights': {'attribution': 'Synthetic'},
                'survey_year': 2008, 'vertical_datum': None, 'native_resolution_m': native,
                'reviewed_at': '2026-10-01'} for i in ids}


def _run_builder(monkeypatch, grids, sources, *extra, captured=None):
    pytest.importorskip('rasterio')
    bs = _load_builder()
    region = {'id': 'synthetic-bay', 'bounds': [-121.5, 35.0, -120.0, 36.0],
              'source_bindings': {'bathymetry': list(sources)}}
    captured = {} if captured is None else captured
    monkeypatch.setattr(bs, 'load_region', lambda ident: region)
    monkeypatch.setattr(bs, 'load_catalogs', lambda: (None, sources))
    monkeypatch.setattr(bs, 'atomic_json', lambda path, value: captured.update(doc=value, path=path) or {'sha256': '0' * 64, 'bytes': 1})
    argv = ['build_depth_contours.py', '--region', 'synthetic-bay', *extra]
    for ident, path in grids.items():
        argv += ['--grid', f'{ident}={path}']
    monkeypatch.setattr(sys, 'argv', argv)
    bs.main()
    return captured['doc']


def _slope(shape, shallow=-10.0, deep=-60.0):
    import numpy as np
    h, w = shape
    return np.tile(np.linspace(shallow, deep, w), (h, 1))


X0, Y0 = 690_000.0, 3_915_000.0


def test_guard_feet_levels_and_lonlat(tmp_path, monkeypatch):
    a = _tif(tmp_path / 'a.tif', _slope((64, 64)), X0, Y0)
    doc = _run_builder(monkeypatch, {'usgs-a': a}, _sources('usgs-a'))
    depths = sorted(f['properties']['depth_ft'] for f in doc['features'] if f['properties']['kind'] == 'contour')
    assert depths and all(d % 30 == 0 and 30 <= d <= 196 for d in depths)
    lon, lat = doc['features'][0]['geometry']['coordinates'][0][0]
    assert -121.5 < lon < -120.0 and 35.0 < lat < 36.0 and doc['provenance']['units'] == 'ft'


def test_grid_contributing_no_water_block_is_refused(tmp_path, monkeypatch):
    a = _tif(tmp_path / 'a.tif', _slope((64, 64)), X0, Y0)
    b = _tif(tmp_path / 'b.tif', -_slope((64, 64)), X0 + 128, Y0)          # positive-down: no water by this method
    with pytest.raises(SystemExit, match=r"no valid water block: \['usgs-b'\]"):
        _run_builder(monkeypatch, {'usgs-a': a, 'usgs-b': b}, _sources('usgs-a', 'usgs-b'))


def test_same_file_under_two_sources_is_refused(tmp_path, monkeypatch):
    a = _tif(tmp_path / 'a.tif', _slope((64, 64)), X0, Y0)
    with pytest.raises(SystemExit, match='same file'):
        _run_builder(monkeypatch, {'usgs-a': a, 'usgs-b': a}, _sources('usgs-a', 'usgs-b'))


@pytest.mark.parametrize('cell,native', [(4.0, 2), (2.0, None)])
def test_grid_cell_must_match_reviewed_native_resolution(tmp_path, monkeypatch, cell, native):
    a = _tif(tmp_path / 'a.tif', _slope((32, 32)), X0, Y0, cell=cell)
    with pytest.raises(SystemExit, match='differs from reviewed native_resolution_m'):
        _run_builder(monkeypatch, {'usgs-a': a}, _sources('usgs-a', native=native))


def test_omitted_binding_is_recorded_and_an_unapproved_grid_is_refused_before_any_read(tmp_path, monkeypatch):
    import hashlib
    import numpy as np
    import rasterio
    sources = _sources('usgs-a', 'noaa-x')
    sources['noaa-x']['review_status'] = 'candidate'
    a = _tif(tmp_path / 'a.tif', _slope((64, 64)), X0, Y0)
    doc = _run_builder(monkeypatch, {'usgs-a': a}, sources)
    assert doc['provenance']['sources_omitted'] == [{'source_id': 'noaa-x', 'review_status': 'candidate'}]
    x = _tif(tmp_path / 'x.tif', np.full((8, 8), -20.0), X0, Y0)
    # The builder's sha256 is hashlib.file_digest; both spies are on the modules the builder imports.
    calls = []
    monkeypatch.setattr(rasterio, 'open', lambda *a, **k: calls.append(('open', a)))
    monkeypatch.setattr(hashlib, 'file_digest', lambda *a, **k: calls.append(('sha256', a)))
    with pytest.raises(SystemExit, match='not an approved bathymetry source'):
        _run_builder(monkeypatch, {'usgs-a': a, 'noaa-x': x}, sources)
    assert calls == []


def test_held_output_traces_a_candidate_grid_privately_and_the_default_still_refuses_it(tmp_path, monkeypatch):
    import rasterio
    from skippercast.platform import depth_contours as dc
    sources = _sources('noaa-x')
    sources['noaa-x'].update(review_status='candidate', rights={'attribution': 'Synthetic', 'license': 'CC0-1.0'})
    x = _tif(tmp_path / 'x.tif', _slope((64, 64)), X0, Y0)
    captured = {}
    doc = _run_builder(monkeypatch, {'noaa-x': x}, sources, '--held-output', str(tmp_path / 'held.geojson'), captured=captured)
    assert captured['path'] == (tmp_path / 'held.geojson').resolve()
    assert doc['provenance']['publication_held'] is True
    assert doc['provenance']['held_sources'] == [{'source_id': 'noaa-x', 'review_status': 'candidate'}]
    assert any(f['properties']['kind'] == 'contour' for f in doc['features'])
    calls = []
    monkeypatch.setattr(rasterio, 'open', lambda *a, **k: calls.append(a))
    with pytest.raises(SystemExit, match='is not an approved bathymetry source'):
        _run_builder(monkeypatch, {'noaa-x': x}, sources)
    assert calls == []
    with pytest.raises(ValueError, match='are held and cannot be published'):
        dc.check_contours(doc, {'id': 'synthetic-bay', 'bounds': [-121.5, 35.0, -120.0, 36.0],
                                'source_bindings': {'bathymetry': ['noaa-x']}}, sources)


@pytest.mark.parametrize('under_repo', [True, False])
def test_held_output_in_the_repo_or_of_a_restricted_source_is_refused_before_any_read(tmp_path, monkeypatch, under_repo):
    import rasterio
    from skippercast.platform import contracts
    sources = _sources('csumb-x')
    if under_repo:
        monkeypatch.setattr(contracts, 'REPO', tmp_path)
        out, message = tmp_path / 'catalog/x.geojson', 'outside the work tree'
    else:
        sources['csumb-x'].update(review_status='restricted', rights={'attribution': 'Synthetic', 'license': 'unresolved'})
        out, message = tmp_path / 'held.geojson', 'cannot be traced, even held: restricted, licence unresolved'
    x = _tif(tmp_path / 'x.tif', _slope((64, 64)), X0, Y0)
    calls, captured = [], {}
    monkeypatch.setattr(rasterio, 'open', lambda *a, **k: calls.append(a))
    with pytest.raises(SystemExit, match=message):
        _run_builder(monkeypatch, {'csumb-x': x}, sources, '--held-output', str(out), captured=captured)
    assert calls == [] and captured == {} and not out.exists()


# P5: regular NOAA BAG grids (synthetic, made with the tests/gis/test_seafloor_adapters.py make_bag pattern).
def _bag(tmp_path, name, values, x0, y0, survey='H99999', start='2019-07-14', vertical=None, crs='EPSG:32610'):
    """A regular BAG of `values`; its metadata gains a survey start and, if given, a replacement VERT_CS (h5py)."""
    pytest.importorskip('h5py')
    import h5py
    import numpy as np
    from rasterio.shutil import copy as raster_copy
    path = tmp_path / f'{survey}_{name}_2m.bag'
    raster_copy(_tif(tmp_path / f'{name}.tif', values, x0, y0, crs=crs), path, driver='BAG', VAR_ABSTRACT=f'{survey} synthetic')
    with h5py.File(path, 'r+') as f:
        xml = f['BAG_root/metadata'][:].tobytes().decode('utf-8').rstrip('\0')
        xml = xml.replace('</gmi:MI_Metadata>', f'<gml:beginPosition>{start}</gml:beginPosition></gmi:MI_Metadata>')
        xml = xml.replace('VERT_CS["unknown", VERT_DATUM["unknown", 2000]]', vertical or 'VERT_CS["unknown", VERT_DATUM["unknown", 2000]]')
        del f['BAG_root/metadata']
        f['BAG_root'].create_dataset('metadata', data=np.frombuffer(xml.encode('utf-8'), dtype='S1'))
    return path


def _bag_sources():
    sources = _sources('noaa-bag', native=None)
    sources['noaa-bag'].update(adapter='bag', survey_year=None)
    return sources


def _build(monkeypatch, sources, *args, bounds=(-121.5, 35.0, -120.0, 36.0), setup=None):
    bs = _load_builder()
    region = {'id': 'synthetic-bay', 'bounds': list(bounds), 'source_bindings': {'bathymetry': list(sources)}}
    captured = {}
    monkeypatch.setattr(bs, 'load_region', lambda ident: region)
    monkeypatch.setattr(bs, 'load_catalogs', lambda: (None, sources))
    monkeypatch.setattr(bs, 'atomic_json', lambda path, value: captured.update(doc=value) or {'sha256': '0' * 64, 'bytes': 1})
    if setup:
        setup(bs)
    monkeypatch.setattr(sys, 'argv', ['build_depth_contours.py', '--region', 'synthetic-bay', *args])
    bs.main()
    return captured['doc']


def _lines(doc):
    return [(f['id'], f['properties'].get('depth_ft'), f['geometry']) for f in doc['features']]


def test_bag_traces_like_its_geotiff_and_carries_its_own_date_survey_and_declared_datum(tmp_path, monkeypatch):
    values = _slope((64, 64))
    tif = _tif(tmp_path / 'same.tif', values, X0, Y0)
    want = _build(monkeypatch, _sources('noaa-bag'), '--grid', f'noaa-bag={tif}')
    got = _build(monkeypatch, _bag_sources(), '--grid', f'noaa-bag={_bag(tmp_path, "b", values, X0, Y0)}',
                 '--bag-survey', 'noaa-bag=H99999')
    assert any(f['properties']['kind'] == 'contour' for f in got['features']) and _lines(got) == _lines(want)
    entry = got['provenance']['sources'][0]
    assert (entry['survey_date'], entry['survey_id'], entry['vertical_datum']) == ('2019-07-14', 'H99999', 'unverified source datum')
    assert entry['vertical_datum_source'] == 'bag-metadata' and entry['native_cell_m'] == 2.0
    assert got['provenance']['datum_note'].endswith("BAG surveys: the datum each BAG's metadata declares, copied as declared. "
                                                    'Not converted or certified.')
    assert want['provenance']['datum_note'] == (
        "Depths are below each survey's own vertical datum. The original GeoTIFFs declare none; "
        'the companion USGS report (Open-File Report 2023-1064) names MLLW. Not converted or certified.')


def test_compound_bag_traces_using_its_horizontal_crs(tmp_path, monkeypatch):
    import rasterio
    from pyproj import CRS
    from pyproj.crs import CompoundCRS
    crs = CompoundCRS('UTM + MLLW', [CRS('EPSG:32610'), CRS('EPSG:5866')])
    values = _slope((64, 64))
    path = _bag(tmp_path, 'compound', values, X0, Y0, crs=crs.to_wkt())
    with rasterio.open(path) as grid:
        assert CRS(grid.crs).is_compound
    def check_horizontal(bs):
        check = bs.preflight.check_grid

        def checked(meta, **kwargs):
            assert not CRS(meta['crs_wkt']).is_compound
            assert meta['crs_projected'] and meta['crs_linear_units'] == 'metre'
            return check(meta, **kwargs)
        monkeypatch.setattr(bs.preflight, 'check_grid', checked)

    got = _build(monkeypatch, _bag_sources(), '--grid', f'noaa-bag={path}', '--bag-survey', 'noaa-bag=H99999',
                 setup=check_horizontal)
    tif = _tif(tmp_path / 'projected.tif', values, X0, Y0)
    want = _build(monkeypatch, _sources('noaa-bag'), '--grid', f'noaa-bag={tif}')
    assert _lines(got) == _lines(want)
    assert any(f['properties']['kind'] == 'contour' for f in got['features'])
    assert got['provenance']['horizontal_crs'] == want['provenance']['horizontal_crs']


def test_receipt_shaped_bound_compound_bag_traces_using_source_crs(tmp_path, monkeypatch):
    import rasterio
    from pyproj import CRS
    # NOAA's W00433 shape: the legacy TOWGS84 makes the PROJCS a bound CRS.
    wkt = '''COMPD_CS["NAD83 / UTM zone 11N + MLLW depth",
        PROJCS["NAD83 / UTM zone 11N",
            GEOGCS["NAD83",DATUM["North_American_Datum_1983",
                SPHEROID["GRS 1980",6378137,298.257222101],TOWGS84[0,0,0,0,0,0,0]],
                PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],
            PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],
            PARAMETER["central_meridian",-117],PARAMETER["scale_factor",0.9996],
            PARAMETER["false_easting",500000],PARAMETER["false_northing",0],
            UNIT["metre",1],AUTHORITY["EPSG","26911"]],
        VERT_CS["MLLW depth",VERT_DATUM["Mean Lower Low Water",2000],
            UNIT["metre",1],AXIS["Depth",DOWN]]]'''
    values = _slope((64, 64))
    path = _bag(tmp_path, 'bound-compound', values, X0, Y0, crs=wkt)
    # GDAL's BAG writer can canonicalize NAD83 and drop TOWGS84. Restore the
    # producer's legacy datum binding in the actual BAG metadata, not a mock.
    import h5py
    import numpy as np
    with h5py.File(path, 'r+') as f:
        xml = f['BAG_root/metadata'][:].tobytes().decode('utf-8').rstrip('\0')
        if 'TOWGS84[' not in xml:
            xml = xml.replace('AUTHORITY["EPSG","6269"]]',
                              'TOWGS84[0,0,0,0,0,0,0],AUTHORITY["EPSG","6269"]]')
        del f['BAG_root/metadata']
        f['BAG_root'].create_dataset('metadata', data=np.frombuffer(xml.encode('utf-8'), dtype='S1'))
    with rasterio.open(path) as grid:
        compound = CRS(grid.crs)
        assert compound.is_compound and compound.sub_crs_list[0].is_bound

    def check_horizontal(bs):
        check = bs.preflight.check_grid

        def checked(meta, **kwargs):
            horizontal = CRS(meta['crs_wkt'])
            assert not horizontal.is_compound and not horizontal.is_bound
            assert horizontal.equals(CRS('EPSG:26911'))
            assert meta['crs_projected'] and meta['crs_linear_units'] == 'metre'
            return check(meta, **kwargs)
        monkeypatch.setattr(bs.preflight, 'check_grid', checked)

    bounds = (-116, 35, -114, 36)
    got = _build(monkeypatch, _bag_sources(), '--grid', f'noaa-bag={path}', '--bag-survey', 'noaa-bag=H99999',
                 bounds=bounds, setup=check_horizontal)
    tif = _tif(tmp_path / 'nad83.tif', values, X0, Y0, crs='EPSG:26911')
    want = _build(monkeypatch, _sources('noaa-bag'), '--grid', f'noaa-bag={tif}', bounds=bounds)
    assert _lines(got) == _lines(want)
    assert any(f['properties']['kind'] == 'contour' for f in got['features'])
    assert got['provenance']['horizontal_crs'] == 'EPSG:26911'
    assert got['provenance']['sources'][0]['vertical_datum'] == 'Mean Lower Low Water'


def test_bag_reads_are_clipped_to_the_region_with_no_survey_edge_along_the_clip(tmp_path, monkeypatch):
    from pyproj import Transformer
    lon = lambda x: Transformer.from_crs('EPSG:32610', 'EPSG:4326', always_xy=True).transform(x, Y0 - 128)[0]  # noqa: E731
    path = _bag(tmp_path, 'wide', _slope((128, 1256)), X0, Y0)       # 2,512 m wide: 2 km past the clipped east bound

    def edge_along(doc, east):
        edges = [ln for f in doc['features'] if f['properties']['kind'] == 'survey-edge' for ln in f['geometry']['coordinates']]
        return any(abs(a[0] - b[0]) < 1e-4 and abs(a[1] - b[1]) > 5e-4 and a[0] > east - 5e-4
                   for ln in edges for a, b in zip(ln, ln[1:]))
    args = ('--grid', f'noaa-bag={path}', '--bag-survey', 'noaa-bag=H99999')
    assert edge_along(_build(monkeypatch, _bag_sources(), *args), lon(X0 + 2512))     # control: the grid's own east edge
    east = lon(X0 + 512)
    doc = _build(monkeypatch, _bag_sources(), *args, bounds=(-121.5, 35.0, east, 36.0))
    points = [pt for f in doc['features'] for ln in f['geometry']['coordinates'] for pt in ln]
    assert any(f['properties']['kind'] == 'contour' for f in doc['features'])
    assert max(p[0] for p in points) <= east and not edge_along(doc, east)


@pytest.mark.parametrize('case,message', [('vr', 'overview rejected'), ('no-survey', 'needs --bag-survey'),
                                          ('twice', 'given twice'), ('ellipsoid', 'ellipsoid-referenced BAG'),
                                          ('preflight', 'preflight refused: pixels'), ('control', None)])
def test_bag_refusals_come_before_any_read(tmp_path, monkeypatch, case, message):
    import functools
    import h5py
    import numpy as np
    from rasterio.io import DatasetReader
    ellipsoid = 'VERT_CS["WGS 84 ellipsoidal height", VERT_DATUM["World Geodetic System 1984 ellipsoid", 2002]]'
    path = _bag(tmp_path, 'b', _slope((64, 64)), X0, Y0, vertical=ellipsoid if case == 'ellipsoid' else None)
    if case == 'vr':
        with h5py.File(path, 'r+') as f:
            f['BAG_root'].create_dataset('varres_refinements', data=np.zeros((1, 2)))
    args = ['--grid', f'noaa-bag={path}'] + ([] if case == 'no-survey' else ['--bag-survey', 'noaa-bag=H99999'])
    args += ['--grid', f'noaa-bag={path}'] if case == 'twice' else []
    # The first strip of this 64 x 64 grid is 4,096 native pixels, over a cap lowered to 1,000.
    cap = None if case != 'preflight' else (
        lambda bs: monkeypatch.setattr(bs.preflight, 'check_grid', functools.partial(bs.preflight.check_grid, max_pixels=1000)))
    reads, read = [], DatasetReader.read
    monkeypatch.setattr(DatasetReader, 'read', lambda self, *a, **k: reads.append(self.name) or read(self, *a, **k))
    if message is None:
        _build(monkeypatch, _bag_sources(), *args, setup=cap)
        assert reads
        return
    with pytest.raises(SystemExit, match=message):
        _build(monkeypatch, _bag_sources(), *args, setup=cap)
    assert reads == []


def test_grids_of_two_declared_datums_meeting_at_a_seam_leave_the_straddling_blocks_a_gap(tmp_path, monkeypatch):
    a = _tif(tmp_path / 'a.tif', _slope((64, 60)), X0, Y0)                # ends 8 m into block column 7
    b = _tif(tmp_path / 'b.tif', _slope((64, 64)), X0 + 120, Y0)          # starts there
    supported = {}
    for datum in ('MLLW', 'NAVD88'):
        sources = _sources('usgs-a', 'usgs-b')
        sources['usgs-a']['vertical_datum'], sources['usgs-b']['vertical_datum'] = 'MLLW', datum
        doc = _run_builder(monkeypatch, {'usgs-a': a, 'usgs-b': b}, sources)
        supported[datum] = [s['supported_blocks'] for s in doc['provenance']['sources']]
    # One datum: the 8 seam blocks merge native cells and count. Two datums: they are a gap, never a mean.
    assert supported == {'MLLW': [64, 56], 'NAVD88': [56, 56]}


@pytest.mark.parametrize('complete_middle', [True, False])
def test_cross_datum_block_prefers_a_complete_grid_over_early_partial_cells(tmp_path, complete_middle):
    from contextlib import ExitStack
    import numpy as np
    import rasterio
    bs = _load_builder()
    early = np.full((8, 8), -9999.0)
    early[0, 0] = -10
    middle = np.full((8, 8), -20.0)
    if not complete_middle:
        middle[0, 0] = -9999
    late = np.full((8, 8), -30.0)
    late[0, 0] = -9999  # The first datum's group completes only by merging partial grids.
    paths = [_tif(tmp_path / f'{i}.tif', a, X0, Y0) for i, a in enumerate((early, middle, late))]
    lattice = (X0, Y0, 1, 1)
    with ExitStack() as stack:
        grids = [stack.enter_context(rasterio.open(p)) for p in paths]
        depth, owner = bs.merged_blocks(grids, lattice, [bs.native_offsets(g, lattice) for g in grids],
                                        [(8, 'MLLW'), (8, 'NAVD88'), (8, 'MLLW')])
    assert owner[0, 0] == (1 if complete_middle else 2)
    metres = 20 if complete_middle else (10 + 63 * 30) / 64
    assert depth[0, 0] == pytest.approx(metres * bs.dc.FEET_PER_M)


def test_output_writes_the_approved_only_collection_outside_the_tree(tmp_path, monkeypatch):
    from skippercast.platform import depth_contours as dc
    sources = _sources('usgs-a')
    a = _tif(tmp_path / 'a.tif', _slope((64, 64)), X0, Y0)
    captured = {}
    doc = _run_builder(monkeypatch, {'usgs-a': a}, sources, '--output', str(tmp_path / 'out.geojson'), captured=captured)
    assert captured['path'] == (tmp_path / 'out.geojson').resolve()
    assert 'publication_held' not in doc['provenance'] and 'held_sources' not in doc['provenance']
    assert any(f['properties']['kind'] == 'contour' for f in doc['features'])
    dc.check_contours(doc, {'id': 'synthetic-bay', 'bounds': [-121.5, 35.0, -120.0, 36.0],
                            'source_bindings': {'bathymetry': ['usgs-a']}}, sources)


def test_output_in_the_repo_is_refused_before_any_read(tmp_path, monkeypatch):
    import rasterio
    from skippercast.platform import contracts
    monkeypatch.setattr(contracts, 'REPO', tmp_path)
    out = tmp_path / 'catalog/x.geojson'
    a = _tif(tmp_path / 'a.tif', _slope((64, 64)), X0, Y0)
    calls, captured = [], {}
    monkeypatch.setattr(rasterio, 'open', lambda *a, **k: calls.append(a))
    with pytest.raises(SystemExit, match='Output must be outside the work tree'):
        _run_builder(monkeypatch, {'usgs-a': a}, _sources('usgs-a'), '--output', str(out), captured=captured)
    assert calls == [] and captured == {} and not out.exists()


def test_output_and_held_output_are_mutually_exclusive(tmp_path, monkeypatch, capsys):
    import rasterio
    a = _tif(tmp_path / 'a.tif', _slope((64, 64)), X0, Y0)
    calls, captured = [], {}
    monkeypatch.setattr(rasterio, 'open', lambda *a, **k: calls.append(a))
    with pytest.raises(SystemExit) as info:
        _run_builder(monkeypatch, {'usgs-a': a}, _sources('usgs-a'), '--output', str(tmp_path / 'o.geojson'),
                     '--held-output', str(tmp_path / 'h.geojson'), captured=captured)
    assert info.value.code == 2 and 'not allowed with argument' in capsys.readouterr().err
    assert calls == [] and captured == {}


def _ec(path, codes, tags=None, hint=None, x0=X0):
    """An EC provenance raster (uint8 codes, EC_VERSION tag) and, with `hint`, the shoal_hint.tif beside it."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    for p, values, dtype in ((path, codes, 'uint8'), (path.with_name('shoal_hint.tif'), hint, 'float32')):
        if values is not None:
            with rasterio.open(p, 'w', driver='GTiff', width=values.shape[1], height=values.shape[0], count=1,
                               dtype=dtype, crs='EPSG:32610', transform=from_origin(x0, Y0, 2.0, 2.0)) as ds:
                ds.update_tags(**({'EC_VERSION': '1.0'} if tags is None else tags))
                ds.write(np.asarray(values, dtype=dtype), 1)
    return path


def test_provenance_cuts_contours_into_class_runs_and_draws_unresolved_areas(tmp_path, monkeypatch):
    import numpy as np
    from pyproj import Transformer
    from skippercast.platform import depth_contours as dc
    a = _tif(tmp_path / 'a.tif', _slope((128, 128), shallow=-2.0), X0, Y0)   # 16 x 16 blocks; 30 ft between block cols 1 and 2
    codes, hint = np.full((128, 128), 10), np.full((128, 128), np.nan)
    codes[24:32, 8:16] = 20                       # one filled block (row 3, col 1) on the 30 ft line
    codes[64:80, 8:24] = 30                       # verified 2 x 2 blocks: a square is verified only with four verified corners
    codes[0:8, 64:72], hint[0:8, 64:72] = 41, -3.0  # one unresolved-conflict block on the top edge, off every contour
    (tmp_path / 'ec').mkdir()
    prov = _ec(tmp_path / 'ec' / 'provenance.tif', codes, hint=hint)
    monkeypatch.setattr(dc, 'simplify', lambda line, tolerance, scale: [list(p) for p in line])  # compare traced points
    plain = _run_builder(monkeypatch, {'usgs-a': a}, _sources('usgs-a'))
    doc = _run_builder(monkeypatch, {'usgs-a': a}, _sources('usgs-a'), '--provenance', f'usgs-a={prov}')
    by_id = {f['id']: f for f in doc['features']}
    runs = [by_id[f'usgs-a-30ft{s}'] for s in ('', '-filled', '-verified')]
    assert [f['properties']['provenance'] for f in runs] == ['measured', 'filled', 'verified']
    points = lambda fs: {tuple(p) for f in fs for line in f['geometry']['coordinates'] for p in line}  # noqa: E731
    assert points(runs) == points([f for f in plain['features'] if f['id'] == 'usgs-a-30ft'])
    assert sum(len(f['geometry']['coordinates']) for f in runs) == 5      # measured, filled, measured, verified, measured
    area = by_id['usgs-a-unresolved-conflict']
    assert area['geometry']['type'] == 'MultiPolygon' and area['properties'] == {
        'kind': 'unresolved-area', 'reason': 'conflict', 'blocks': 1, 'shoal_hint_ft': 10, 'source_id': 'usgs-a',
        'survey_date': '2008', 'vertical_datum': dc.UNVERIFIED_DATUM}
    assert [f['properties']['kind'] for f in doc['features']].count('unresolved-area') == 1
    # The survey edge runs round the unresolved block (within its 12 m simplification) exactly as round a gap.
    from shapely.geometry import MultiLineString, Point
    to_utm = Transformer.from_crs('EPSG:4326', 'EPSG:32610', always_xy=True).transform
    edge = lambda d: MultiLineString([[to_utm(*p) for p in line] for f in d['features']  # noqa: E731
                                      if f['properties']['kind'] == 'survey-edge' for line in f['geometry']['coordinates']])
    notch = Point(X0 + 136, Y0 - 16)                  # the middle of the block's lower side, 16 m below the grid's top
    assert edge(doc).distance(notch) <= 12.5 and edge(plain).distance(notch) >= 15
    entry = doc['provenance']['sources'][0]
    assert entry['ec_version'] == '1.0' and entry['supported_blocks'] == 255
    assert entry['provenance_counts'] == {'measured': 250, 'filled': 1, 'verified': 4, 'unresolved': 1}
    assert 'never as contours' in doc['provenance']['method'] and 'never as contours' not in plain['provenance']['method']
    assert not any(f['properties']['kind'] == 'unresolved-area' for f in dc.overview_contours(doc)['features'])  # 16 m span


# sha256 of the output JSON, written by the builder before EC5 on these fixtures; without --provenance it must not move.
FROZEN = {'slope': '3046a67e2b992103d4bdac5c02de98419ffead5c69642469e73095494fe73697',
          'seam': '6e1108d81aaad2d0b58d7f8ac4ad1e4ca77d01a419f5c9a4148ecbfd6a4a1476'}


def test_without_provenance_the_output_matches_the_frozen_pre_change_bytes(tmp_path, monkeypatch):
    import hashlib
    import json
    a = _tif(tmp_path / 'a.tif', _slope((128, 128), shallow=-2.0), X0, Y0)
    b = _tif(tmp_path / 'b.tif', _slope((64, 64)), X0 + 248, Y0)
    got = {'slope': _run_builder(monkeypatch, {'usgs-a': a}, _sources('usgs-a')),
           'seam': _run_builder(monkeypatch, {'usgs-a': a, 'usgs-b': b}, _sources('usgs-a', 'usgs-b'))}
    assert {k: hashlib.sha256(json.dumps(v).encode()).hexdigest() for k, v in got.items()} == FROZEN


@pytest.mark.parametrize('case,message', [
    ('unknown id', 'only for a source given with --grid'), ('size', 'does not match the survey grid'),
    ('transform', 'does not match the survey grid'), ('no tag', 'no EC_VERSION tag')])
def test_provenance_refusals_come_before_any_read(tmp_path, monkeypatch, case, message):
    import hashlib
    import numpy as np
    import rasterio
    a = _tif(tmp_path / 'a.tif', _slope((64, 64)), X0, Y0)
    shape, x0, tags = ((32, 32) if case == 'size' else (64, 64)), (X0 + 16 if case == 'transform' else X0), None
    prov = _ec(tmp_path / 'provenance.tif', np.full(shape, 10), tags={} if case == 'no tag' else None, x0=x0)
    reads = []
    monkeypatch.setattr(rasterio.io.DatasetReader, 'read', lambda *a, **k: reads.append(a))
    monkeypatch.setattr(hashlib, 'file_digest', lambda *a, **k: reads.append(a))
    with pytest.raises(SystemExit, match=message):
        _run_builder(monkeypatch, {'usgs-a': a}, _sources('usgs-a'), '--provenance',
                     f'{"usgs-x" if case == "unknown id" else "usgs-a"}={prov}')
    assert reads == []
