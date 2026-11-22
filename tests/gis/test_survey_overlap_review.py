"""Exercise the seam selector on saved, synthetic survey-detail files."""

import json
import subprocess
import sys

import pytest
from pyproj import Transformer
from shapely import transform
from shapely.geometry import MultiPolygon, Polygon, box, mapping

from scripts.relief.survey_overlap_review import review
from tests._support import ROOT


def _feature(geometry, tier, grid=2):
    return {
        'type': 'Feature',
        'geometry': geometry,
        'properties': {'tier': tier, 'sources': []} if tier == 'none' else {
            'tier': tier, 'grid_m': grid, 'source': 'Fixture survey', 'sources': ['fixture-survey'],
        },
    }


def _detail(tmp_path, region, *features):
    path = tmp_path / f'{region}.geojson'
    path.write_text(json.dumps({
        'type': 'FeatureCollection', 'region': region, 'navigation': 'NOT FOR NAVIGATION',
        'features': features,
    }), encoding='utf-8')
    return path


def test_shared_edge_with_different_vertex_counts_is_not_an_overlap(tmp_path):
    # Independent projection of differently segmented edges can manufacture a sliver.
    south = box(-120.1, 36.9, -119.9, 37)
    north = Polygon([(-120.1, 37), (-120, 37), (-119.9, 37),
                     (-119.9, 37.1), (-120.1, 37.1)])
    a = _detail(tmp_path, 'fixture-south', _feature(mapping(south), '2m'))
    b = _detail(tmp_path, 'fixture-north', _feature(mapping(north), 'estimated'))

    report = review([a, b])

    assert report['status'] == 'complete'
    assert report['disagreements'] == []


def test_overlap_retains_hole_and_reports_square_metres_by_region_and_tier(tmp_path):
    # Known metre dimensions detect degree-area, envelope/filled-hole, and
    # grid-based relabelling errors, even though both nominal grids are 2 m.
    shell = box(0, 0, 1000, 1000)
    hole = box(250, 250, 750, 750)
    to_lonlat = Transformer.from_crs('EPSG:3310', 'EPSG:4326', always_xy=True).transform
    with_hole = Polygon(shell.exterior.coords, [hole.exterior.coords])
    islands = MultiPolygon([shell, box(2000, 0, 3000, 1000)])
    a = _detail(tmp_path, 'fixture-alpha',
                _feature(mapping(transform(with_hole, to_lonlat, interleaved=False)), '2m'))
    b = _detail(tmp_path, 'fixture-beta',
                _feature(mapping(transform(islands, to_lonlat, interleaved=False)), 'estimated'))

    report = review([b, a])

    assert report['status'] == 'complete'
    assert report['area_crs'] == 'EPSG:3310'
    assert report['disagreements'] == [{
        'regions': ['fixture-alpha', 'fixture-beta'], 'tiers': ['2m', 'estimated'],
        'area_m2': pytest.approx(750_000, abs=0.01),
    }]


def test_equal_tiers_do_not_disagree_even_with_different_grids(tmp_path):
    # A comparison of nominal grid size or all intersections would report this pair.
    geometry = mapping(box(-120.1, 37, -120, 37.1))
    a = _detail(tmp_path, 'fixture-alpha', _feature(geometry, 'estimated', grid=4))
    b = _detail(tmp_path, 'fixture-beta', _feature(geometry, 'estimated', grid=8))

    report = review([a, b])

    assert report['status'] == 'complete'
    assert report['disagreements'] == []


def test_group_counts_duplicate_support_once_and_keeps_explicit_none(tmp_path):
    # Summing raw pairwise matches would double the explicit none/5m area;
    # discarding none or merging every differing pair would lose a group.
    shell = box(0, 0, 1000, 1000)
    inner = box(250, 250, 750, 750)
    project = Transformer.from_crs('EPSG:3310', 'EPSG:4326', always_xy=True).transform
    geometry = mapping(transform(shell, project, interleaved=False))
    explicit_none = _feature(geometry, 'none')
    a = _detail(tmp_path, 'fixture-alpha', explicit_none, explicit_none,
                _feature(mapping(transform(inner, project, interleaved=False)), '2m'))
    b = _detail(tmp_path, 'fixture-beta', _feature(geometry, '5m'))

    report = review([a, b])

    assert report['status'] == 'complete'
    groups = [(row['tiers'], row['area_m2']) for row in report['disagreements']]
    assert [tiers for tiers, _ in groups] == [['2m', '5m'], ['none', '5m']]
    assert groups[1][1] == pytest.approx(1_000_000, abs=0.01)
    assert groups[0][1] == pytest.approx(250_000, abs=0.01)


@pytest.mark.parametrize('coordinates', [
    [[[-120, 37], [-119.9, 37], [-119.9, 37.1], [-120, 37.1]]],
    [[[-120, 37], [-119.9, 37.1], [-119.9, 37], [-120, 37.1], [-120, 37]]],
], ids=['unclosed-ring', 'self-intersection'])
def test_malformed_geometry_makes_the_report_incomplete(tmp_path, coordinates):
    # GEOS can close a ring on read; skipping/repairing either bad geometry
    # would hide incomplete evidence, even when other features could disagree.
    geometry = mapping(box(-120, 37, -119.9, 37.1))
    bad = {'type': 'Polygon', 'coordinates': coordinates}
    a = _detail(tmp_path, 'fixture-alpha', _feature(geometry, '2m'), _feature(bad, 'none'))
    b = _detail(tmp_path, 'fixture-beta', _feature(geometry, 'estimated'))
    cli = ROOT / 'scripts' / 'relief' / 'survey_overlap_review.py'

    run = subprocess.run([sys.executable, str(cli), str(a), str(b)], cwd=tmp_path,
                         capture_output=True, text=True, timeout=15)

    assert run.returncode == 1, run.stderr
    report = json.loads(run.stdout)
    assert report['status'] == 'incomplete'
    assert report['disagreements'] == []
    assert report['issue'].startswith('input 1: feature 1: invalid polygon')


def test_grid_tier_is_not_a_substitute_for_missing_tier(tmp_path):
    # A compiled grid-family tag is not a confidence label or unsurveyed evidence.
    geometry = mapping(box(-120.1, 37, -120, 37.1))
    missing = _feature(geometry, 'estimated', grid=8)
    del missing['properties']['tier']
    missing['properties']['grid_tier'] = '4-16m-compiled'
    a = _detail(tmp_path, 'fixture-alpha', missing)
    b = _detail(tmp_path, 'fixture-beta', _feature(geometry, '5m'))

    report = review([a, b])

    assert report['status'] == 'incomplete'
    assert report['disagreements'] == []
    assert 'properties.tier' in report['issue']


def test_single_region_is_incomplete_not_a_zero_disagreement_comparison(tmp_path):
    # Absent peer data must not become an empty synthetic second survey.
    geometry = mapping(box(-120.1, 37, -120, 37.1))
    a = _detail(tmp_path, 'fixture-alpha', _feature(geometry, '2m'))

    report = review([a])

    assert report['status'] == 'incomplete'
    assert report['regions'] == ['fixture-alpha']
    assert report['disagreements'] == []


def test_third_input_is_rejected_before_any_read(tmp_path):
    # Silent truncation would return a comparison that omits a requested input.
    paths = [tmp_path / f'fixture-{index}.geojson' for index in range(3)]
    with pytest.raises(ValueError, match='one or two'):
        review(paths)
