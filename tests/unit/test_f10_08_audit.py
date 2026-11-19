"""F10-08: validate both sizes before replacing a generation of depth contours."""
import json

import pytest

from skippercast.platform import depth_contours as dc

NAMES = ('depth-contours.geojson', 'depth-contours-overview.geojson')
LIMITS = ('MAX_BYTES', 'OVERVIEW_MAX_BYTES')


@pytest.fixture
def contour_pair(tmp_path):
    sources = {name: {'review_status': 'approved', 'needs': ['bathymetry'], 'reviewed_at': '2026-01-01'}
               for name in ('survey-a', 'survey-b')}
    region = {'id': 'synthetic-bay', 'bounds': [0, 0, 1, 1], 'source_bindings': {'bathymetry': list(sources)}}
    import_path = tmp_path / 'catalog/depth-contours/synthetic-bay.geojson'
    import_path.parent.mkdir(parents=True)
    out = tmp_path / 'out'

    def write_import(source, digest):
        survey = {'source_id': source, 'survey_date': '2020', 'vertical_datum': 'synthétique'}
        import_path.write_text(json.dumps({
            'type': 'FeatureCollection', 'schema_version': 1,
            'provenance': {'region_id': region['id'], 'bounds': region['bounds'], 'features': 1,
                           'units': 'ft', 'interval_ft': 30, 'shelf_limit_ft': 600,
                           'sources': [{**survey, 'sha256': digest * 64}]},
            'features': [{'type': 'Feature', 'id': 'synthetic-30ft',
                          'properties': {**survey, 'kind': 'contour', 'depth_ft': 30, 'index': False},
                          'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [1, 1]]}}],
        }))

    def publish(output=out):
        return dc.publish_depth_contours(tmp_path, region, output, sources)

    write_import('survey-a', 'a')
    publish()
    return import_path, out, sources, write_import, publish


def _pair(directory):
    return {name: (directory / name).read_bytes() for name in NAMES}


@pytest.mark.parametrize('oversized', [0, 1], ids=['full', 'overview'])
def test_budget_failure_preserves_both_previous_files(contour_pair, monkeypatch, oversized):
    # Writing either final name before both checks can replace or erase a member of the old pair.
    _, out, _, write_import, publish = contour_pair
    previous = _pair(out)
    write_import('survey-a', 'b')
    control = out.with_name('control')
    publish(control)
    replacement = _pair(control)
    assert all(previous[name] != replacement[name] for name in NAMES)
    for name, limit in zip(NAMES, LIMITS):
        monkeypatch.setattr(dc, limit, len(replacement[name]))

    name = NAMES[oversized]
    monkeypatch.setattr(dc, LIMITS[oversized], len(replacement[name]) - 1)
    with pytest.raises(ValueError, match=rf'{name} .* {len(replacement[name])} bytes, over its'):
        publish()
    assert {path.name for path in out.iterdir()} == set(NAMES)
    assert _pair(out) == previous

    monkeypatch.setattr(dc, LIMITS[oversized], len(replacement[name]))
    publish()
    assert _pair(out) == replacement
    assert {path.name for path in out.iterdir()} == set(NAMES)


def test_missing_import_removes_both_previous_files(contour_pair):
    # An absent import is a removal, not a failed replacement.
    import_path, out, _, _, publish = contour_pair
    import_path.unlink()
    assert publish() is None
    assert not any(out.iterdir())


def test_explicitly_held_import_removes_both_previous_files(contour_pair):
    # A region-level publication hold must not leave the previously published layer in place.
    import_path, out, _, _, publish = contour_pair
    collection = json.loads(import_path.read_text())
    collection['provenance']['publication_held'] = True
    import_path.write_text(json.dumps(collection))
    with pytest.raises(ValueError, match='held and cannot be published'):
        publish()
    assert not any(out.iterdir())


@pytest.mark.parametrize('eligible_replacement', [False, True], ids=['withdrawn-import', 'oversized-new-source'])
def test_revoked_source_is_not_retained_after_failure(contour_pair, monkeypatch, eligible_replacement):
    # The prior layer may use a revoked source even when the incoming import no longer names it.
    _, out, sources, write_import, publish = contour_pair
    sources['survey-a']['rights'] = {'public_display': 'excluded'}
    if eligible_replacement:
        write_import('survey-b', 'b')
        monkeypatch.setattr(dc, 'OVERVIEW_MAX_BYTES', 1)
        reason = 'over its 1-byte budget'
    else:
        reason = 'not cleared for public display'
    with pytest.raises(ValueError, match=reason):
        publish()
    assert not any(out.iterdir())
