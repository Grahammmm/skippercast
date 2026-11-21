"""F06-06 / SCA-262: render handoff binds source rights and reviewer rights consistently.

Contract: the packet's top-level ``rights`` is the SOURCE rights record that ``produce`` hashed into
``facts``; reviewer rights are only compared against it. Two records that agree on ``private_use`` and
the evidence set round-trip through produce -> verify even when annotated differently; records that
disagree give the specific hold ``imagery_rights_review_mismatch`` in both produce and verify, and the
packet is never PRIVATE_PREVIEW_READY.

Believable bug it catches: produce overwriting ``rights`` with the reviewer's record after the facts were
hashed from the supplied one, so verify rebuilds different facts and a packet the producer just wrote
fails with "render facts changed or forged".

SYNTHETIC DOUBLES replace mapping facts, review binding and evidence reads; no raster, rights evidence,
account, location or network is touched.
"""
import copy
import json
from unittest import mock

import pytest

from skippercast.coastal.handoff import render

NOW = '2026-10-24T12:00:00+00:00'
RUN = dict(synthetic=True, segment_id='synthetic-seg-1', segment=dict(label='SYNTHETIC'))
EV_A = dict(path='synthetic/a.json', sha256='a' * 64, bytes=1, contract='synthetic')
EV_B = dict(path='synthetic/b.json', sha256='b' * 64, bytes=1, contract='synthetic')
MISMATCH = 'imagery_rights_review_mismatch'


def _facts(root, run, imagery, alignment, *, now, rights=None, minimum_valid_until=None):
    # Like the real _facts: the supplied rights record is part of the hashed facts.
    holds = [] if rights and rights.get('private_use') is True and rights.get('evidence') else ['imagery_private_rights_missing']
    return dict(imagery=imagery, alignment=alignment, rights=copy.deepcopy(rights), terrain={'t': 1},
                mask={'m': 1}, vertical={'v': 1}, segment=run['segment'], segment_id=run['segment_id']), holds


def _review_holds(root, review, facts_digest, **kwargs):
    return [] if review is not None else ['independent_review_missing']


@pytest.fixture
def produce_verify(tmp_path):
    def run(source, reviewer):
        with mock.patch.object(render, '_facts', _facts), mock.patch.object(render, 'review_holds', _review_holds), \
                mock.patch.object(render, 'resolve', lambda *a, **k: tmp_path):
            doc = render.produce(tmp_path, copy.deepcopy(RUN), output_dir='out', now=NOW, imagery={'i': 1},
                                 alignment={'a': 1}, review=dict(rights=reviewer), rights=source)
            written = json.loads((tmp_path / 'out' / 'render-handoff.json').read_text())
            return doc, written, render.verify(tmp_path, written, now=NOW)
    return run


def test_matching_records_with_different_annotations_round_trip(produce_verify):
    source = dict(private_use=True, evidence=[EV_A, EV_B], note='source annotation')
    reviewer = dict(private_use=True, evidence=[EV_B, EV_A], note='reviewer annotation')
    doc, written, result = produce_verify(source, reviewer)
    assert doc['rights'] == source  # source record stays at top level, not replaced by reviewer text
    assert doc['state'] == 'PRIVATE_PREVIEW_READY' and doc['facts']['rights'] == source
    assert result['ready'] is True and result['holds'] == []


@pytest.mark.parametrize('reviewer', [
    dict(private_use=True, evidence=[EV_B]),            # different evidence set
    dict(private_use=True, evidence=[EV_A, EV_B]),      # extra evidence
])
def test_disagreeing_evidence_is_a_specific_hold_before_completion(produce_verify, reviewer):
    doc, written, result = produce_verify(dict(private_use=True, evidence=[EV_A]), reviewer)
    assert MISMATCH in doc['slices'][0]['private_preview']['holds']
    assert doc['state'] == 'BLOCKED' and doc['selected_slice_ids'] == []
    assert doc['rights']['evidence'] == [EV_A]
    assert result['ready'] is False and MISMATCH in result['holds']  # verifies (no 'forged'), but held


def test_missing_source_rights_with_reviewer_rights_is_held_not_unverifiable(produce_verify):
    doc, written, result = produce_verify(None, dict(private_use=True, evidence=[EV_A]))
    assert doc['rights'] is None and doc['state'] == 'BLOCKED'
    assert {'imagery_private_rights_missing', MISMATCH} <= set(result['holds'])
