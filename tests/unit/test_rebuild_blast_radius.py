"""Offline controls at the saved rebuild-plan JSON boundary."""
import json
import subprocess
import sys

import pytest

from skippercast.relief.rebuild_plan import plan
from tests._support import ROOT


def invoke(tmp_path, raw, *expected):
    path = tmp_path / 'plan.json'
    path.write_text(raw, encoding='utf-8')
    return subprocess.run([
        sys.executable, '-B', str(ROOT / 'scripts/relief/rebuild_blast_radius.py'),
        '--plan', str(path), *expected,
    ], cwd=tmp_path, capture_output=True, text=True, timeout=10)


def test_scoped_rebuilds_and_missing_region(tmp_path):
    """Preserve scope/reasons and expose the roster gap, not a fabricated reuse row.

    Catches merging private/public tiles, indexing reuse, or inferring the roster
    from the plan itself. The directory contains only JSON, no stage artifacts.
    """
    current = {'stage_digest': {'mosaic.public': 'new', 'tiles.public': 'same',
                                'tiles.private': 'new'}, 'style': {}}
    docs = {key: {'code': {'stage_digest': digest}} for key, digest in (
        ('mosaic.public', 'old'), ('tiles.public', 'same'), ('tiles.private', 'new'),
    )}
    east = plan(docs, current)
    west = plan(docs | {'tiles.private': None}, current)
    raw = json.dumps({'regions': [{'region': 'west-test', 'stages': west},
                                  {'region': 'east-test', 'stages': east}],
                      'summary': {'regions': 2, 'rebuild_heavy': 3}})
    result = invoke(tmp_path, raw, 'west-test', 'missing-test', 'east-test')
    assert (result.returncode, result.stderr) == (0, '')
    shared = {'stage': 'mosaic.public', 'action': 'rebuild', 'reasons': ['code']}
    public_reuse = {'stage': 'tiles.public', 'action': 'reuse', 'reasons': []}
    assert json.loads(result.stdout) == {
        'regions': {
            'east-test': [shared, {'stage': 'tiles.private', 'action': 'reuse', 'reasons': []},
                          public_reuse],
            'west-test': [shared, {'stage': 'tiles.private', 'action': 'rebuild',
                                   'reasons': ['missing']}, public_reuse],
        },
        'affected_regions_by_stage': {'mosaic.public': ['east-test', 'west-test'],
                                      'tiles.private': ['west-test']},
        'incomplete_regions': ['missing-test'],
    }
    assert {path.name for path in tmp_path.iterdir()} == {'plan.json'}


@pytest.mark.parametrize(('raw', 'message'), [
    ('{"regions":[', 'Expecting value'),
    ('{"regions":[],"regions":[]}', 'duplicate JSON field'),
    ('{"regions":{}}', 'regions list'),
    ('{"regions":[{"region":"other-test","stages":[]}]}', 'unexpected or invalid plan region'),
    ('{"regions":[{"region":"west-test","stages":[]}]}', 'nonempty stages list'),
])
def test_invalid_envelope_is_not_an_empty_plan(tmp_path, raw, message):
    """Broken JSON/envelopes must not default to a successful empty report."""
    assert_refused(invoke(tmp_path, raw, 'west-test'), message)


REUSE = {'stage': 'tiles.private', 'action': 'reuse', 'reasons': []}


@pytest.mark.parametrize(('change', 'message'), [
    ({'action': 'verified'}, 'invalid action or reasons'),
    ({'reasons': ['code']}, 'invalid action or reasons'),
    ({'reasons': ''}, 'invalid action or reasons'),
    ({'action': 'rebuild', 'reasons': [3]}, 'invalid action or reasons'),
    ({'stage': 'tiles.'}, 'invalid stage key'),
])
def test_malformed_row_never_defaults_to_reuse(tmp_path, change, message):
    """A later malformed row must not be coerced to reuse or yield partial stdout."""
    raw = json.dumps({'regions': [
        {'region': 'east-test', 'stages': [REUSE]},
        {'region': 'west-test', 'stages': [REUSE | change]},
    ]})
    assert_refused(invoke(tmp_path, raw, 'east-test', 'west-test'), message)


@pytest.mark.parametrize('duplicate', ['region', 'stage', 'roster'])
def test_duplicates_do_not_overwrite_decisions(tmp_path, duplicate):
    """Catch last-wins indexing that erases a rebuild behind a later reuse row."""
    rebuild = REUSE | {'action': 'rebuild', 'reasons': ['code']}
    blocks = [{'region': 'west-test', 'stages': [rebuild]}]
    expected = ['west-test']
    if duplicate == 'region':
        blocks.append({'region': 'west-test', 'stages': [REUSE]})
    elif duplicate == 'stage':
        blocks[0]['stages'].append(REUSE)
    else:
        expected.append('west-test')
    assert_refused(invoke(tmp_path, json.dumps({'regions': blocks}), *expected), 'duplicate')


def assert_refused(result, message):
    assert result.returncode == 2
    assert result.stdout == ''
    assert message in result.stderr
