"""PR854 six-finding regressions; exclusively owned synthetic temporary roots."""
import copy
import os
from pathlib import Path
import sqlite3
import stat

import pytest

from tests.gis.test_coast_segment_close import (
    ARCHIVE, QUEUE, HEAD, Closed, archive_segment, cache_files, close_common,
    closed, exclusive_synthetic_campaign, ledger_module, manifest_of, refs,
    release_args, release_hot_cache,
)

pytestmark = pytest.mark.gis


@pytest.mark.parametrize('operation', ['archive', 'release'])
@pytest.mark.parametrize('cause', ['controller', 'close', 'ownership', 'lease-active', 'lease-expired', 'running', 'queued'])
def test_quiescence_refusals(closed, monkeypatch, operation, cause):
    import fcntl
    from skippercast.coastal.coordinator.store import SCHEMA
    f = closed
    if operation == 'release':
        f.archive_now()
        out, digest, _ = f.write_list()
    root = f.queue / 'var/coastal'
    root.mkdir(parents=True, exist_ok=True)
    held = None
    if cause in ('controller', 'close'):
        path = root / 'coordinator.lock' if cause == 'controller' else f.queue / 'close.lock'
        held = path.open('a')
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        reason = 'exclusive writer lock unavailable'
    elif cause == 'ownership':
        monkeypatch.delenv('COAST_EXCLUSIVE_WRITER')
        reason = 'exclusive writer assertion absent'
    else:
        with sqlite3.connect(root / 'coordinator.sqlite') as db:
            db.executescript(SCHEMA)
            db.execute("INSERT INTO jobs(job_id,segment_id,stage,idempotency_key,state,max_attempts,created,record_json) VALUES(?,?,?,?,?,?,?,?)",
                       ('job:synthetic', 'seg:3310:0:0:5000', 'map', 'synthetic',
                        'done' if cause.startswith('lease-') else cause, 1, 1, '{}'))
            if cause.startswith('lease-'):
                db.execute('INSERT INTO leases VALUES(?,?,?,?,?,?)',
                           ('job:synthetic', 'synthetic', '{}', None, 0 if cause == 'lease-expired' else 10**12, 0))
        reason = 'leases present' if cause.startswith('lease-') else 'consumer'
    before = {p: p.read_bytes() for p in cache_files(f)}
    ledger_before = f.ledger.read_bytes()
    store_before = {p: (p.read_bytes(), p.stat().st_ino) for p in root.glob('coordinator.sqlite*')}
    try:
        with pytest.raises(close_common.Refused, match=reason):
            f.archive_now() if operation == 'archive' else release_hot_cache.release(f.bindings, **release_args(f, out, digest))
    finally:
        if held:
            held.close()
    assert before == {p: p.read_bytes() for p in before}
    assert f.ledger.read_bytes() == ledger_before
    assert store_before == {p: (p.read_bytes(), p.stat().st_ino) for p in root.glob('coordinator.sqlite*')}


@pytest.mark.parametrize('wal', [False, True])
def test_quiet_store_read_has_no_source_side_effects(closed, wal):
    from skippercast.coastal.coordinator.store import SCHEMA
    f = closed
    root = f.queue / 'var/coastal'
    root.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(root / 'coordinator.sqlite') as db:
        db.executescript(SCHEMA)
        if wal:
            db.execute('PRAGMA journal_mode=WAL')
    db.close()
    def inventory():
        entries = {}
        for path in [root, *root.rglob('*')]:
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                value = ('symlink', info.st_ino, info.st_mode, os.readlink(path))
            elif stat.S_ISDIR(info.st_mode):
                children = sorted(p.name for p in path.iterdir()
                                  if not (path == root and p.name == 'coordinator.lock'))
                value = ('directory', info.st_ino, info.st_mode, children)
            else:
                assert stat.S_ISREG(info.st_mode)
                value = ('file', info.st_ino, info.st_mode, path.read_bytes())
            entries[path.relative_to(root)] = value
        return entries
    before = inventory()
    f.archive_now()
    after = inventory()
    assert before == {p: after[p] for p in before}
    assert set(after) == set(before) | {Path('coordinator.lock')}
    assert after[Path('coordinator.lock')][0] == 'file'


@pytest.mark.parametrize('boundary', ['segment', 'campaign', 'segment-snapshot', 'campaign-snapshot'])
def test_crash_prefix_reconciliation(closed, monkeypatch, boundary):
    f = closed
    original_append = ledger_module.append
    original_write = archive_segment.write_retained
    def append(path, *args, **kwargs):
        if Path(path) == (f.ledger if boundary == 'segment' else f.campaign_ledger) and boundary in ('segment', 'campaign'):
            raise OSError('synthetic append boundary')
        return original_append(path, *args, **kwargs)
    def write(root, relative, raw):
        if relative == (close_common.SEGMENT_SNAPSHOT if boundary == 'segment-snapshot' else close_common.CAMPAIGN_SNAPSHOT) and boundary.endswith('snapshot'):
            raise OSError('synthetic snapshot boundary')
        return original_write(root, relative, raw)
    monkeypatch.setattr(ledger_module, 'append', append)
    monkeypatch.setattr(archive_segment, 'write_retained', write)
    with pytest.raises(OSError, match='synthetic'):
        f.archive_now()
    assert (f.archive / close_common.MANIFEST).exists()
    before = {p: p.read_bytes() for p in f.archive.rglob('*') if p.is_file()}
    with pytest.raises(close_common.Refused, match='runtime payload differs'):
        archive_segment.archive(f.resolver(), campaign_path=f.campaign_path, ledger=f.ledger,
                                campaign_ledger=f.campaign_ledger, head=dict(HEAD, created_utc='2026-10-24T00:00:00Z'),
                                reserve_bytes=0, close_id='close01')
    monkeypatch.setattr(ledger_module, 'append', original_append)
    monkeypatch.setattr(archive_segment, 'write_retained', original_write)
    first = f.archive_now()
    assert f.archive_now() == first
    assert before == {p: p.read_bytes() for p in before}
    assert len(ledger_module.verify(f.ledger)) == len(ledger_module.verify(f.campaign_ledger)) == 3
    assert f.verify()['total_files'] >= 1


@pytest.mark.parametrize('cause', ['receipt', 'journal', 'intent', 'reservation', 'marker', 'after-marker', 'final-write'])
def test_release_accounting_failures(closed, monkeypatch, cause):
    f = closed
    f.archive_now()
    out, digest, _ = f.write_list()
    target = out.with_name('release-receipt.json')
    journal = out.with_name('release-accounting')
    before = {p: p.read_bytes() for p in cache_files(f)}
    if cause == 'receipt':
        target.write_bytes(b'old evidence\n')
    if cause == 'journal':
        journal.mkdir()
    original_write = release_hot_cache.write_once
    def write(path, value):
        if ((cause == 'intent' and path.name == 'intent.json') or (cause == 'marker' and path.name.endswith('-before.json'))
                or (cause == 'after-marker' and path.name.endswith('-after.json'))):
            raise OSError('synthetic journal failure')
        return original_write(path, value)
    monkeypatch.setattr(release_hot_cache, 'write_once', write)
    original_open = os.open
    original_os_write = os.write
    def open_file(path, *args, **kwargs):
        if cause == 'reservation' and path == 'release-receipt.json':
            raise PermissionError('synthetic unwritable receipt')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(os, 'open', open_file)
    def write_fd(fd, data):
        if cause == 'final-write' and bytes(data).startswith(b'{"archive_metrics"'):
            raise OSError('synthetic final receipt failure')
        return original_os_write(fd, data)
    monkeypatch.setattr(os, 'write', write_fd)
    if cause in ('marker', 'after-marker'):
        receipt, _ = release_hot_cache.release(f.bindings, **release_args(f, out, digest))
        assert receipt['status'] == 'partial'
        assert bool(receipt['released']) == (cause == 'after-marker')
    else:
        with pytest.raises((OSError, close_common.Refused)):
            release_hot_cache.release(f.bindings, **release_args(f, out, digest))
    if cause in ('final-write', 'after-marker'):
        assert not cache_files(f)
        assert refs.loads((journal / 'intent.json').read_bytes())['release_list_sha256'] == digest
        if cause == 'final-write':
            assert refs.loads((journal / '000000-after.json').read_bytes())['status'] == 'unlinked'
        else:
            assert refs.loads((journal / '000000-before.json').read_bytes())['status'] == 'pending'
            assert not (journal / '000000-after.json').exists()
    else:
        assert before == {p: p.read_bytes() for p in before}
    if cause == 'receipt':
        assert target.read_bytes() == b'old evidence\n'


def test_metrics_known_bytes_and_aliases():
    def item(path, retained, size, root=ARCHIVE):
        return dict(source_ref=dict(root_id=QUEUE, path=path, sha256='a'*64, bytes=size),
                    retained_ref=dict(root_id=root, path=retained, sha256='a'*64, bytes=size))
    manifest = dict(files=[item('cache/raw', 'raw.bin', 7, 'raw:campaign'),
                           item('cache/raw-alias', 'raw.bin', 7, 'raw:campaign'),
                           item('cache/derived', 'inputs/derived', 11),
                           item('var/coastal/jobs/map/lease/output/terrain.tif', 'products/terrain', 13),
                           item('plans/admission.json', 'queue/admission.json', 17)],
                    cache_candidates=[dict(size=7), dict(size=7), dict(size=11)])
    metrics = close_common.archive_metrics(manifest)
    assert metrics['archived_bytes'] == dict(raw_equivalent=7, derived=11, products=13, metadata=17)
    assert metrics['proposed_release_bytes'] == 25
    assert metrics['peak_hot_cache']['status'] == 'unavailable' and metrics['peak_hot_cache']['bytes'] is None


def test_diagnostic_history_then_corrected_accept_closes(tmp_path):
    from tests.gis.test_coast_sign_off_graph import Cycle, prepare, opener, writer
    c = Cycle(tmp_path).round()
    context = copy.deepcopy(c.context)
    context.update(admission=None, attempt=2, supersedes=c.context_ref, mode='diagnostic',
                   observations=[dict(code='POSTED_SHA_ABSENT', path='admission', expected='independent posted Ref', observed=None)])
    attempt = c.r.parent / 'a02'
    (attempt / 'tier3').mkdir(parents=True)
    context_ref, diagnostic = prepare.prepare(c.resolver, context, 1, 2, attempt / 'context.json')
    assert diagnostic
    report, code = opener.open_packet(c.resolver, context_ref, c.path(c.packet_ref), c.packet_ref['sha256'],
                                      'synthetic-reviewer', c.reviewer_ref, attempt / 'tier3/open-report.json')
    assert code == 3
    result = writer.write_verdict(c.resolver, context_ref, report, c.decisions(), 1,
                                  attempt / 'tier3/verdict.json', c.queue / 'ledger.jsonl', c.queue.parent / 'campaign-ledger.jsonl')
    c.previous_context, c.previous_verdict = context_ref, result['verdict']
    c.round(number=2)
    assert c.open() == 0
    c.write(c.decisions())
    f = Closed.__new__(Closed)
    f.queue, f.raw, f.tmp = c.queue, Path(c.bindings['raw:campaign']), tmp_path
    f.archive = tmp_path / 'closed-diagnostic'
    f.archive.mkdir()
    f.bindings = dict(c.bindings, **{ARCHIVE: str(f.archive)})
    f.ledger, f.campaign_ledger = c.queue / 'ledger.jsonl', c.queue.parent / 'campaign-ledger.jsonl'
    f.campaign_path = c.path(c.instances['admission']['campaign'])
    f.archive_now()
    before = c.queue.with_name('queue-unavailable')
    c.queue.rename(before)
    try:
        assert f.verify()['total_files'] >= 1
    finally:
        before.rename(c.queue)
    assert any(i['source_ref'] == context_ref for i in manifest_of(f)['files'])


def test_normal_historical_ref_corruption_still_refuses(closed):
    f = closed
    first = ledger_module.verify(f.ledger)[0]
    context = refs.loads(f.resolver().read(first['context']))
    target = f.queue / context['run']['path']
    target.write_bytes(target.read_bytes() + b' ')
    before = f.ledger.read_bytes()
    with pytest.raises(ValueError, match='mismatch'):
        f.archive_now()
    assert f.ledger.read_bytes() == before
    assert not (f.archive / close_common.MANIFEST).exists()


@pytest.mark.parametrize('case', ['diagnostic', 'diagnostic-corrupt', 'normal-corrupt', 'diagnostic-root', 'current-corrupt'])
def test_supersedes_preserves_edge_roles(tmp_path, case):
    from tests.gis.test_coast_sign_off_graph import Cycle, prepare, validator
    c = Cycle(tmp_path).round()
    if case == 'normal-corrupt':
        previous = c.context_ref
    else:
        diagnostic = copy.deepcopy(c.context)
        diagnostic.update(admission=None, attempt=2, supersedes=c.context_ref, mode='diagnostic',
                          observations=[dict(code='POSTED_SHA_ABSENT', path='admission',
                                             expected='independent posted Ref', observed=None)])
        attempt = c.r.parent / 'a02'
        attempt.mkdir()
        previous, is_diagnostic = prepare.prepare(c.resolver, diagnostic, 1, 2, attempt / 'context.json')
        assert is_diagnostic
    current = copy.deepcopy(c.context)
    current.update(review_round=2, supersedes=previous)
    if case == 'diagnostic-root':
        with pytest.raises(ValueError, match='diagnostic context is not a full-graph scientific input'):
            validator.GraphValidator(c.resolver).reference(previous, contract='coast-review-context-v1')
        return
    if case == 'diagnostic-corrupt':
        target = c.path(previous)
    elif case in ('normal-corrupt', 'current-corrupt'):
        target = c.path(c.context['run'])
    else:
        target = None
    if target is not None:
        raw = target.read_bytes()
        target.write_bytes(raw[:-1] + (b' ' if raw[-1:] != b' ' else b'\n'))
        with pytest.raises(ValueError, match='mismatch'):
            validator.validate(current, c.resolver, root_id=QUEUE)
    else:
        assert validator.validate(current, c.resolver, root_id=QUEUE) == current


@pytest.mark.parametrize('case', ['anchored', 'reordered', 'diagnostic-corrupt',
                                  'normal-history-corrupt', 'unanchored', 'cached-unanchored'])
def test_open_report_recovers_only_anchored_diagnostic_roles(tmp_path, case):
    from tests.gis.test_coast_sign_off_graph import Cycle, prepare, validator, opener, writer
    c = Cycle(tmp_path).round()
    normal_ref = c.context_ref
    normal_run = c.context['run']
    diagnostic = copy.deepcopy(c.context)
    diagnostic.update(admission=None, attempt=2, supersedes=normal_ref, mode='diagnostic',
                      observations=[dict(code='POSTED_SHA_ABSENT', path='admission',
                                         expected='independent posted Ref', observed=None)])
    attempt = c.r.parent / 'a02'
    attempt.mkdir()
    previous, is_diagnostic = prepare.prepare(c.resolver, diagnostic, 1, 2, attempt / 'context.json')
    assert is_diagnostic
    if case not in ('unanchored', 'cached-unanchored'):
        (attempt / 'tier3').mkdir()
        report_ref, code = opener.open_packet(c.resolver, previous, c.path(c.packet_ref), c.packet_ref['sha256'],
                                              'synthetic-reviewer', c.reviewer_ref, attempt / 'tier3/open-report.json')
        assert code == 3
        result = writer.write_verdict(c.resolver, previous, report_ref, c.decisions(), 1,
                                      attempt / 'tier3/verdict.json', c.queue / 'ledger.jsonl',
                                      c.queue.parent / 'campaign-ledger.jsonl')
        c.previous_verdict = result['verdict']
        c.previous_context = previous
        c.round(number=2)
    assert c.open() == 0
    report = refs.loads(c.resolver.read(c.report_ref))
    if case in ('unanchored', 'cached-unanchored'):
        assert previous not in report['verified_refs']
        report['verified_refs'].append(previous)
    else:
        assert previous in report['verified_refs']
    # Even a normal historical context listed alongside the diagnostic one
    # remains a scientific edge, not an identity-table exemption.
    report['verified_refs'].append(normal_ref)
    graph = validator.GraphValidator(c.resolver)
    if case == 'cached-unanchored':
        graph.reference(previous, scope='identity_snapshot', contract='coast-review-context-v1')
    if case == 'reordered':
        report = dict(verified_refs=report.pop('verified_refs'), **report)
    if case in ('diagnostic-corrupt', 'normal-history-corrupt'):
        target = c.path(previous if case == 'diagnostic-corrupt' else normal_run)
        raw = target.read_bytes()
        target.write_bytes(raw[:-1] + (b' ' if raw[-1:] != b' ' else b'\n'))
        with pytest.raises(ValueError, match='mismatch'):
            graph.document(report, root_id=QUEUE)
    elif case in ('unanchored', 'cached-unanchored'):
        with pytest.raises(ValueError, match='diagnostic context is not a full-graph scientific input'):
            graph.document(report, root_id=QUEUE)
    else:
        graph.document(report, root_id=QUEUE)
