"""Synthetic Store boundaries for once-per-operation source-free validation."""
import json
from types import SimpleNamespace

import pytest

from skippercast.coastal.coordinator import source_free, store as coordinator_store
from skippercast.coastal.handoff.common import digest, ref, resolve, write


@pytest.fixture(params=["finish", "recovery"])
def completion(request, tmp_path, monkeypatch):
    recovery = request.param == "recovery"
    state = "failed_uncertain" if recovery else "running"
    now, token = 1000, "test-lease"
    params = {"core_index": 0, "producer_sha": "e" * 64}
    job = dict(job_id="job:fixture", segment_id="segment-fixture", stage="map",
               code_sha="a" * 64, deps_sha="b" * 64, params_sha="c" * 64,
               input_manifest_sha="d" * 64, input_manifest={"fixture": True},
               params=params,
               sourcefree_contract=source_free.CONTRACT)
    job_id = job["job_id"]
    store = coordinator_store.Store(tmp_path / "queue.sqlite", root=tmp_path, clock=lambda: now,
                                    policy={"watermarks": {"low": 1, "high": 2, "held_cap": 1},
                                            "worker_network": False})
    db = store.db
    db.execute("INSERT INTO regions(region) VALUES('fixture')")
    db.execute("INSERT INTO segments VALUES (?, 'fixture', ?)", (job["segment_id"], '{"region":"fixture"}'))
    db.execute("INSERT INTO jobs(job_id,segment_id,stage,idempotency_key,state,max_attempts,created,record_json) "
               "VALUES (?, ?, 'map', ?, ?, 2, ?, ?)",
               (job_id, job["segment_id"], job_id, state, now, json.dumps(job)))
    db.execute("INSERT INTO leases VALUES (?, ?, ?, NULL, ?, ?)",
               (job_id, token, '{"fixture":"stopped"}', now + 30, now))

    trace = []
    producer, qualified = {"sha256": params["producer_sha"]}, {"fixture": "qualification"}

    def read_input(*args, **kwargs):
        assert db.in_transaction
        trace.append("verify")
        return {"producer_proofs": [producer]}, [dict(packet={"synthetic": True},
            facts={"header": {"window": [0, 0, 1, 1]}}, result_ref=qualified,
            valid=SimpleNamespace(sum=lambda: 1))]

    def check_rasters(root, receipt, expected, items):
        # Synthetic stand-in for GIS-specific checking; keep real byte references.
        assert {key: receipt[key] for key in expected} == expected
        for artifact in receipt["artifacts"]:
            resolve(root, artifact)

    monkeypatch.setattr(source_free, "validate_input", read_input)
    monkeypatch.setattr(source_free.contained_batch, "_verify", check_rasters)
    monkeypatch.setattr(coordinator_store, "identity_stopped", lambda identity: identity == {"fixture": "stopped"})

    def settle(lease, **kwargs):
        assert lease == token and db.in_transaction
        assert db.execute("SELECT state FROM jobs").fetchone()[0] == state
        assert db.execute("SELECT token FROM leases").fetchone()[0] == token
        trace.append("settle")

    authority = SimpleNamespace(charge=settle, recover_uncertain=settle)
    monkeypatch.setattr(store, "budget_for", lambda region: authority)

    output = tmp_path / "var/coastal/jobs/job-fixture" / token / "output"
    raster = output / "synthetic.json"
    write(raster, {"sample": 1})
    raster_ref = ref(tmp_path, raster, "synthetic")
    core_path = output / "core.json"
    write(core_path, dict(schema=source_free.CORE,
        binding=digest(dict(input=job["input_manifest"], params=job["params"],
                            code_sha=job["code_sha"], deps_sha=job["deps_sha"])),
        source_accessed=False, publication_prohibited=True, state="mapped_pending_render_review",
        synthetic=True, native_window=[0, 0, 1, 1], valid_cells=1, nominal_valid_area_m2=4,
        producer_proof=producer, qualified_result=qualified, artifacts=[raster_ref]))
    core_ref = ref(tmp_path, core_path, source_free.CORE)
    result_path = output / "result.json"
    write(result_path, dict(schema="coastal-stage-result-v1", **{k: job[k] for k in source_free.IDENTITY_FIELDS},
        lease_token=token, state="done", holds=[], sourcefree_contract=source_free.CONTRACT,
        mapped_core=core_ref, artifacts=[core_ref, raster_ref], usage={"bytes": 0, "requests": 0},
        provenance={"synthetic": True, "source_accessed": False}, verified=True))
    result_ref = ref(tmp_path, result_path, "coastal-stage-result-v1")

    def invoke(descriptor=result_ref):
        if not recovery:
            return store.finish(job_id, token, descriptor, settle_budget=True)
        receipt_path = tmp_path / "recovery.json"
        write(output.parent / "intent.json", {})
        write(receipt_path, dict(job_id=job_id, lease_token=token, result=descriptor,
                                processes_stopped=True, attested_by="synthetic", runtime_recovery={"fixture": True}))
        return source_free.recover_completion(store, job_id,
            ref(tmp_path, receipt_path, "coastal-sourcefree-recovery-v1"))

    try:
        yield SimpleNamespace(db=db, invoke=invoke, trace=trace, state=state, job_id=job_id,
                              result_ref=result_ref, raster=raster)
    finally:
        store.close()


def test_each_operation_verifies_once_and_revalidates_replays(completion):
    # A second validation after durable settlement, or a stale proof reused by
    # a new invocation, violates the fenced operation's contract.
    f = completion
    assert f.invoke() is True
    assert f.trace == ["verify", "settle"]
    assert tuple(f.db.execute("SELECT state,result_sha FROM jobs").fetchone()) == ("done", f.result_ref["sha256"])
    assert not f.db.execute("SELECT * FROM leases").fetchall()
    assert f.db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 2
    f.trace.clear()
    assert f.invoke() is False
    assert f.trace == ["verify"]

    f.trace.clear()
    write(f.raster, {"sample": 2})  # same-length bytes, different digest
    with pytest.raises(ValueError, match="artifact bytes/hash changed"):
        f.invoke()
    assert f.trace == ["verify"]


@pytest.mark.parametrize("invalid", ["changed", "unowned"])
def test_invalid_output_cannot_settle_budget(completion, tmp_path, invalid):
    # Even a result claiming it was verified must be checked before settling.
    f = completion
    if invalid == "changed":
        write(f.raster, {"sample": 2})
        result_ref, error = f.result_ref, "artifact bytes/hash changed"
    else:
        copy = tmp_path / "unowned-result.json"
        copy.write_bytes((tmp_path / f.result_ref["path"]).read_bytes())
        result_ref, error = {**f.result_ref, "path": copy.name}, "result (output ownership|path)"
    with pytest.raises(ValueError, match=error):
        f.invoke(result_ref)
    assert "settle" not in f.trace
    assert tuple(f.db.execute("SELECT state,result_sha FROM jobs").fetchone()) == (f.state, None)
    assert f.db.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 1
    assert not f.db.execute("SELECT * FROM artifacts").fetchall()


def test_replay_rejects_unowned_copy(completion, tmp_path):
    # The replay's SHA match is not evidence of ownership at a different path.
    f = completion
    assert f.invoke() is True
    copy = tmp_path / "unowned-result.json"
    copy.write_bytes((tmp_path / f.result_ref["path"]).read_bytes())
    with pytest.raises(ValueError, match="result output ownership|exact prior recovery receipt"):
        f.invoke({**f.result_ref, "path": copy.name})
    assert f.trace.count("settle") == 1
