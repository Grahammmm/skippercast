"""F11-14: recording a second reach must not replace the first reach's review."""
from datetime import datetime, timedelta, timezone

import pytest

from skippercast.platform.contracts import atomic_json, read_json
from skippercast.seafloor import source_review


def test_discovery_reviews_remain_independent_by_reach_and_context(tmp_path, monkeypatch):
    source = 'synthetic-source'
    manifest = {'surveys': [{'id': source, 'status': 'candidate'}]}
    queue = [{'id': source}]
    atomic_json(tmp_path/'catalog/reaches.json', {'reaches': [{'id': r} for r in 'abc']})
    for filename in ('catalog/habitat-rules.json', 'dist/data/atlas.json',
                     'var/seafloor/reference/cells.json'):
        atomic_json(tmp_path/filename, {})
    (tmp_path/'requirements-survey.txt').touch()
    evidence = 'var/seafloor/synthetic-review.json'
    atomic_json(tmp_path/evidence, {'fixture': True})
    checkpoint = tmp_path/source_review.RELATIVE
    rules = tmp_path/'catalog/habitat-rules.json'
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    later = start + timedelta(days=1)
    expiry = start + timedelta(days=7)

    def record(reach, outcome, when):
        source_review.record(tmp_path, manifest, source, [reach], outcome, evidence,
                             now=when, note='Synthetic review')

    def outcome(reaches, when):
        active, deferred, warnings = source_review.partition(
            tmp_path, manifest, queue, reaches, now=when)
        assert not warnings
        if not deferred:
            assert active == queue
            return None
        assert not active and len(deferred) == 1 and deferred[0]['id'] == source
        return deferred[0]['review_outcome']

    record('a', 'no-incremental-support', start)
    legacy = read_json(checkpoint)  # A v1 checkpoint with one decision per source.
    assert outcome(['a'], later) == 'no-incremental-support'
    record('b', 'needs-original-input', later)
    assert outcome(['b'], later) == 'needs-original-input'
    assert outcome(['a'], later) == 'no-incremental-support'
    assert outcome(['c'], later) is None
    # A broader request still needs one review covering every requested reach.
    assert outcome(['a', 'b'], later) is None
    assert legacy['reviews'][0] in read_json(checkpoint)['reviews']
    assert outcome(['a'], expiry) is None
    assert outcome(['b'], expiry) == 'needs-original-input'

    atomic_json(rules, {'fixture': 'changed'})
    assert outcome(['a'], later) is None
    record('a', 'no-valid-shallow-support', later)
    assert outcome(['a'], later) == 'no-valid-shallow-support'
    atomic_json(rules, {})
    assert outcome(['a'], later) == 'no-incremental-support'
    assert outcome(['a'], expiry) is None

    state = read_json(checkpoint)
    original = next(row for row in state['reviews'] if row == legacy['reviews'][0])
    original['evidence']['document']['fixture'] = False
    atomic_json(checkpoint, state)
    assert outcome(['a'], later) is None
    assert outcome(['b'], later) == 'needs-original-input'

    record('b', 'already-qualified', later)
    assert outcome(['b'], later) == 'already-qualified'
    assert len(read_json(checkpoint)['reviews']) == len(state['reviews'])

    before = checkpoint.read_bytes()
    monkeypatch.setattr(source_review, 'MAX_BYTES', len(before))
    with pytest.raises(ValueError, match='exceeds bounded size'):
        record('c', 'no-incremental-support', later)
    assert checkpoint.read_bytes() == before
