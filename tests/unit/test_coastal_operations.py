"""T12 integrated coordinator operations: cost-bound stop, worker recovery,
resume after a killed controller, and process/lease cleanup.

These run the real Store, Coordinator, Budget ledger and detached supervisor on
Linux; only the stage executable is a fault-injection worker. Dispatching
controllers run out of process from a clean package export
(tests/_coastal_operations.py). Each test owns its queue root under tmp_path.
"""
import json
import os
import signal
import sys
import time

import pytest

from skippercast.coastal.runner import _group_state
from tests._coastal_operations import Harness, alive, export_package, policy, wait_for

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="coastal supervisor requires Linux /proc")


@pytest.fixture(scope="module")
def export(tmp_path_factory):
    return export_package(tmp_path_factory.mktemp("package-export"))


@pytest.fixture
def ops(tmp_path, export):
    harness = Harness(tmp_path, export)
    yield harness
    harness.close()


def states(results):
    return [r["state"] for r in results]


def test_controller_identity_ignores_this_process_sys_path(tmp_path, export, monkeypatch):
    # Other tests on the same xdist worker can leave a dependency directory on
    # sys.path (research scripts prepend host-local ones on import). The queue's
    # code/deps identity must still be the controller's, or every job is
    # invalidated as stale and every run is idle.
    leaked = tmp_path / "leaked-site"
    dist_info = leaked / "numpy-9.9.9.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text("Metadata-Version: 2.1\nName: numpy\nVersion: 9.9.9\n")
    monkeypatch.syspath_prepend(str(leaked))

    from skippercast.coastal.coordinator.loop import implementation_hashes
    base = tmp_path / "harness"
    base.mkdir()
    ops = Harness(base, export)
    try:
        assert implementation_hashes(ops.root)[1] != ops.deps   # this process now disagrees
        ops.job("only", "done")
        assert states(ops.run()) == ["done", "idle"]
    finally:
        ops.close()


# --- cost-bound stop ---------------------------------------------------------

# The harness default 2 s lease (heartbeat every 2/3 s) is what the killed-
# controller test needs to watch a lease lapse. A dispatch whose heartbeat or
# commit is starved for more than ~1.3 s by a loaded host (the parallel gate)
# then fails as `failed_uncertain: expired or superseded lease`, which is the
# correct fencing outcome but not what a byte-cap test is about. These tests
# use the production lease (30 s), so only the byte cap decides what runs.
COST_LEASE_S = 30


@pytest.fixture
def cost_ops(tmp_path, export):
    harness = Harness(tmp_path, export, policy_value=policy(lease_s=COST_LEASE_S))
    yield harness
    harness.close()


def test_byte_cap_stops_dispatch_before_launch_and_never_refunds(cost_ops):
    ops = cost_ops
    # Cap 250 B, 100 B per job: two fit, the third would overshoot the cap.
    first = ops.job("first", "underreport")    # claims it read nothing
    second = ops.job("second", "overreport")   # claims it read 1 GB
    third = ops.job("third", "done")

    results = ops.run()
    assert states(results) == ["done", "done", "idle"], results

    jobs = ops.jobs()
    assert jobs[first]["state"] == jobs[second]["state"] == "done"
    assert jobs[third]["state"] == "held" and jobs[third]["holds"] == ["budget_exhausted"]
    # The held job's worker was never launched; it has no lease and no job dir.
    assert ops.launches() == ["first.1.launch", "second.1.launch"]
    assert ops.lease(third) is None and not ops.job_dir(third).exists()
    # Worker-reported counters can neither refund nor inflate the authoritative
    # ledger: each settled attempt is charged its full write-ahead reservation.
    ledger = ops.ledger()
    assert ledger["charged"]["bytes"] == ledger["reserved"]["bytes"] == 200
    assert {e["state"] for e in ledger["reservations"].values()} == {"settled"}
    assert ops.effective_bytes() <= ops.policy["budgets"]["bytes"]
    assert [d["reason"] for _, d in ops.events("budget_exhausted")] == [None]


def test_exhausted_byte_cap_stops_every_later_job(cost_ops):
    ops = cost_ops
    jobs = [ops.job(f"j{i}", "done", budget={"bytes": 125}) for i in range(4)]

    results = ops.run()
    assert states(results) == ["done", "done", "idle"], results

    current = ops.jobs()
    assert [current[j]["state"] for j in jobs] == ["done", "done", "held", "held"]
    assert {tuple(current[j]["holds"]) for j in jobs[2:]} == {("byte_budget_exhausted",)}
    assert ops.effective_bytes() == ops.policy["budgets"]["bytes"] == 250
    # A later controller, even for zero-byte work, still cannot spend past the cap.
    late = ops.job("late", "done", budget={"bytes": 0})
    assert states(ops.run()) == ["idle"]
    assert ops.jobs()[late]["holds"] == ["byte_budget_exhausted"]
    assert len(ops.launches()) == 2


def test_wall_clock_cap_stops_dispatch(tmp_path, export):
    ops = Harness(tmp_path, export, offset=0.0, policy_value=policy(budgets={"wall_s": 100, "bytes": 1000}))
    try:
        early = ops.job("early", "done")
        assert states(ops.run(max_jobs=1)) == ["done"]

        # Inject 80 s of elapsed mission time: 20 s remain, the job needs 30 s.
        ops.offset += 80
        squeezed = ops.job("squeezed", "done")
        assert states(ops.run()) == ["idle"]
        assert ops.jobs()[squeezed]["holds"] == ["budget_exhausted"]

        # Past the whole wall cap: any job, however small, is stopped.
        ops.offset += 30
        tiny = ops.job("tiny", "done", budget={"wall_s": 1})
        assert states(ops.run()) == ["idle"]
        assert ops.jobs()[tiny]["holds"] == ["wall_budget_exhausted"]
        assert ops.launches() == ["early.1.launch"]
        assert ops.jobs()[early]["state"] == "done"
        assert ops.ledger()["elapsed_s"] >= 110
    finally:
        ops.close()


# --- worker recovery -----------------------------------------------------------

def test_worker_crash_stops_mission_until_recovered_then_resumes(ops):
    crashed = ops.job("crashed", "crash", "done", budget={"bytes": 80})
    sibling = ops.job("sibling", "done", budget={"bytes": 80})

    # The worker dies without a result: the run stops at once and the whole
    # reservation is retained as uncertain (no inferred refund).
    assert states(ops.run()) == ["failed_uncertain"]
    jobs = ops.jobs()
    assert jobs[crashed]["state"] == "failed_uncertain"
    assert jobs[crashed]["holds"] == ["ValueError:accounting requires a successful bound execution"]
    assert jobs[sibling]["state"] == "queued"
    token = ops.lease(crashed)["token"]
    entry = ops.ledger()["reservations"][token]
    assert entry["state"] == "uncertain" and entry["charged"]["bytes"] == 0
    assert ops.effective_bytes() == 80
    intent = ops.intent(crashed, token)
    assert (intent["rc"], intent["processes_stopped"], intent["ownership_complete"]) == (9, True, True)

    # Until an operator recovers it, no controller dispatches anything else, and
    # the sibling is paused rather than permanently held.
    assert states(ops.run()) == ["idle"]
    assert ops.jobs()[sibling]["state"] == "queued"
    assert sibling in {job for job, _ in ops.events("budget_paused_uncertain")}
    assert ops.launches() == ["crashed.1.launch"]

    receipt = ops.recovery_receipts(crashed)
    assert ops.store.recover(crashed, receipt) is True
    assert ops.store.recover(crashed, receipt) is False   # exact replay is idempotent
    assert ops.jobs()[crashed]["state"] == "queued" and ops.lease(crashed) is None
    recovered = ops.ledger()["reservations"][token]
    assert recovered["state"] == "settled" and recovered["charged"]["bytes"] == 80
    assert recovered["recovery_status"] == "stopped_uncertain_execution_accounted"

    # Resume: the recovered job retries (attempt 2) and the sibling runs once.
    assert states(ops.run()) == ["done", "done", "idle"]
    jobs = ops.jobs()
    assert (jobs[crashed]["state"], jobs[crashed]["attempts"]) == ("done", 2)
    assert (jobs[sibling]["state"], jobs[sibling]["attempts"]) == ("done", 1)
    assert ops.launches() == ["crashed.1.launch", "crashed.2.launch", "sibling.1.launch"]
    assert ops.effective_bytes() == 240 <= ops.policy["budgets"]["bytes"]
    assert ops.store.db.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0


def test_retryable_failure_backs_off_then_exhausts_attempt_cap(tmp_path, export):
    ops = Harness(tmp_path, export, offset=0.0)
    try:
        recovers = ops.job("recovers", "retryable", "done", budget={"bytes": 50})
        exhausts = ops.job("exhausts", "retryable", "retryable", budget={"bytes": 50})

        assert states(ops.run()) == ["failed_retryable", "failed_retryable", "idle"]
        assert {ops.jobs()[j]["state"] for j in (recovers, exhausts)} == {"queued"}
        # Exponential backoff: nothing is retried early.
        assert states(ops.run()) == ["idle"]
        assert len(ops.launches()) == 2

        ops.offset += 130
        assert states(ops.run()) == ["done", "failed_retryable", "idle"]
        jobs = ops.jobs()
        assert (jobs[recovers]["state"], jobs[recovers]["attempts"]) == ("done", 2)
        assert (jobs[exhausts]["state"], jobs[exhausts]["attempts"]) == ("failed_terminal", 2)
        assert [job for job, _ in ops.events("attempts_exhausted")] == [exhausts]
        # The attempt cap is final: no third launch, every attempt fully charged.
        ops.offset += 10**4
        assert states(ops.run()) == ["idle"]
        assert len(ops.launches()) == 4
        assert ops.ledger()["charged"]["bytes"] == 200 == ops.effective_bytes()
    finally:
        ops.close()


# --- resume after a killed controller -------------------------------------------

def test_killed_controller_resumes_without_duplicate_or_unfenced_work(ops):
    slow = ops.job("slow", "block", "done", budget={"bytes": 80})
    fast = ops.job("fast", "done", budget={"bytes": 80})

    controller = ops.start()
    try:
        wait_for(lambda: ops.launches("slow") and ops.jobs()[slow]["state"] == "running",
                 message="slow worker running")
        token = ops.lease(slow)["token"]
        os.kill(controller.pid, signal.SIGKILL)    # hard crash: no handler, no cleanup
        controller.wait(timeout=10)
    finally:
        if controller.poll() is None:
            controller.kill()

    # A replacement controller sees the lost dispatch owner and starts nothing.
    assert states(ops.run()) == ["idle"]
    assert ops.jobs()[fast]["state"] == "queued"
    assert ops.launches() == ["slow.1.launch"]

    # Once the dead controller's lease lapses the job needs explicit recovery,
    # which is refused while its worker is still alive.
    wait_for(lambda: ops.store.expire() >= 0 and ops.jobs()[slow]["state"] == "failed_uncertain",
             message="lease expiry")
    assert ops.jobs()[slow]["holds"] == ["recovery_required"]
    worker = json.loads((ops.markers / "slow.1.launch").read_text())["pid"]
    assert alive(worker)
    with pytest.raises(ValueError, match="child live or unverifiable"):
        ops.store.recover(slow, ops.recovery_receipts(slow))

    # The orphaned attempt finishes under its detached supervisor, but its result
    # is never committed: the fenced lease died with the controller.
    (ops.markers / "slow.release").write_text("go")
    wait_for(lambda: ops.intent(slow, token).get("state") == "finished", message="supervisor finish")
    assert (ops.job_dir(slow, token) / "output/result.json").exists()
    assert ops.jobs()[slow]["result_sha"] is None
    # Publishing "finished" precedes the supervisor's own exit. Recovery checks
    # every recorded owned group, not just the worker PID.
    intent = ops.intent(slow, token)
    identities = [intent["supervisor"], intent["child"], *intent["owned_descendants"]]
    group_states = []

    def owned_groups_stopped():
        group_states[:] = [_group_state(identity) for identity in identities]
        return all(state == "stopped" for state in group_states)

    try:
        wait_for(owned_groups_stopped, timeout=5, message="owned process groups stopped")
    except AssertionError as exc:
        raise AssertionError(f"owned groups did not stop: {list(zip(identities, group_states))}") from exc

    assert ops.store.recover(slow, ops.recovery_receipts(slow)) is True
    assert ops.ledger()["reservations"][token]["state"] == "settled"

    assert states(ops.run()) == ["done", "done", "idle"]
    jobs = ops.jobs()
    assert (jobs[slow]["state"], jobs[slow]["attempts"]) == ("done", 2)
    assert (jobs[fast]["state"], jobs[fast]["attempts"]) == ("done", 1)
    assert ops.launches() == ["fast.1.launch", "slow.1.launch", "slow.2.launch"]
    assert ops.effective_bytes() == 240 <= ops.policy["budgets"]["bytes"]
    assert ops.store.db.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0


# --- cleanup -----------------------------------------------------------------------

def test_wall_timeout_kills_worker_and_detached_grandchild(ops):
    stuck = ops.job("stuck", "orphan", "done", budget={"wall_s": 3})

    started = time.monotonic()
    assert states(ops.run()) == ["failed_uncertain"]
    assert time.monotonic() - started < 20   # deadline 3 s + TERM/KILL grace, not the 120 s sleep

    worker = json.loads((ops.markers / "stuck.1.launch").read_text())["pid"]
    grandchild = json.loads((ops.markers / "stuck.1.orphan").read_text())["pid"]
    token = ops.lease(stuck)["token"]
    intent = ops.intent(stuck, token)
    # The worker ignored SIGTERM and its grandchild left the session; the
    # subreaper supervisor still owned and stopped both.
    assert intent["status"] == "timeout"
    assert intent["processes_stopped"] is True and intent["ownership_complete"] is True
    assert {worker, grandchild} <= {d["pid"] for d in intent["owned_descendants"]}
    for pid in (worker, grandchild, intent["supervisor"]["pid"]):
        assert not alive(pid), pid
    assert ops.ledger()["reservations"][token]["state"] == "uncertain"

    assert ops.store.recover(stuck, ops.recovery_receipts(stuck)) is True
    assert states(ops.run()) == ["done", "idle"]
    assert ops.jobs()[stuck]["state"] == "done"
    assert ops.store.db.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0
    assert {e["state"] for e in ops.ledger()["reservations"].values()} == {"settled"}
