"""Offline controls for the North seam planning report."""

import json

import pytest

from scripts.relief import north_seam_windows as seams
from tests._support import ROOT


def test_checked_in_north_roster_has_seven_ordered_geographic_joins(capsys):
    """Alphabetic sorting, skipping contacts, or emitting unions changes the report."""
    seams.main(['--root', str(ROOT)])
    first = capsys.readouterr().out
    seams.main(['--root', str(ROOT)])
    assert capsys.readouterr().out == first

    report = json.loads(first)
    assert report['crs'] == 'WGS84'
    assert report['bounds_order'] == ['west', 'south', 'east', 'north']
    assert 'QA planning bounds only' in report['purpose']
    assert [
        (*row['regions'], row['status'], row['candidate_window']) for row in report['joins']
    ] == [
        ('point-reyes-pigeon', 'bodega-point-reyes', 'edge_contact', None),
        ('bodega-point-reyes', 'point-arena-bodega', 'overlap', [-123.7, 38.4, -122.85, 38.5]),
        ('point-arena-bodega', 'fort-bragg-point-arena', 'overlap',
         [-124.2, 38.958333333333336, -123.25, 39.0]),
        ('fort-bragg-point-arena', 'shelter-cove-north-mendocino', 'edge_contact', None),
        ('shelter-cove-north-mendocino', 'humboldt-bay-cape-mendocino', 'edge_contact', None),
        ('humboldt-bay-cape-mendocino', 'trinidad-klamath', 'edge_contact', None),
        ('trinidad-klamath', 'crescent-city', 'edge_contact', None),
    ]


def _write_configs(root, second):
    base = [-124, 38, -123, 40]
    for idx, region in reversed(list(enumerate(seams.NORTH_RELEASES))):
        path = root / 'regions' / region / 'region.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            'bounds': second if idx == 1 else base,
            # Alternate footprints must not mask a gap in the release rectangles.
            'fishing_bounds': base,
        }), encoding='utf-8')


@pytest.mark.parametrize(('second', 'status', 'window'), [
    pytest.param([-124.5, 39, -123.5, 41], 'overlap', (-124, 39, -123.5, 40), id='both-axes'),
    pytest.param([-123, 39, -122, 41], 'edge_contact', None, id='longitude-edge'),
    pytest.param([-123, 40, -122, 41], 'point_contact', None, id='corner-only'),
    pytest.param([-122.9, 39, -122, 41], 'gap', None, id='longitude-gap-latitude-overlap'),
    pytest.param([-124.5, 40.1, -123.5, 41], 'gap', None, id='latitude-gap-longitude-overlap'),
    pytest.param([-122.9, 40, -122, 41], 'gap', None, id='gap-wins-over-edge-on-other-axis'),
])
def test_window_requires_positive_width_and_height(tmp_path, second, status, window):
    """A latitude-only sweep, closed-box overlap or touch-before-gap logic mislabels a join."""
    _write_configs(tmp_path, second)
    assert seams.plan_windows(tmp_path)[0] == {
        'regions': ('point-reyes-pigeon', 'bodega-point-reyes'),
        'status': status,
        'candidate_window': window,
    }


def test_invalid_rectangle_is_not_reported_as_a_geographic_gap(tmp_path):
    """An inverted config must fail reading rather than manufacture a gap."""
    _write_configs(tmp_path, [-123, 39, -124, 41])
    with pytest.raises(ValueError, match='bodega-point-reyes: invalid WGS84 release rectangle'):
        seams.plan_windows(tmp_path)
