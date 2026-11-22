"""Offline recipe-to-footprint controls; no source data is needed."""

import json
import shutil

import pytest

from scripts.relief import north_preview_source_fit as fit
from tests._support import ROOT


REGIONS = (
    'point-reyes-pigeon',
    'bodega-point-reyes',
    'point-arena-bodega',
    'fort-bragg-point-arena',
    'shelter-cove-north-mendocino',
    'humboldt-bay-cape-mendocino',
    'trinidad-klamath',
    'crescent-city',
)


@pytest.fixture
def recipe_root(tmp_path, monkeypatch):
    # Keep the real loader, using only the two tracked anchors and synthetic
    # recipes for the other releases; the loader still checks schema and style.
    monkeypatch.setenv('SKIPPERCAST_ROOT', str(tmp_path))
    for name in ('schemas/sc-render-v1.schema.json', 'style/index.json'):
        dest = tmp_path / name
        dest.parent.mkdir()
        shutil.copyfile(ROOT / name, dest)
    for region in REGIONS:
        recipe = tmp_path / 'regions' / region / 'render.json'
        recipe.parent.mkdir(parents=True)
        if region in {'point-arena-bodega', 'crescent-city'}:
            shutil.copyfile(ROOT / recipe.relative_to(tmp_path), recipe)
        else:
            recipe.write_text(json.dumps({
                'schema': 'sc-render/1', 'region': region, 'piers': [],
                'previews': [{'id': 'fixture-z13', 'center': [-124, 40], 'size_m': 4000, 'zoom': 13}],
            }), encoding='utf-8')
    return tmp_path


def test_cli_reports_inside_and_hole_within_same_bbox_and_keeps_unavailable(recipe_root, capsys):
    # Both anchor centers are strictly within this one shell's bbox. Testing
    # only the bbox (or dropping the inner ring) would mislabel Bodega as inside.
    fixture = recipe_root / 'footprints.json'
    fixture.write_text(json.dumps({'point-arena-bodega': {
        'type': 'Polygon',
        'coordinates': [
            [[-124, 38], [-123, 38], [-123, 39], [-124, 39], [-124, 38]],
            [[-123.10, 38.30], [-123.10, 38.37], [-123.01, 38.37], [-123.01, 38.30], [-123.10, 38.30]],
        ],
    }}), encoding='utf-8')
    assert fit.main([str(fixture)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert 'not evidence of measured support' in report['scope']
    # Iterating only supplied footprints would silently omit seven regions;
    # treating missing geometry as an empty polygon would report false negatives.
    unavailable = [{'id': 'fixture-z13', 'center': [-124, 40], 'status': 'unavailable'}]
    expected = dict.fromkeys(REGIONS, unavailable)
    expected['point-arena-bodega'] = [
        {'id': 'bodega-harbor-distant-planning-origin-z13', 'center': [-123.05, 38.33], 'status': 'outside'},
        {'id': 'arena-nearshore-z15', 'center': [-123.78, 38.84], 'status': 'inside'},
    ]
    expected['crescent-city'] = [
        {'id': 'crescent-city-harbor-z13', 'center': [-124.185, 41.744], 'status': 'unavailable'},
        {'id': 'crescent-south-z15', 'center': [-124.26, 41.7], 'status': 'unavailable'},
    ]
    assert report['regions'] == expected


def test_refuses_invalid_polygon_instead_of_reporting_outside():
    # A self-crossing ring can produce a false negative rather than an error
    # from a point predicate, making malformed geometry look like a valid miss.
    with pytest.raises(ValueError, match='point-arena-bodega: invalid synthetic footprint'):
        fit.source_fit({'point-arena-bodega': {
            'type': 'Polygon',
            'coordinates': [[[-124, 38], [-123, 39], [-124, 39], [-123, 38], [-124, 38]]],
        }})
