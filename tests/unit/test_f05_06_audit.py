"""SCA-358 / F05-06: bridge continuation receipts stay within their own reader limit.

The native v3 run summary carries run-scoped store counts (never the global queue dump),
binds its inline per-window details by digest, and a continuation re-verifies those
details before any tick. Synthetic queues only; no network, real rows or locations.
"""
import hashlib
import json
import os

import pytest

from skippercast.coastal.coordinator import bridge_run as driver, catalog_bridge
from tests.coast_contract_factory import load_helper
from tests.unit.test_coast_local_screen import ls as screener
from tests.unit.test_coastal_bridge_run import (  # noqa: F401 -- shared fixtures
    CLOCK, enqueue, foreign_jobs, offline_and_provenance, run, synthetic_dispatch, world,
)

validator = load_helper("validate_coast_receipt")


def add_synthetic_history(w, count=18000):
    """Unrelated, already-finished foreign jobs and charges sharing the queue."""
    _, foreign_id = foreign_jobs(w)
    db = w.ops.store.db
    seed = db.execute("SELECT * FROM jobs WHERE job_id=?", (foreign_id,)).fetchone()
    job = json.loads(seed["record_json"])
    rows, charges = [], []
    for n in range(count):
        job["params"] = {"synthetic_history": n}
        job["params_sha"] = driver.digest(job["params"])
        key = driver._identity(job)
        job["job_id"] = "job:" + key[:24]
        rows.append((job["job_id"], job["segment_id"], job["stage"], key, "cancelled", seed["max_attempts"],
                     seed["created"], json.dumps(job), json.dumps(["synthetic-foreign-only"])))
        charges.append((job["job_id"], 1, 1, 0))
    db.executemany("INSERT INTO jobs(job_id,segment_id,stage,idempotency_key,state,max_attempts,created,"
                   "record_json,holds_json) VALUES(?,?,?,?,?,?,?,?,?)", rows)
    db.executemany("INSERT INTO charges(job_id,wall_s,bytes,requests) VALUES(?,?,?,?)", charges)
    return foreign_id


def rewrite(path, value):
    os.chmod(path, 0o644)
    path.write_bytes(driver._encode(value))


def tick_count(w):
    return w.ops.store.db.execute("SELECT COUNT(*) FROM events WHERE kind='tick'").fetchone()[0]


@pytest.mark.parametrize("oversized", [False, True], ids=["ordinary-control", "oversized-history"])
def test_continuation_reads_a_bounded_scoped_predecessor(world, oversized):
    w = world
    enqueue(w)
    foreign_id = add_synthetic_history(w) if oversized else foreign_jobs(w)[1]
    first = run(w, until=CLOCK.timestamp() + 0.1)
    assert first["stop_reason"] == "deadline" and first["ticks_used"] == 0
    raw = (w.p / "runs/run-00.json").read_bytes()
    print(f"{'oversized' if oversized else 'ordinary'}: wrote {len(raw)} bytes; "
          f"reader limit {catalog_bridge.MAX_DOCUMENT_BYTES}")
    assert len(raw) <= catalog_bridge.MAX_DOCUMENT_BYTES
    assert foreign_id.encode() not in raw and b"synthetic-foreign-only" not in raw
    scope = first["store_status"]
    assert scope["schema"] == "coastal-coordinator-scope-v1" and scope["store"] == "present"
    assert scope["foreign"]["jobs"] == (18002 if oversized else 2)
    assert scope["foreign"]["charges"] == (18000 if oversized else 0)
    validator.validate_schema(first)
    second = run(w, sequence=1, continuation=True, until=CLOCK.timestamp() + 0.1)
    assert second["continuation_of"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert screener.Plan(w.p).summary == second
    print("continuation retained the exact prior digest")


def test_corrupt_or_global_details_refuse_before_any_tick(world, synthetic_dispatch):
    w = world
    enqueue(w)
    first = run(w, ticks=3)
    assert first["stop_reason"] == "max_ticks"
    path = w.p / "runs/run-00.json"
    products = [p for wnd in first["windows"] for info in wnd["stages"].values() for p in info.get("products", {}).values()]
    assert products, "the synthetic run must have produced per-window details"
    ticks = tick_count(w)

    def refused(value, match):
        rewrite(path, value)
        with pytest.raises(ValueError, match=match):
            run(w, sequence=1, continuation=True)
        assert not (w.p / "runs/run-01.json").exists() and tick_count(w) == ticks

    edited = json.loads(json.dumps(first))
    edited["windows"][0]["stages"]["acquire"]["holds"] = ["edited"]
    refused(edited, "per-window details digest mismatch")
    refused(dict(first, store_status=driver.queue_status(w.root / driver.DATABASE)), "run-scoped store counts required")
    refused({k: v for k, v in first.items() if k != "windows_sha256"}, "per-window details digest mismatch")
    # A changed detail file refuses even when the summary itself is intact.
    rewrite(path, first)
    target = w.root / products[0]["path"]
    original = target.read_bytes()
    os.chmod(target, 0o644)
    target.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="reference hash/bytes mismatch"):
        run(w, sequence=1, continuation=True)
    assert not (w.p / "runs/run-01.json").exists() and tick_count(w) == ticks
    target.write_bytes(original)
    resumed = run(w, sequence=1, continuation=True)
    assert resumed["sequence"] == 1 and resumed["ticks_used"] > 0
    print("corrupt, missing-digest and global-dump predecessors refused before any tick; restored bytes resume")


def test_readers_bind_v3_details(world, synthetic_dispatch, monkeypatch):
    monkeypatch.setenv("COAST_CARD_ID", "t_00000000")
    w = world
    enqueue(w)
    summary = run(w)
    assert summary["schema"] == "coast-run-summary-v3" and summary["counts"]["map_done"] == 2
    validator.validate_schema(summary)
    with pytest.raises(ValueError, match="schema coast-run-summary-v3"):
        validator.validate_schema(dict(summary, store_status=driver.queue_status(w.root / driver.DATABASE)))
    path = w.p / "runs/run-00.json"
    rewrite(path, dict(summary, windows=summary["windows"][::-1]))
    with pytest.raises(screener.Refused, match="per-window details digest mismatch"):
        screener.Plan(w.p)


def test_v1_predecessor_still_continues(world):
    w = world
    enqueue(w)
    first = run(w, until=CLOCK.timestamp() + 0.1)
    legacy = {k: v for k, v in first.items() if k != "windows_sha256"}
    legacy.update(schema="coast-run-summary-v1", store_status=driver.queue_status(w.root / driver.DATABASE))
    validator.validate_schema(legacy)
    rewrite(w.p / "runs/run-00.json", legacy)
    second = run(w, sequence=1, continuation=True, until=CLOCK.timestamp() + 0.1)
    assert second["schema"] == "coast-run-summary-v3" and second["sequence"] == 1


def test_oversized_details_are_withheld_explicitly(world, synthetic_dispatch, monkeypatch):
    w = world
    enqueue(w)
    monkeypatch.setattr(driver, "MAX_SUMMARY_BYTES", 6000)
    summary = run(w)
    raw = (w.p / "runs/run-00.json").read_bytes()
    assert summary["stop_reason"] == "integrity_error" and "per-window details withheld" in summary["problems"][0]
    assert all(wnd["stages"] == {} and wnd["unfinished_reason"] == "integrity_error" for wnd in summary["windows"])
    assert summary["counts"]["unfinished"] == summary["counts"]["windows"] == 2
    assert len(raw) <= 6000
    many = [f"p{n}" for n in range(100)]
    assert driver._bounded(many) == many[:64] + ["36 further problems omitted from the bounded run summary"]
    print(f"over-bound details withheld, not truncated: {len(raw)} bytes")
