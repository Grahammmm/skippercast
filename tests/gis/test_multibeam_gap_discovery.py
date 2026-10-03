"""Gap acquisition must avoid already supported bottom and credit no new area."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

import pytest
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from research.scripts.discover_noaa_multibeam_footprints import (
    FIELDS, discover_gaps, gap_sectors,
)

pytestmark = pytest.mark.gis


def snapshot(folder, cells):
    payload = {'reach': 'test-reach', 'cells': cells}
    raw = json.dumps(payload).encode()
    (folder/'coverage-cells.json').write_bytes(raw)
    (folder/'coverage-checkpoint.json').write_text(json.dumps({
        'cells_sha256': hashlib.sha256(raw).hexdigest(), 'physical_input_hash': 'a'*64,
    }))


def cell(x, y, valid=0, band=62500):
    return {'id': f'3310:{x}:{y}', 'reach': 'test-reach', 'tier': int(valid >= 15625),
            'band_area_m2': band, 'valid_area_m2': valid,
            'source_id': 'known' if valid else 'unknown',
            'available_source_ids': ['known'] if valid else []}


def fake_fetch(url):
    args = parse_qs(urlsplit(url).query)
    if urlsplit(url).path.endswith('/0'):
        return {'geometryType': 'esriGeometryPolygon', 'maxRecordCount': 2000,
                'fields': [{'name': name} for name in FIELDS.split(',')]}, 'b'*64
    if 'returnCountOnly' in args:
        return {'count': 1}, 'c'*64
    return {'features': [{'attributes': {'OBJECTID': 1, 'DOWNLOAD_URL': 'https://www.ncei.noaa.gov/'}}]}, 'd'*64


def test_queries_exact_zero_support_cells_and_excludes_partial_support():
    with TemporaryDirectory() as temp:
        folder = Path(temp)
        snapshot(folder, [cell(-270, -1420), cell(-269, -1420, 10), cell(-270, -1419, 62500)])
        groups, receipt = gap_sectors(folder)
        assert len(groups) == 1
        assert receipt['partial_support_cells_excluded'] == 1
        ring = groups[0]['query_geometry']['rings'][0]
        assert Polygon(ring).area == 62500
        assert Polygon(ring).contains(Point(-270*250+125, -1420*250+125))
        assert not Polygon(ring).covers(Point(-269*250+125, -1420*250+125))
        calls = []
        def fetch(url):
            calls.append(url)
            return fake_fetch(url)
        result = discover_gaps(folder, fetch)
        args = parse_qs(urlsplit(calls[1]).query)
        assert args['geometryType'] == ['esriGeometryPolygon']
        assert args['inSR'] == ['3310']
        assert result['new_measured_km2'] == 0
        assert not result['fishing_target'] and not result['exportable']


def test_owned_batch_edges_never_lose_or_duplicate_cells():
    with TemporaryDirectory() as temp:
        folder = Path(temp)
        snapshot(folder, [cell(-270+i, -1420) for i in range(5)])
        groups, _ = gap_sectors(folder, max_cells=2)
        ids = [ident for group in groups for ident in group['planning_cell_ids']]
        assert len(ids) == len(set(ids)) == 5
        polygons = [Polygon(group['query_geometry']['rings'][0]) for group in groups]
        assert unary_union(polygons).area == 5*62500
        result = discover_gaps(folder, fake_fetch, max_cells=2, max_groups=2)
        assert result['queried_group_count'] == 2 and result['remaining_group_count'] == 1
        resume = folder/'resume.json'; resume.write_text(json.dumps(result))
        follow = discover_gaps(folder, fake_fetch, max_cells=2, max_groups=2, resume_from=resume)
        assert follow['remaining_group_count'] == 0
        assert follow['sectors'][0]['planning_cell_ids'] == groups[2]['planning_cell_ids']
        assert not set(follow['sectors'][0]['planning_cell_ids']) & set(result['sectors'][0]['planning_cell_ids'])
        assert result['unique_footprint_object_ids'] == 1  # Duplicate surveys are not extra evidence.


def test_no_gap_has_no_network_or_area_credit():
    with TemporaryDirectory() as temp:
        folder = Path(temp)
        snapshot(folder, [cell(-270, -1420, 62500), cell(-269, -1420, band=0)])
        result = discover_gaps(folder, lambda url: pytest.fail('No gap needs no request'))
        assert result['queried_group_count'] == 0
        assert result['new_measured_km2'] == 0


def test_corrupt_checkpoint_fails_before_request():
    with TemporaryDirectory() as temp:
        folder = Path(temp)
        snapshot(folder, [cell(-270, -1420)])
        (folder/'coverage-cells.json').write_text('{}')
        with pytest.raises(ValueError, match='hash mismatch'):
            discover_gaps(folder, lambda url: pytest.fail('Invalid cache must not query'))


@pytest.mark.parametrize('change', [
    {'valid_area_m2': float('nan')}, {'valid_area_m2': -1}, {'band_area_m2': 62501},
    {'source_id': 'known'}, {'available_source_ids': ['known']}, {'reach': 'other'},
    {'id': '3310:1.5:2'}, {'id': '3310:-0270:-1420'},
])
def test_invalid_or_contradictory_cells_are_not_gap_evidence(change):
    with TemporaryDirectory() as temp:
        folder = Path(temp)
        item = cell(-270, -1420); item.update(change); snapshot(folder, [item])
        with pytest.raises(ValueError):
            gap_sectors(folder)


def test_duplicate_cells_fail_and_holes_keep_esri_orientation():
    with TemporaryDirectory() as temp:
        folder = Path(temp)
        snapshot(folder, [cell(-270, -1420), cell(-270, -1420)])
        with pytest.raises(ValueError, match='duplicate'):
            gap_sectors(folder)
        cells = [cell(x, y) for x in range(-272, -269) for y in range(-1422, -1419)
                 if (x,y) != (-271,-1421)]
        snapshot(folder, cells)
        groups, _ = gap_sectors(folder)
        outer, hole = groups[0]['query_geometry']['rings']
        assert not Polygon(outer).exterior.is_ccw and Polygon(hole).exterior.is_ccw
        assert Polygon(outer, [hole]).area == 8*62500


@pytest.mark.parametrize('value', [0, 257, True, 1.5])
def test_invalid_batch_bounds(value):
    with pytest.raises(ValueError, match='1–256'):
        gap_sectors(Path('never-read'), value)


def test_resume_requires_identical_checkpoint_and_batch_size():
    with TemporaryDirectory() as temp:
        folder = Path(temp)
        snapshot(folder, [cell(-270+i, -1420) for i in range(3)])
        result = discover_gaps(folder, fake_fetch, max_cells=1, max_groups=1)
        resume = folder/'resume.json'; resume.write_text(json.dumps(result))
        with pytest.raises(ValueError, match='requires a checked'):
            discover_gaps(folder, fake_fetch, start_group=1)
        with pytest.raises(ValueError, match='differs'):
            discover_gaps(folder, fake_fetch, max_cells=2, resume_from=resume)
        snapshot(folder, [cell(-270, -1420)])
        with pytest.raises(ValueError, match='differs'):
            discover_gaps(folder, fake_fetch, max_cells=1, resume_from=resume)


def test_missing_identity_is_not_a_verified_snapshot():
    with TemporaryDirectory() as temp:
        folder = Path(temp); snapshot(folder, [cell(-270, -1420)])
        path = folder/'coverage-checkpoint.json'; data = json.loads(path.read_text())
        data.pop('physical_input_hash'); path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match='physical input identity'):
            gap_sectors(folder)


def test_large_polygon_uses_post_instead_of_exceeding_url_limits(monkeypatch):
    from research.scripts import discover_noaa_multibeam_footprints as module
    from io import BytesIO
    seen = []
    def opened(request, timeout):
        seen.append(request)
        return BytesIO(b'{}')
    monkeypatch.setattr(module, 'urlopen', opened)
    module.fetch_json(module.LAYER + '/query?geometry=' + 'x'*7000)
    assert seen[0].get_method() == 'POST'
    assert seen[0].full_url == module.LAYER + '/query'
    assert seen[0].data.startswith(b'geometry=')
    module.fetch_json(module.LAYER + '?f=json')
    assert isinstance(seen[1], str)
