"""Audit repro (2026-10-22): coastal_four128_admission.evidence_summary admits
independent evidence (including the rights review) that records holds or a
refusal.

``doc.get('holds', doc.get('holds_added', []))`` ignores ``holds_added`` whenever
a ``holds`` key exists, and only the literal substring 'HOLD' in ``status`` is
refused, so a REFUSED rights review passes. The repository's review documents
carry their holds in ``holds_added`` (handoff/common.py, ordered_trial.py).
Each test asserts the correct behaviour (refuse) and fails on current code.
"""
import datetime as dt
import hashlib
import json

import pytest

from research.scripts import coastal_four128_admission as admission

WINDOWS = [[3634, 3616, 128, 128]]


def _setup(tmp_path, rights_overrides):
    evidence = tmp_path / 'evidence'
    stage = tmp_path / 'stage'
    (stage / 'metadata').mkdir(parents=True)
    evidence.mkdir()
    selection = tmp_path / 'selection.json'
    selection.write_text('{"selection": true}')
    sel_sha = hashlib.sha256(selection.read_bytes()).hexdigest()
    now = dt.datetime(2026, 10, 22, 12, tzinfo=dt.timezone.utc)
    for name, contract in admission.DOCS.items():
        doc = dict(schema=contract, window_set=WINDOWS, status='PASS', holds=[],
                   checked_at=(now - dt.timedelta(hours=1)).isoformat(),
                   valid_until=(now + dt.timedelta(hours=10)).isoformat(),
                   reviewer_id='fable-2nd-look',
                   prescan_evidence=[dict(path=str(selection), sha256=sel_sha)])
        if name == 'independent-four128-rights-review':
            doc.update(rights_overrides)
        raw = json.dumps(doc).encode()
        (evidence / (name + '.json')).write_bytes(raw)
        (stage / 'metadata' / (name + '.json')).write_bytes(raw)
    cfg = dict(docs=admission.DOCS, evidence_root=str(evidence), staging_root=str(stage),
               windows=WINDOWS, inputs=dict(selection=dict(path=str(selection), sha256=sel_sha)))
    return cfg, now.timestamp()


def test_baseline_clean_evidence_is_admitted(tmp_path):
    cfg, now = _setup(tmp_path, {})
    assert set(admission.evidence_summary(cfg, now)) == set(admission.DOCS)


def test_rights_review_holds_added_are_not_ignored(tmp_path):
    cfg, now = _setup(tmp_path, dict(holds=[], holds_added=['csumb-noncommercial-only-not-cleared']))
    with pytest.raises(ValueError, match='evidence held'):
        admission.evidence_summary(cfg, now)


def test_refused_rights_review_is_not_admitted(tmp_path):
    cfg, now = _setup(tmp_path, dict(status='REFUSED_SOURCE_RIGHTS_UNRESOLVED'))
    with pytest.raises(ValueError):
        admission.evidence_summary(cfg, now)
