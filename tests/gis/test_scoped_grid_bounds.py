"""RF0415-14: scoped reference bounds are admitted before any source work or raster allocation."""
import json
from unittest.mock import patch

import numpy as np
import pytest
from rasterio.transform import Affine
from shapely.geometry import LineString, mapping

from skippercast.seafloor import grid, reference, scoped_grid
from skippercast.seafloor.scope_paths import resolve_scope
from tests._support import ROOT

CENTRAL = ROOT / 'catalog/seafloor-scope.json'
VALID = [-122.00, 36.00, -121.99, 36.01]
SWAPPED = [-121.99, 36.00, -122.00, 36.01]
NAME = 'Scope bounds'


class Sentinel(AssertionError):
    pass


def scope_root(tmp_path, bounds=VALID, **extra):
    (tmp_path / 'catalog').mkdir(exist_ok=True)
    source = json.loads(CENTRAL.read_text())
    source.update(id='offline-demo', bounds=bounds, priority_anchor=[.5, .5],
                  regions=[{'id': 'demo-region', 'start_anchor': [.1, .1]}], **extra)
    config = tmp_path / 'catalog/demo-scope.json'
    config.write_text(json.dumps(source))
    return tmp_path, config


def raw_scope_root(tmp_path, bounds_text):
    """Write the config by hand so JSON-only spellings (1e309, absent key) survive."""
    root, config = scope_root(tmp_path)
    text = config.read_text().replace(json.dumps(VALID), bounds_text, 1)
    assert bounds_text in text
    config.write_text(text)
    return root, config


def tree(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None)
            for p in sorted(root.rglob('*'))}


def fail_fast():
    """Patches that fail the test on any source helper, mosaic or writer call."""
    def boom(*args, **kwargs):
        raise Sentinel('work started before bounds admission')
    return [patch.object(target, name, side_effect=boom) for target, name in (
        (scoped_grid.reference, 'planning_spine'), (scoped_grid.reference, 'scheme_tiles'),
        (scoped_grid.reference, 'samples'), (scoped_grid, 'make_reaches'),
        (scoped_grid, 'mosaic_reference'), (scoped_grid, 'atomic_json'),
        (scoped_grid, 'read_json'), (scoped_grid, 'sha256'))]


def refused(root, config, **kwargs):
    before = tree(root)
    patches = fail_fast()
    for p in patches:
        p.start()
    try:
        with pytest.raises(ValueError) as caught:
            scoped_grid.build(root, scope_config=config, **kwargs)
    finally:
        for p in patches:
            p.stop()
    assert NAME in str(caught.value)
    assert 'west, south, east, north' in str(caught.value)
    assert tree(root) == before
    assert not (root / 'var').exists()


class AllocationObserved(Exception):
    pass


def test_swapped_longitudes_refused_before_world_allocation(tmp_path):
    root, config = scope_root(tmp_path, SWAPPED)
    spine = LineString([(0, 0), (1000, 0)])
    requested = []

    def spy(shape, dtype=None):
        requested.append(tuple(shape))
        raise AllocationObserved(shape)

    with patch.object(reference, 'planning_spine', return_value=spine), \
         patch.object(scoped_grid, 'make_reaches', return_value=[]), \
         patch.object(reference, 'scheme_tiles', return_value=({'scheme_sha256': 'f', 'scheme_url': 'f'}, [])), \
         patch.object(reference, 'samples', return_value=[]), \
         patch.object(scoped_grid, 'sha256', return_value='fixture-hash'), \
         patch.object(grid.np, 'zeros', side_effect=spy):
        with pytest.raises(ValueError, match=NAME):
            scoped_grid.build(root, scope_config=config)
    assert requested == []
    assert not (root / 'var').exists()


def test_valid_bounds_reach_the_real_mosaic_allocation_with_a_small_request(tmp_path):
    """Control: the same spy sees the ordinary small request for the non-swapped bounds."""
    root, config = scope_root(tmp_path)
    spine = LineString([(0, 0), (1000, 0)])
    requested = []

    def spy(shape, dtype=None):
        requested.append(tuple(shape))
        raise AllocationObserved(shape)

    with patch.object(reference, 'planning_spine', return_value=spine), \
         patch.object(scoped_grid, 'make_reaches', return_value=[]), \
         patch.object(reference, 'scheme_tiles', return_value=({'scheme_sha256': 'f', 'scheme_url': 'f'}, [])), \
         patch.object(reference, 'samples', return_value=[]), \
         patch.object(scoped_grid, 'sha256', return_value='fixture-hash'), \
         patch.object(grid.np, 'zeros', side_effect=spy):
        with pytest.raises(AllocationObserved):
            scoped_grid.build(root, scope_config=config)
    assert len(requested) == 1 and requested[0][0] * requested[0][1] < 10_000


@pytest.mark.parametrize('text', [
    'null', '36', '"-122,36,-121,37"', '{"west": -122}', '[]', '[-122, 36, -121]',
    '[-122, 36, -121, 37, 0]', '[true, 36, -121, 37]', '["-122", 36, -121, 37]',
    '[null, 36, -121, 37]', '[[-122], 36, -121, 37]', '[-122, 36, -121, {"n": 37}]',
    '[-122, 36, -121, false]'])
def test_invalid_shape_and_type_before_source_work(tmp_path, text):
    root, config = raw_scope_root(tmp_path, text)
    refused(root, config)


def test_absent_bounds_before_source_work(tmp_path):
    root, config = scope_root(tmp_path)
    document = json.loads(config.read_text())
    del document['bounds']
    config.write_text(json.dumps(document))
    refused(root, config)


@pytest.mark.parametrize('bounds', [
    [-122, 36, -122, 37], [-122, 36, -121, 36], [-122, 37, -121, 36],
    [-121, 36, -122, 37], [-180.0001, 0, 0, 1], [0, 0, 180.0001, 1],
    [0, -90.0001, 1, 1], [0, 0, 1, 90.0001], [180, 0, 180, 1],
    [10 ** 400, 0, 10 ** 400 + 1, 1], [-10 ** 400, 0, 1, 1], [0, 0, 1, 10 ** 400],
    [170, 0, -170, 1]])
def test_ordered_geographic_range_required(tmp_path, bounds):
    root, config = scope_root(tmp_path, bounds)
    refused(root, config)


@pytest.mark.parametrize('text', ['[-1e309, 36, -121, 37]', '[-122, 36, 1e309, 37]',
                                  '[-122, -1e309, -121, 37]', '[-122, 36, -121, 1e309]'])
def test_decoded_infinity_fails_closed(tmp_path, text):
    root, config = raw_scope_root(tmp_path, text)
    refused(root, config)


def test_injected_nan_fails_closed(tmp_path):
    root, config = scope_root(tmp_path)
    loaded, paths = resolve_scope(root, scope_config=config)
    for bounds in ([float('nan'), 36, -121, 37], [-122, 36, float('nan'), 37],
                   [-122, float('nan'), -121, 37], [-122, 36, -121, float('nan')]):
        injected = dict(loaded, bounds=bounds)
        with patch.object(scoped_grid, 'resolve_scope', return_value=(injected, paths)):
            refused(root, config)


def test_invalid_bounds_do_not_consume_or_replace_existing_artifacts(tmp_path):
    root, config = scope_root(tmp_path, SWAPPED)
    paths = resolve_scope(root, scope_config=config)[1]
    seeded = {paths.ledger_path: b'ledger sentinel', paths.reaches_path: b'reaches sentinel',
              paths.cells_path: b'cells sentinel', paths.build_receipt_path: b'receipt sentinel'}
    for path, data in seeded.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    before = tree(root)
    patches = fail_fast()
    for p in patches:
        p.start()
    try:
        with pytest.raises(ValueError, match=NAME):
            scoped_grid.build(root, scope_config=config)
    finally:
        for p in patches:
            p.stop()
    assert tree(root) == before
    assert {p: p.read_bytes() for p in seeded} == seeded


def test_fresh_root_gets_no_reference_directory_or_temp_file(tmp_path):
    root, config = scope_root(tmp_path, SWAPPED)
    refused(root, config)
    assert not list(root.rglob('*.tmp'))


class Projection:
    """Place every cell centre at a chosen lon/lat so half-open edges can be probed."""
    def __init__(self, lon, lat):
        self.lon, self.lat = lon, lat

    def transform(self, x, y):
        return np.full(np.shape(x), self.lon), np.full(np.shape(y), self.lat)


def build_with_cell_at(tmp_path, bounds, lon, lat):
    root, config = scope_root(tmp_path, bounds)
    spine = LineString([(0, 0), (1000, 0)])
    reaches = [{'id': 'demo-region-r01', 'region': 'demo-region', 'order': 1, 'start_m': 0,
                'end_m': 1000, 'length_m': 1000, 'bounds_3310': [0, 0, 1000, 0],
                'geometry': mapping(spine)}]
    with patch.object(reference, 'planning_spine', return_value=spine), \
         patch.object(scoped_grid, 'make_reaches', return_value=reaches), \
         patch.object(reference, 'scheme_tiles', return_value=({'scheme_sha256': 'f', 'scheme_url': 'f'}, [])), \
         patch.object(reference, 'samples', return_value=[]), \
         patch.object(scoped_grid, 'mosaic_reference',
                      return_value=(np.full((10, 10), 2, dtype='uint8'), Affine(25, 0, 0, 0, -25, 250))), \
         patch.object(scoped_grid, 'assign_reaches', return_value=np.array([0])), \
         patch.object(scoped_grid.Transformer, 'from_crs', return_value=Projection(lon, lat)), \
         patch.object(scoped_grid, 'sha256', return_value='fixture-hash'):
        ledger, unchanged = scoped_grid.build(root, scope_config=config)
    paths = resolve_scope(root, scope_config=config)[1]
    cells = json.loads(paths.cells_path.read_text())['cells']
    return root, ledger, unchanged, cells


@pytest.mark.parametrize('bounds', [[0, 0, 1, 1], VALID, [0, 0, 1.0, 1.0], [-180, -90, 180, 90]])
@pytest.mark.parametrize('place, kept', [
    ('west-south corner', True), ('east edge', False), ('north edge', False),
    ('interior', True), ('west edge, interior latitude', True), ('south edge, interior longitude', True)])
def test_valid_bounds_preserve_control_and_half_open_edges(tmp_path, bounds, place, kept):
    west, south, east, north = bounds
    mid_lon, mid_lat = (west + east) / 2, (south + north) / 2
    lon, lat = {'west-south corner': (west, south), 'east edge': (east, mid_lat),
                'north edge': (mid_lon, north), 'interior': (mid_lon, mid_lat),
                'west edge, interior latitude': (west, mid_lat),
                'south edge, interior longitude': (mid_lon, south)}[place]
    root, ledger, unchanged, cells = build_with_cell_at(tmp_path, bounds, lon, lat)
    assert not unchanged
    assert ledger['scope'] == 'offline-demo'
    assert ledger['stage'] == 'M1-reference-baseline'
    assert len(cells) == (1 if kept else 0)
    assert (root / 'var/seafloor/scopes/offline-demo/seafloor-ledger.json').is_file()
    assert not (root / 'var/seafloor/reference').exists()


def test_existing_explicit_config_requirement_is_unchanged(tmp_path):
    with pytest.raises(ValueError, match='requires an explicit scope config'):
        scoped_grid.build(tmp_path)


def test_central_config_is_refused_before_bounds_admission(tmp_path):
    (tmp_path / 'catalog').mkdir()
    document = json.loads(CENTRAL.read_text())
    document['bounds'] = SWAPPED
    (tmp_path / 'catalog/seafloor-scope.json').write_text(json.dumps(document))
    with pytest.raises(ValueError, match='retained central grid builder'):
        scoped_grid.build(tmp_path, scope_config='catalog/seafloor-scope.json')
