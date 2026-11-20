"""F10-01: scientific approval is not permission to publish depth contours."""
import json

import pytest

from skippercast.platform import depth_contours as dc
from skippercast.platform.contracts import load_catalogs

SOURCE = 'synthetic-survey'
REGION = {'id': 'synthetic-bay', 'bounds': [0, 0, 1, 1],
          'source_bindings': {'bathymetry': [SOURCE]}}
OUTPUT_NAMES = ('depth-contours.geojson', 'depth-contours-overview.geojson')


@pytest.fixture
def contour_import(tmp_path):
    catalog = tmp_path / 'catalog'
    directory = catalog / 'depth-contours'
    directory.mkdir(parents=True)
    survey = {'source_id': SOURCE, 'survey_date': '2020', 'vertical_datum': 'synthetic datum'}
    collection = {
        'type': 'FeatureCollection', 'schema_version': 1,
        'provenance': {'region_id': REGION['id'], 'bounds': REGION['bounds'], 'features': 1,
                       'units': 'ft', 'interval_ft': 30, 'shelf_limit_ft': 600,
                       'sources': [{**survey, 'sha256': 'a' * 64}]},
        'features': [{'type': 'Feature', 'id': 'synthetic-30ft',
                      'properties': {**survey, 'kind': 'contour', 'depth_ft': 30, 'index': False},
                      'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [1, 1]]}}],
    }
    (catalog / 'data-needs.json').write_text(json.dumps({'schema_version': 1, 'needs': [{'id': 'bathymetry'}]}))
    return directory / 'synthetic-bay.geojson', collection


def _sources(root, *, display=None, **decision):
    rights = {'license': 'public-domain', 'commercial_use': 'allowed', 'attribution_required': True,
              'attribution': 'Synthetic survey', 'terms_url': 'https://example.org/terms'}
    if display is not None:
        rights['public_display'] = display
    row = {'id': SOURCE, 'documentation_url': 'https://example.org/survey', 'rights': rights,
           'needs': ['bathymetry'], 'review_status': 'approved', 'reviewed_at': '2026-01-01', **decision}
    (root / 'catalog/sources.json').write_text(json.dumps({'schema_version': 1, 'sources': [row]}))
    return load_catalogs(root)[1]


@pytest.mark.parametrize('decision', [
    pytest.param({'publication_allowed': False}, id='publication-false'),
    pytest.param({'display': 'private'}, id='display-private'),
    pytest.param({'display': 'excluded'}, id='display-excluded'),
])
def test_contour_publication_denies_each_explicit_decision(tmp_path, contour_import, decision):
    path, collection = contour_import
    path.write_text(json.dumps(collection))
    sources = _sources(tmp_path, **decision)
    fresh, previous = tmp_path / 'fresh', tmp_path / 'previous'
    previous.mkdir()
    old = {name: f'previous {name}'.encode() for name in OUTPUT_NAMES}
    for name, content in old.items():
        (previous / name).write_bytes(content)

    for output in (fresh, previous):
        with pytest.raises(ValueError, match=f'{SOURCE}.*not cleared for public display'):
            dc.publish_depth_contours(tmp_path, REGION, output, sources)
    assert not fresh.exists()
    assert {p.name: p.read_bytes() for p in previous.iterdir()} == old


@pytest.mark.parametrize('display', ['allowed', None], ids=['explicitly-allowed', 'legacy'])
def test_contour_publication_keeps_allowed_and_legacy_sources(tmp_path, contour_import, display):
    path, collection = contour_import
    path.write_text(json.dumps(collection))
    sources = _sources(tmp_path, display=display)
    out = tmp_path / 'public'

    assert dc.publish_depth_contours(tmp_path, REGION, out, sources) == tuple(
        f'regions/synthetic-bay/{name}' for name in OUTPUT_NAMES)
    for name in OUTPUT_NAMES:
        written = json.loads((out / name).read_text())
        assert [f['properties'] for f in written['features']] == [collection['features'][0]['properties']]


def test_private_review_still_accepts_held_contours_without_public_writes(tmp_path, contour_import):
    path, collection = contour_import
    collection['provenance'].update(publication_held=True, held_sources=[])
    path.write_text(json.dumps(collection))
    sources = _sources(tmp_path, display='private')
    out = tmp_path / 'public'

    dc.check_held_contours(collection, REGION, sources)
    with pytest.raises(ValueError, match='held and cannot be published'):
        dc.publish_depth_contours(tmp_path, REGION, out, sources)
    assert not out.exists()
