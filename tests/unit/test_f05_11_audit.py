"""F05-11: status must not treat an elapsed review as a request for fresh science."""
from contextlib import closing
import json

import pytest

from skippercast.coastal.coordinator import ordered_trial as ot, saved_area as sa


DEADLINE = 4600


@pytest.fixture
def continuation(tmp_path):
    # Seed only the outcome of an earlier adoption, not a real producer/archive.
    root = tmp_path.resolve()
    (root / 'metadata').mkdir()
    windows = [[0, 128, 128, 128], [128, 128, 128, 128], [0, 0, 128, 128], [128, 0, 128, 128]]
    adoption = dict(path='metadata/adoption.json', sha256='a' * 64, bytes=42, contract=sa.ADOPTION)
    grant = dict(schema='coastal-authenticated-policy-v1', source=dict(bytes=36757568),
                 source_root=str(root / 'synthetic-source'), source_relative_path='synthetic.bag',
                 execution_profile=ot.CONTAINED, window_side=128, window_count=4, window_set=windows,
                 saved_area_continuation_contract=sa.CONTRACT, saved_area_adoption=adoption,
                 ordered_scope_contract=ot.LARGER_SCOPE, geographic_review={}, output_root=str(root),
                 output_retention=dict(profile='coastal-managed-output-32-v2'),
                 larger_runtime_contract=ot.LARGER_RUNTIME, source_volume_cap_bytes=220545408,
                 prior_effective_bytes=895006524, cumulative_limit_bytes=1115551932)
    grant_path = root / 'metadata/grant.json'
    ot.write(grant_path, grant)
    grant_ref = ot.ref(root, grant_path, grant['schema'])
    proof = dict(schema=sa.ADOPTION, adoption=adoption, window=windows[0], source=grant['source'],
                 execution_grant_sha=ot.digest(grant))
    ctl = object.__new__(ot.Controller)  # Start at the status/action boundary with a prepared parent.
    ctl.root = root
    ctl.path = root / 'ordered.json'
    ctl.descriptor = {'sha256': 'b' * 64}
    ctl.preparation = dict(grant=grant_ref, grant_identity=ot.grant_identity(grant), window_set=windows,
                           saved_area_continuation_contract=sa.CONTRACT, saved_area_adoption=adoption,
                           deadline_epoch=DEADLINE, source_cutoff_epoch=3400, native_clock_bound=True,
                           output_roots=[str(root)], scratch_roots=[], output_cap_bytes=1048576, scratch_cap_bytes=1)
    action_path = root / 'action.json'
    ot.write(action_path, dict(schema=ot.ACTION, preparation=ctl.descriptor, stage='acquire', index=1))
    action = ot.ref(root, action_path, ot.ACTION)
    ctl.clock = lambda: DEADLINE + 1
    policy = dict(watermarks=dict(low=1, high=2, held_cap=1), worker_network=False)
    with closing(ot.Store(root / 'native.sqlite', root=root, clock=lambda: ctl.clock(), policy=policy)) as store:
        store.db.execute(sa.SCHEMA)
        store.db.execute('INSERT INTO saved_area_adoptions VALUES(?,?,?)',
                         (ot.digest(grant), adoption['sha256'], json.dumps(proof)))
        yield ctl, ot.RealAdapter(store), action, proof


@pytest.mark.parametrize('elapsed', [0, 1])
def test_expired_status_reads_registration_but_actions_and_acceptance_still_fail(continuation, elapsed):
    ctl, adapter, action, proof = continuation
    ctl.clock = lambda: DEADLINE + elapsed
    db = adapter.native.db
    db.execute('PRAGMA query_only=ON')
    # Regression: real prospective validation rejects now > horizon before status can say archived.
    status = ctl.status(adapter)
    assert status['archived'] is True
    assert status['saved_area_adoption'] == proof['adoption']
    assert status['windows'] == [dict(acquire='done', qualify='done'), {}, {}, {}]
    assert status['next'] == {'state': 'deadline'}
    with pytest.raises(ValueError, match='immutable parent UTC deadline'):
        adapter.saved_area_acceptance(ctl.preparation)
    with pytest.raises(ValueError, match='immutable parent UTC deadline'):
        ctl.step(adapter, action)
    assert not ctl.path.exists()


def test_live_status_still_requires_fresh_science_and_exact_registration(continuation, monkeypatch):
    ctl, adapter, _, proof = continuation
    ctl.clock = lambda: 1100

    def fresh_validation(root, descriptor, grant, *, now, horizon):
        assert (now, horizon) == (1100, DEADLINE)
        return proof

    monkeypatch.setattr(sa, 'validate_adoption', fresh_validation)
    status = ctl.status(adapter)
    assert status['archived'] is False
    assert status['windows'][0] == dict(acquire='done', qualify='done')
    assert status['next'] == dict(state='ready', stage='acquire', index=1)
    adapter.native.db.execute('DELETE FROM saved_area_adoptions')
    with pytest.raises(ValueError, match='exact registered adopted producer'):
        ctl.status(adapter)


@pytest.mark.parametrize('sql', [
    'DROP TABLE saved_area_adoptions',
    "UPDATE saved_area_adoptions SET adoption_sha='wrong'",
    "UPDATE saved_area_adoptions SET record_json='{}'",
])
def test_expired_status_refuses_missing_or_mismatched_registration(continuation, sql):
    ctl, adapter, _, _ = continuation
    adapter.native.db.execute(sql)
    with pytest.raises(ValueError, match='exact registered adopted producer'):
        ctl.status(adapter)
