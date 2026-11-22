"""Synthetic proposal rows exercise the offline report's actual JSON CLI."""

import json

from scripts.relief.north_a_binding_reuse import main

DIGEST_A = '1' * 64
DIGEST_B = '2' * 64
REGION_A = 'fixture-north-a'
REGION_B = 'fixture-north-b'


def proposal(region, digest, filename='native.tif'):
    return {'region': region, 'native_sha256': digest, 'filename': filename}


def run_report(tmp_path, rows):
    path = tmp_path / 'proposals.json'
    path.write_text(json.dumps(rows), encoding='utf-8')
    return main([str(path)])


def test_shared_digest_across_regions_is_one_reused_digest(tmp_path, capsys):
    # Counting bindings as separate evidence or splitting by filename hides reuse.
    rows = [proposal(REGION_B, DIGEST_A, 'renamed.tif'), proposal(REGION_A, DIGEST_A)]
    assert run_report(tmp_path, rows) == 0
    assert json.loads(capsys.readouterr().out) == {
        'unique_digest_count': 1,
        'reused_digest_count': 1,
        'incidence': [{'native_sha256': DIGEST_A, 'regions': [REGION_A, REGION_B], 'reused': True}],
    }


def test_same_filename_with_distinct_digests_is_not_reuse(tmp_path, capsys):
    # Grouping by filename conflates separate revisions that share a basename.
    rows = [proposal(REGION_B, DIGEST_B), proposal(REGION_A, DIGEST_A)]
    assert run_report(tmp_path, rows) == 0
    assert json.loads(capsys.readouterr().out) == {
        'unique_digest_count': 2,
        'reused_digest_count': 0,
        'incidence': [
            {'native_sha256': DIGEST_A, 'regions': [REGION_A], 'reused': False},
            {'native_sha256': DIGEST_B, 'regions': [REGION_B], 'reused': False},
        ],
    }


def test_duplicate_proposal_for_one_region_is_not_cross_region_reuse(tmp_path, capsys):
    # Counting occurrences instead of distinct regions invents cross-region reuse.
    rows = [proposal(REGION_A, DIGEST_A)] * 2
    assert run_report(tmp_path, rows) == 0
    assert json.loads(capsys.readouterr().out) == {
        'unique_digest_count': 1,
        'reused_digest_count': 0,
        'incidence': [{'native_sha256': DIGEST_A, 'regions': [REGION_A], 'reused': False}],
    }


def test_malformed_digest_cannot_produce_a_partial_report(tmp_path, capsys):
    # Accepting or skipping a truncated digest would emit a misleading incidence table.
    rows = [proposal(REGION_A, DIGEST_A), proposal(REGION_B, DIGEST_A[:-1])]
    assert run_report(tmp_path, rows) == 1
    output = capsys.readouterr()
    assert not output.out
    assert 'row 2: native_sha256' in output.err
