"""SCA-265 / F06-11: the 32 KiB bound covers the adopted manifest fields up front.

Contract: with a managed store, import_retained sizes the final-equivalent source-free
manifest (including saved_area_adoption and execution_grant_identity) before it copies or
registers its first retained artifact. Believable bug: sizing only the ordinary manifest lets
an adopted manifest that is too large pass the forecast, copy artifacts and spend
reservations, and only then fail in write_artifact. Heavy validators are replaced by small
fakes; the producer database is a real read-only SQLite file.
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from skippercast.coastal.authenticated_v1 import profiles
from skippercast.coastal.coordinator import saved_area, source_free

CAP = 32768
LABEL = 'sourcefree manifest'
IDENTITY = dict(stage='qualify', segment_id='seg', code_sha='c', deps_sha='d', params_sha='p', input_manifest_sha='i')


class Reached(Exception):
    """Raised by the fake managed writer: the size preflight passed and copying began."""


class Writer:
    def __init__(self):
        self.copies = 0

    def relative_path(self, target):
        return target.name

    def write_bytes(self, *args, **kwargs):
        self.copies += 1
        raise Reached


class Store:
    def __init__(self, root, grant):
        self.root = root
        self.policy = {'managed_output_grant': grant}
        self.managed_outputs = Writer()
        self.registered = []

    def write_artifact(self, *args, **kwargs):
        self.registered.append(args)

    add_segment = write_artifact


@pytest.fixture
def run(tmp_path, monkeypatch):
    origin = (tmp_path / 'origin').resolve()
    fresh = (tmp_path / 'fresh').resolve()
    origin.mkdir()
    fresh.mkdir()
    blob = origin / 'blob.json'
    blob.write_bytes(b'{}')
    result_path = 'var/coastal/jobs/j-1/L/output/result.json'
    qualified = dict(path=result_path, sha256='r' * 64, bytes=2, contract='coastal-authenticated-stage-result-v1')
    artifact = dict(path='var/a.json', sha256='a' * 64, bytes=2, contract='coastal-retained-support-v1')
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

    packet_ref = dict(path='var/packet.json', sha256='b' * 64, bytes=2, contract='coastal-terrain-only-input-v1')
    plan = dict(side=128, packets=[packet_ref], parent_grant=dict(path='var/g.json', sha256='g' * 64, bytes=2,
                contract='coastal-authenticated-policy-v1'), segment=dict(path='var/s.json'), baselines=[])
    docs = {'coastal-contained-mapping-plan-v1': plan, 'coastal-authenticated-policy-v1': dict(identity=parent),
            'coastal-segment-v1': dict(segment_id='seg')}
    item = dict(packet=dict(synthetic=True, qualified_result=qualified), result_ref=qualified,
                facts=dict(header=dict(window='w')))
    monkeypatch.setattr(source_free, 'load', lambda root, value, contract=None: docs[contract])
    monkeypatch.setattr(source_free, 'resolve', lambda *a, **k: blob)
    monkeypatch.setattr(source_free.contained_batch, '_prepare',
                        lambda *a, **k: ([item], [dict(native_window='w', source='src', segment_id='seg')]))
    result = dict(job_id='j:1', lease_token='L', artifacts=[artifact], **IDENTITY)
    monkeypatch.setattr(source_free, '_copy_refs', lambda *a: (result, [artifact]))
    monkeypatch.setattr(profiles, 'grant_identity', lambda doc: doc['identity'])
    current = {}
    monkeypatch.setattr(saved_area, 'validate_adoption', lambda root, descriptor, grant, **k: current['adoption'])
    sizes = []
    real = source_free._managed_metadata_bytes
    monkeypatch.setattr(source_free, '_managed_metadata_bytes',
                        lambda value, label: (sizes.append(len(real(value, label))) if label == LABEL else None) or real(value, label))

    def call(pad, where):
        adoption = dict(origin_root=str(origin), fresh_review_root=str(fresh), adoption=dict(path='x'),
                        original_grant_identity=parent, pad='x' * pad if where == 'adoption' else '')
        execution = dict(name='execution', pad='x' * pad if where == 'grant' else '')
        current['adoption'] = adoption
        store = Store(fresh, dict(identity=execution))
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        try:
            source_free.import_retained(store, source_root=origin, source_db=db, plan_ref=dict(path='p'), now=now,
                                        deadline=now + timedelta(seconds=60), adoption=adoption)
        except Reached:
            return store, 'reached'
        except ValueError as error:
            return store, str(error)
        raise AssertionError('import_retained neither copied nor refused')
    call.sizes = sizes
    return call


@pytest.mark.parametrize('where', ['adoption', 'grant'])
def test_only_the_added_fields_over_cap_refuse_before_first_copy(run, where):
    _, outcome = run(0, where)
    assert outcome == 'reached'                      # positive control: in-bound adoption passes the preflight
    base = run.sizes[-1]
    assert base < CAP

    store, outcome = run(CAP - base, where)           # exactly at the cap: still accepted
    assert outcome == 'reached' and run.sizes[-1] == CAP

    store, outcome = run(CAP - base + 1, where)       # one byte over, caused only by adoption/grant fields
    assert 'managed sourcefree manifest32KiB bound before import' in outcome
    assert store.managed_outputs.copies == 0 and store.registered == []
