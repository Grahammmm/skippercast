"""Original-sounding parity, sign, registration, masks and failure fixtures."""
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from pyproj import Transformer
import pytest
import rasterio

from research.scripts.prepare_multibeam_grid import (
    MBGRID_SHA, MBLIST_SHA, grid_recipe, prepare, read_grid, reconcile)
from research.scripts.triage_multibeam_beams import COLUMNS

pytestmark = pytest.mark.gis


def fixture_arrays():
    h = dict(ncols=3., nrows=2., xllcorner=700000., yllcorner=3820000.,
             cellsize=5., nodata_value=-99999.)
    topo = np.array([[-30., -91.44, -99999.], [-20., -91., -100.]])
    count = np.array([[2., 1., -99999.], [3., 2., 1.]])
    dispersion = np.array([[5., 0., -99999.], [10., 1., 0.]])
    inverse = Transformer.from_crs(32610, 4326, always_xy=True)
    beams = []
    for (row, col), depths in { (0, 0): [30, 35], (0, 1): [91.44],
            (1, 0): [10, 20, 30], (1, 1): [91, 92], (1, 2): [100]}.items():
        lon, lat = inverse.transform(700002.5+col*5, 3820007.5-row*5)
        beams.extend((lon, lat, d) for d in depths)
    return h, topo, count, dispersion, np.asarray(beams)


def test_upper_topography_median_sign_and_mixed_depth_bins():
    h, z, c, sd, beams = fixture_arrays()
    arrays, safe, stats = reconcile(h, z, c, sd, beams, epsg=32610)
    assert arrays[0][0, 0] == 30  # Not average 32.5, and no double sign flip.
    assert arrays[3][0, 0] == 30 and arrays[4][0, 0] == 35
    assert safe.tolist() == [[True, True, False], [True, False, True]]
    assert stats['mixed_depth_boundary_bins'] == 1
    assert stats['safe_nominal_shallow_bins'] == 3
    assert stats['original_good_beams_in_grid'] == 9
    assert stats['independently_checked_bins'] == 5


@pytest.mark.parametrize('target', ['topography', 'count', 'dispersion'])
def test_original_parity_rejects_changed_cells(target):
    h, z, c, sd, beams = fixture_arrays()
    {'topography': z, 'count': c, 'dispersion': sd}[target][0, 0] += 1
    with pytest.raises(ValueError, match='parity'):
        reconcile(h, z, c, sd, beams, epsg=32610)


def test_empty_grid_is_unknown_and_boundary_precision_is_held():
    h, z, c, sd, beams = fixture_arrays()
    empty = np.full_like(z, -99999.)
    _, safe, stats = reconcile(h, empty, empty, empty, np.empty((0, 3)), epsg=32610)
    assert not safe.any() and stats['occupied_bins'] == 0
    inverse = Transformer.from_crs(32610, 4326, always_xy=True)
    lon, lat = inverse.transform(700005., 3820007.5)
    z = empty.copy(); c = empty.copy(); sd = empty.copy()
    # The printed corner may put the point on either side. Neither cell may
    # establish fine support merely because one chosen bin matches the count.
    z[0, 1] = -30; c[0, 1] = 1; sd[0, 1] = 0
    _, safe, stats = reconcile(h, z, c, sd, np.array([[lon, lat, 30]]), epsg=32610)
    assert stats['registration_ambiguous_bins'] >= 1
    assert not safe[0, 1]


def write_ascii(path, h, a):
    path.write_text(''.join(f'{k} {v}\n' for k, v in h.items()) +
                    ''.join(' '.join(str(v) for v in row)+'\n' for row in a))


def setup_batch(tmp_path):
    h, z, c, sd, points = fixture_arrays()
    native = tmp_path/'original.mb57'; native.write_bytes(b'Synthetic offline original bytes')
    source_sha = hashlib.sha256(native.read_bytes()).hexdigest()
    grids = [tmp_path/n for n in ('grid.asc', 'grid_num.asc', 'grid_sd.asc')]
    for p, a in zip(grids, (z, c, sd)): write_ascii(p, h, a)
    source = {'path': str(native), 'bytes': native.stat().st_size, 'sha256': source_sha}
    recipe = {'returncode': 0, 'binary_sha256': MBGRID_SHA, 'depth_datum': 'unknown',
        'command': ['/official/mbgrid', '-Ilist.mb-1', '-Ogrid', '-A2', '-F2', '-C0',
                    '-G4', '-M', '-P1', '-U0', '-E5/5meters!', '-JUTM10N', '-R-121/-120/34/35'],
        'inputs': [source], 'outputs': [{'path': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in grids]}
    recipe_path = tmp_path/'recipe.json'; recipe_path.write_text(json.dumps(recipe))
    table = tmp_path/'beams.tsv.gz'
    raw = ''.join(f'{lon:.12f} {lat:.12f} {d} 0 893326000 1 {i}\n' for i, (lon, lat, d) in enumerate(points)).encode()
    with gzip.open(table, 'wb') as f: f.write(raw)
    beam_receipt = {'columns': COLUMNS, 'binary_sha256': MBLIST_SHA, 'rows': len(points),
        'stdout_sha256': hashlib.sha256(raw).hexdigest(), 'command': ['/official/mblist', '-F57', '-I'+str(native), '-MA', '-OXYzFMN#']}
    beam_path = tmp_path/'beam-receipt.json'; beam_path.write_text(json.dumps(beam_receipt))
    return grids, recipe_path, [(table, beam_path)], native


def test_normalized_cog_retains_transform_mask_and_diagnostics(tmp_path):
    grids, receipt, pairs, _ = setup_batch(tmp_path)
    output = tmp_path/'normalized.tif'
    result = prepare(grids, receipt, pairs, tmp_path, output)
    assert result['new_measured_km2'] == 0 and not result['source_qualified']
    assert not result['exportable'] and result['vertical_datum'] == 'unknown'
    with rasterio.open(output) as ds:
        assert ds.count == 5 and ds.crs.to_epsg() == 32610
        assert ds.transform.c == 700000 and ds.transform.f == 3820010
        assert ds.xy(0, 0) == (700002.5, 3820007.5)
        assert ds.read(1)[0, 0] == 30 and np.isnan(ds.read(1)[1, 1])
        assert ds.dataset_mask().tolist() == [[255, 255, 0], [255, 0, 255]]
        assert ds.descriptions[2] == 'median_dispersion_m_not_uncertainty'
        assert ds.tags()['grid_spacing_basis'].startswith('derived bin spacing')
    with pytest.raises(ValueError, match='overwrite'):
        prepare(grids, receipt, pairs, tmp_path, output)


@pytest.mark.parametrize('kind', ['source', 'grid', 'beam', 'alignment'])
def test_failures_leave_no_completed_output(tmp_path, kind):
    grids, receipt, pairs, native = setup_batch(tmp_path)
    if kind == 'source': native.write_bytes(b'changed')
    elif kind == 'grid': grids[0].write_text(grids[0].read_text().replace('-30.0', '-31.0'))
    elif kind == 'beam':
        with gzip.open(pairs[0][0], 'ab') as f: f.write(b'0 0 2 0 1 1 99\n')
    else:
        text = grids[1].read_text().replace('700000.0', '700001.0'); grids[1].write_text(text)
        r = json.loads(receipt.read_text()); r['outputs'][1]['sha256'] = hashlib.sha256(grids[1].read_bytes()).hexdigest(); receipt.write_text(json.dumps(r))
    out = tmp_path/'normalized.tif'
    with pytest.raises(ValueError): prepare(grids, receipt, pairs, tmp_path, out)
    assert not out.exists() and not out.with_suffix('.json').exists()


@pytest.mark.parametrize('option', ['-C5', '-Kworld.grd', '-P10', '-A1', '-F1', '-Q'])
def test_reject_filled_decimated_or_changed_processing(tmp_path, option):
    _, receipt, _, _ = setup_batch(tmp_path)
    r = json.loads(receipt.read_text()); r['command'].append(option)
    with pytest.raises(ValueError): grid_recipe(r)


def test_ascii_dimensions_and_corner_semantics_are_explicit(tmp_path):
    p = tmp_path/'grid.asc'; h, z, _, _, _ = fixture_arrays()
    write_ascii(p, h, z)
    header, a, _ = read_grid(p)
    assert header == h and np.array_equal(a, z)
    p.write_text(p.read_text().replace('xllcorner', 'xllcenter'))
    with pytest.raises(ValueError, match='corner'): read_grid(p)


def test_implicit_time_selection_recipe_is_rejected(tmp_path):
    _, receipt, _, _ = setup_batch(tmp_path)
    r = json.loads(receipt.read_text()); r['command'].remove('-U0')
    with pytest.raises(ValueError, match='recipe'): grid_recipe(r)


@pytest.mark.parametrize('value', ['nan', 'inf', '-inf'])
def test_ascii_nonfinite_values_are_not_missing_measurements(tmp_path, value):
    p = tmp_path/'grid.asc'; h, z, _, _, _ = fixture_arrays()
    write_ascii(p, h, z)
    p.write_text(p.read_text().replace('-30.0', value))
    with pytest.raises(ValueError, match='Nonfinite'): read_grid(p)


def test_boundary_withholds_both_plausible_neighbor_bins():
    h, z, c, sd, _ = fixture_arrays()
    inverse = Transformer.from_crs(32610, 4326, always_xy=True)
    lon, lat = inverse.transform(h['xllcorner']+5, h['yllcorner']+7.5)
    z[:] = -99999; c[:] = -99999; sd[:] = -99999
    z[0, 0] = -30; c[0, 0] = 1; sd[0, 0] = 0
    _, safe, stats = reconcile(h, z, c, sd, np.array([[lon,lat,30]]), epsg=32610)
    assert not safe.any() and stats['registration_ambiguous_bins'] >= 2


def test_grid_roles_cannot_be_swapped(tmp_path):
    grids, receipt, pairs, _ = setup_batch(tmp_path)
    with pytest.raises(ValueError, match='roles'):
        prepare([grids[1],grids[0],grids[2]],receipt,pairs,tmp_path,tmp_path/'out.tif')
