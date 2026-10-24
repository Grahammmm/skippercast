"""Exclusive, bounded execution of an admitted frozen bridge plan (no downloads).

Only this driver and its own synchronous tick/heartbeat may write the queue.
The admission's exclusive_writer attestation is an operator precondition, not
an assertion that flock excludes uncooperative writers. Contaminated queues
require separate operator recovery, never automatic repair here.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from importlib.resources import files
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import time
from typing import Any

from ..cli import queue_status
from . import catalog_bridge, loop
from .segments import from_bbox, segment
from .stages import NEXT, ORDER, digest
from .store import Store

DATABASE = "var/coastal/coordinator.sqlite"
STAGES = ("acquire", "qualify", "map", "render")
STATES = {"queued", "done", "held", "failed_terminal", "failed_retryable",
          "failed_uncertain", "stale", "cancelled", "claimed", "running"}
PARTITION = ("map_done", "held", "failed_terminal", "failed_uncertain",
             "stale", "cancelled", "unfinished")
CONTINUABLE = {"deadline", "max_ticks", "not_claimable"}
HEX = re.compile(r"[0-9a-f]{64}")
LABEL = re.compile(r"[A-Za-z0-9_-]+")


def utc(epoch=None):
    return datetime.fromtimestamp(time.time() if epoch is None else epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def _absolute(path):
    path = Path(path)
    if not path.is_absolute() or any(p in {".", ".."} for p in str(path).split("/")):
        raise ValueError("absolute normalized paths required")
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError("symlink path refused")
    return path


def _relative(path):
    if (not isinstance(path, str) or not path or path.startswith("/")
            or "\\" in path or "\x00" in path
            or any(p in {"", ".", ".."} for p in path.split("/"))):
        raise ValueError("confined relative POSIX path required")
    return path


@contextmanager
def _parent(root, relative):
    """No-follow directory-FD traversal; root bindings cannot come from receipts."""
    parts = _relative(relative).split("/")
    fd = os.open(_absolute(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd, parts[-1]
    finally:
        os.close(fd)


def _read(root, relative, *, metadata=True):
    with _parent(root, relative) as (parent, leaf):
        fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or metadata and info.st_size > catalog_bridge.MAX_DOCUMENT_BYTES:
                raise ValueError("regular bounded metadata required")
            return stream.read()


def _json(root, relative):
    return json.loads(_read(root, relative), parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def _ref(root, path, root_id):
    relative = _absolute(path).relative_to(root).as_posix()
    raw = _read(root, relative)
    return dict(root_id=root_id, path=relative, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))


def _verify(root, ref, root_id, *, metadata=True) -> Any:
    if "root_id" in ref and ref["root_id"] != root_id:
        raise ValueError("unexpected reference namespace")
    if not HEX.fullmatch(ref.get("sha256", "")) or type(ref.get("bytes")) is not int:
        raise ValueError("invalid byte reference")
    raw = _read(root, ref["path"], metadata=metadata)
    if len(raw) != ref["bytes"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError("reference hash/bytes mismatch: " + ref["path"])
    return json.loads(raw) if metadata else raw


def _freeze(root, path, value):
    relative = _absolute(path).relative_to(root).as_posix()
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    with _parent(root, relative) as (parent, leaf):
        fd = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444, dir_fd=parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(parent)


def _new_output(root, path):
    path = _absolute(path)
    relative = path.relative_to(root).as_posix()
    with _parent(root, relative) as (parent, leaf):
        try:
            os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return path
    raise ValueError("output exists; use a new immutable attempt")


def _header(schema, admission):
    # Explicit runtime provenance, never inferred from a profile or model alias.
    names = {"author_profile": "COAST_AUTHOR_PROFILE", "author_model": "COAST_AUTHOR_MODEL",
             "card_id": "COAST_CARD_ID", "code_commit": "COAST_CODE_COMMIT", "skill_commit": "COAST_SKILL_COMMIT"}
    header = {key: os.environ.get(env) for key, env in names.items()}
    if any(not isinstance(v, str) or not v.strip() for v in header.values()):
        raise ValueError("explicit COAST runtime provenance environment required")
    return dict(header, schema=schema, created_utc=utc(),
                **{key: admission[key] for key in ("campaign_segment_id", "coordinator_segment_id", "plan_id", "plan_sha256")})


def _policy():
    return json.loads(files("skippercast.coastal.coordinator").joinpath("policy.json").read_text())


@contextmanager
def _snapshot(root):
    path = root / DATABASE
    _absolute(path)
    if not path.exists():
        yield None
        return
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        yield connection
    finally:
        connection.close()


def _rows(db):
    return {} if db is None else {r["job_id"]: dict(r) for r in db.execute("SELECT * FROM jobs")}


def _identity(record):
    """Store's generic idempotency identity; no writes or dispatch gates bypassed."""
    ref = record.get("input_manifest")
    owned = ({"schema": "coastal-owned-input-v1", "path": _relative(ref["path"]),
              "sha256": ref["sha256"], "bytes": ref["bytes"]} if ref else "0" * 64)
    return digest([record["stage"], record["segment_id"], owned, record["code_sha"],
                   record["deps_sha"], digest(record["params"]), digest(record["budget"])])


def _preflight(root, db, binding):
    try:
        return _preflight_checked(root, db, binding)
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as error:
        return ["unclassifiable Store/policy: " + str(error)]


def _preflight_checked(root, db, binding):
    reasons = []
    if os.environ.get("COAST_EXCLUSIVE_WRITER") != str(root):
        reasons.append("current operator exclusive writer assertion absent")
    if loop.implementation_hashes(root) != tuple(binding):
        reasons.append("imported implementation changed")
    if db is None:
        return reasons
    for table in ("authenticated_missions", "sourcefree_imports", "retained_producers"):
        if db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone() and db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
            reasons.append("foreign mission policy: " + table)
    if db.execute("SELECT 1 FROM leases LIMIT 1").fetchone():
        reasons.append("leases present (expired or unexpired)")
    for row in _rows(db).values():
        job = json.loads(row["record_json"])
        if (job.get("code_sha"), job.get("deps_sha")) != tuple(binding):
            reasons.append("foreign or stale identity: " + row["job_id"])
        if row["state"] not in STATES or row["state"] in {"stale", "claimed", "running", "failed_uncertain"}:
            reasons.append("unsafe state: " + row["job_id"] + ":" + row["state"])
        if (row["stage"] not in ORDER or job.get("execution_contract") or job.get("sourcefree_contract")
                or job.get("managed_output_grant") or job.get("stage") != row["stage"]):
            reasons.append("foreign execution contract: " + row["job_id"])
        elif (_identity(job) != row["idempotency_key"] or "job:" + row["idempotency_key"][:24] != row["job_id"]
              or job["segment_id"] != row["segment_id"] or job["job_id"] != row["job_id"]
              or job["params_sha"] != digest(job["params"])
              or job["input_manifest_sha"] != (job["input_manifest"]["sha256"] if job["input_manifest"] else "0"*64)):
            reasons.append("Store identity mismatch: " + row["job_id"])
    # Existing authority must agree; opening Store must not reset a mission.
    for path in (root / DATABASE).parent.glob("budget-*.json"):
        ledger = _json(root, path.relative_to(root).as_posix())
        limits = dict(_policy()["budgets"], attempts_per_candidate=_policy()["max_attempts"])
        if (any(ledger.get("limits", {}).get(k) != v for k, v in limits.items())
                or ledger.get("limits_sha256") != digest(ledger.get("limits"))):
            reasons.append("foreign budget policy: " + path.name)
    return reasons


def _bind_window(position, job, window, item, grids, record, campaign, keys):
    """Bind one ordered expansion item, before any queue or output is created.

    item carries the four expansion fields plus read-only manifest context;
    grids carries entries and the per-selection grid identities seen so far.
    Refusal order is part of the admission contract.
    """
    selection, decision, index, native_window = item["expansion"]
    source_id = selection["source_id"]
    is_set = "windows" in selection

    def refuse(code, detail=None):
        raise ValueError("window binding mismatch: " + code + (": " + detail if detail else ""))

    if window["window_key"] in keys:
        refuse("duplicate")
    keys.add(window["window_key"])
    if (job.get("source_id") != source_id
            or is_set and (job.get("window_index") != index or job.get("window") != native_window)
            or not is_set and ("window_index" in job or "window" in job)):
        refuse("job")
    grid_sha, idx = window["grid_sha256"], window["idx"]
    key = f"{window['source_id']}#{grid_sha}#{idx}"
    if (type(idx) is not int or idx != index or window["window_key"] != key
            or window["window_dir"] != hashlib.sha256(key.encode()).hexdigest()):
        refuse("idx", "window/grid/owner binding mismatch")
    if window["pixel_window"] != native_window:
        refuse("pixel_window")
    if window["source_id"] != source_id:
        refuse("source")
    grid = grids["entries"].get(grid_sha)
    if (grid is None or digest(grid["definition"]) != grid_sha
            or grids["selection_grid"].setdefault(source_id, grid_sha) != grid_sha):
        refuse("grid")
    definition = grid["definition"]
    if (grid["source_id"] != source_id or definition["source_sha256"] != selection["source"]["sha256"]):
        refuse("grid_source")
    if definition["tiling_version"] != ("window-set-v1" if is_set else "single-selected-v1"):
        refuse("tiling_version", "window-set grid requires reviewed PC-6 support")
    if is_set:
        tiling = selection["tiling"]
        native_windows = selection["windows"]
        if (definition["tiling"] != tiling
                or (definition["width"], definition["height"]) != (tiling["width"], tiling["height"])
                or (definition["tile_width"], definition["tile_height"]) != (tiling["tile"], tiling["tile"])
                or grid["total"] != len(native_windows)
                or grid["cols"] != len({w[0] for w in native_windows})
                or grid["rows"] != len({w[1] for w in native_windows})):
            refuse("grid_shape")
    elif (definition["pixel_window"] != selection["window"]
            or (grid["cols"], grid["rows"], grid["total"]) != (1, 1, 1)):
        refuse("grid_shape")
    # Prove the native pixel-centre owner; an admission label is not geography.
    from pyproj import Transformer
    col, row, width, height = window["pixel_window"]
    a, b, c, d, e, f = definition["affine_transform"]
    if (any(type(definition[k]) is not int or definition[k] <= 0 for k in ("width", "height", "tile_width", "tile_height"))
            or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in (a, b, c, d, e, f))
            or col+width > definition["width"] or row+height > definition["height"]):
        refuse("owner", "invalid source grid/window bounds")
    if is_set and (problem := catalog_bridge.tiling_affine_problem(selection["tiling"], definition)):
        refuse("grid_geometry", problem)
    x, y = col + width/2, row + height/2
    transform = Transformer.from_crs(definition["raster_crs"], "EPSG:3310", always_xy=True)
    cx, cy = transform.transform(a*x+b*y+c, d*x+e*y+f)
    owner = segment(math.floor(cx/5000)*5000, math.floor(cy/5000)*5000, region=item["root"].name)
    if window["owner_segment_id"] != record["segment_id"]:
        refuse("owner", "window/grid/owner binding mismatch")
    if owner["segment_id"] != record["segment_id"]:
        refuse("owner", "pixel centre owner mismatch")
    from shapely.geometry import Polygon, box
    geographic = Transformer.from_crs(definition["raster_crs"], "OGC:CRS84", always_xy=True)
    corners = [(col, row), (col+width, row), (col+width, row+height), (col, row+height)]
    edge = []
    for start, end in zip(corners, corners[1:]+corners[:1]):
        for step in range(41):
            px = start[0] + (end[0]-start[0])*step/41
            py = start[1] + (end[1]-start[1])*step/41
            edge.append(geographic.transform(a*px+b*py+c, d*px+e*py+f))
    footprint = Polygon(edge)
    if (not footprint.is_valid or footprint.is_empty
            or footprint.intersection(box(*campaign["bbox_crs84"])).area <= 0
            or footprint.intersection(box(*record["bbox_crs84"])).area <= 0):
        refuse("footprint", "window footprint does not overlap campaign/owner")
    try:
        native = _verify(item["root"], job["input_manifest"], item["root_id"])
        expected_native = catalog_bridge.native_job(item["plan"], selection, decision,
                                                    item["catalog_ref"], window=native_window)
        if native != expected_native:
            refuse("native", "native manifest differs from pinned plan/catalog")
        catalog_bridge.cached_source(item["root"], native["source"])
        catalog_bridge._window(native["window"])
        if (job.get("stage") != "acquire" or native.get("schema") != catalog_bridge.NATIVE_JOB
                or native.get("segment_id") != record["segment_id"] or native["source"] != selection["source"]
                or native["window"] != native_window or native["catalog_lineage"]["source_id"] != source_id
                or native["catalog_lineage"]["catalog_sha256"] != item["catalog_ref"]["sha256"]):
            refuse("native", "native manifest binding mismatch")
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError("window binding mismatch: native") from error


def _context(root, admission_path, bridge_path, segment_path):
    try:
        return _context_checked(root, admission_path, bridge_path, segment_path)
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError("invalid admission binding") from error


def _context_checked(root, admission_path, bridge_path, segment_path):
    root_id = "queue:" + root.name
    admission = _json(root, _absolute(admission_path).relative_to(root).as_posix())
    if (admission.get("schema") != "coast-admission-v1" or admission.get("campaign_segment_id") != root.name
            or not LABEL.fullmatch(root.name) or not LABEL.fullmatch(admission.get("plan_id", ""))
            or admission.get("holds") != []):
        raise ValueError("held/invalid campaign admission")
    p = root / "plans" / admission["plan_id"]
    if admission_path != p / "admission.json" or segment_path != p / "segment.json" or bridge_path != p / "bridge/bridge-receipt.json":
        raise ValueError("admission/plan directory binding mismatch")
    preconditions = admission.get("preconditions", {})
    if preconditions.get("exclusive_writer") is not True or not preconditions.get("attested_by"):
        raise ValueError("operator exclusive_writer attestation required")
    record = _verify(root, admission["segment_record"], root_id)
    if admission["segment_record"] != _ref(root, segment_path, root_id):
        raise ValueError("segment record pin mismatch")
    expected = segment(record["bbox"][0], record["bbox"][1], region=root.name)
    if any(record.get(k) != v for k, v in expected.items()):
        raise ValueError("lattice ID/projected bbox mismatch")
    campaign = _verify(root, admission["campaign"], root_id)
    if campaign.get("campaign_segment_id") != root.name:
        raise ValueError("campaign identity mismatch")
    records = from_bbox(campaign["bbox_crs84"], region=root.name)
    match = [r for r in records if r["segment_id"] == record["segment_id"]]
    if not match or any(record.get(k) != v for k, v in match[0].items()):
        raise ValueError("lattice CRS84 bbox mismatch")
    if record["segment_id"] != admission["coordinator_segment_id"]:
        raise ValueError("coordinator identity mismatch")
    plan = _verify(root, admission["plan_file"], root_id)
    if admission["plan_file"]["path"] != f"plans/{admission['plan_id']}/plan.json" or digest(plan) != admission["plan_sha256"]:
        raise ValueError("plan digest mismatch")
    if plan["segment"] != {k: record[k] for k in ("segment_id", "bbox_crs84")}:
        raise ValueError("plan segment binding mismatch")
    if plan.get("synthetic", False) is not record.get("synthetic", False):
        raise ValueError("synthetic plan/record binding mismatch")
    catalog = _verify(root, admission["catalog"], root_id)
    catalog_raw = _read(root, admission["catalog"]["path"])
    catalog_bridge.check_catalog(catalog)
    catalog_bridge.check_plan(plan, catalog_raw, catalog)
    checked = catalog_bridge.evaluate(root, root / admission["catalog"]["path"], plan)
    if any(d["state"] != "selected" for d in checked["decisions"]):
        raise ValueError("catalog selection no longer admissible")
    dry = _verify(root, admission["dry_run"], root_id)
    bridge = _json(root, bridge_path.relative_to(root).as_posix())
    if (bridge.get("schema") != catalog_bridge.RECEIPT or bridge.get("plan_sha256") != digest(plan)
            or bridge.get("segment") != plan["segment"] or bridge.get("segment_id") != record["segment_id"]
            or bridge.get("held_source_ids") != [] or bridge.get("execution_authorized") is not False
            or bridge.get("network_requests") != 0 or bridge.get("budget") != plan["budget"]
            or dry.get("plan_sha256") != digest(plan) or dry.get("held_source_ids") != []):
        raise ValueError("bridge/dry receipt binding mismatch")
    jobs, windows = bridge["jobs"], admission["windows"]
    expected_bridge = catalog_bridge._receipt(catalog_bridge.RECEIPT, plan, checked)
    expected_bridge.update(jobs=jobs, budget=plan["budget"], segment=checked["segment"])
    expected_dry = catalog_bridge._receipt(catalog_bridge.DRY_RUN, plan, checked)
    decisions = {d["source_id"]: d for d in checked["decisions"]}
    expected = [(selection, decisions[selection["source_id"]], index, native_window)
                for selection in plan["selections"]
                for index, native_window in enumerate(catalog_bridge._selection_windows(selection))]
    expected_dry["would_enqueue"] = []
    for selection, decision, index, native_window in expected:
        entry = dict(stage="acquire", source_id=selection["source_id"], native_job_sha256=digest(
            catalog_bridge.native_job(plan, selection, decision, checked["catalog_ref"], window=native_window)))
        if "windows" in selection:
            entry.update(window_index=index, window=native_window)
        expected_dry["would_enqueue"].append(entry)
    if bridge != expected_bridge or dry != expected_dry:
        raise ValueError("bridge/dry decisions or caps differ from pinned plan")
    if (not 1 <= len(jobs) <= catalog_bridge.MAX_JOBS
            or all("windows" not in s for s in plan["selections"]) and len(jobs) > catalog_bridge.LEGACY_MAX_JOBS
            or not len(jobs) == len(windows) == len(expected) == len(dry["would_enqueue"])
            or bridge["selected_source_ids"] != list(dict.fromkeys(s["source_id"] for s in plan["selections"]))):
        raise ValueError("admission window population mismatch")
    grids = dict(entries={g["grid_sha256"]: g for g in admission["grids"]}, selection_grid={})
    keys = set()
    for position, (job, window, expansion) in enumerate(zip(jobs, windows, expected)):
        item = dict(expansion=expansion, root=root, root_id=root_id, plan=plan, catalog_ref=checked["catalog_ref"])
        _bind_window(position, job, window, item, grids, record, campaign, keys)
    if (len(grids["entries"]) != len(admission["grids"])
            or {w["grid_sha256"] for w in windows} != set(grids["entries"])):
        raise ValueError("admission grid population mismatch")
    catalog_bridge.check_budget(bridge["budget"])
    if sum(s["source"]["bytes"] for s in plan["selections"]) > plan["max_total_bytes"]:
        raise ValueError("bridge total byte cap")
    return admission, bridge, record, root_id


def enqueue(root, bridge_receipt, segment_path, admission_path, out, *, clock=time.time):
    root = _absolute(root)
    bridge_receipt, segment_path, admission_path = map(_absolute, (bridge_receipt, segment_path, admission_path))
    out = _new_output(root, out)
    admission, bridge, record, namespace = _context(root, admission_path, bridge_receipt, segment_path)
    header = _header("coast-enqueue-receipt-v1", admission)
    bridge_ref = _ref(root, bridge_receipt, namespace)
    if out != bridge_receipt.parent / "enqueue-receipt.json":
        raise ValueError("enqueue output must be the plan's bridge/enqueue-receipt.json")
    intent = root / "var/coastal/enqueue-intents" / (bridge_ref["sha256"] + ".json")
    binding = loop.implementation_hashes(root)
    with loop.controller_lock((root / DATABASE).with_suffix(".lock")):
        with _snapshot(root) as db:
            reasons = _preflight(root, db, binding)
            if db is not None:
                row = db.execute("SELECT record_json FROM segments WHERE segment_id=?", (record["segment_id"],)).fetchone()
                if row and json.loads(row[0]) != record:
                    reasons.append("existing segment bbox/record differs")
            if reasons:
                raise ValueError("preflight_refused: " + "; ".join(reasons))
            before = set(_rows(db))
        if intent.exists():
            raise ValueError("enqueue intent exists; explicit reconciliation required")
        _absolute(intent.parent)
        intent.parent.mkdir(exist_ok=True)
        # Durable fence precedes Store constructor or segment insertion.
        _freeze(root, intent, dict(header, schema="coast-enqueue-intent-v1", bridge=bridge_ref,
                                  admission=_ref(root, admission_path, namespace), code_sha=binding[0], deps_sha=binding[1]))
        store = Store(root / DATABASE, root=root, clock=clock)
        try:
            store.add_segment(record)
            ids = catalog_bridge.enqueue(store, bridge_ref, code_sha=binding[0], deps_sha=binding[1])
        finally:
            store.close()
        result = dict(header, admission=_ref(root, admission_path, namespace), bridge=bridge_ref,
                      code_sha=binding[0], deps_sha=binding[1], store_path=DATABASE,
                      intent=_ref(root, intent, namespace),
                      jobs=[dict(window_key=w["window_key"], source_id=j["source_id"], root_job_id=job_id,
                                 input_manifest=dict(j["input_manifest"], root_id=namespace), new_row=job_id not in before)
                            for w, j, job_id in zip(admission["windows"], bridge["jobs"], ids)])
        _freeze(root, out, result)
        return result


def _result(root, db, row, namespace):
    if not row["result_sha"]:
        return None, None
    job = json.loads(row["record_json"])
    # The committed SHA, not a directory glob or a path prefix, picks the attempt.
    matches = []
    for event in db.execute("SELECT detail_json FROM events WHERE job_id=? AND kind='claimed'", (row["job_id"],)):
        token = json.loads(event[0])["token"]
        if not re.fullmatch(r"[0-9a-f]{32}", token):
            raise ValueError("unknown job-dir lease layout")
        path = root / "var/coastal/jobs" / row["job_id"].replace(":", "-") / token / "output/result.json"
        if not path.exists():
            continue
        ref = _ref(root, path, namespace)
        if ref["sha256"] == row["result_sha"]:
            value = _verify(root, ref, namespace)
            if (value.get("schema") != "coastal-stage-result-v1" or value.get("lease_token") != token
                    or any(value.get(k) != job[k] for k in ("job_id", "stage", "segment_id", "code_sha", "deps_sha", "params_sha", "input_manifest_sha"))):
                raise ValueError("committed result identity mismatch")
            if not db.execute("SELECT 1 FROM events WHERE job_id=? AND kind='finished' AND json_extract(detail_json,'$.result_sha')=?", (row["job_id"], ref["sha256"])).fetchone():
                raise ValueError("result missing committed event")
            matches.append((value, ref))
    if len(matches) != 1:
        raise ValueError("missing/ambiguous committed result")
    return matches[0]


def _lineage(root, db, receipt, namespace, *, now):
    rows = _rows(db)
    windows, lineage = [], set()
    for entry in receipt["jobs"]:
        current = entry["root_job_id"]
        expected_ref = {k: v for k, v in entry["input_manifest"].items() if k != "root_id"}
        stages = {}
        for stage in STAGES:
            if current not in rows or current in lineage:
                raise ValueError("missing/shared lineage job")
            row = rows[current]
            job = json.loads(row["record_json"])
            if (job["stage"] != stage or job["segment_id"] != receipt["coordinator_segment_id"]
                    or (job["code_sha"], job["deps_sha"]) != (receipt["code_sha"], receipt["deps_sha"])
                    or job["input_manifest"] != expected_ref or _identity(job) != row["idempotency_key"]):
                raise ValueError("lineage Store identity mismatch")
            if stage == "acquire":
                bridge = _verify(root, receipt["bridge"], namespace)
                if job["params"] != {} or job["budget"] != bridge["budget"]:
                    raise ValueError("root execution identity differs from bridge")
            _verify(root, job["input_manifest"], namespace)
            lineage.add(current)
            value, result_ref = _result(root, db, row, namespace)
            if value and value["state"] != row["state"] and not (
                    row["state"] in {"stale", "cancelled", "claimed", "running", "failed_uncertain"}
                    or value["state"] == "failed_retryable" and row["state"] in {"queued", "failed_terminal"}):
                raise ValueError("committed result/Store state disagreement")
            info = dict(job_id=current, state=row["state"], holds=json.loads(row["holds_json"]),
                        input_manifest=dict(job["input_manifest"], root_id=namespace), result_ref=result_ref,
                        missing_reason=None, products={})
            if value:
                info["committed_state"] = value["state"]
                if row["state"] == value["state"]:
                    info["holds"] = value["holds"]
                info["usage"] = value["usage"]
                for artifact in value["artifacts"]:
                    if not Path(_relative(artifact["path"])).is_relative_to(Path(result_ref["path"]).parent):
                        raise ValueError("foreign-owned stage artifact")
                    _verify(root, artifact, namespace, metadata=artifact["path"].endswith(".json"))
                    info["products"][artifact.get("contract", artifact.get("kind", "artifact"))] = dict(artifact, root_id=namespace)
                if stage == "qualify" and row["state"] == "done":
                    refs = [a for a in value["artifacts"] if a.get("contract") == "private-mapping-input-v2"]
                    if len(refs) != 1:
                        raise ValueError("missing qualification handoff")
                    document = _verify(root, refs[0], namespace)
                    info["support"] = dict(document["native_facts"]["support"],
                                           valid_cells=document["native_facts"]["valid_count"],
                                           mask_sha256=document["valid_support"]["sha256"])
                    info["products"]["support"] = dict(document["valid_support"], root_id=namespace)
                    _verify(root, document["valid_support"], namespace, metadata=False)
                if stage == "map" and row["state"] == "done":
                    refs = [a for a in value["artifacts"] if a.get("contract") == "coastal-mapping-run-v1"]
                    if len(refs) != 1:
                        raise ValueError("missing map run")
                    run = _verify(root, refs[0], namespace)
                    for output in run["outputs"].values():
                        _verify(root, output, namespace, metadata=output["path"].endswith(".json"))
                    cells = _verify(root, run["outputs"]["cells"], namespace)
                    info.update(native_valid_count=cells["native_valid_count"], depth_m=cells["depth_m"])
                    info["products"].update({k: dict(v, root_id=namespace) for k, v in run["outputs"].items()})
            stages[stage] = info
            if stage == "render" or row["state"] != "done":
                break
            if value is None or not value.get("next_job"):
                raise ValueError("successful predecessor missing committed successor")
            successor = value["next_job"]
            if successor.get("stage") != NEXT[stage]:
                raise ValueError("wrong successor stage")
            expected_ref = successor["input_manifest"]
            _verify(root, expected_ref, namespace)
            parent_output = Path(result_ref["path"]).parent
            child_path = Path(_relative(expected_ref["path"]))
            if not child_path.is_relative_to(parent_output) or child_path == parent_output:
                raise ValueError("foreign-owned successor input")
            child = dict(stage=NEXT[stage], segment_id=job["segment_id"],
                         code_sha=successor.get("code_sha", job["code_sha"]), deps_sha=successor.get("deps_sha", job["deps_sha"]),
                         params=successor.get("params") or {}, input_manifest=expected_ref,
                         budget=successor.get("budget") or {"wall_s": 60, "memory_bytes": 1073741824, "bytes": 0, "requests": 0})
            key = _identity(child)
            candidates = [r for r in rows.values() if r["stage"] == NEXT[stage]
                          and r["segment_id"] == job["segment_id"]
                          and json.loads(r["record_json"]).get("input_manifest") == expected_ref]
            if (len(candidates) != 1 or candidates[0]["job_id"] != "job:" + key[:24]
                    or candidates[0]["idempotency_key"] != key):
                raise ValueError("missing/ambiguous exact successor")
            current = candidates[0]["job_id"]
        deepest = next(stages[s] for s in reversed(STAGES[:3]) if s in stages)
        state = deepest["state"]
        classification = "map_done" if stages.get("map", {}).get("state") == "done" else state if state in PARTITION else "unfinished"
        reason = None if classification != "unfinished" else ("not_before" if rows[deepest["job_id"]]["not_before"] > now else state)
        for stage in STAGES[:3]:
            stages.setdefault(stage, dict(state="missing", missing_reason="predecessor_not_completed", holds=[], result_ref=None, products={}))
        windows.append(dict(window_key=entry["window_key"], source_id=entry["source_id"], root_job_id=entry["root_job_id"],
                            state=classification, unfinished_reason=reason, stages=stages))
    registered = {e["root_job_id"] for e in receipt["jobs"]}
    manifests = {e["input_manifest"]["path"] for e in receipt["jobs"]}
    for row in rows.values():
        job = json.loads(row["record_json"])
        if job["stage"] == "acquire" and (job.get("input_manifest") or {}).get("path") in manifests and row["job_id"] not in registered:
            raise ValueError("unregistered acquire root for receipt")
    return windows, lineage


def _foreign(db, lineage):
    """Compare job-specific foreign state, not expected global tick telemetry."""
    return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")
                    if row["job_id"] is not None and row["job_id"] not in lineage]
            for table in ("jobs", "events", "leases", "charges")}


def run(root, enqueue_receipt, out, *, max_ticks, until, stop_after="map", continuation_of=None, clock=time.time):
    root, enqueue_receipt = _absolute(root), _absolute(enqueue_receipt)
    out = _new_output(root, out)
    if stop_after != "map" or type(max_ticks) is not int or max_ticks < 1 or not math.isfinite(until):
        raise ValueError("bounded map-only ticks and finite deadline required")
    receipt = _json(root, enqueue_receipt.relative_to(root).as_posix())
    if receipt.get("schema") != "coast-enqueue-receipt-v1" or receipt.get("store_path") != DATABASE:
        raise ValueError("enqueue receipt required")
    namespace = "queue:" + root.name
    admission_ref, bridge_ref = receipt["admission"], receipt["bridge"]
    admission = _verify(root, admission_ref, namespace)
    bridge = _verify(root, bridge_ref, namespace)
    context_problems = []
    try:
        _context(root, root / admission_ref["path"], root / bridge_ref["path"], root / admission["segment_record"]["path"])
    except (ValueError, KeyError, TypeError, OSError) as error:
        context_problems.append("admission input integrity: " + str(error))
    intent = _verify(root, receipt["intent"], namespace)
    if (intent["bridge"] != bridge_ref or intent["admission"] != admission_ref
            or intent.get("code_sha") != receipt["code_sha"] or intent.get("deps_sha") != receipt["deps_sha"]):
        raise ValueError("intent binding mismatch")
    for key in ("campaign_segment_id", "coordinator_segment_id", "plan_id", "plan_sha256"):
        if receipt[key] != admission[key]:
            raise ValueError("enqueue identity mismatch")
    if len(receipt["jobs"]) != len(admission["windows"]):
        raise ValueError("enqueue population mismatch")
    for entry, window, job in zip(receipt["jobs"], admission["windows"], bridge["jobs"]):
        if (entry["window_key"] != window["window_key"] or entry["source_id"] != job["source_id"]
                or entry["input_manifest"] != dict(job["input_manifest"], root_id=namespace)):
            raise ValueError("enqueue root manifest mismatch")
    header = _header("coast-run-summary-v1", admission)
    enq_ref = _ref(root, enqueue_receipt, namespace)
    previous_ref, sequence = None, 0
    if continuation_of is not None:
        continuation_of = _absolute(continuation_of)
        previous_ref = _ref(root, continuation_of, namespace)
        previous = _verify(root, previous_ref, namespace)
        if (previous.get("schema") != "coast-run-summary-v1" or previous.get("enqueue") != enq_ref
                or previous.get("stop_reason") not in CONTINUABLE
                or previous.get("code_sha") != receipt["code_sha"] or previous.get("deps_sha") != receipt["deps_sha"]
                or previous.get("enqueued_job_ids") != [j["root_job_id"] for j in receipt["jobs"]]):
            raise ValueError("ordinary continuation not authorized")
        sequence = previous["sequence"] + 1
    if out != root / "plans" / admission["plan_id"] / "runs" / f"run-{sequence:02}.json":
        raise ValueError("run output sequence/path mismatch")
    started, monotonic = clock(), time.monotonic()
    ticks, problems, windows, lineage = 0, list(context_problems), [], set()
    stop = "integrity_error"
    binding = (receipt["code_sha"], receipt["deps_sha"])
    with loop.controller_lock((root / DATABASE).with_suffix(".lock")):
        while True:
            if context_problems:
                stop = "integrity_error"
                break
            with _snapshot(root) as db:
                try:
                    if db is None:
                        raise ValueError("Store missing")
                    windows, lineage = _lineage(root, db, receipt, namespace, now=clock())
                except (ValueError, KeyError, TypeError, OSError) as error:
                    problems.append(str(error))
                    stop = "integrity_error"
                    break
                reasons = _preflight(root, db, binding)
                if reasons:
                    problems.extend(reasons)
                    stop = "preflight_refused"
                    break
                if all(w["state"] in {"map_done", "held", "failed_terminal", "cancelled"} for w in windows):
                    stop = "terminal"
                    break
                if clock() + 1 >= until:
                    stop = "deadline"
                    break
                if ticks >= max_ticks:
                    stop = "max_ticks"
                    break
                rows = _rows(db)
                # Admission (receipt jobs) order, never window_key: its decimal idx sorts 0, 1, 10, 2.
                frontier = sorted((order, STAGES.index(stage), info["job_id"])
                                  for order, w in enumerate(windows) for stage, info in w["stages"].items()
                                  if stage != "render" and info["state"] == "queued"
                                  and rows[info["job_id"]]["not_before"] <= clock()
                                  and rows[info["job_id"]]["attempts"] < rows[info["job_id"]]["max_attempts"])
                if not frontier:
                    stop = "not_claimable"
                    break
                foreign = _foreign(db, lineage)
            store = Store(root / DATABASE, root=root, clock=clock)
            try:
                outcome = loop.Coordinator(store, clock=clock).tick(until=until, job_id=frontier[0][2])
                ticks += 1
            finally:
                store.close()
            with _snapshot(root) as db:
                try:
                    _, updated_lineage = _lineage(root, db, receipt, namespace, now=clock())
                except (ValueError, KeyError, TypeError, OSError) as error:
                    problems.append(str(error))
                    stop = "integrity_error"
                    break
                if _foreign(db, updated_lineage) != foreign:
                    problems.append("foreign state changed; exclusive writer violated")
                    stop = "failed_uncertain"
                    break
            if outcome["state"] in {"failed_uncertain", "deadline"}:
                stop = outcome["state"]
                break
            if outcome["state"] == "idle":
                with _snapshot(root) as db:
                    windows, lineage = _lineage(root, db, receipt, namespace, now=clock())
                if any(w["stages"].get(STAGES[frontier[0][1]], {}).get("job_id") == frontier[0][2]
                       and w["stages"][STAGES[frontier[0][1]]]["state"] == "queued" for w in windows):
                    stop = "not_claimable"
                    break
        with _snapshot(root) as db:
            try:
                if context_problems:
                    raise ValueError("admission inputs invalid")
                windows, lineage = _lineage(root, db, receipt, namespace, now=clock())
            except (ValueError, KeyError, TypeError, OSError) as error:
                problems.append(str(error))
                # Do not advertise previous partial lineage as a clean snapshot.
                windows = [dict(window_key=j["window_key"], root_job_id=j["root_job_id"], source_id=j["source_id"],
                                state="unfinished", unfinished_reason="integrity_error", stages={}) for j in receipt["jobs"]]
            rows = _rows(db)
            foreign_count = sum(r["state"] == "queued" for k, r in rows.items() if k not in lineage)
            renders = sum(r["stage"] == "render" and r["state"] == "queued" for k, r in rows.items() if k in lineage)
            charges = [] if db is None else [dict(r) for r in db.execute("SELECT * FROM charges") if r["job_id"] in lineage]
        counts = {key: sum(w["state"] == key for w in windows) for key in PARTITION}
        holds = Counter(h for w in windows for info in w["stages"].values() for h in info.get("holds", []))
        counts.update(windows=len(windows), by_hold_reason=dict(holds))
        sources = {s["source"]["sha256"]: s["source"]["bytes"] for s in bridge["decisions"] if s["state"] == "selected"}
        result = dict(header, sequence=sequence, continuation_of=previous_ref, admission=admission_ref,
                      bridge=bridge_ref, enqueue=enq_ref, code_sha=binding[0], deps_sha=binding[1],
                      enqueued_job_ids=[j["root_job_id"] for j in receipt["jobs"]], stop_reason=stop, problems=problems,
                      started_utc=utc(started), finished_utc=utc(clock()), wall_s=time.monotonic()-monotonic,
                      ticks_used=ticks, max_ticks=max_ticks, until_epoch=until, stop_after="map",
                      windows=windows, counts=counts, bridge_caps=bridge["caps"], bytes=dict(unique_sources=sum(sources.values())),
                      usage=dict(requests=sum(c["requests"] for c in charges), bytes_in=sum(c["bytes"] for c in charges)),
                      untouched=dict(foreign_queued_jobs_seen=foreign_count, render_jobs_left_queued=renders),
                      store_status=queue_status(root / DATABASE))
        _freeze(root, out, result)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("enqueue", "run", "status"):
        sub = commands.add_parser(name)
        sub.add_argument("--root", type=Path, required=True)
        if name == "enqueue":
            for flag in ("bridge-receipt", "segment", "admission", "out"):
                sub.add_argument("--" + flag, type=Path, required=True)
        if name == "run":
            for flag in ("enqueue-receipt", "out"):
                sub.add_argument("--" + flag, type=Path, required=True)
            sub.add_argument("--stop-after", choices=["map"], required=True)
            sub.add_argument("--max-ticks", type=int, required=True)
            sub.add_argument("--until", type=float, required=True)
            sub.add_argument("--continuation-of", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            root = _absolute(args.root)
            result = queue_status(_absolute(root / DATABASE))
        elif args.command == "enqueue":
            result = enqueue(args.root, args.bridge_receipt, args.segment, args.admission, args.out)
        else:
            result = run(args.root, args.enqueue_receipt, args.out, max_ticks=args.max_ticks,
                         until=args.until, stop_after=args.stop_after, continuation_of=args.continuation_of)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 3 if result.get("stop_reason") in {"preflight_refused", "integrity_error", "failed_uncertain"} else 0
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, RuntimeError) as error:
        print(json.dumps(dict(schema="coast-bridge-run-error-v1", error=str(error))), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
