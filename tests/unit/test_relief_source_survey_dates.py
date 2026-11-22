import json

import pytest

from scripts.relief.source_survey_dates import main, reconcile


def _write_inputs(tmp_path, credits, catalogue):
    contours = tmp_path / 'contours.geojson'
    sources = tmp_path / 'sources.json'
    contours.write_text(json.dumps({
        'type': 'FeatureCollection',
        'features': [],
        'provenance': {
            'region_id': 'fixture-coast', 'set': 'ft-v3', 'sources': credits,
            'sources_omitted': [{'source_id': 'not-credited', 'review_status': 'approved'}],
        },
    }), encoding='utf-8')
    sources.write_text(json.dumps({'schema_version': 1, 'sources': catalogue}), encoding='utf-8')
    return contours, sources


def test_reconciles_only_credited_ids_without_date_fallback(tmp_path, capsys):
    # A register-style year fallback, timestamp inference, inner join or scan-order sort
    # would misclassify, drop or shuffle rows in this mixed release.
    credits = [
        {'source_id': 'unknown'},
        {'source_id': 'partial', 'survey_date': '2004-03'},
        {'source_id': 'decoy', 'survey_date': 'unstated'},
        {'source_id': 'blank', 'survey_date': None, 'retrieved_at': '2024-11-01'},
    ]
    catalogue = [
        {'id': 'not-credited', 'survey_date': '2024-01-01'},
        {'id': 'partial', 'survey_date': '2004-03'},
        {'id': 'decoy', 'survey_year': 2012, 'retrieved_at': '2026-04-01T09:00:00Z',
         'publication_date': '2025-10-01'},
        {'id': 'blank', 'survey_date': '2001-06-03'},
    ]
    paths = _write_inputs(tmp_path, credits, catalogue)
    before = [path.read_bytes() for path in paths]
    assert main([str(path) for path in paths]) == 0
    out = capsys.readouterr().out
    assert json.loads(out) == {'region_id': 'fixture-coast', 'sources': [
        {'source_id': 'blank', 'status': 'metadata_missing', 'release': {'survey_date': None},
         'catalogue': {'survey_date': '2001-06-03'}, 'review': []},
        {'source_id': 'decoy', 'status': 'explicitly_unstated', 'release': {'survey_date': 'unstated'},
         'catalogue': {'survey_year': 2012}, 'review': []},
        {'source_id': 'partial', 'status': 'release_date_supplied', 'release': {'survey_date': '2004-03'},
         'catalogue': {'survey_date': '2004-03'}, 'review': []},
        {'source_id': 'unknown', 'status': 'metadata_missing', 'release': {}, 'catalogue': None,
         'review': ['catalogue_source_missing']},
    ]}
    assert [path.read_bytes() for path in paths] == before
    assert sorted(tmp_path.iterdir()) == sorted(paths)
    _write_inputs(tmp_path, credits[::-1], catalogue[::-1])
    assert main([str(path) for path in paths]) == 0
    assert capsys.readouterr().out == out


@pytest.mark.parametrize(('release', 'catalogue', 'status'), [
    ('unstated', '2008-06-01', 'explicitly_unstated'),
    ('2003-11-14', 'unstated', 'release_date_supplied'),
    ('2003', '2003-01-01 to 2003-11-14', 'release_date_supplied'),
    ('2003-11-14', '2008-06-01', 'release_date_supplied'),
], ids=['release-unstated', 'catalogue-unstated', 'year-versus-range', 'different-days'])
def test_date_disagreement_retains_both_versions_for_review(tmp_path, release, catalogue, status):
    # Choosing one version or coercing everything to a year hides date-text disagreements.
    paths = _write_inputs(tmp_path, [{'source_id': 'survey', 'survey_date': release}],
                          [{'id': 'survey', 'survey_date': catalogue}])
    assert reconcile(*paths)['sources'] == [
        {'source_id': 'survey', 'status': status, 'release': {'survey_date': release},
         'catalogue': {'survey_date': catalogue}, 'review': ['survey_date_differs']},
    ]


@pytest.mark.parametrize(('release', 'year', 'review'), [
    ('2003', 2008, ['survey_year_differs']),
    ('2003-11-14', 2003, []),
    ('2003-11', 2008, ['survey_year_differs']),
    ('unstated', 2008, []),
    (None, 2008, []),
    ('2023-02-29', 2008, ['invalid_release_survey_date']),
])
def test_catalogue_year_is_compared_without_replacing_saved_date(tmp_path, release, year, review):
    paths = _write_inputs(tmp_path, [{'source_id': 'survey', 'survey_date': release}],
                          [{'id': 'survey', 'survey_year': year}])
    row = reconcile(*paths)['sources'][0]
    assert row['release'] == {'survey_date': release}
    assert row['catalogue'] == {'survey_year': year}
    assert row['review'] == review


def test_date_and_year_disagreements_are_independently_reported(tmp_path):
    paths = _write_inputs(tmp_path, [{'source_id': 'survey', 'survey_date': '2003'}],
                          [{'id': 'survey', 'survey_date': '2004', 'survey_year': 2008}])
    assert reconcile(*paths)['sources'][0]['review'] == ['survey_date_differs', 'survey_year_differs']


def test_bad_release_date_is_not_valid_evidence_or_explicitly_unstated(tmp_path):
    # Nonempty text alone is not survey-date evidence; a calendar-invalid leap day is decisive.
    paths = _write_inputs(tmp_path, [{'source_id': 'survey', 'survey_date': '2023-02-29'}],
                          [{'id': 'survey', 'survey_date': None}])
    assert reconcile(*paths)['sources'] == [
        {'source_id': 'survey', 'status': 'metadata_missing', 'release': {'survey_date': '2023-02-29'},
         'catalogue': {'survey_date': None}, 'review': ['invalid_release_survey_date']},
    ]


def test_unmatched_id_does_not_erase_saved_release_date(tmp_path):
    # An unmatched catalogue lookup is a separate problem, not a reason to discard saved data.
    paths = _write_inputs(tmp_path, [{'source_id': 'survey', 'survey_date': '2024-02-29'}], [])
    assert reconcile(*paths)['sources'] == [
        {'source_id': 'survey', 'status': 'release_date_supplied', 'release': {'survey_date': '2024-02-29'},
         'catalogue': None, 'review': ['catalogue_source_missing']},
    ]


@pytest.mark.parametrize('duplicate_side', ['release', 'catalogue'])
def test_duplicate_id_cannot_silently_win_the_join(tmp_path, duplicate_side):
    # Last-write-wins indexing could erase a contradictory declaration in either input.
    credits = [{'source_id': 'survey', 'survey_date': '2001'}]
    catalogue = [{'id': 'survey', 'survey_date': '2001'}]
    if duplicate_side == 'release':
        credits.append({'source_id': 'survey', 'survey_date': 'unstated'})
    else:
        catalogue.append({'id': 'survey', 'survey_date': '2002'})
    with pytest.raises(ValueError, match='duplicate'):
        reconcile(*_write_inputs(tmp_path, credits, catalogue))
