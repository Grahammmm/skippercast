"""Audit repro (2026-10-22): mapping_claim_guard accepts any file whose *name*
contains 'rights' / 'restriction' or 'mpa' / 'live'+'readback' as the
publication receipts of a ``published`` job. Content is never read, one file can
satisfy all three roles, and substrings such as 'mpa' in 'company' count.
Each test asserts the correct behaviour (refuse) and fails on current code.
"""
import pytest

from research.scripts.mapping_claim_guard import GuardError, validate_checkpoint


def _checkpoint(receipts):
    return {
        'coordinator': 'astra-orchestrator',
        'jobs': [{
            'id': 'job-1', 'state': 'published', 'owner': 'codex',
            'dispatch_state': 'queued', 'output_path': 'out/job-1',
            'receipt_paths': receipts,
        }],
    }


def test_single_failed_file_cannot_stand_in_for_all_three_receipts(tmp_path):
    # One file whose content records a FAILED rights review, no MPA screen and no read-back.
    (tmp_path / 'rights-restriction-live-readback.json').write_text(
        '{"rights": "DENIED_NONCOMMERCIAL_ONLY", "mpa_screen": "not_run", "live_readback": "FAILED"}')
    with pytest.raises(GuardError):
        validate_checkpoint(_checkpoint(['rights-restriction-live-readback.json']), base_dir=tmp_path)


def test_unrelated_filenames_count_as_restriction_receipt(tmp_path):
    # 'company-logo.json' is not an MPA/restriction receipt; 'mpa' is a substring of 'company'.
    for name in ('rights-review.json', 'company-logo.json', 'live-readback.json'):
        (tmp_path / name).write_text('{}')
    with pytest.raises(GuardError):
        validate_checkpoint(_checkpoint(['rights-review.json', 'company-logo.json', 'live-readback.json']),
                            base_dir=tmp_path)
