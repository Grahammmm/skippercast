"""PC-9 offline driver tests. Scientific dispatch is explicitly synthetic here.

Store, Coordinator ticks, leases, identity and Budget are real. Tiny synthetic
scientific handoffs stand in for the GIS producers; their verifiers alone are
patched. No scientific acceptance is asserted by these queue/receipt tests.
"""
import ast
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import ssl  # Load socket subclasses before the no-network fixture replaces socket.socket.
from types import SimpleNamespace

import pytest

from skippercast.coastal.coordinator import bridge_run as driver, catalog_bridge, loop
from skippercast.coastal.coordinator.segments import from_bbox, segment
from skippercast.coastal.coordinator.stages import digest
from skippercast.coastal.coordinator.store import Store
from skippercast.coastal.handoff.common import ref, write
from tests import _coastal_catalog_fixture as fx
from tests._coastal_operations import Harness
from tests._support import FakeClock, NOW

CLOCK = FakeClock()


@pytest.fixture(autouse=True)
def offline_and_provenance(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("driver must not open a socket")
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, refuse)
    for key, value in dict(AUTHOR_PROFILE="synthetic-builder", AUTHOR_MODEL="synthetic-test-model",
                           CARD_ID="synthetic-card", CODE_COMMIT="1"*40, SKILL_COMMIT="2"*40).items():
        monkeypatch.setenv("COAST_" + key, value)


@pytest.fixture
def world(tmp_path, monkeypatch, request):
    pytest.importorskip("pyproj")  # Core-only CI has no lattice transformer; survey CI runs these.
    # Harness supplies an isolated real Store. No exported supervisor is needed
    # for the in-process synthetic stage dispatcher used by these unit tests.
    ops = Harness(tmp_path, tmp_path, policy_value=driver._policy())
    old_root = ops.root
    ops.close()
    root = old_root.rename(tmp_path / "C1-synthetic")
    monkeypatch.setenv("COAST_EXCLUSIVE_WRITER", str(root))
    ops.root = root
    ops.store_path = root / driver.DATABASE
    ops.store = ops.open()
    ops.store.clock = CLOCK.timestamp
    ops.store.progress_clock = CLOCK.timestamp
    campaign = dict(campaign_segment_id=root.name, bbox_crs84=[-120.6, 34.45, -120.59, 34.46])
    record = from_bbox(campaign["bbox_crs84"], region=root.name)[0]
    record["synthetic"] = True
    campaign["bbox_crs84"] = record["bbox_crs84"]
    plan_dir = root / "plans/pilot01"
    plan_dir.mkdir(parents=True)
    (plan_dir / "runs").mkdir()
    write(root / "campaign.json", campaign)
    write(plan_dir / "segment.json", record)
    rows, selections, windows, grids = [], [], [], []
    for i in range(2):
        source = fx.cache_file(root, f"cache/s{i}.tif", data=b"II*\x00synthetic-source-"+str(i).encode())
        extra = {}
        if getattr(request, "param", None) == "real-stages":
            import numpy as np
            import rasterio
            from rasterio.transform import from_origin
            from skippercast.coastal import vertical
            from skippercast.coastal.handoff import mapping_input
            path = root/source["path"]
            with rasterio.open(path, "w", driver="GTiff", width=4, height=4, count=1, dtype="float32",
                               crs="EPSG:3310", transform=from_origin(record["bbox"][0]+1000, record["bbox"][3]-1000, 250, 250)) as ds:
                ds.write(-np.arange(1, 17, dtype="float32").reshape(4, 4), 1)
                ds.set_band_unit(1, "m")
                ds.update_tags(vertical_sign="positive_up", vertical_datum="MLLW", scale_offset_applied="false")
            source = ref(root, path, "native-raster-v1")
            with rasterio.open(path) as ds:
                observed = vertical.from_raster(ds, source_sha256=source["sha256"])
            block = dict(schema="vertical-v1", **observed["facts"], conflicts=[], evidence=[vertical.evidence_from_observation(observed)])
            write(root/"fixture-evidence.json", dict(synthetic=True))
            rights = dict(private_use=True, evidence=[ref(root, root/"fixture-evidence.json", "synthetic-fixture-evidence-v1")])
            qualification = mapping_input.produce(root, source, segment_id=record["segment_id"], segment=record,
                window=[0, 0, 4, 4], vertical=block, rights=rights, output_dir=f"fixture-qualification-{i}", synthetic=True)
            write(root/f"fixture-review-{i}.json", dict(schema="coastal-private-input-review-v2", independent=True,
                reviewer_id="synthetic-test-reviewer", facts_digest=qualification["facts_digest"],
                checked_at=driver.utc(CLOCK.timestamp()-60), valid_until=driver.utc(CLOCK.timestamp()+86400), decision="accept", holds_added=[]))
            extra = dict(vertical=block, rights=rights, review=ref(root, root/f"fixture-review-{i}.json", "coastal-private-input-review-v2"))
        row = fx.candidate(f"s{i}.tif", bbox=record["bbox_crs84"], size=source["bytes"], source_hash=source["sha256"])
        rows.append(row)
        selections.append(dict(fx.selection(row["source_id"], source), **extra))
        grid = dict(source_sha256=source["sha256"], raster_crs="EPSG:3310",
                    affine_transform=[250, 0, record["bbox"][0]+1000, 0, -250, record["bbox"][3]-1000],
                    width=4, height=4, tile_width=4, tile_height=4, tiling_version="single-selected-v1", pixel_window=[0, 0, 4, 4])
        grid_sha = digest(grid)
        grids.append(dict(grid_sha256=grid_sha, definition=grid))
        key = f"{row['source_id']}#{grid_sha}#0"
        windows.append(dict(window_key=key, window_dir=hashlib.sha256(key.encode()).hexdigest(),
                            source_id=row["source_id"], grid_sha256=grid_sha, idx=0,
                            pixel_window=[0, 0, 4, 4], owner_segment_id=record["segment_id"]))
    catalog = fx.frozen_catalog(rows)
    sha = fx.write_catalog(root / "catalog.json", catalog)
    plan = fx.plan(catalog, sha, selections, segment_id=record["segment_id"], bbox=record["bbox_crs84"])
    write(plan_dir / "plan.json", plan)
    catalog_bridge.dry_run(root, root / "catalog.json", plan, plan_dir / "dry")
    bridge = catalog_bridge.run(root, root / "catalog.json", plan, plan_dir / "bridge")
    namespace = "queue:" + root.name
    admission = dict(schema="coast-admission-v1", campaign_segment_id=root.name, coordinator_segment_id=record["segment_id"],
                     plan_id=plan_dir.name, plan_sha256=digest(plan), holds=[],
                     preconditions=dict(exclusive_writer=True, attested_by="synthetic-test-operator"), windows=windows, grids=grids,
                     **{key: driver._ref(root, path, namespace) for key, path in dict(campaign=root/"campaign.json",
                         segment_record=plan_dir/"segment.json", plan_file=plan_dir/"plan.json", catalog=root/"catalog.json",
                         dry_run=plan_dir/"dry/bridge-dry-run-receipt.json").items()})
    write(plan_dir / "admission.json", admission)
    value = SimpleNamespace(root=root, p=plan_dir, record=record, plan=plan, admission=admission,
                            bridge=bridge, ops=ops, namespace=namespace)
    yield value
    ops.close()


def enqueue(w):
    return driver.enqueue(w.root, w.p/"bridge/bridge-receipt.json", w.p/"segment.json", w.p/"admission.json", w.p/"bridge/enqueue-receipt.json", clock=CLOCK.timestamp)


def run(w, *, sequence=0, continuation=False, ticks=10, until=None):
    return driver.run(w.root, w.p/"bridge/enqueue-receipt.json", w.p/f"runs/run-{sequence:02}.json",
                      max_ticks=ticks, until=until if until is not None else CLOCK.timestamp()+120, clock=CLOCK.timestamp,
                      continuation_of=w.p/f"runs/run-{sequence-1:02}.json" if continuation else None)


def snapshot(w):
    return list(w.ops.store.db.iterdump())


def test_campaign_lattice_enqueue_order_and_duplicate_fence(world):
    w = world
    receipt = enqueue(w)
    assert receipt["schema"] == "coast-enqueue-receipt-v1"
    assert receipt["campaign_segment_id"] != receipt["coordinator_segment_id"]
    assert receipt["plan_sha256"] == digest(w.plan)
    assert receipt["plan_sha256"] != receipt["admission"]["sha256"]
    jobs = [dict(r) for r in w.ops.store.db.execute("SELECT * FROM jobs ORDER BY rowid")]
    assert len(jobs) == 2
    assert [j["job_id"] for j in jobs] == [j["root_job_id"] for j in receipt["jobs"]]
    assert all(j["new_row"] for j in receipt["jobs"])
    assert [j["window_key"] for j in receipt["jobs"]] == [x["window_key"] for x in w.admission["windows"]]
    assert all(j["stage"] == "acquire" for j in jobs)
    for key in ("admission", "bridge", "intent"):
        assert set(receipt[key]) == {"root_id", "path", "sha256", "bytes"}
        driver._verify(w.root, receipt[key], w.namespace)
    before = snapshot(w)
    with pytest.raises(ValueError, match="output exists"):
        enqueue(w)
    assert snapshot(w) == before


def test_intent_only_crash_fences_retry_without_mutation(world):
    w = world
    bridge_ref = driver._ref(w.root, w.p/"bridge/bridge-receipt.json", w.namespace)
    intent = w.root/"var/coastal/enqueue-intents"/(bridge_ref["sha256"]+".json")
    intent.parent.mkdir()
    intent.write_text('{"synthetic_crash":true}\n')
    before = snapshot(w)
    with pytest.raises(ValueError, match="intent exists"):
        enqueue(w)
    assert snapshot(w) == before


@pytest.mark.parametrize("field,value", [("segment_id", "C1-synthetic"), ("bbox", [0, 0, 5000, 5000]),
                                            ("bbox_crs84", [0, 0, 1, 1]), ("crs", "EPSG:4326")])
def test_bad_geographic_record_refused_before_store_changes(world, field, value):
    w = world
    record = dict(w.record, **{field: value})
    write(w.p/"segment.json", record)
    admission = deepcopy(w.admission)
    admission["segment_record"] = driver._ref(w.root, w.p/"segment.json", w.namespace)
    write(w.p/"admission.json", admission)
    before = snapshot(w)
    with pytest.raises(ValueError):
        enqueue(w)
    assert snapshot(w) == before


def test_existing_bbox_mismatch_refused(world):
    w = world
    w.ops.store.add_segment(dict(w.record, bbox_crs84=[0, 0, 1, 1]))
    before = snapshot(w)
    with pytest.raises(ValueError, match="existing segment bbox"):
        enqueue(w)
    assert snapshot(w) == before


def foreign_jobs(w, *, code=None):
    record = segment(0, 0, region="foreign-synthetic")
    record["synthetic"] = True
    w.ops.store.add_segment(record)
    code_sha, deps_sha = loop.implementation_hashes(w.root)
    return [w.ops.store.enqueue(record["segment_id"], stage, code_sha=code or code_sha, deps_sha=deps_sha,
                                params=dict(synthetic_foreign=stage)) for stage in ("acquire", "render")]


def foreign_snapshot(w, ids):
    with driver._snapshot(w.root) as db:
        return {table: [dict(row) for row in db.execute(f"SELECT * FROM {table}") if row["job_id"] in ids]
                for table in ("jobs", "events", "leases", "charges")}


@pytest.fixture
def synthetic_dispatch(monkeypatch):
    from skippercast.coastal import mapping
    from skippercast.coastal.handoff import mapping_input
    # Synthetic queue fixtures are deliberately not real scientific evidence.
    monkeypatch.setattr(mapping_input, "verify", lambda *a, **k: dict(ready=True, holds=[]))
    monkeypatch.setattr(mapping, "verify", lambda *a, **k: dict(ready=True, holds=[]))
    def dispatch(coordinator, job, job_path, out, identity_callback, deadline):
        root = coordinator.store.root
        out.mkdir(parents=True)
        stage = job["stage"]
        base = {key: job[key] for key in ("job_id", "stage", "segment_id", "lease_token", "code_sha", "deps_sha", "params_sha", "input_manifest_sha")}
        result = dict(base, schema="coastal-stage-result-v1", state="done", holds=[], artifacts=[],
                      usage=dict(requests=0, bytes_in=0), provenance=dict(libs={"synthetic-fixture": "v1"}, synthetic=True))
        if stage == "acquire":
            native = json.loads((root/job["input_manifest"]["path"]).read_text())
            write(out/"native.json", native)
            next_ref = ref(root, out/"native.json", catalog_bridge.NATIVE_JOB)
        elif stage == "qualify":
            (out/"mask.tif").write_bytes(b"synthetic-support-not-a-real-raster")
            support = ref(root, out/"mask.tif", "coastal-native-support-v2")
            document = dict(schema="private-mapping-input-v2", synthetic=True, segment_id=job["segment_id"],
                            segment=job["segment"], facts_digest="a"*64,
                            native_facts=dict(valid_count=16, support=dict(valid_cells=16)), valid_support=support)
            write(out/"mapping-input.json", document)
            next_ref = ref(root, out/"mapping-input.json", document["schema"])
            result["artifacts"] = [next_ref]
        elif stage == "map":
            cells = dict(schema="coastal-terrain-summary-v1", native_valid_count=16,
                         depth_m=dict(count=16, min=1.0, max=16.0, mean=8.5, p80="unknown"))
            write(out/"cells.json", cells)
            (out/"terrain.tif").write_bytes(b"synthetic-terrain-not-a-real-raster")
            outputs = dict(cells=ref(root, out/"cells.json", cells["schema"]),
                           terrain=ref(root, out/"terrain.tif", "coastal-normalized-terrain-v1"))
            document = dict(schema="coastal-mapping-run-v1", synthetic=True, segment_id=job["segment_id"],
                            segment=job["segment"], facts_digest="a"*64, outputs=outputs)
            write(out/"run.json", document)
            next_ref = ref(root, out/"run.json", document["schema"])
            result["artifacts"] = [next_ref, *outputs.values()]
        else:
            raise AssertionError("render must never run")
        result["next_job"] = dict(stage={"acquire": "qualify", "qualify": "map", "map": "render"}[stage],
                                  input_manifest=next_ref, params={}, budget=job["budget"])
        write(out/"result.json", result)
        return SimpleNamespace(rc=0)
    original_init = loop.Coordinator.__init__
    def initialize(coordinator, store, **kwargs):
        original_init(coordinator, store, dispatcher=lambda *a: dispatch(coordinator, *a), **kwargs)
    monkeypatch.setattr(loop.Coordinator, "__init__", initialize)
    return dispatch


def test_two_windows_map_lineage_keeps_foreign_and_render_untouched(world, synthetic_dispatch):
    w = world
    receipt = enqueue(w)
    ids = foreign_jobs(w)
    foreign_before = foreign_snapshot(w, ids)
    summary = run(w)
    assert summary["stop_reason"] == "terminal", summary["problems"]
    assert summary["ticks_used"] == 6
    assert summary["counts"]["map_done"] == summary["counts"]["windows"] == 2
    assert summary["usage"]["requests"] == 0
    assert summary["untouched"] == dict(foreign_queued_jobs_seen=2, render_jobs_left_queued=2)
    assert foreign_snapshot(w, ids) == foreign_before
    assert summary["enqueued_job_ids"] == [j["root_job_id"] for j in receipt["jobs"]]
    assert len(list(w.ops.store.db.execute("SELECT * FROM jobs"))) == 10
    for window in summary["windows"]:
        assert window["stages"]["render"]["state"] == "queued"
        assert window["stages"]["qualify"]["support"]["valid_cells"] == 16
        assert window["stages"]["map"]["depth_m"] == dict(count=16, min=1.0, max=16.0, mean=8.5, p80="unknown")
        assert window["stages"]["map"]["native_valid_count"] == 16
    assert summary["store_status"] == driver.queue_status(w.root/driver.DATABASE)
    with pytest.raises(ValueError, match="output exists"):
        run(w)


@pytest.mark.parametrize("contamination", ["old_identity", "expired_lease", "live_lease", "stale", "running", "contract"])
def test_unsafe_foreign_preflight_refuses_without_mutation(world, contamination):
    w = world
    enqueue(w)
    ids = foreign_jobs(w, code="a"*64 if contamination == "old_identity" else None)
    db = w.ops.store.db
    if contamination in {"expired_lease", "live_lease"}:
        db.execute("INSERT INTO leases VALUES(?,?,?,NULL,?,?)", (ids[1], "b"*32, "{}", 0 if contamination == "expired_lease" else CLOCK.timestamp()+100, 0))
    elif contamination in {"stale", "running"}:
        db.execute("UPDATE jobs SET state=? WHERE job_id=?", (contamination, ids[1]))
    elif contamination == "contract":
        job = json.loads(db.execute("SELECT record_json FROM jobs WHERE job_id=?", (ids[1],)).fetchone()[0])
        job["execution_contract"] = "foreign-contract"
        db.execute("UPDATE jobs SET record_json=? WHERE job_id=?", (json.dumps(job), ids[1]))
    before = snapshot(w)
    summary = run(w)
    assert summary["stop_reason"] == "preflight_refused"
    assert summary["ticks_used"] == summary["usage"]["requests"] == 0
    assert summary["counts"]["unfinished"] == 2
    assert snapshot(w) == before


def test_enqueue_unsafe_foreign_refuses_before_segment_intent_or_event(world):
    w = world
    foreign_jobs(w, code="a"*64)
    before = snapshot(w)
    with pytest.raises(ValueError, match="preflight_refused"):
        enqueue(w)
    assert snapshot(w) == before
    assert not (w.root/"var/coastal/enqueue-intents").exists()


def test_missing_current_ownership_assertion_refuses_read_only(world, monkeypatch):
    w = world
    enqueue(w)
    monkeypatch.delenv("COAST_EXCLUSIVE_WRITER")
    before = snapshot(w)
    summary = run(w)
    assert summary["stop_reason"] == "preflight_refused"
    assert summary["ticks_used"] == 0
    assert snapshot(w) == before


def test_changed_native_input_emits_integrity_summary_without_store_writes(world):
    w = world
    enqueue(w)
    path = w.root/w.bridge["jobs"][0]["input_manifest"]["path"]
    path.chmod(0o644)  # This test owns these synthetic frozen bytes.
    path.write_bytes(path.read_bytes()+b" ")
    before = snapshot(w)
    summary = run(w)
    assert summary["stop_reason"] == "integrity_error"
    assert summary["ticks_used"] == 0
    assert summary["counts"]["unfinished"] == 2
    assert snapshot(w) == before


def test_store_created_only_after_validated_enqueue(world):
    w = world
    w.ops.close()
    # Move the empty fixture Store aside rather than deleting any data.
    (w.root/driver.DATABASE).rename(w.root/"empty-fixture-store.sqlite")
    receipt = enqueue(w)
    assert all(j["new_row"] for j in receipt["jobs"])
    assert len(driver.queue_status(w.root/driver.DATABASE)["jobs"]) == 2
    w.ops.store = w.ops.open()


def test_preflight_rechecked_before_second_tick(world, synthetic_dispatch, monkeypatch):
    w = world
    enqueue(w)
    ids = foreign_jobs(w)
    original_tick = loop.Coordinator.tick
    after = []
    def tick(coordinator, **kwargs):
        outcome = original_tick(coordinator, **kwargs)
        monkeypatch.setattr(loop, "implementation_hashes", lambda root: ("b"*64, "c"*64))
        after.extend(snapshot(w))
        return outcome
    monkeypatch.setattr(loop.Coordinator, "tick", tick)
    summary = run(w)
    assert summary["stop_reason"] == "preflight_refused"
    assert summary["ticks_used"] == 1
    assert snapshot(w) == after
    assert summary["usage"]["requests"] == 0


def test_deadline_continuation_stable_roots_new_successor_rows(world, synthetic_dispatch):
    w = world
    receipt = enqueue(w)
    first = run(w, until=CLOCK.timestamp()+0.1)
    assert first["stop_reason"] == "deadline" and first["ticks_used"] == 0
    assert first["counts"]["unfinished"] == 2
    first_bytes = (w.p/"runs/run-00.json").read_bytes()
    second = run(w, sequence=1, continuation=True, ticks=1)
    assert second["stop_reason"] == "max_ticks" and second["ticks_used"] == 1
    assert second["enqueued_job_ids"] == first["enqueued_job_ids"]
    assert second["continuation_of"]["sha256"] == hashlib.sha256(first_bytes).hexdigest()
    assert len(list(w.ops.store.db.execute("SELECT * FROM jobs"))) == 3
    third = run(w, sequence=2, continuation=True)
    assert third["stop_reason"] == "terminal" and third["ticks_used"] == 5
    assert third["counts"]["map_done"] == 2
    assert len(list(w.ops.store.db.execute("SELECT * FROM jobs"))) == 8
    roots = [r[0] for r in w.ops.store.db.execute("SELECT job_id FROM jobs WHERE stage='acquire'")]
    assert set(roots) == set(first["enqueued_job_ids"])
    assert all(s["usage"]["requests"] == 0 for s in (first, second, third))
    assert (w.p/"runs/run-00.json").read_bytes() == first_bytes
    with pytest.raises(ValueError, match="continuation not authorized"):
        run(w, sequence=3, continuation=True)


@pytest.mark.parametrize("state,stop", [("stale", "preflight_refused"), ("cancelled", "terminal"), ("held", "terminal"),
                                        ("failed_terminal", "terminal"), ("failed_uncertain", "preflight_refused"), ("queued", "not_claimable")])
def test_frontier_never_false_success(world, state, stop):
    w = world
    enqueue(w)
    w.ops.store.db.execute("UPDATE jobs SET state=?,not_before=?", (state, CLOCK.timestamp()+100))
    summary = run(w)
    assert summary["stop_reason"] == stop
    assert summary["counts"]["map_done"] == 0
    assert summary["counts"]["unfinished" if state == "queued" else state] == 2
    assert summary["usage"]["requests"] == 0


def test_missing_committed_successor_is_integrity_failure(world, synthetic_dispatch):
    w = world
    enqueue(w)
    run(w, ticks=1)
    w.ops.store.db.execute("DELETE FROM jobs WHERE stage='qualify'")
    before = snapshot(w)
    summary = run(w, sequence=1, continuation=True)
    assert summary["stop_reason"] == "integrity_error"
    assert summary["counts"]["unfinished"] == 2
    assert summary["ticks_used"] == 0
    assert snapshot(w) == before


def test_status_cli_is_read_only_and_no_old_aliases(tmp_path, capsys):
    assert driver.main(["status", "--root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "uninitialized"
    assert not (tmp_path/"var").exists()
    with pytest.raises(SystemExit):
        driver.main(["run", "--root", str(tmp_path), "--max-jobs", "2"])


def test_module_has_no_network_client_imports():
    names = set()
    for node in ast.walk(ast.parse(Path(driver.__file__).read_text())):
        if isinstance(node, ast.Import):
            names.update(n.name for n in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module)
    assert not names & {"socket", "urllib.request", "http.client", "requests", "httpx", "ssl", "subprocess"}


@pytest.mark.gis
@pytest.mark.parametrize("world", ["real-stages"], indirect=True)
def test_real_stage_producers_preserve_two_windows_without_scientific_patches(world, monkeypatch):
    from skippercast.coastal.stage_cli import execute
    w = world
    enqueue(w)
    original_init = loop.Coordinator.__init__
    def dispatch(job, job_path, out, identity_callback, deadline):
        value = execute(job, out, now=NOW)
        write(out/"result.json", value)
        return SimpleNamespace(rc={"done": 0, "held": 3}[value["state"]])
    def initialize(coordinator, store, **kwargs):
        original_init(coordinator, store, dispatcher=dispatch, **kwargs)
    monkeypatch.setattr(loop.Coordinator, "__init__", initialize)
    summary = run(w)
    assert summary["stop_reason"] == "terminal", summary["problems"]
    assert summary["counts"]["map_done"] == 2, summary["windows"]
    assert summary["ticks_used"] == 6
    assert summary["usage"]["requests"] == 0
    assert summary["untouched"]["render_jobs_left_queued"] == 2
