import json
import subprocess
import sys

from tests._support import ROOT


def _artifact(path, hex_digit, size):
    # Synthetic records matching the envelope's size-bearing layers; no files exist.
    return {'path': path, 'sha256': hex_digit * 64, 'bytes': size}


def _budget(tmp_path, cap, *artifacts):
    return subprocess.run(
        [sys.executable, str(ROOT / 'scripts/relief/r8_evidence_budget.py'),
         '--batch', 'central-fixture', '--attachment-cap-bytes', str(cap)],
        input=json.dumps({'artifacts': artifacts}), text=True, capture_output=True,
        cwd=tmp_path, check=False,
    )


def test_shared_digest_at_exact_cap(tmp_path):
    # Counting rows twice would reject an exact fit; deduplicating by path or
    # size would instead undercount distinct payloads from different envelopes.
    result = _budget(tmp_path, 14, _artifact('relief.pmtiles', 'a', 6),
                     _artifact('alias.pmtiles', 'a', 6), _artifact('relief.pmtiles', 'b', 4),
                     _artifact('other.pmtiles', 'c', 4))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        'batch': 'central-fixture', 'unique_bytes': 14,
        'largest_item': {'sha256': 'a' * 64, 'bytes': 6},
        'attachment_cap_bytes': 14, 'within_attachment_cap': True,
    }
    assert not list(tmp_path.iterdir())  # No attachment or copied artifact.


def test_batch_one_byte_over_cap(tmp_path):
    # Comparing only the largest item against the cap would miss this overflow.
    result = _budget(tmp_path, 9, _artifact('small.pmtiles', 'a', 4),
                     _artifact('large.pmtiles', 'b', 6))
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['unique_bytes'] == 10
    assert report['largest_item'] == {'sha256': 'b' * 64, 'bytes': 6}
    assert report['within_attachment_cap'] is False


def test_shared_digest_with_conflicting_sizes_is_rejected(tmp_path):
    # First- or last-record-wins deduplication would silently report a budget.
    result = _budget(tmp_path, 100, _artifact('relief.pmtiles', 'a', 6),
                     _artifact('alias.pmtiles', 'a', 7))
    assert result.returncode == 2
    assert 'conflicting sizes for SHA256' in result.stderr
    assert not result.stdout
