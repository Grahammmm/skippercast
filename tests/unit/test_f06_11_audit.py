"""SCA-265 / F06-11: the 32 KiB bound covers the adopted manifest fields up front.

Contract: with a managed store, import_retained sizes the final-equivalent source-free
manifest (including saved_area_adoption and execution_grant_identity) before it copies or
registers its first retained artifact. Believable bug: sizing only the ordinary manifest lets
an adopted manifest that is too large pass the forecast, copy artifacts and spend
reservations, and only then fail in write_artifact. Heavy validators are replaced by small
fakes; the producer database is a real read-only SQLite file. The positive control completes
the whole import (real file copies, real manifest write bounded at 32 KiB, real SQLite
registration) and validates the registered manifest with the real source_free.validate_input;
only saved_area.validate_adoption, which needs a full production saved-area mission fixture, is
a fake that returns the recorded adoption.
"""
import contextlib
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from skippercast.coastal.authenticated_v1 import profiles
from skippercast.coastal.coordinator import saved_area, source_free
from skippercast.coastal.handoff import common

CAP = 32768
LABEL = 'sourcefree manifest'
IDENTITY = dict(stage='qualify', segment_id='seg', code_sha='c', deps_sha='d', params_sha='p', input_manifest_sha='i')


class Reached(Exception):
    """Raised by the fake managed writer: the size preflight passed and copying began."""


class Writer:
    def __init__(self, root, stop):
        self.root = root
        self.stop = stop
        self.copies = 0

    def relative_path(self, target):
        return target.relative_to(self.root)

    def write_bytes(self, relative, data, **kwargs):
        self.copies += 1
        if self.stop:
            raise Reached
        assert len(data) <= kwargs['max_bytes']
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


class Store:
    def __init__(self, root, grant, stop=True):
        self.root = root
        self.policy = {'managed_output_grant': grant}
        self.managed_outputs = Writer(root, stop)
        self.registered = []
        self.db = sqlite3.connect(root.parent / (root.name + '.sqlite'), isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(source_free.SCHEMA + 'CREATE TABLE events(utc,job_id,kind,detail_json);')
        self.db.execute(saved_area.SCHEMA)

    def write_artifact(self, path, value, *, max_bytes=131072, **kwargs):
        # Managed writers refuse a document over its bound; mirror that for the real manifest.
        if len(json.dumps(value, sort_keys=True, separators=(',', ':'))) + 1 > max_bytes:
            raise ValueError('managed artifact over its byte bound')
        self.registered.append(path)
        common.write(path, value)

    def add_segment(self, record):
        pass

    def event(self, job_id, kind, detail):
        self.db.execute('INSERT INTO events VALUES(0,?,?,?)', (job_id, kind, json.dumps(detail)))

    @contextlib.contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise


@pytest.fixture
def run(tmp_path, monkeypatch):
    origin = (tmp_path / 'origin').resolve()
    (origin / 'var').mkdir(parents=True)
    body = b'{}'
    body_sha = hashlib.sha256(body).hexdigest()
    for name in ('a.json', 'packet.json', 'g.json'):
        (origin / 'var' / name).write_bytes(body)
    result_path = 'var/coastal/jobs/j-1/L/output/result.json'
    qualified = dict(path=result_path, sha256='r' * 64, bytes=2, contract='coastal-authenticated-stage-result-v1')
    artifact = dict(path='var/a.json', sha256=body_sha, bytes=2, contract='coastal-retained-support-v1')
    parent = dict(name='parent', source='src', window_count=4, window_side=128, window_set=['w'],
                  execution_profile=profiles.CONTAINED)
    db = origin / 'producer.sqlite'
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE jobs(job_id,state,stage,result_sha,record_json)')
    con.execute('CREATE TABLE authenticated_artifacts(job_id,path,sha256,bytes,contract,committed_result_sha,lease_token)')
    record = dict(execution_contract='coastal-authenticated-job-v1', job_id='j:1', source_domain_grant=parent, **IDENTITY)
    con.execute('INSERT INTO jobs VALUES(?,?,?,?,?)', ('j:1', 'done', 'qualify', qualified['sha256'], json.dumps(record)))
    con.execute('INSERT INTO authenticated_artifacts VALUES(?,?,?,?,?,?,?)',
                ('j:1', artifact['path'], artifact['sha256'], 2, artifact['contract'], qualified['sha256'], 'L'))
    con.commit()
    con.close()

    packet_ref = dict(path='var/packet.json', sha256=body_sha, bytes=2, contract='coastal-terrain-only-input-v1')
    plan = dict(side=128, packets=[packet_ref], parent_grant=dict(path='var/g.json', sha256=body_sha, bytes=2,
                contract='coastal-authenticated-policy-v1'), segment=dict(path='var/s.json'), baselines=[])
    docs = {'coastal-contained-mapping-plan-v1': plan, 'coastal-authenticated-policy-v1': dict(identity=parent),
            'coastal-segment-v1': dict(segment_id='seg')}
    item = dict(packet=dict(synthetic=True, qualified_result=qualified), result_ref=qualified,
                facts=dict(header=dict(window='w')))
    real_load = source_free.load
    # The plan, parent grant and segment are stand-ins; the manifest and proofs the import writes are loaded for real.
    monkeypatch.setattr(source_free, 'load',
                        lambda root, value, contract=None: docs[contract] if contract in docs else real_load(root, value, contract=contract))
    monkeypatch.setattr(source_free.contained_batch, '_prepare',
                        lambda *a, **k: ([item], [dict(native_window='w', source='src', segment_id='seg')]))
    result = dict(job_id='j:1', lease_token='L', artifacts=[artifact], **IDENTITY)
    monkeypatch.setattr(source_free, '_copy_refs', lambda *a: (result, [artifact]))
    monkeypatch.setattr(profiles, 'grant_identity', lambda doc: doc['identity'])
    current = {}

    def fake_validate_adoption(root, descriptor, grant, **k):
        # Stand-in for the deep saved-area mission validation: bind it to the exact registered inputs.
        assert grant == current['grant'] and descriptor == current['adoption']['adoption']
        return current['adoption']
    monkeypatch.setattr(saved_area, 'validate_adoption', fake_validate_adoption)
    sizes = []
    real = source_free._managed_metadata_bytes
    monkeypatch.setattr(source_free, '_managed_metadata_bytes',
                        lambda value, label: (sizes.append(len(real(value, label))) if label == LABEL else None) or real(value, label))
    count = []

    def call(pad, where, complete=False):
        fresh = (tmp_path / ('fresh%d' % len(count))).resolve()
        count.append(fresh)
        fresh.mkdir()
        adoption = dict(origin_root=str(origin), fresh_review_root=str(fresh), adoption=dict(path='x'),
                        original_grant_identity=parent, qualified_result=qualified,
                        pad='x' * pad if where == 'adoption' else '')
        execution = dict(name='execution', pad='x' * pad if where == 'grant' else '')
        grant = dict(identity=execution)
        current.update(adoption=adoption, grant=grant)
        store = Store(fresh, grant, stop=not complete)
        store.db.execute('INSERT INTO saved_area_adoptions VALUES(?,?,?)',     # as import_adopted registers it
                         (source_free.digest(grant), 'x', json.dumps(adoption, sort_keys=True)))
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        deadline = now + timedelta(seconds=60)
        try:
            descriptor = source_free.import_retained(store, source_root=origin, source_db=db,
                    plan_ref=dict(path='p', sha256='p' * 64), now=now, deadline=deadline, adoption=adoption)
        except Reached:
            return store, 'reached'
        except ValueError as error:
            return store, str(error)
        if not complete:
            raise AssertionError('import_retained neither copied nor refused')
        return store, (descriptor, now, deadline)
    call.sizes = sizes
    return call


@pytest.mark.parametrize('where', ['adoption', 'grant'])
def test_only_the_added_fields_over_cap_refuse_before_first_copy(run, where):
    _, outcome = run(0, where)
    assert outcome == 'reached'                      # in-bound adoption passes the preflight
    base = run.sizes[-1]
    assert base < CAP

    store, outcome = run(CAP - base, where)           # exactly at the cap: still accepted
    assert outcome == 'reached' and run.sizes[-1] == CAP

    store, outcome = run(CAP - base + 1, where)       # one byte over, caused only by adoption/grant fields
    assert 'managed sourcefree manifest32KiB bound before import' in outcome
    assert store.managed_outputs.copies == 0 and store.registered == []


@pytest.mark.parametrize('where', ['adoption', 'grant'])
@pytest.mark.parametrize('at_cap', [False, True])
def test_in_bound_adoption_completes_import_and_validates(run, where, at_cap):
    """Positive control: the whole import runs, then validate_input accepts the registered manifest."""
    run(0, where)
    base = run.sizes[-1]
    store, (descriptor, now, deadline) = run(CAP - base if at_cap else 0, where, complete=True)
    assert store.managed_outputs.copies == 3
    assert descriptor['bytes'] == run.sizes[-1] == (CAP if at_cap else base)   # forecast equals the written manifest

    document, items = source_free.validate_input(store, descriptor, now=now, horizon=deadline)
    assert document['saved_area_adoption']['original_grant_identity']['name'] == 'parent'
    assert document['execution_grant_identity'] == store.policy['managed_output_grant']['identity']
    assert len(items) == 1 and len(document['imported_artifacts']) == 3
    assert store.db.execute('SELECT COUNT(*) FROM sourcefree_imports').fetchone()[0] == 1
