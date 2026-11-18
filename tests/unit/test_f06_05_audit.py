"""F06-05 / SCA-217: an expired lease is recorded once, not on every tick.

Contract: Store.expire() is a state transition. The first call moves a job with a lapsed lease to
failed_uncertain and appends one lease_expired_uncertain event; the lease row (the fence, with its
process identities) and the first hold reason stay until explicit recover(). Believable bug it
catches: expire() re-selecting the same lease each tick, rewriting holds_json and appending an
event per poll (growth in the 512 KiB managed database with no new evidence).
Offline synthetic rows only; no processes, transports or real data.
"""
import json
import sys

import pytest

from skippercast.coastal.coordinator.store import FencedLease, Store

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="coastal coordinator requires Linux /proc")

CONTROLLER = {"pid": 1, "start": "10", "boot": "b", "group": 1, "session": 1}
CHILD = {"pid": 2, "start": "11", "boot": "b", "group": 2, "session": 1}


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def world(tmp_path):
    clock = Clock()
    store = Store(tmp_path / "coordinator.sqlite", root=tmp_path, clock=clock)
    store.db.execute("INSERT INTO segments VALUES('s1','r','{}')")
    yield store, clock
    store.close()


def lease(store, job_id, token, *, expires, state="running"):
    store.db.execute("INSERT INTO jobs(job_id,segment_id,stage,idempotency_key,state,max_attempts,created,record_json)"
                     " VALUES(?,?,?,?,?,2,0,'{}')", (job_id, "s1", "map", "k-" + job_id, state))
    store.db.execute("INSERT INTO leases VALUES(?,?,?,?,?,0)",
                     (job_id, token, json.dumps(CONTROLLER), json.dumps(CHILD), expires))


def events(store, kind="lease_expired_uncertain"):
    return store.db.execute("SELECT job_id,detail_json FROM events WHERE kind=?", (kind,)).fetchall()


def job(store, job_id):
    return store.db.execute("SELECT state,holds_json FROM jobs WHERE job_id=?", (job_id,)).fetchone()


def test_two_ticks_record_one_expiry_event_and_keep_the_fence(world):
    store, clock = world
    lease(store, "j1", "tok1", expires=900.0)
    assert store.expire() == 1
    first = events(store)
    clock.now += 60
    assert store.expire() == 0
    assert store.expire() == 0
    assert events(store) == first and len(first) == 1
    detail = json.loads(first[0]["detail_json"])
    assert detail["token"] == "tok1" and json.loads(detail["child_json"]) == CHILD
    assert json.loads(detail["controller_json"]) == CONTROLLER
    assert tuple(job(store, "j1")) == ("failed_uncertain", '["recovery_required"]')
    assert store.db.execute("SELECT token FROM leases WHERE job_id='j1'").fetchone()[0] == "tok1"


def test_expiry_does_not_mask_first_uncertainty_reason(world):
    store, clock = world
    lease(store, "j1", "tok1", expires=900.0)
    store.uncertain("j1", "tok1", "worker_reported_ambiguous")
    assert store.expire() == 0
    assert tuple(job(store, "j1")) == ("failed_uncertain", '["worker_reported_ambiguous"]')
    assert events(store) == []


def test_late_heartbeat_stays_fenced_and_lease_row_unchanged(world):
    store, clock = world
    lease(store, "j1", "tok1", expires=900.0)
    before = tuple(store.db.execute("SELECT * FROM leases").fetchone())
    assert store.expire() == 1
    with pytest.raises(FencedLease):
        store.heartbeat("j1", "tok1", lease_s=30)
    clock.now += 120
    assert store.expire() == 0
    assert len(events(store)) == 1
    assert tuple(store.db.execute("SELECT * FROM leases").fetchone()) == before


def test_valid_control_live_lease_untouched_and_other_expired_lease_recorded(world):
    store, clock = world
    lease(store, "live", "tok-live", expires=2000.0)
    store.db.execute("INSERT INTO segments VALUES('s2','r','{}')")
    store.db.execute("INSERT INTO jobs(job_id,segment_id,stage,idempotency_key,state,max_attempts,created,record_json)"
                     " VALUES('dead','s2','map','k-dead','running',2,0,'{}')")
    store.db.execute("INSERT INTO leases VALUES('dead','tok-dead',?,NULL,900.0,0)", (json.dumps(CONTROLLER),))
    assert store.expire() == 1
    assert store.expire() == 0
    assert [row["job_id"] for row in events(store)] == ["dead"]
    assert job(store, "live")["state"] == "running"
