"""SC-3 catalog -> coordinator acquire bridge: allowlist, caps, source-free, no network.

A frozen discovery catalog (#734 shape, synthetic) is bridged to the acquire
stage's `coastal-native-job-v1` input. Every test runs with sockets disabled.
"""
import ast
import json
import os
from pathlib import Path
import socket
import stat

import pytest

from skippercast.coastal.coordinator import catalog_bridge as bridge
from skippercast.http import Allowlist, default_allowlist
from tests import _coastal_catalog_fixture as fx
from tests._support import FIXTURES

ALLOW = Allowlist([fx.HOST])


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the catalog bridge must not open a socket")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.fixture
def world(tmp_path):
    root = tmp_path / "queue"
    root.mkdir()
    source = fx.cache_file(root, "sources/H11952_MB_2m_MLLW_1of1.bag")
    rows = [fx.candidate("H11952_MB_2m_MLLW_1of1.bag", size=source["bytes"], source_hash=source["sha256"])]
    catalog = fx.frozen_catalog(rows)
    path = tmp_path / "catalog.json"
    sha = fx.write_catalog(path, catalog)
    sel = fx.selection(rows[0]["source_id"], source)
    return dict(root=root, tmp=tmp_path, catalog=catalog, path=path, sha=sha, source=source, rows=rows,
                plan=fx.plan(catalog, sha, [sel]))


def rebuild(world, rows, selections, **plan_changes):
    catalog = fx.frozen_catalog(rows)
    path = world["tmp"] / f"catalog-{len(list(world['tmp'].glob('catalog-*.json')))}.json"
    sha = fx.write_catalog(path, catalog)
    return path, fx.plan(catalog, sha, selections, **plan_changes)


def test_dry_run_selects_allowlisted_cached_lead_and_writes_only_a_receipt(world):
    receipt = bridge.dry_run(world["root"], world["path"], world["plan"], world["tmp"] / "dry", allowlist=ALLOW)
    assert receipt["schema"] == bridge.DRY_RUN
    assert receipt["selected_source_ids"] == [world["rows"][0]["source_id"]] and receipt["held_source_ids"] == []
    assert receipt["network_requests"] == receipt["source_opens"] == receipt["source_bytes_read"] == 0
    assert receipt["review_required"] is True and receipt["execution_authorized"] is False
    assert receipt["catalog"]["catalog_id"] == world["catalog"]["catalog_id"]
    assert receipt["catalog"]["sha256"] == world["sha"]
    assert receipt["decisions"][0]["catalog_hash_binding"] == "matched"
    assert [w["stage"] for w in receipt["would_enqueue"]] == ["acquire"]
    assert receipt["caps"]["max_jobs"] == bridge.MAX_JOBS and receipt["caps"]["selected_bytes"] == world["source"]["bytes"]
    written = sorted(p.name for p in (world["tmp"] / "dry").iterdir())
    assert written == ["bridge-dry-run-receipt.json"]
    assert not os.stat(world["tmp"] / "dry" / written[0]).st_mode & 0o222
    with pytest.raises(ValueError, match="never reused"):
        bridge.dry_run(world["root"], world["path"], world["plan"], world["tmp"] / "dry", allowlist=ALLOW)


def test_default_allowlist_admits_the_reviewed_ncei_host(world):
    assert fx.HOST in default_allowlist().exact
    receipt = bridge.dry_run(world["root"], world["path"], world["plan"], world["tmp"] / "dry")
    assert receipt["selected_source_ids"] == [world["rows"][0]["source_id"]]


@pytest.mark.parametrize("url, reason", [
    ("http://data.ngdc.noaa.gov/x.bag", "access_url_not_https"),
    ("https://gis.ngdc.noaa.gov/x.bag", "access_host_not_on_reviewed_allowlist"),
    ("https://data.ngdc.noaa.gov.evil.test/x.bag", "access_host_not_on_reviewed_allowlist"),
    ("https://user:pw@data.ngdc.noaa.gov/x.bag", "access_url_credentials_or_port"),
    ("https://data.ngdc.noaa.gov:8443/x.bag", "access_url_credentials_or_port"),
    ("https://data.ngdc.noaa.gov:notaport/x.bag", "access_url_malformed"),
    ("https://[data.ngdc.noaa.gov/x.bag", "access_url_malformed"),
    ("", "access_url_not_https"),
])
def test_access_url_must_be_https_on_an_exact_allowlisted_host(world, url, reason):
    rows = [fx.candidate("x.bag", url=url)]
    path, plan = rebuild(world, rows, [fx.selection(rows[0]["source_id"], world["source"])])
    receipt = bridge.dry_run(world["root"], path, plan, world["tmp"] / "dry", allowlist=ALLOW)
    assert receipt["selected_source_ids"] == [] and reason in receipt["decisions"][0]["holds"]


def test_suffix_wildcard_never_admits_a_host(world):
    wildcard = Allowlist(["*.ngdc.noaa.gov"])
    assert wildcard.allows(fx.HOST)
    receipt = bridge.dry_run(world["root"], world["path"], world["plan"], world["tmp"] / "dry", allowlist=wildcard)
    assert receipt["decisions"][0]["holds"] == ["access_host_not_on_reviewed_allowlist"]


def test_bridge_never_widens_the_allowlist(world):
    before = frozenset(ALLOW.exact)
    bridge.dry_run(world["root"], world["path"], world["plan"], world["tmp"] / "dry", allowlist=ALLOW)
    assert ALLOW.exact == before


def test_job_count_cap_refuses_before_any_write(world):
    rows = [fx.candidate(f"s{i}.bag") for i in range(bridge.MAX_SOURCES + 1)]
    sels = [fx.selection(r["source_id"], world["source"]) for r in rows]
    path, plan = rebuild(world, rows, sels)
    with pytest.raises(ValueError, match="1..4"):
        bridge.dry_run(world["root"], path, plan, world["tmp"] / "dry", allowlist=ALLOW)
    assert not (world["tmp"] / "dry").exists()


@pytest.mark.parametrize("changes, match", [
    (dict(max_total_bytes=bridge.MAX_TOTAL_BYTES + 1), "max_total_bytes"),
    (dict(max_total_bytes=0), "max_total_bytes"),
    (dict(budget=dict(fx.BUDGET, requests=1)), "zero requests"),
    (dict(budget=dict(fx.BUDGET, wall_s=bridge.MAX_WALL_S + 1)), "wall"),
    (dict(budget=dict(fx.BUDGET, bytes=bridge.MAX_TOTAL_BYTES + 1)), "byte budget"),
    (dict(budget=dict(fx.BUDGET, extra=1)), "exactly"),
    (dict(budget=dict(fx.BUDGET, bytes=1.5)), "integers"),
])
def test_caps_are_fixed_and_checked_before_any_write(world, changes, match):
    plan = dict(world["plan"], **changes)
    with pytest.raises(ValueError, match=match):
        bridge.dry_run(world["root"], world["path"], plan, world["tmp"] / "dry", allowlist=ALLOW)
    assert not (world["tmp"] / "dry").exists()


def test_selected_bytes_must_fit_the_total_and_per_job_caps(world):
    small = world["source"]["bytes"] - 1
    with pytest.raises(ValueError, match="max_total_bytes"):
        bridge.dry_run(world["root"], world["path"], dict(world["plan"], max_total_bytes=small),
                       world["tmp"] / "a", allowlist=ALLOW)
    with pytest.raises(ValueError, match="per-job"):
        bridge.dry_run(world["root"], world["path"], dict(world["plan"], budget=dict(fx.BUDGET, bytes=small)),
                       world["tmp"] / "b", allowlist=ALLOW)


@pytest.mark.parametrize("change, match", [
    (dict(execution_authorized=True), "authorizes nothing"),
    (dict(review_required=False), "authorizes nothing"),
    (dict(mapping_accepted=True), "authorizes nothing"),
    (dict(schema="coastal-source-v1"), "frozen discovery catalog"),
])
def test_catalog_must_stay_review_required_metadata(world, change, match):
    catalog = fx.frozen_catalog(world["rows"], **change)
    path = world["tmp"] / "bad.json"
    sha = fx.write_catalog(path, catalog)
    plan = fx.plan(catalog, sha, world["plan"]["selections"])
    with pytest.raises(ValueError, match=match):
        bridge.dry_run(world["root"], path, plan, world["tmp"] / "dry", allowlist=ALLOW)


def test_catalog_integrity_and_plan_binding(world):
    tampered = json.loads(world["path"].read_text())
    tampered["usable_source_ids"].append("ncei:injected")
    path = world["tmp"] / "tampered.json"
    fx.write_catalog(path, tampered)
    with pytest.raises(ValueError, match="catalog_id"):
        bridge.dry_run(world["root"], path, world["plan"], world["tmp"] / "a", allowlist=ALLOW)
    other = dict(world["plan"], catalog_sha256="f" * 64)
    with pytest.raises(ValueError, match="exact frozen catalog"):
        bridge.dry_run(world["root"], world["path"], other, world["tmp"] / "b", allowlist=ALLOW)


def test_candidate_gates_hold_with_reasons(world):
    src = world["source"]
    rows = [fx.candidate("blocked.bag", usable=False), fx.candidate("old.bag", expires="2000-01-01T00:00:00Z"),
            fx.candidate("far.bag", bbox=[10.0, 10.0, 11.0, 11.0]),
            fx.candidate("size.bag", size=src["bytes"] + 1)]
    sels = [fx.selection(r["source_id"], src) for r in rows]
    path, plan = rebuild(world, rows, sels)
    receipt = bridge.dry_run(world["root"], path, plan, world["tmp"] / "dry", allowlist=ALLOW)
    holds = {d["source_id"]: d["holds"] for d in receipt["decisions"]}
    assert receipt["selected_source_ids"] == []
    assert {"not_a_usable_catalog_lead", "catalog_rejection_reasons_present"} <= set(holds["ncei:blocked.bag"])
    assert holds["ncei:old.bag"] == ["catalog_candidate_expired"]
    assert holds["ncei:far.bag"] == ["catalog_extent_does_not_overlap_segment"]
    assert holds["ncei:size.bag"] == ["cached_size_differs_from_catalog"]


def test_candidate_expiry_must_be_a_utc_stamp(world):
    rows = [fx.candidate("noexpiry.bag", expires=None), fx.candidate("local.bag", expires="2099-01-01T00:00:00"),
            fx.candidate("whole.bag", expires="2099-01-01T00:00:00Z")]
    path, plan = rebuild(world, rows, [fx.selection(r["source_id"], world["source"]) for r in rows])
    receipt = bridge.dry_run(world["root"], path, plan, world["tmp"] / "dry", allowlist=ALLOW)
    holds = {d["source_id"]: d["holds"] for d in receipt["decisions"]}
    assert holds["ncei:noexpiry.bag"] == holds["ncei:local.bag"] == ["catalog_candidate_expiry_unknown"]
    assert holds["ncei:whole.bag"] == []


def test_catalog_hash_binds_the_cached_ref(world):
    src = world["source"]
    rows = [fx.candidate("a.bag", source_hash="sha256:" + "e" * 64), fx.candidate("b.bag", source_hash="md5:abc"),
            fx.candidate("c.bag", source_hash=src["sha256"].upper())]
    path, plan = rebuild(world, rows, [fx.selection(r["source_id"], src) for r in rows])
    receipt = bridge.dry_run(world["root"], path, plan, world["tmp"] / "dry", allowlist=ALLOW)
    by = {d["source_id"]: d for d in receipt["decisions"]}
    assert by["ncei:a.bag"]["holds"] == ["cached_sha256_differs_from_catalog"]
    assert by["ncei:b.bag"]["state"] == "selected" and by["ncei:b.bag"]["catalog_hash_binding"] == "unknown"
    assert by["ncei:c.bag"]["catalog_hash_binding"] == "matched"


def test_unknown_selection_is_held(world):
    plan = fx.plan(world["catalog"], world["sha"], [fx.selection("ncei:not-there.bag", world["source"])])
    receipt = bridge.dry_run(world["root"], world["path"], plan, world["tmp"] / "dry", allowlist=ALLOW)
    assert receipt["decisions"] == [dict(source_id="ncei:not-there.bag", state="held", holds=["not_in_catalog"])]


def _single(world, source=None, window=None):
    sel = fx.selection(world["rows"][0]["source_id"], source or world["source"], window=window)
    receipt = bridge.dry_run(world["root"], world["path"], fx.plan(world["catalog"], world["sha"], [sel]),
                             world["tmp"] / f"dry-{len(list(world['tmp'].glob('dry-*')))}", allowlist=ALLOW)
    return receipt["decisions"][0]


def test_cached_source_is_checked_by_lstat_and_never_opened(world):
    path = world["root"] / world["source"]["path"]
    path.chmod(0)
    try:
        assert _single(world)["state"] == "selected"
    finally:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


@pytest.mark.parametrize("mutate, reason", [
    (lambda s, root: dict(s, path=str(root / s["path"])), "relative to the queue root"),
    (lambda s, root: dict(s, path="../outside.bag"), "relative to the queue root"),
    (lambda s, root: dict(s, bytes=s["bytes"] + 1), "byte count differs"),
    (lambda s, root: dict(s, path="sources/missing.bag"), "No such file"),
    (lambda s, root: dict(s, path="sources/H11952.vrt"), "native BAG or GeoTIFF"),
    (lambda s, root: dict(s, sha256="nothex"), "sha256"),
])
def test_cached_source_ref_gates(world, mutate, reason):
    decision = _single(world, source=mutate(world["source"], world["root"]))
    assert decision["state"] == "held" and reason in decision["holds"][0]


def test_symlinked_cached_source_is_held(world):
    link = world["root"] / "sources/link.bag"
    link.symlink_to(world["root"] / world["source"]["path"])
    decision = _single(world, source=dict(world["source"], path="sources/link.bag"))
    assert "symlink" in decision["holds"][0]


def test_window_cap_is_the_acquire_stage_cap():
    from skippercast.coastal.handoff import mapping_input
    assert bridge.MAX_WINDOW_CELLS == mapping_input.MAX_CELLS == 262_144


def test_window_is_bounded_like_the_acquire_stage(world):
    assert _single(world, window=[0, 0, 512, 512])["state"] == "selected"
    # Malformed windows stay per-candidate holds.
    assert _single(world, window=[0, 0, 0, 4])["state"] == "held"
    assert _single(world, window=[0, 0, True, 4])["state"] == "held"


@pytest.mark.parametrize("window", [[0, 0, 262_145, 1], [0, 0, 513, 512], [0, 0, 1024, 1024]])
def test_check_plan_refuses_a_window_the_acquire_stage_refuses(world, window):
    sel = fx.selection(world["rows"][0]["source_id"], world["source"], window=window)
    path, plan = rebuild(world, world["rows"], [sel])
    raw = path.read_bytes()
    with pytest.raises(ValueError, match="native_window_bound"):
        bridge.check_plan(plan, raw, json.loads(raw))
    out = world["tmp"] / "refused"
    with pytest.raises(ValueError, match="native_window_bound"):
        bridge.dry_run(world["root"], path, plan, out, allowlist=ALLOW)
    assert not out.exists()


def test_dispatch_gate_holds_a_window_the_acquire_stage_refuses(world):
    """A 262,145-cell native job reaching the Store is held before dispatch, not at acquire."""
    from skippercast.coastal.coordinator.stages import verify_ref
    from skippercast.coastal.coordinator.store import Store
    from tests._coastal_operations import policy
    source = fx.cache_file(world["root"], "sources/synthetic.tif", data=b"II*\x00synthetic")
    rows = [fx.candidate("synthetic.tif", size=source["bytes"], source_hash=source["sha256"])]
    path, plan = rebuild(world, rows, [fx.selection(rows[0]["source_id"], source)])
    receipt = bridge.run(world["root"], path, plan, world["root"] / "bridge", allowlist=ALLOW)
    store = Store(world["root"] / "var/coastal/coordinator.sqlite", root=world["root"], policy=policy())
    try:
        store.add_segment(dict(schema="coastal-segment-v1", segment_id=plan["segment"]["segment_id"],
                               region="t12-operations", crs="EPSG:3310", bbox=[0, 0, 5000, 5000],
                               bbox_crs84=fx.SEGMENT_BBOX, synthetic=True))
        ref = dict(path=receipt["output"]["path"], sha256=receipt["output"]["sha256"],
                   bytes=receipt["output"]["bytes"], kind="input", contract=bridge.RECEIPT)
        [job_id] = bridge.enqueue(store, ref, code_sha="a" * 64, deps_sha="b" * 64)
        job = json.loads(store.db.execute("SELECT record_json FROM jobs WHERE job_id=?",
                                          (job_id,)).fetchone()[0])
        manifest = json.loads(verify_ref(world["root"], job["input_manifest"]).read_text())

        def gate(window, name):
            raw = (json.dumps(dict(manifest, window=window), sort_keys=True) + "\n").encode()
            (world["root"] / name).write_bytes(raw)
            job_ref = dict(job["input_manifest"], path=name, sha256=bridge._sha(raw), bytes=len(raw))
            return store._evidence_gate(dict(job, input_manifest=job_ref))

        assert gate([0, 0, 512, 512], "at-cap.json") == (True, [])
        assert gate([0, 0, 262_144, 1], "at-cap-strip.json") == (True, [])
        assert gate([0, 0, 262_145, 1], "over-cap.json") == (False, ["native_window_bound"])
        assert gate([0, 0, 1024, 1024], "old-cap.json") == (False, ["native_window_bound"])
        assert gate([0, 0, True, 4], "bool.json") == (False, ["native_window_bound"])
    finally:
        store.close()


def test_run_writes_native_jobs_inside_root_and_enqueue_feeds_acquire(world, tmp_path):
    from skippercast.coastal.coordinator.store import Store
    from tests._coastal_operations import policy
    with pytest.raises(ValueError, match="inside the coordinator queue root"):
        bridge.run(world["root"], world["path"], world["plan"], tmp_path / "outside", allowlist=ALLOW)
    receipt = bridge.run(world["root"], world["path"], world["plan"], world["root"] / "bridge", allowlist=ALLOW)
    assert receipt["schema"] == bridge.RECEIPT and len(receipt["jobs"]) == 1
    job_ref = receipt["jobs"][0]["input_manifest"]
    manifest = json.loads((world["root"] / job_ref["path"]).read_text())
    assert manifest["schema"] == "coastal-native-job-v1" and manifest["source"] == world["source"]
    assert manifest["segment_id"] == world["plan"]["segment"]["segment_id"] and manifest["window"] == [0, 0, 4, 4]
    assert manifest["catalog_lineage"]["catalog_id"] == world["catalog"]["catalog_id"]
    assert manifest["catalog_lineage"]["review_required"] is True
    store = Store(world["root"] / "var/coastal/coordinator.sqlite", root=world["root"], policy=policy())
    try:
        record = dict(schema="coastal-segment-v1", segment_id=world["plan"]["segment"]["segment_id"],
                      region="t12-operations", crs="EPSG:3310", bbox=[0, 0, 5000, 5000],
                      bbox_crs84=fx.SEGMENT_BBOX)
        store.add_segment(record)
        ref = dict(path=receipt["output"]["path"], sha256=receipt["output"]["sha256"],
                   bytes=receipt["output"]["bytes"], kind="input", contract=bridge.RECEIPT)
        ids = bridge.enqueue(store, ref, code_sha="a" * 64, deps_sha="b" * 64)
        rows = store.db.execute("SELECT stage,state,record_json FROM jobs").fetchall()
        assert [(r["stage"], r["state"]) for r in rows] == [("acquire", "queued")]
        queued = json.loads(rows[0]["record_json"])
        assert queued["job_id"] == ids[0] and queued["input_manifest"] == job_ref
        assert queued["budget"] == fx.BUDGET
        # Idempotent: the same bridged job is one queued acquire job.
        assert bridge.enqueue(store, ref, code_sha="a" * 64, deps_sha="b" * 64) == ids
    finally:
        store.close()


def _enqueue_relative(root_arg, receipt):
    """Both the receipt ref and every native-job ref verify against the root and enqueue."""
    from skippercast.coastal.coordinator.stages import verify_ref
    from skippercast.coastal.coordinator.store import Store
    from tests._coastal_operations import policy
    root = Path(root_arg).resolve()
    ref = dict(path=receipt["output"]["path"], sha256=receipt["output"]["sha256"],
               bytes=receipt["output"]["bytes"], kind="input", contract=bridge.RECEIPT)
    assert not Path(ref["path"]).is_absolute()
    assert verify_ref(root, ref).parent.parent == root
    for job in receipt["jobs"]:
        assert not Path(job["input_manifest"]["path"]).is_absolute()
        verify_ref(root, job["input_manifest"])
    store = Store(Path(root_arg) / "var/coastal/coordinator.sqlite", root=root_arg, policy=policy())
    try:
        store.add_segment(dict(schema="coastal-segment-v1", segment_id=receipt["segment"]["segment_id"],
                               region="t12-operations", crs="EPSG:3310", bbox=[0, 0, 5000, 5000],
                               bbox_crs84=fx.SEGMENT_BBOX))
        ids = bridge.enqueue(store, ref, code_sha="a" * 64, deps_sha="b" * 64)
        rows = store.db.execute("SELECT stage,state,record_json FROM jobs").fetchall()
        assert [(r["stage"], r["state"]) for r in rows] == [("acquire", "queued")]
        assert json.loads(rows[0]["record_json"])["job_id"] == ids[0]
        assert json.loads(rows[0]["record_json"])["input_manifest"] == receipt["jobs"][0]["input_manifest"]
    finally:
        store.close()


@pytest.mark.parametrize("absolute_root", [False, True], ids=["relative-root", "absolute-root"])
def test_run_with_relative_output_writes_consistent_refs_and_enqueues(world, monkeypatch, absolute_root):
    # tmp_path is absolute; work from its parent so root and out are genuinely relative.
    monkeypatch.chdir(world["tmp"].parent)
    rel_root = Path(world["tmp"].name) / "queue"
    assert not rel_root.is_absolute() and rel_root.resolve() == world["root"].resolve()
    root_arg = world["root"] if absolute_root else rel_root
    out = rel_root / "relative-output"
    assert not out.is_absolute()
    receipt = bridge.run(root_arg, world["path"], world["plan"], out, allowlist=ALLOW)
    assert receipt["output"]["path"] == "relative-output/bridge-receipt.json"
    assert receipt["jobs"][0]["input_manifest"]["path"] == "relative-output/native-job-00.json"
    assert sorted(p.name for p in (world["root"] / "relative-output").iterdir()) == [
        "bridge-receipt.json", "native-job-00.json"]
    _enqueue_relative(root_arg, receipt)
    # The no-reuse gate holds for the same relative directory and its absolute spelling.
    for again in (out, world["root"] / "relative-output"):
        with pytest.raises(ValueError, match="never reused"):
            bridge.run(root_arg, world["path"], world["plan"], again, allowlist=ALLOW)


def test_relative_output_outside_the_root_is_refused_before_any_write(world, monkeypatch):
    monkeypatch.chdir(world["tmp"])
    for out in (Path("outside"), Path("queue/../outside"), Path("queue/..")):
        with pytest.raises(ValueError, match="inside the coordinator queue root|plain final name"):
            bridge.run(Path("queue"), world["path"], world["plan"], out, allowlist=ALLOW)
    assert not (world["tmp"] / "outside").exists()
    escape = world["root"] / "escape"
    escape.symlink_to(world["tmp"], target_is_directory=True)
    with pytest.raises(ValueError, match="inside the coordinator queue root"):
        bridge.run(Path("queue"), world["path"], world["plan"], Path("queue/escape/out"), allowlist=ALLOW)
    assert not (world["tmp"] / "out").exists()


def test_enqueue_refuses_a_segment_that_differs(world):
    from skippercast.coastal.coordinator.store import Store
    from tests._coastal_operations import policy
    receipt = bridge.run(world["root"], world["path"], world["plan"], world["root"] / "bridge", allowlist=ALLOW)
    store = Store(world["root"] / "var/coastal/coordinator.sqlite", root=world["root"], policy=policy())
    try:
        store.add_segment(dict(schema="coastal-segment-v1", segment_id=world["plan"]["segment"]["segment_id"],
                               region="t12-operations", crs="EPSG:3310", bbox=[0, 0, 5000, 5000],
                               bbox_crs84=[0.0, 0.0, 1.0, 1.0]))
        ref = dict(path=receipt["output"]["path"], sha256=receipt["output"]["sha256"],
                   bytes=receipt["output"]["bytes"], kind="input", contract=bridge.RECEIPT)
        with pytest.raises(ValueError, match="segment differs"):
            bridge.enqueue(store, ref, code_sha="a" * 64, deps_sha="b" * 64)
        assert store.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    finally:
        store.close()


def test_bridge_module_imports_no_network_client():
    tree = ast.parse(Path(bridge.__file__).read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(("." * node.level) + (node.module or ""))
    forbidden = {"socket", "urllib.request", "http.client", "requests", "httpx", "ssl", "subprocess"}
    assert not names & forbidden, names & forbidden
    assert "...live_discovery" not in names and "..live_discovery" not in names


def _tile(width, height, tile=512):
    """Row-major 512x512 tiling of a native grid, from its north-west corner."""
    return [[x, y, min(tile, width - x), min(tile, height - y)]
            for y in range(0, height, tile) for x in range(0, width, tile)]


def _assert_tiles(windows, width, height):
    """The windows partition the grid exactly: in bounds, no overlap, no gap."""
    area = 0
    for index, (x, y, w, h) in enumerate(windows):
        assert 0 <= x and 0 <= y and x + w <= width and y + h <= height, (index, windows[index])
        area += w * h
        for x2, y2, w2, h2 in windows[:index]:
            assert not (x < x2 + w2 and x2 < x + w and y < y2 + h2 and y2 < y + h), "overlap"
    assert area == width * height, "gap"


def test_window_set_plan_enqueues_one_job_per_window_in_index_order(world):
    """A 64-window plan enqueues 64 acquire jobs whose windows tile the raster (G5)."""
    from skippercast.coastal.coordinator.store import Store
    from tests._coastal_operations import policy
    grid = {"width": 4096, "height": 4096}
    windows = _tile(grid["width"], grid["height"])
    assert len(windows) == bridge.MAX_WINDOWS == 64
    sel = fx.window_set(world["rows"][0]["source_id"], world["source"], windows, grid=grid)
    plan = fx.plan(world["catalog"], world["sha"], [sel])
    receipt = bridge.run(world["root"], world["path"], plan, world["root"] / "bridge-ws", allowlist=ALLOW)
    assert len(receipt["jobs"]) == 64
    # The receipt lists every window with its index and manifest sha256, in index order.
    assert [job["window_index"] for job in receipt["jobs"]] == list(range(64))
    assert [job["window"] for job in receipt["jobs"]] == windows
    assert [job["input_manifest"]["sha256"] for job in receipt["jobs"]]
    # A cached source is counted once toward the byte budget, not once per window.
    assert receipt["caps"]["selected_bytes"] == world["source"]["bytes"]
    store = Store(world["root"] / "var/coastal/coordinator.sqlite", root=world["root"], policy=policy())
    try:
        store.add_segment(dict(schema="coastal-segment-v1", segment_id=plan["segment"]["segment_id"],
                               region="t12-operations", crs="EPSG:3310", bbox=[0, 0, 5000, 5000],
                               bbox_crs84=fx.SEGMENT_BBOX))
        ref = dict(path=receipt["output"]["path"], sha256=receipt["output"]["sha256"],
                   bytes=receipt["output"]["bytes"], kind="input", contract=bridge.RECEIPT)
        ids = bridge.enqueue(store, ref, code_sha="a" * 64, deps_sha="b" * 64)
        assert len(ids) == 64
        # Job ids come back in index order: ids[i] is the i-th window's acquire job.
        for i, job_id in enumerate(ids):
            queued = json.loads(store.db.execute("SELECT record_json FROM jobs WHERE job_id=?",
                                                 (job_id,)).fetchone()[0])
            assert queued["input_manifest"] == receipt["jobs"][i]["input_manifest"]
            manifest = json.loads((world["root"] / queued["input_manifest"]["path"]).read_text())
            assert manifest["window"] == windows[i]
    finally:
        store.close()
    _assert_tiles(windows, grid["width"], grid["height"])


def test_four_window_plan_keeps_today_receipt_except_the_raised_job_cap(world):
    """Backward compatibility: today's max plan (four sources, one window each) is unchanged.

    The gate decisions, the selected/held lists and every native-job manifest (the
    ``would_enqueue`` sha256s) stay byte-identical to today's receipt; the only delta is
    the caps block, which this card raises (MAX_JOBS: 4 -> N x sources, G5).
    """
    source = world["source"]
    rows = [fx.candidate(f"s{i}.bag", size=source["bytes"], source_hash=source["sha256"])
            for i in range(bridge.MAX_SOURCES)]
    sels = [fx.selection(r["source_id"], source) for r in rows]
    path, plan = rebuild(world, rows, sels)
    receipt = bridge.dry_run(world["root"], path, plan, world["tmp"] / "dry", allowlist=ALLOW)
    golden = json.loads((FIXTURES / "bridge-4-window-dry-run-receipt.json").read_text())
    for key in ("decisions", "would_enqueue", "selected_source_ids", "held_source_ids",
                "plan_sha256", "catalog", "segment_id", "schema", "network_requests",
                "source_opens", "source_bytes_read", "review_required", "mapping_accepted",
                "execution_authorized", "note"):
        assert receipt[key] == golden[key], key
    assert len(receipt["would_enqueue"]) == 4
    assert receipt["caps"] == dict(golden["caps"], max_jobs=bridge.MAX_JOBS,
                                   max_sources=bridge.MAX_SOURCES,
                                   max_windows_per_source=bridge.MAX_WINDOWS)


def test_65th_window_is_refused_before_any_write(world):
    windows = [[0, 0, 512, 512]] * 65
    sel = fx.window_set(world["rows"][0]["source_id"], world["source"], windows)
    plan = fx.plan(world["catalog"], world["sha"], [sel])
    out = world["tmp"] / "refused-65"
    with pytest.raises(ValueError, match="window_set_size"):
        bridge.dry_run(world["root"], world["path"], plan, out, allowlist=ALLOW)
    assert not out.exists()


def test_window_above_the_acquire_bound_is_refused_before_any_write(world):
    windows = [[0, 0, 512, 512]] * 63 + [[0, 0, 513, 512]]
    sel = fx.window_set(world["rows"][0]["source_id"], world["source"], windows)
    plan = fx.plan(world["catalog"], world["sha"], [sel])
    out = world["tmp"] / "refused-overcap"
    with pytest.raises(ValueError, match="native_window_bound"):
        bridge.dry_run(world["root"], world["path"], plan, out, allowlist=ALLOW)
    assert not out.exists()


@pytest.mark.parametrize("windows, grid, match", [
    ([[0, 0, 512, 512], [256, 0, 512, 512]], {"width": 1024, "height": 512}, "overlap"),
    ([[0, 0, 512, 512]], {"width": 1024, "height": 512}, "gap"),
    ([[512, 0, 512, 512]], {"width": 512, "height": 512}, "outside"),
    ([[512, 0, 512, 512], [0, 0, 512, 512]], {"width": 1024, "height": 512}, "row-major"),
])
def test_window_set_must_tile_its_declared_grid(world, windows, grid, match):
    sel = fx.window_set(world["rows"][0]["source_id"], world["source"], windows, grid=grid)
    plan = fx.plan(world["catalog"], world["sha"], [sel])
    out = world["tmp"] / f"tile-{match}"
    with pytest.raises(ValueError, match=match):
        bridge.dry_run(world["root"], world["path"], plan, out, allowlist=ALLOW)
    assert not out.exists()
