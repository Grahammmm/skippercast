"""Shelf depth contours (CI6-13): the tracer, the check, the overview and the publish step, offline."""
import json

import pytest

from skippercast.platform import depth_contours as dc
from tests._support import ROOT

REGION = {'id': 'test-bay', 'bounds': [-121.2, 35.0, -120.7, 35.6],
          'source_bindings': {'bathymetry': ['survey-a', 'survey-b']}}
SOURCES = {
    'survey-a': {'review_status': 'approved', 'needs': ['bathymetry'], 'reviewed_at': '2026-09-26T00:00:00Z'},
    'survey-b': {'review_status': 'approved', 'needs': ['bathymetry'], 'reviewed_at': '2026-10-01'},
    'survey-c': {'review_status': 'candidate', 'needs': ['bathymetry'], 'reviewed_at': '2026-10-01'},
}
SHA = 'a' * 64


def collection(features=None, sources=('survey-a',)):
    features = features if features is not None else [
        {'type': 'Feature', 'id': 'survey-a-30ft', 'geometry': {'type': 'MultiLineString', 'coordinates': [[[-121.0, 35.2], [-120.95, 35.25], [-120.9, 35.3]]]},
         'properties': {'kind': 'contour', 'depth_ft': 30, 'index': False, 'source_id': 'survey-a', 'survey_date': '2008', 'vertical_datum': dc.UNVERIFIED_DATUM}},
        {'type': 'Feature', 'id': 'survey-a-150ft', 'geometry': {'type': 'LineString', 'coordinates': [[-121.1, 35.2], [-121.05, 35.3]]},
         'properties': {'kind': 'contour', 'depth_ft': 150, 'index': True, 'source_id': 'survey-a', 'survey_date': '2008', 'vertical_datum': dc.UNVERIFIED_DATUM}},
        {'type': 'Feature', 'id': 'survey-a-edge', 'geometry': {'type': 'MultiLineString', 'coordinates': [[[-121.15, 35.1], [-121.15, 35.5]]]},
         'properties': {'kind': 'survey-edge', 'source_id': 'survey-a', 'survey_date': '2008', 'vertical_datum': dc.UNVERIFIED_DATUM}},
    ]
    return {'type': 'FeatureCollection', 'schema_version': dc.SCHEMA_VERSION, 'features': features, 'provenance': {
        'region_id': 'test-bay', 'units': 'ft', 'interval_ft': dc.INTERVAL_FT, 'index_ft': dc.INDEX_FT, 'shelf_limit_ft': dc.SHELF_LIMIT_FT,
        'bounds': REGION['bounds'], 'features': len(features),
        'sources': [{'source_id': s, 'sha256': SHA, 'survey_date': '2008', 'vertical_datum': dc.UNVERIFIED_DATUM} for s in sources]}}


def test_levels_are_interval_multiples_on_the_shelf():
    assert dc.levels(0, 100) == [30, 60, 90]
    assert dc.levels(31, 61) == [60]
    assert dc.levels(550, 900) == [570, 600], 'never past the shelf limit'
    assert dc.levels(0, 20) == []


def test_trace_a_slope_gives_one_straight_line_per_depth():
    # Depth rises 10 ft per column: the 30 ft line crosses each row halfway between columns 2 and 4.
    grid = [[c * 10 + 5 for c in range(8)] for _ in range(4)]
    lines = dc.trace(grid, [30, 60])
    assert len(lines[30]) == 1 and len(lines[60]) == 1
    xs = {round(x, 6) for x, _ in lines[30][0]}
    assert xs == {2.5}, 'linear interpolation along the edge'
    assert sorted(y for _, y in lines[30][0]) == [0, 1, 2, 3], 'the line spans every row'


def test_trace_stops_at_a_gap_and_never_bridges_it():
    grid = [[c * 10 + 5 for c in range(8)] for _ in range(5)]
    grid[2] = [None] * 8
    lines = dc.trace(grid, [30])[30]
    assert len(lines) == 2, 'one line above the gap row, one below'
    for line in lines:
        ys = [y for _, y in line]
        assert not (min(ys) < 2 < max(ys)), 'no line runs through the missing row'
        assert 2 not in ys


def test_trace_a_pit_is_a_closed_ring_and_a_saddle_splits_by_the_mean():
    pit = [[0, 0, 0], [0, 50, 0], [0, 0, 0]]
    ring = dc.trace(pit, [30])[30]
    assert len(ring) == 1 and ring[0][0] == ring[0][-1] and len(ring[0]) == 5
    # Opposite corners deep: mean 40 >= 30, so the deep corners join through the centre and two lines cut off the shallow ones.
    saddle = [[50, 10], [10, 70]]
    lines = dc.trace(saddle, [30])[30]
    assert len(lines) == 2 and all(len(line) == 2 for line in lines)


def test_check_accepts_a_complete_contour_set():
    dc.check_contours(collection(), REGION, SOURCES)


@pytest.mark.parametrize('edit, message', [
    (lambda c: c['provenance'].update(region_id='other'), 'not its FeatureCollection'),
    (lambda c: c['provenance'].update(units='m'), 'feet'),
    (lambda c: c['provenance'].update(interval_ft=20), 'incomplete provenance'),
    (lambda c: c['provenance'].update(features=99), 'incomplete provenance'),
    (lambda c: c['provenance']['sources'][0].update(sha256='nope'), 'grid hash'),
    (lambda c: c['provenance']['sources'][0].update(vertical_datum=''), 'datum'),
    (lambda c: c['features'][0]['properties'].update(vertical_datum='MLLW'), 'survey date or datum'),
    (lambda c: c['features'][0]['properties'].update(survey_date='2019'), 'survey date or datum'),
    (lambda c: c['features'][0]['properties'].update(depth_ft=45), 'shelf contour'),
    (lambda c: c['features'][0]['properties'].update(depth_ft=630), 'shelf contour'),
    (lambda c: c['features'][1]['properties'].update(index=False), 'shelf contour'),
    (lambda c: c['features'][0]['properties'].update(kind='sounding'), 'unlisted source'),
    (lambda c: c['features'][0].update(geometry={'type': 'LineString', 'coordinates': [[-122.0, 35.2], [-121.0, 35.2]]}), 'inside'),
])
def test_check_rejects_gaps(edit, message):
    c = collection()
    edit(c)
    with pytest.raises(ValueError, match=message):
        dc.check_contours(c, REGION, SOURCES)


def test_check_rejects_a_source_that_is_not_an_approved_binding():
    with pytest.raises(ValueError, match='approved bathymetry binding'):
        dc.check_contours(collection(sources=('survey-a', 'survey-c')), REGION, SOURCES)
    unbound = {**REGION, 'source_bindings': {'bathymetry': ['survey-b']}}
    with pytest.raises(ValueError, match='approved bathymetry binding'):
        dc.check_contours(collection(), unbound, SOURCES)


def test_review_expires_is_a_year_after_the_oldest_review():
    c = collection(sources=('survey-a', 'survey-b'))
    assert dc.review_expires(c, SOURCES) == '2027-09-26'
    with pytest.raises(ValueError, match='no review date'):
        dc.review_expires(c, {**SOURCES, 'survey-a': {}})


def test_overview_drops_short_lines_and_keeps_properties():
    c = collection()
    light = dc.overview_contours(c)
    ids = [f['id'] for f in light['features']]
    assert 'survey-a-30ft' in ids and 'survey-a-edge' in ids
    assert light['provenance']['overview']['max_zoom'] == dc.OVERVIEW_MAX_ZOOM
    assert light['provenance']['features'] == len(light['features'])
    for f in light['features']:
        assert f['properties'] == next(g for g in c['features'] if g['id'] == f['id'])['properties']
    stub = collection(features=[{**c['features'][0], 'geometry': {'type': 'LineString', 'coordinates': [[-121.0, 35.2], [-121.0001, 35.2001]]}}])
    assert dc.overview_contours(stub)['features'] == [], 'a stub shorter than the minimum span is left out'


def test_publish_writes_both_forms_with_the_age_limit_and_enforces_the_budget(tmp_path, monkeypatch):
    root, out = tmp_path / 'root', tmp_path / 'out'
    (root / 'catalog/depth-contours').mkdir(parents=True)
    out.mkdir()
    assert dc.publish_depth_contours(root, REGION, out, SOURCES) is None, 'no import: nothing published'
    (root / 'catalog/depth-contours/test-bay.geojson').write_text(json.dumps(collection()))
    paths = dc.publish_depth_contours(root, REGION, out, SOURCES)
    assert paths == ('regions/test-bay/depth-contours.geojson', 'regions/test-bay/depth-contours-overview.geojson')
    full = json.loads((out / 'depth-contours.geojson').read_text())
    assert full['provenance']['review_expires'] == '2027-09-26' and full['provenance']['review_days'] == 365
    assert json.loads((out / 'depth-contours-overview.geojson').read_text())['provenance']['review_expires'] == '2027-09-26'
    monkeypatch.setattr(dc, 'MAX_BYTES', 100)
    with pytest.raises(ValueError, match='over its 100-byte budget'):
        dc.publish_depth_contours(root, REGION, out, SOURCES)
    assert not (out / 'depth-contours.geojson').exists(), 'an over-budget form is not left behind'
    (root / 'catalog/depth-contours/test-bay.geojson').unlink()
    (out / 'depth-contours.geojson').write_text('{}')
    assert dc.publish_depth_contours(root, REGION, out, SOURCES) is None
    assert not (out / 'depth-contours.geojson').exists() and not (out / 'depth-contours-overview.geojson').exists(), 'stale copies removed'


def test_the_committed_morro_bay_publication_is_within_budget_and_says_its_datum():
    root = ROOT
    for name, budget in (('depth-contours.geojson', dc.MAX_BYTES), ('depth-contours-overview.geojson', dc.OVERVIEW_MAX_BYTES)):
        path = root / 'dist/regions/morro-bay' / name
        assert path.stat().st_size <= budget, name
        data = json.loads(path.read_text())
        assert data['provenance']['units'] == 'ft' and data['provenance']['interval_ft'] == dc.INTERVAL_FT
        assert {f['properties']['vertical_datum'] for f in data['features']} == {dc.UNVERIFIED_DATUM}
        assert 'Not for navigation' in data['provenance']['limitations']


def test_omitted_sources_names_morro_bays_approved_but_untraced_bag_survey():
    from skippercast.platform.contracts import load_catalogs, load_region
    traced = ['usgs-point-buchon', 'usgs-morro-bay', 'usgs-point-estero']
    assert dc.omitted_sources(load_region('morro-bay'), load_catalogs()[1], traced) == \
        [{'source_id': 'noaa-bag', 'review_status': 'approved'}]
    with pytest.raises(ValueError, match='not in the source catalog'):
        dc.omitted_sources(REGION, {'survey-a': SOURCES['survey-a']}, ['survey-a'])


@pytest.mark.parametrize('omitted', [[], [{'source_id': 'survey-b', 'review_status': 'candidate'}]])
def test_check_rejects_a_misstated_omitted_list_and_accepts_none(omitted):
    c = collection()
    dc.check_contours(c, REGION, SOURCES)
    c['provenance']['sources_omitted'] = omitted
    with pytest.raises(ValueError, match='misstate the omitted bound surveys'):
        dc.check_contours(c, REGION, SOURCES)


def test_publish_records_the_omitted_bound_surveys_in_both_forms(tmp_path):
    (tmp_path / 'catalog/depth-contours').mkdir(parents=True)
    (tmp_path / 'catalog/depth-contours/test-bay.geojson').write_text(json.dumps(collection()))
    dc.publish_depth_contours(tmp_path, REGION, tmp_path, SOURCES)
    for name in ('depth-contours.geojson', 'depth-contours-overview.geojson'):
        provenance = json.loads((tmp_path / name).read_text())['provenance']
        assert provenance['sources_omitted'] == [{'source_id': 'survey-b', 'review_status': 'approved'}], name


def test_the_committed_morro_bay_publication_names_its_omitted_survey():
    for name in ('depth-contours.geojson', 'depth-contours-overview.geojson'):
        provenance = json.loads((ROOT / 'dist/regions/morro-bay' / name).read_text())['provenance']
        assert provenance['sources_omitted'] == [{'source_id': 'noaa-bag', 'review_status': 'approved'}], name


@pytest.mark.parametrize('where', ['collection', 'provenance', 'feature properties'])
def test_check_refuses_a_held_collection_wherever_it_is_marked(where):
    c = collection()
    target = {'collection': c, 'provenance': c['provenance'], 'feature properties': c['features'][0]['properties']}[where]
    target['publication_held'] = True
    with pytest.raises(ValueError, match='are held and cannot be published'):
        dc.check_contours(c, REGION, SOURCES)


def test_held_check_accepts_a_held_candidate_set_that_publication_refuses():
    region = {**REGION, 'source_bindings': {'bathymetry': ['survey-a', 'survey-c']}}
    c = collection(sources=('survey-a', 'survey-c'))
    with pytest.raises(ValueError, match='approved bathymetry binding'):
        dc.check_contours(c, region, SOURCES)
    c['provenance'].update(publication_held=True, held_sources=[{'source_id': 'survey-c', 'review_status': 'candidate'}])
    dc.check_held_contours(c, region, SOURCES)
    with pytest.raises(ValueError, match='are held and cannot be published'):
        dc.check_contours(c, region, SOURCES)
    for wrong in ([], [{'source_id': 'survey-c', 'review_status': 'approved'}]):
        with pytest.raises(ValueError, match='publication hold and held sources'):
            dc.check_held_contours({**c, 'provenance': {**c['provenance'], 'held_sources': wrong}}, region, SOURCES)
    restricted = {**SOURCES, 'survey-c': {**SOURCES['survey-c'], 'review_status': 'restricted'}}
    with pytest.raises(ValueError, match='approved bathymetry binding'):
        dc.check_held_contours(c, region, restricted)
