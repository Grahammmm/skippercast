"""Exercise the offline CLI on synthetic saved receipts, not a stage runner."""
import json
import subprocess
import sys
from typing import Any

import pytest

from skippercast.relief import receipts
from tests._support import ROOT

CLI = ROOT / 'scripts/relief/receipt_generation_diff.py'
INPUT_HASH = 'a' * 64
CODE_DIGEST = 'b' * 64
PUBLIC_GEN = 'c' * 64
PRIVATE_GEN = 'd' * 64
NEW_GEN = 'e' * 64


def _doc(tmp_path, **fields) -> dict[str, Any]:
    doc: dict[str, Any] = dict(schema=receipts.SCHEMA, region='fixture-bay', stage='tiles', scope='public',
               inputs=[dict(path=str(tmp_path / 'original'), role='grid', sha256=INPUT_HASH)],
               upstream=[dict(stage='mosaic', scope='public', generation=PUBLIC_GEN),
                         dict(stage='mosaic', scope='private', generation=PRIVATE_GEN)],
               code=dict(repo_sha='a' * 40, stage_digest=CODE_DIGEST), params={'zoom': 1},
               status='ok', outputs=[], attempt=1)
    doc.update(fields)
    doc['generation'] = receipts.generation(doc['inputs'], doc['upstream'],
                                            doc['code']['stage_digest'], doc['params'])
    return doc


def _run(tmp_path, before, after, *, exit_code=0):
    paths = [tmp_path / 'before.json', tmp_path / 'after.json']
    for path, doc in zip(paths, (before, after), strict=True):
        if isinstance(doc, dict):
            receipts.write_json_atomic(path, doc)
        elif doc is not None:
            path.write_text(doc, encoding='utf-8')
    result = subprocess.run([sys.executable, '-B', str(CLI), *paths], cwd=tmp_path,
                            capture_output=True, text=True, check=False, timeout=10)
    assert result.returncode == exit_code, (result.stdout, result.stderr)
    assert result.stderr == ''
    return json.loads(result.stdout)


def _assert_valid(report, before, after):
    assert report['evidence'] == {
        side: {'recorded': doc['generation'], 'recomputed': doc['generation']}
        for side, doc in (('before', before), ('after', after))
    }


def test_path_only_move_does_not_explain_a_miss(tmp_path):
    # Comparing input rows verbatim, or opening their absent paths, would fail.
    before = _doc(tmp_path)
    after = _doc(tmp_path, inputs=[dict(before['inputs'][0], path=str(tmp_path / 'relocated'))])
    report = _run(tmp_path, before, after)
    assert report['status'] == 'same'
    assert report['changes'] == {}
    assert before['generation'] == after['generation']
    _assert_valid(report, before, after)


def test_unhashed_metadata_and_receipt_list_order_do_not_explain_a_miss(tmp_path):
    # Whole-document equality or order-sensitive identity would flag this repeat.
    grid = _doc(tmp_path)['inputs'][0]
    before = _doc(tmp_path, inputs=[grid, dict(grid, role='mask')], host={'load5': 0.5},
                  started='2020-01-01T00:00:00Z')
    after = _doc(tmp_path, inputs=before['inputs'][::-1], upstream=before['upstream'][::-1],
                 host={'load5': 0.75}, started='2020-01-02T00:00:00Z',
                 code=dict(before['code'], repo_sha='b' * 40))
    report = _run(tmp_path, before, after)
    assert report['status'] == 'same'
    assert report['changes'] == {}
    _assert_valid(report, before, after)


def test_changed_scoped_upstream_with_unchanged_repo_sha(tmp_path):
    # Keying only by stage would let the unchanged private row hide the public one.
    before = _doc(tmp_path)
    public, private = before['upstream']
    after = _doc(tmp_path, upstream=[dict(public, generation=NEW_GEN), private])
    report = _run(tmp_path, before, after)
    assert report['status'] == 'changed'
    assert report['target'] == {'region': 'fixture-bay', 'stage': 'tiles', 'scope': 'public'}
    assert report['changes'] == {'upstream': {'mosaic.public': {'before': [PUBLIC_GEN], 'after': [NEW_GEN]}}}
    assert before['generation'] != after['generation']
    _assert_valid(report, before, after)


def test_reports_only_changed_identity_members(tmp_path):
    # Sets lose the duplicate grid; comparing just roles or just hashes loses
    # a changed pair. Python equality loses 1 -> True; get() conflates null and missing.
    grid = _doc(tmp_path)['inputs'][0]
    before = _doc(tmp_path, inputs=[grid, dict(grid, role='mask', sha256=NEW_GEN)])
    after = _doc(tmp_path, inputs=[grid, grid, dict(grid, role='mask')],
                 code=dict(before['code'], stage_digest=NEW_GEN),
                 params={'zoom': True, 'optional': None})
    report = _run(tmp_path, before, after)
    assert report['status'] == 'changed'
    assert report['changes'] == {
        'inputs': [{'role': 'grid', 'sha256': INPUT_HASH, 'before': 1, 'after': 2},
                   {'role': 'mask', 'sha256': INPUT_HASH, 'before': 0, 'after': 1},
                   {'role': 'mask', 'sha256': NEW_GEN, 'before': 1, 'after': 0}],
        'stage_digest': {'before': CODE_DIGEST, 'after': NEW_GEN},
        'params': {'zoom': {'before': 1, 'after': True}, 'optional': {'after': None}},
    }
    assert report['changes']['params']['zoom']['after'] is True
    _assert_valid(report, before, after)


def test_recomputes_both_generations_and_refuses_stale_hash(tmp_path):
    # A copied, syntactically valid generation must not mask a params edit or
    # allow invalid evidence to be reported as an ordinary difference.
    before = _doc(tmp_path)
    after = _doc(tmp_path, params={'zoom': 2})
    forged = dict(after, generation=before['generation'])
    report = _run(tmp_path, before, forged, exit_code=1)
    assert report['status'] == 'invalid_evidence'
    assert 'changes' not in report
    assert report['evidence']['before'] == dict(recorded=before['generation'], recomputed=before['generation'])
    assert report['evidence']['after'] == dict(recorded=before['generation'], recomputed=after['generation'],
                                               error='recorded generation does not match recomputed generation')


@pytest.mark.parametrize(('before', 'reason'), [(None, 'receipt not found'), ('{', 'cannot read a JSON receipt object')],
                         ids=['missing', 'malformed-json'])
def test_unreadable_side_does_not_prevent_checking_its_peer(tmp_path, before, reason):
    # Do not treat absent/broken JSON as an empty receipt or short-circuit the peer.
    after = _doc(tmp_path)
    assert _run(tmp_path, before, after, exit_code=1) == {
        'status': 'invalid_evidence',
        'evidence': {'before': {'error': reason},
                     'after': {'recorded': after['generation'], 'recomputed': after['generation']}},
    }


def test_refuses_malformed_identity_even_when_hash_matches(tmp_path):
    # generation() stringifies roles; a matching hash is not a shape check.
    before = _doc(tmp_path, inputs=[dict(role=123, sha256=INPUT_HASH)])
    report = _run(tmp_path, before, _doc(tmp_path), exit_code=1)
    assert report['status'] == 'invalid_evidence'
    assert report['evidence']['before'] == {'error': 'input roles or hashes malformed'}


@pytest.mark.parametrize(('field', 'other'), [('region', 'other-bay'), ('stage', 'shade'), ('scope', None)])
def test_refuses_comparison_across_targets_even_with_identical_generation(tmp_path, field, other):
    # Generation excludes target identity; matching it does not qualify a pair.
    before, after = _doc(tmp_path), _doc(tmp_path, **{field: other})
    report = _run(tmp_path, before, after, exit_code=1)
    assert report['status'] == 'different_target'
    assert 'changes' not in report
    assert report['before'][field] == before[field]
    assert report['after'][field] == other
    _assert_valid(report, before, after)
