"""Qualify the Central batch selector at the real R8 parser/read boundary."""

import json
from pathlib import Path

import pytest

from scripts.relief import central_r8_request, r8_packet
from skippercast.relief import package, receipts
from tests._support import ROOT


@pytest.fixture
def artifact_reads(monkeypatch):
    reads = []

    def read_artifact(root, relative):
        reads.append((root, relative))
        if relative == 'stages/package.json':
            data = dict(schema=receipts.SCHEMA, region=root.name, stage='package', scope=None,
                        status='ok', generation='a' * 64, outputs=[], upstream=[], attempt=1)
            return MemoryArtifact(receipts.canonical(data))
        raise FileNotFoundError('synthetic missing artifact')

    monkeypatch.setattr(package, 'artifact_path', read_artifact)
    return reads


class MemoryArtifact:
    def __init__(self, data):
        self.data = data

    def read_bytes(self):
        return self.data


@pytest.mark.parametrize(('batch', 'regions', 'check_membership'), [
    ('central-r8-1', ['big-sur-coast', 'cambria-san-simeon', 'south-big-sur-san-simeon'], False),
    ('central-r8-2', ['monterey-point-sur', 'point-arguello-conception', 'santa-cruz-monterey-bay'], True),
])
def test_committed_batches_replay_in_r8(batch, regions, check_membership, tmp_path, capsys, artifact_reads):
    # A sorted, default, or malformed argv could select the wrong intake or never reach the consumer.
    out = tmp_path.resolve() / 'synthetic OUT'
    request = ['--batch', batch, '--out', str(out)]
    if check_membership:
        request += ['--regions', *regions]
    assert central_r8_request.main(request) == 0
    emitted = capsys.readouterr()
    argv = json.loads(emitted.out)
    assert emitted.err == ''
    assert argv == ['python', 'scripts/relief/r8_packet.py', '--out', str(out), *regions]
    assert artifact_reads == []
    assert not out.exists()

    # The real parser and envelope lookup run; the only stand-in is artifact access.
    assert r8_packet.main(argv[2:]) == 1  # synthetic envelope is intentionally absent
    replay = capsys.readouterr()
    assert replay.err == ''
    assert replay.out.splitlines() == [f'NOT READY {r}: synthetic missing artifact' for r in regions]
    assert artifact_reads == [
        (out / r, path) for r in regions
        for path in ('stages/package.json', f'review/{"a" * 64}/envelope.json')
    ]
    assert not out.exists()


@pytest.mark.parametrize(('extra', 'reason'), [
    (['--regions', 'big-sur-coast'], 'full ordered membership'),  # subset silently accepted
    (['--regions', 'cambria-san-simeon', 'big-sur-coast', 'south-big-sur-san-simeon'],
     'full ordered membership'),  # set comparison loses order
    (['--regions', 'big-sur-coast', 'cambria-san-simeon', 'big-sur-coast'],
     'full ordered membership'),  # length alone accepts a duplicate
    (['--batch', 'central-r8-2'], 'only once'),  # last batch wins
    (['--out', './other-synthetic-out'], 'only once'),  # last OUT wins
    (['--regions', 'big-sur-coast', '--regions', 'cambria-san-simeon'], 'only once'),  # repeated override
])
def test_refuses_partial_or_ambiguous_overrides(extra, reason, tmp_path, capsys, artifact_reads):
    with pytest.raises(SystemExit) as caught:
        central_r8_request.main(['--batch', 'central-r8-1', '--out', str(tmp_path / 'out'), *extra])
    assert caught.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ''
    assert reason in captured.err
    assert artifact_reads == []


@pytest.mark.parametrize(('options', 'reason'), [
    (['--out', './synthetic-out'], '--batch'),  # default batch
    (['--batch', 'central-r8-1'], '--out'),  # default artifact root
    (['--batch', 'unknown', '--out', './synthetic-out'], 'unknown Central batch'),  # silent fallback
    (['--batch', 'central-r8-1', '--out', 'https://example.invalid/out'], 'local path'),  # remote OUT
])
def test_requires_explicit_batch_and_local_out(options, reason, capsys, artifact_reads):
    with pytest.raises(SystemExit) as caught:
        central_r8_request.main(options)
    assert caught.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ''
    assert reason in captured.err
    assert artifact_reads == []


@pytest.mark.parametrize(('defect', 'reason'), [
    ('duplicate-member', 'repeated Central region ID'),  # duplicate disguised by a matching template
    ('cross-batch-member', 'repeated Central region ID'),  # validating only the selected row misses overlap
    ('duplicate-batch-id', 'duplicate Central batch ID'),  # dictionary assignment masks ambiguity
    ('too-many-members', 'one to three Central region IDs'),  # oversized packet emitted before R8 rejects it
    ('template-order', 'ordered batch membership'),  # stale fixture template overrides authoritative order
    ('noncentral-member', 'not a Central region ID'),  # an arbitrary region slug passes a shape check
])
def test_bad_roster_emits_no_argv_and_requests_no_artifact(defect, reason, tmp_path, monkeypatch,
                                                             capsys, artifact_reads):
    roster = Path('docs/operations/fixtures/relief-central-r8-batches.json')
    doc = json.loads((ROOT / roster).read_text(encoding='utf-8'))
    first, second = doc['batches']
    if defect == 'duplicate-batch-id':
        second['id'] = first['id']
    elif defect == 'cross-batch-member':
        second['regions'][0] = first['regions'][0]
        second['packet_argv'][4:] = second['regions']
    elif defect == 'template-order':
        first['packet_argv'][-2:] = reversed(first['packet_argv'][-2:])
    else:
        if defect == 'duplicate-member':
            first['regions'][2] = first['regions'][0]
        elif defect == 'too-many-members':
            first['regions'].append(second['regions'][0])
        else:
            first['regions'][0] = 'synthetic-noncentral'
        first['packet_argv'][4:] = first['regions']
    sandbox_roster = tmp_path / roster.name
    sandbox_roster.write_text(json.dumps(doc), encoding='utf-8')
    monkeypatch.setattr(central_r8_request, '_ROSTER', sandbox_roster)

    with pytest.raises(SystemExit) as caught:
        central_r8_request.main(['--batch', 'central-r8-1', '--out', str(tmp_path / 'out')])
    assert caught.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ''
    assert reason in captured.err
    assert artifact_reads == []
