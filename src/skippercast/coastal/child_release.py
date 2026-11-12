"""Read-only authority boundary for released render and browser children."""
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time

from .handoff.common import digest
from .output_writer import (BROWSER_PROFILE, PRIVATE_RENDER_PROFILE,
                            validate_output_plan, validate_partition)
from .coordinator.loop import implementation_hashes

MAX_DOCUMENT = 128 * 1024


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("finite non-boolean clock required")
    return value


def _canonical(value):
    if not isinstance(value, str):
        raise ValueError("absolute canonical path required")
    path = Path(value)
    if not path.is_absolute() or str(path) != value or ".." in path.parts:
        raise ValueError("absolute canonical path required")
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise ValueError("path aliases forbidden")
    if path.resolve(strict=False) != path:
        raise ValueError("path aliases forbidden")
    return path


def _document(wrapper, expected_root, contract, *, raw=False):
    if not isinstance(wrapper, dict) or set(wrapper) != {"root", "path", "bytes", "sha256", "contract"}:
        raise ValueError("exact pinned descriptor wrapper required")
    root = _canonical(wrapper["root"])
    if root != expected_root or not root.is_dir():
        raise ValueError("descriptor domain mismatch")
    relative = wrapper["path"]
    if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts or str(Path(relative)) != relative:
        raise ValueError("canonical relative descriptor required")
    path = _canonical(str(root / relative))
    size = wrapper["bytes"]
    if type(size) is not int or not 0 < size <= MAX_DOCUMENT or wrapper["contract"] != contract:
        raise ValueError("bounded typed descriptor required")
    before = path.lstat()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or opened.st_size != size or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("single-link exact regular metadata required")
        chunks = []
        remaining = size + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(fd)
        named = path.lstat()
        key = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)
        if key(opened) != key(after) or key(after) != key(named) or len(data) != size or hashlib.sha256(data).hexdigest() != wrapper["sha256"]:
            raise ValueError("metadata changed or digest mismatch")
    finally:
        os.close(fd)
    if raw:
        return data
    document = json.loads(data)
    if not isinstance(document, dict) or document.get("schema") != contract:
        raise ValueError("metadata schema mismatch")
    return document


def _plain(wrapper):
    return {key: value for key, value in wrapper.items() if key != "root"}


def _clock(document, schema, mission, owner_ref, boot, wall, now, horizon, mono, actual):
    if document.get("schema") != schema or document.get("mission_id") != mission or document.get("owner_authorization") != owner_ref or document.get("boot_id") != boot or type(document.get("wall_seconds")) is not int or document["wall_seconds"] != wall:
        raise ValueError("clock authority mismatch")
    start, end, mstart, mend = [_number(document.get(k)) for k in ("start_epoch", "deadline_epoch", "start_monotonic", "deadline_monotonic")]
    if start < 0 or mstart < 0 or abs(end-start-wall) > 1e-6 or abs(mend-mstart-wall) > 1e-6 or not start <= now <= actual < end or not actual < horizon <= end or not mstart <= mono < mend:
        raise ValueError("expired, future or inconsistent clock")
    return start, end, mstart, mend


def validate_child_release(context, role, now, horizon):
    """Validate exact released authority without creating files, ledgers or units."""
    now, horizon = _number(now), _number(horizon)
    if role not in ("render", "browser") or not isinstance(context, dict) or context.get("schema") != "coastal-child-release-context-v1":
        raise ValueError("supported typed child context required")
    grant = context.get("child_grant")
    if not isinstance(grant, dict) or grant.get("execution_authorized") is not True or grant.get("output_partition_role") != role:
        raise ValueError("exact released child grant required")
    partition = validate_partition(grant)
    plan = validate_output_plan(grant)
    if plan["profile"] != {"render": PRIVATE_RENDER_PROFILE, "browser": BROWSER_PROFILE}[role]:
        raise ValueError("fixed child profile required")
    mission = context.get("mission_id")
    if not isinstance(mission, str) or not mission or grant.get("mission_id") != mission:
        raise ValueError("exact mission identity required")
    child = _canonical(grant["output_root"])
    if context.get("output_root") != str(child):
        raise ValueError("child root mismatch")
    runtime = _canonical(partition["children"]["runtime"]["output_root"])
    native = _canonical(str(runtime / "execution"))
    owner_ref = context.get("owner_authorization")
    owner = _document(owner_ref, native, "coastal-new-mission-owner-authorization-v1")
    runtime_ref = context.get("runtime_grant")
    if not isinstance(runtime_ref, dict) or not isinstance(runtime_ref.get("contract"), str):
        raise ValueError("pinned runtime grant required")
    parent = _document(runtime_ref, native, "coastal-authenticated-policy-v1")
    validate_partition(parent)
    from .coordinator.saved_area import continuation_grant
    continuation_grant(parent)
    if parent.get("output_partition") != partition or parent.get("output_partition_role") != "runtime" or parent.get("execution_authorized") is not True or parent.get("mission_id") != mission:
        raise ValueError("runtime grant authority mismatch")
    if grant.get("parent_runtime_grant_sha256") != digest(parent):
        raise ValueError("child parent grant mismatch")
    expected = dict(source_bytes=220545408, source_admissions=6, source_prior_effective_bytes=895006524, source_cumulative_limit_bytes=1115551932, global_wall_seconds=18000, mapping_wall_seconds=3600)
    if any(type(owner.get(k)) is not int or owner[k] != v for k, v in expected.items()) or owner.get("mission_id") != mission or owner.get("execution_authorized") is not True or owner.get("output_root") != str(runtime) or owner.get("output_partition") != partition:
        raise ValueError("owner scope/source/partition mismatch")
    registry = _document(context.get("allocation_registry"), runtime, "coastal-single-mission-allocation-v1")
    if context["allocation_registry"]["path"] != "control/allocation-registry.json" or registry.get("mission_id") != mission or registry.get("output_root") != str(runtime) or registry.get("output_partition") != partition or registry.get("owner_authorization") != _plain(owner_ref) or registry.get("owner_sha256") != digest(owner) or registry.get("grant_sha256") != digest(parent) or registry.get("second_mission_allowed") is not False:
        raise ValueError("allocation registry mismatch")
    global_clock = _document(context.get("global_clock"), runtime, "coastal-mission-global-clock-v1")
    stage_clock = _document(context.get("stage_clock"), runtime, "coastal-skill-stage-clock-v1")
    if context["stage_clock"]["path"] != "control/" + role + "-stage-clock.json" or stage_clock.get("skill") != role:
        raise ValueError("stage identity mismatch")
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    actual, mono = time.time(), time.monotonic()
    outer = _clock(global_clock, "coastal-mission-global-clock-v1", mission, _plain(owner_ref), boot, 18000, now, horizon, mono, actual)
    inner = _clock(stage_clock, "coastal-skill-stage-clock-v1", mission, _plain(owner_ref), boot, 3600, now, horizon, mono, actual)
    if not outer[0] <= inner[0] < inner[1] <= outer[1] or not outer[2] <= inner[2] < inner[3] <= outer[3]:
        raise ValueError("stage extends global clock")
    stop = _document(context.get("mapping_stop"), runtime, "coastal-four128-stop-proof-v1")
    observed = _number(stop.get("observed_monotonic"))
    properties = stop.get("properties")
    if (context["mapping_stop"]["path"] != "control/mapping-stop.json"
            or stop.get("mission_id") != mission or stop.get("boot_id") != boot
            or stop.get("runtime_grant_sha256") != digest(parent)
            or stop.get("descendants_empty") is not True
            or any(type(stop.get(k)) is not int or stop[k] != 0 for k in ("stop_exit_code", "query_exit_code"))
            or not isinstance(properties, dict) or properties.get("ActiveState") != "inactive"
            or properties.get("ControlGroup") != ""
            or not outer[2] <= observed <= inner[2] <= mono):
        raise ValueError("exact prior stopped mapping proof required")
    code, deps = implementation_hashes(native)
    if any(doc.get("code_sha") != code or doc.get("deps_sha") != deps for doc in (context, grant, parent)):
        raise ValueError("current software identity mismatch")
    controls = context.get("controls", [])
    if not isinstance(controls, list) or len(controls) > 8:
        raise ValueError("bounded controls required")
    seen = set()
    paths = set()
    for control in controls:
        if not isinstance(control, dict) or not isinstance(control.get("role"), str) or not control["role"] or control["role"] in seen or not isinstance(control.get("descriptor"), dict):
            raise ValueError("unique control roles required")
        seen.add(control["role"])
        descriptor = control["descriptor"]
        path = (descriptor.get("root"), descriptor.get("path"))
        if path in paths:
            raise ValueError("control path aliases forbidden")
        paths.add(path)
        _document(control.get("descriptor"), _canonical(control["descriptor"]["root"]), control["descriptor"]["contract"], raw=True)
    return dict(child_grant=grant, owner=owner, registry=registry, runtime_grant=parent,
                global_clock=global_clock, stage_clock=stage_clock, mapping_stop=stop,
                output_root=str(child), grant_digest=digest(grant))
