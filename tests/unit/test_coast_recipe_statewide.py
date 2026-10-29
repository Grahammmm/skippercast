"""OC-STATE: literal metadata oracle at a805ee9bc0a9fdc95fdc88afa8e71a513cc103a9.

Offline preparation only; validation never admits execution or source use.
"""
import json
import shutil
import socket

import pytest

from tests._support import ROOT
import validate_recipe as recipe

# Transcribed from region.json, independently of the generator and validator.
ROWS = {
    'big-sur-coast': ([-122.2, 35.9, -121.45, 36.3], ['noaa-bag'], 300),
    'monterey-point-sur': ([-122.35, 36.3, -121.65, 36.625], ['noaa-bag'], 300),
    'point-arguello-conception': ([-121.25, 34.45, -120.35, 35.07], ['noaa-bag'], 300),
    'santa-barbara-channel': ([-120.65, 34.0, -118.95, 34.45],
                             ['noaa-h13093', 'noaa-h13323', 'noaa-cinms-bathymetry-2025', 'noaa-bag'], 200),
    'channel-islands-north': ([-120.6, 33.85, -119.3, 34.15],
                             ['noaa-h13093', 'noaa-h13323', 'noaa-cinms-bathymetry-2025', 'noaa-bag'], 200),
    'santa-monica-palos-verdes': ([-119.0, 33.65, -118.25, 34.05], ['noaa-bag'], 200),
    'san-pedro-orange-county': ([-118.35, 33.35, -117.5, 33.8], ['noaa-bag'], 200),
    'san-diego': ([-117.6, 32.5343, -117.05, 33.4], ['noaa-bag'], 200),
    'outer-islands-borderland': ([-119.7, 32.75, -118.25, 33.6],
                                ['noaa-cinms-bathymetry-2025', 'noaa-bag'], 200),
    'point-reyes-pigeon': ([-123.3, 37.18333333333333, -122.28, 37.95], ['noaa-bag'], 200),
    'bodega-point-reyes': ([-123.7, 37.95, -122.7, 38.5], ['noaa-bag'], 200),
    'point-arena-bodega': ([-124.2, 38.4, -122.85, 39.0], ['noaa-bag'], 200),
    'fort-bragg-point-arena': ([-124.4, 38.958333333333336, -123.25, 39.45], ['noaa-bag'], 200),
    'shelter-cove-north-mendocino': ([-124.8, 39.45, -123.6, 40.166666666666664], ['noaa-bag'], 200),
    'humboldt-bay-cape-mendocino': ([-124.8, 40.166666666666664, -123.9, 40.95], ['noaa-bag'], 200),
    'trinidad-klamath': ([-124.6, 40.95, -124.0, 41.55], ['noaa-bag'], 200),
    'crescent-city': ([-124.75, 41.55, -124.05, 42.0], ['noaa-bag'], 200),
}
ALL_SLUGS = {
    'morro-bay', 'cambria-san-simeon', 'south-big-sur-san-simeon', 'santa-cruz-monterey-bay',
    'big-sur-coast', 'monterey-point-sur', 'point-arguello-conception',
    'santa-barbara-channel', 'channel-islands-north', 'santa-monica-palos-verdes',
    'san-pedro-orange-county', 'san-diego', 'outer-islands-borderland',
    'point-reyes-pigeon', 'bodega-point-reyes', 'point-arena-bodega', 'fort-bragg-point-arena',
    'shelter-cove-north-mendocino', 'humboldt-bay-cape-mendocino', 'trinidad-klamath', 'crescent-city',
}
STATUSES = {'noaa-bag': 'candidate', 'noaa-h13093': 'approved', 'noaa-h13323': 'approved',
            'noaa-cinms-bathymetry-2025': 'approved'}
DATUMS = {'noaa-bag': 'unknown', 'noaa-h13093': 'MLLW', 'noaa-h13323': 'MLLW',
          'noaa-cinms-bathymetry-2025': 'Unspecified merged hydrographic reference'}


def expected_document(slug, box, sources, depth):
    return {
        'schema_version': 1, 'slug': slug, 'bbox': box, 'depth_target_ft': depth,
        'sources': sources, 'source_review_status': {s: STATUSES[s] for s in sources},
        'datum_policy': {'mode': 'preserve-source-datum',
                         'vertical_datum_by_source': {s: DATUMS[s] for s in sources}},
        'output_root': 'runs/coast-recipes/' + slug,
        'cache_budget_bytes': 25_000_000_000, 'not_for_navigation': True,
    }


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refused(*args, **kwargs):
        raise AssertionError('network forbidden during statewide recipe acceptance')
    for attr in ('socket', 'create_connection', 'getaddrinfo'):
        monkeypatch.setattr(socket, attr, refused)


@pytest.mark.parametrize('slug', ROWS)
def test_new_recipe_matches_literal_metadata_without_execution(slug, tmp_path):
    document = json.loads((ROOT / 'regions' / slug / 'coast.json').read_text())
    assert document == expected_document(slug, *ROWS[slug])
    before = sorted(tmp_path.rglob('*'))
    assert recipe.validate_recipe(document, metadata_root=ROOT, workspace_root=tmp_path) == {
        'slug': slug, 'status': 'REVIEW REQUIRED', 'valid': True,
        'semantic_approval': False, 'execution_allowed': False, 'not_for_navigation': True,
    }
    assert sorted(tmp_path.rglob('*')) == before


def test_complete_statewide_coverage_exactly_once():
    paths = list((ROOT / 'regions').glob('*/coast.json'))
    slugs = [json.loads(p.read_text())['slug'] for p in paths]
    regions = [json.loads(p.read_text())['id'] for p in (ROOT / 'regions').glob('*/region.json')]
    assert len(ROWS) == 17 and len(ALL_SLUGS) == 21
    assert len(slugs) == len(set(slugs)) == 21
    assert len(regions) == len(set(regions)) == 22
    assert all(p.parent.name == slug for p, slug in zip(paths, slugs))
    assert set(slugs) == ALL_SLUGS == recipe.ADMITTED_SLUGS == set(regions) - {'southern-california'}


def test_umbrella_refused_by_admission_then_latitude_in_synthetic_copy(tmp_path, monkeypatch):
    slug = 'southern-california'
    # Same projection rules, but this umbrella is deliberately not a recipe.
    region = json.loads((ROOT / 'regions' / slug / 'region.json').read_text())
    document = expected_document(slug, region['bounds'], region['source_bindings']['bathymetry'],
                                 region['boat']['bottom_depth_limit_ft'])
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    with pytest.raises(recipe.RecipeError, match='unadmitted region slug'):
        recipe.validate_recipe(document, metadata_root=ROOT, workspace_root=workspace)
    metadata = tmp_path / 'metadata'
    for name in ('schemas/coast-recipe-v1.schema.json', 'catalog/sources.json',
                 'catalog/coastal-sectors.json', 'regions/' + slug + '/region.json'):
        target = metadata / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    monkeypatch.setattr(recipe, 'ADMITTED_SLUGS', recipe.ADMITTED_SLUGS | {slug})
    before = sorted(tmp_path.rglob('*'))
    with pytest.raises(recipe.RecipeError, match='outside supported CA discovery latitude coverage'):
        recipe.validate_recipe(document, metadata_root=metadata, workspace_root=workspace)
    assert sorted(tmp_path.rglob('*')) == before
    assert not list(workspace.iterdir())
