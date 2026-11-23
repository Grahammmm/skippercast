"""Exercise the elapsed-evidence report over saved synthetic stage receipts."""
import json

import pytest

from scripts.relief import rebuild_elapsed_evidence
from skippercast.relief import receipts


def _save(tmp_path, name, **overrides):
    path = tmp_path / f'{name}.json'
    doc = {
        'schema': receipts.SCHEMA, 'region': 'fixture-coast', 'stage': 'mosaic',
        'scope': 'public', 'generation': 'a' * 64, 'attempt': 1, 'status': 'ok', 'rc': 0,
        'started': '2026-01-01T00:00:00Z', 'ended': '2026-01-01T00:00:08Z',
        # Saved timings are usable even when their original output is not available.
        'outputs': [{'path': 'absent/grid.tif', 'sha256': 'b' * 64, 'bytes': 1}], 'upstream': [],
    }
    receipts.write_json_atomic(path, doc | overrides)
    return path


def test_reports_only_explicit_samples_grouped_by_region_stage_and_scope(tmp_path, capsys):
    # Pooling scopes/stages/regions or auto-discovering files/history changes these ranges.
    public = _save(tmp_path, 'public')
    slower = _save(tmp_path, 'public-later', ended='2026-01-01T00:00:13Z')
    private = _save(tmp_path, 'private', scope='private', ended='2026-01-01T00:00:42Z')
    other_region = _save(tmp_path, 'other-region', region='other-coast')
    other_stage = _save(tmp_path, 'other-stage', stage='tiles')
    unscoped = _save(tmp_path, 'unscoped', scope=None, ended='2026-01-01T00:00:00Z')
    unlisted = _save(tmp_path, 'not-listed', generation='c' * 64, ended='2026-01-01T00:59:00Z')
    with_history = json.loads(public.read_bytes())
    with_history['generation_history'] = {'c' * 64: json.loads(unlisted.read_bytes())}
    receipts.write_json_atomic(public, with_history)
    paths = [slower, other_stage, private, public, other_region, unscoped]
    assert rebuild_elapsed_evidence.main([str(path) for path in paths]) == 0
    report = json.loads(capsys.readouterr().out)
    assert set(report) == {'groups', 'ignored'}
    assert report['ignored'] == {}
    assert report['groups'] == [
        {'region': 'fixture-coast', 'stage': 'mosaic', 'scope': None,
         'count': 1, 'min_seconds': 0, 'max_seconds': 0},
        {'region': 'fixture-coast', 'stage': 'mosaic', 'scope': 'private',
         'count': 1, 'min_seconds': 42, 'max_seconds': 42},
        {'region': 'fixture-coast', 'stage': 'mosaic', 'scope': 'public',
         'count': 2, 'min_seconds': 8, 'max_seconds': 13},
        {'region': 'fixture-coast', 'stage': 'tiles', 'scope': 'public',
         'count': 1, 'min_seconds': 8, 'max_seconds': 8},
        {'region': 'other-coast', 'stage': 'mosaic', 'scope': 'public',
         'count': 1, 'min_seconds': 8, 'max_seconds': 8},
    ]


def test_deduplicates_saved_copies_but_not_distinct_attempt_identities(tmp_path):
    # Path/byte dedup misses rewritten copies; generation-only dedup drops real retries.
    original = _save(tmp_path, 'original')
    copy = tmp_path / 'copy.json'
    copy.write_bytes(original.read_bytes())
    equivalent = _save(tmp_path, 'equivalent', started='2025-12-31T16:00:00-08:00',
                       ended='2025-12-31T16:00:08-08:00', metrics={'unrelated': 12})
    retry = _save(tmp_path, 'retry', attempt=2)
    different_start = _save(tmp_path, 'different-start', started='2026-01-01T00:00:02Z')
    different_generation = _save(tmp_path, 'different-generation', generation='c' * 64)
    report = rebuild_elapsed_evidence.summarize([copy, retry, original, equivalent,
                                                different_start, different_generation])
    assert report['ignored'] == {'duplicate': 2}
    assert report['groups'] == [
        {'region': 'fixture-coast', 'stage': 'mosaic', 'scope': 'public',
         'count': 4, 'min_seconds': 6, 'max_seconds': 8},
    ]


def test_counts_non_success_and_bad_clocks_separately(tmp_path):
    # Valid-looking clocks don't make held/busy/failed samples, and a backwards
    # clock must not be converted into a duration via abs() or timedelta.seconds.
    busy = _save(tmp_path, 'busy', status='busy')
    held = _save(tmp_path, 'held', status='held', rc=None)
    failed = _save(tmp_path, 'failed', status='failed', rc=1, ended=None)
    negative = _save(tmp_path, 'negative', ended='2026-01-01T00:00:01+01:00')
    naive = _save(tmp_path, 'naive', ended='2026-01-01T00:00:08')
    missing_end = _save(tmp_path, 'missing-end', ended=None)
    malformed_clock = _save(tmp_path, 'malformed-clock', started='not-a-clock')
    report = rebuild_elapsed_evidence.summarize([busy, held, failed, negative, naive,
                                                missing_end, malformed_clock])
    assert report == {'groups': [], 'ignored': {
        'busy': 1, 'held': 1, 'failed': 1, 'negative_elapsed': 1, 'invalid_clock': 3,
    }}


@pytest.mark.parametrize('overrides', [
    {'status': 'done'}, {'schema': 'other/1'}, {'rc': 1}, {'attempt': True},
    {'generation': ''}, {'region': None},
])
def test_does_not_promote_invalid_metadata_to_success(tmp_path, overrides):
    # A clock alone doesn't establish a successful, identifiable receipt.
    path = _save(tmp_path, 'invalid', **overrides)
    assert rebuild_elapsed_evidence.summarize([path]) == {
        'groups': [], 'ignored': {'invalid_receipt': 1},
    }


def test_reports_missing_and_unreadable_inputs_without_dropping_the_good_one(tmp_path):
    # A broken input should not crash or silently become a zero-second observation.
    malformed = tmp_path / 'malformed.json'
    malformed.write_text('{', encoding='utf-8')
    missing = tmp_path / 'missing.json'
    good = _save(tmp_path, 'valid')
    report = rebuild_elapsed_evidence.summarize([missing, malformed, good])
    assert report['ignored'] == {'missing_receipt': 1, 'unreadable_receipt': 1}
    assert [row['count'] for row in report['groups']] == [1]
