"""Offline controls at the saved-receipt CLI boundary."""

import json
import os
from datetime import datetime

from scripts.relief import goal_evidence_age

AS_OF = '2026-01-02T12:00:00Z'


def _receipt(path, verdict, **extra):
    path.write_text(json.dumps({
        'region': 'fixture-coast',
        'base': 'https://fixture.invalid',
        'merge': 'a' * 40,
        'deployed': 'b' * 40,
        'checks': [{'check': 'deploy', 'status': verdict}],
        'verdict': verdict,
        'requests': 2,
        **extra,
    }), encoding='utf-8')
    return path


def _report(capsys, *receipt_args):
    assert goal_evidence_age.main([
        '--as-of', AS_OF, '--max-age-seconds', '86400', *receipt_args,
    ]) == 0
    return json.loads(capsys.readouterr().out)


def test_exact_threshold_is_current_without_promoting_failed_check(tmp_path, capsys):
    """Catch an exclusive cutoff, offset stripping, or fresh evidence overriding FAIL."""
    path = _receipt(tmp_path / 'live.json', 'FAIL')
    row, = _report(capsys, '--receipt', str(path), '2026-01-01T04:00:00-08:00')
    assert (row['freshness'], row['verdict']) == ('current', 'FAIL')


def test_just_over_threshold_is_stale_without_rewriting_receipt(tmp_path, capsys):
    """Catch age truncation to whole seconds or replacing the saved PASS with stale."""
    path = _receipt(tmp_path / 'live.json', 'PASS')
    before = path.read_bytes()
    row, = _report(capsys, '--receipt', str(path), '2026-01-01T11:59:59.999999Z')
    assert (row['freshness'], row['verdict']) == ('stale', 'PASS')
    assert path.read_bytes() == before


def test_missing_attestation_ignores_receipt_and_file_times(tmp_path, capsys):
    """Neither a plausible embedded time nor a recent copy can attest observation."""
    path = _receipt(tmp_path / 'live.json', 'PASS', observed_at=AS_OF)
    # Set a deterministic mtime at the fixed evaluation instant.
    instant = datetime.fromisoformat(AS_OF).timestamp()
    os.utime(path, (instant, instant))
    row, = _report(capsys, '--receipt', str(path))
    assert (row['freshness'], row['observed_at']) == ('unknown', None)


def test_future_attestation_is_unknown(tmp_path, capsys):
    """Catch treating negative age as safely within the freshness threshold."""
    path = _receipt(tmp_path / 'live.json', 'PASS')
    row, = _report(capsys, '--receipt', str(path), '2026-01-02T12:00:00.000001Z')
    assert row['freshness'] == 'unknown'


def test_repeatable_receipts_keep_attestations_bound_to_paths(tmp_path, capsys):
    """Catch coalescing same-region releases or sharing one attestation across inputs."""
    first = _receipt(tmp_path / 'older.json', 'PASS')
    second = _receipt(tmp_path / 'newer.json', 'PASS')
    rows = _report(capsys, '--receipt', str(first), '2026-01-01T00:00:00Z',
                   '--receipt', str(second), '2026-01-02T12:00:00Z')
    assert [(row['receipt'], row['freshness']) for row in rows] == [
        (str(first), 'stale'), (str(second), 'current'),
    ]
