"""Governed discovery keeps its validated monotonic deadline through output admission.

Offline: fake wall/monotonic clocks, synthetic authority documents and a recording
managed-output stand-in. The real validate() and child_release._clock are exercised.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from skippercast.coastal import governed_discovery as gd
from skippercast.coastal.coordinator import saved_area
from skippercast.coastal.output_writer import DISCOVERY_PROFILE

BOOT = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
EPOCH, MONO = 10000.0, 5000.0
NOW, HORIZON = 9990.0, 13500.0
SOURCES = [dict(source_id="s1", sha256="a" * 64, bytes=10)]
ORDER = ["create", "reserve:usable-inputs.json", "reserve:terminal-discovery.json",
         "write:usable-inputs.json", "write:terminal-discovery.json", "audit"]


class Clock:
    def __init__(self):
        self.wall, self.mono = EPOCH, MONO


class Recorder:
    """Stands in for ManagedOutputs; each call may advance the fake clocks."""
    calls = []
    hook = None

    @classmethod
    def _note(cls, label):
        cls.calls.append(label)
        if cls.hook:
            cls.hook(label)

    @classmethod
    def create(cls, root, grant, grant_digest):
        cls._note("create")
        return cls()

    def reserve_file(self, name, **kw):
        self._note("reserve:" + name)

    def write_bytes(self, name, raw, **kw):
        self._note("write:" + name)

    def audit(self):
        self._note("audit")


def build(tmp_path, monkeypatch, *, stage_mono_end=8500.0, global_mono_end=22000.0):
    root = tmp_path / "mission" / "discovery"
    runtime = tmp_path / "mission" / "runtime"
    (tmp_path / "mission").mkdir()
    input_root = tmp_path / "meta"
    part = dict(children=dict(runtime=dict(output_root=str(runtime))))
    ref = lambda name, path=None: dict(path=path or name + ".json", name=name, root="/x")
    owner_ref, plan_ref = ref("owner"), ref("plan")
    policy_ref = dict(path="metadata/discovery-policy.json", name="policy")
    owner = dict(execution_authorized=True, mission_id="m1", output_root=str(runtime), output_partition=part,
                 global_wall_seconds=18000, mapping_wall_seconds=3600, source_bytes=220545408,
                 source_admissions=6, source_prior_effective_bytes=895006524,
                 source_cumulative_limit_bytes=1115551932, discovery_policy=gd._plain(policy_ref))
    parent = dict(execution_authorized=True, output_partition=part, output_partition_role="runtime",
                  mission_id="m1", code_sha="c", deps_sha="d")
    grant = dict(execution_authorized=True, output_partition_role="discovery", output_root=str(root),
                 mission_id="m1", parent_runtime_grant_sha256=gd.digest(parent),
                 discovery_policy=policy_ref, code_sha="c", deps_sha="d")
    registry = dict(mission_id="m1", output_root=str(runtime), output_partition=part,
                    owner_sha256=gd.digest(owner), owner_authorization=gd._plain(owner_ref),
                    grant_sha256=gd.digest(parent), second_mission_allowed=False)
    clk = lambda s, w, start, mstart, mend: dict(
        schema=s, mission_id="m1", owner_authorization=gd._plain(owner_ref), boot_id=BOOT, wall_seconds=w,
        start_epoch=start, deadline_epoch=start + w, start_monotonic=mstart, deadline_monotonic=mend)
    glob = clk("coastal-mission-global-clock-v1", 18000, 9000.0, 4000.0, global_mono_end)
    glob["start_monotonic"] = global_mono_end - 18000
    stage = clk("coastal-skill-stage-clock-v1", 3600, 9900.0, 4900.0, stage_mono_end)
    stage["start_monotonic"] = stage_mono_end - 3600
    stage["skill"] = "discovery"
    policy = dict(mission_id="m1", output_root=str(root), metadata_root=str(input_root), plan=plan_ref,
                  code_sha="c", deps_sha="d", original_source_reads=0, network_requests=0, source_specs=SOURCES)
    docs = dict(owner=owner, runtime=parent, registry=registry, glob=glob, stage=stage, policy=policy, plan={})
    context = dict(schema=gd.SCHEMA, child_grant=grant, mission_id="m1", output_root=str(root),
                   owner_authorization=owner_ref, runtime_grant=ref("runtime"),
                   allocation_registry=ref("registry", "control/allocation-registry.json"),
                   global_clock=ref("glob"), stage_clock=ref("stage", "control/discovery-stage-clock.json"),
                   metadata_root=str(input_root), discovery_policy=policy_ref, plan=plan_ref,
                   code_sha="c", deps_sha="d")
    monkeypatch.setattr(gd, "_document", lambda r, root_, schema: docs[r["name"]])
    monkeypatch.setattr(gd, "_canonical", lambda p: Path(p))
    monkeypatch.setattr(gd, "validate_partition", lambda g: part)
    monkeypatch.setattr(gd, "validate_output_plan", lambda g: dict(profile=DISCOVERY_PROFILE))
    monkeypatch.setattr(gd, "implementation_hashes", lambda native: ("c", "d"))
    monkeypatch.setattr(saved_area, "continuation_grant", lambda p: None)
    clock = Clock()
    monkeypatch.setattr(gd, "time", SimpleNamespace(time=lambda: clock.wall, monotonic=lambda: clock.mono))
    Recorder.calls, Recorder.hook = [], None
    monkeypatch.setattr(gd, "ManagedOutputs", Recorder)
    manifest = dict(sources=[dict(source_id="s1", source=dict(sha256="a" * 64, bytes=10))],
                    usable_source_ids=["s1"])
    state = SimpleNamespace(after=None)

    def fake_inventory(*a, **kw):
        if state.after:
            state.after()
        return manifest
    monkeypatch.setattr(gd.inventory, "inventory", fake_inventory)
    return context, clock, state, root


def jump_mono(clock):
    def go():
        clock.mono = 9000.0  # wall rolled back: epoch stays below every epoch bound
    return go


def test_unexpired_success_is_unchanged(tmp_path, monkeypatch):
    context, clock, state, root = build(tmp_path, monkeypatch)
    result = gd.run(context, now=NOW, horizon=HORIZON)
    assert Recorder.calls == ORDER
    assert result["state"] == "USABLE_METADATA_ONLY" and result["output_root"] == str(root)
    assert result["original_source_reads"] == 0 and result["network_requests"] == 0


def test_validate_retains_monotonic_deadlines(tmp_path, monkeypatch):
    context, clock, state, root = build(tmp_path, monkeypatch)
    *_, deadline, mono_deadline = gd.validate(context, NOW, HORIZON)
    assert (deadline, mono_deadline) == (13500.0, 8500.0)
    # caller horizon earlier than either clock maps from the same sampled pair
    *_, deadline, mono_deadline = gd.validate(context, NOW, 10100.0)
    assert (deadline, mono_deadline) == (10100.0, MONO + 100.0)


def test_rollback_after_inventory_cannot_outlive_stage(tmp_path, monkeypatch):
    context, clock, state, root = build(tmp_path, monkeypatch)
    state.after = jump_mono(clock)
    with pytest.raises(TimeoutError, match="before output"):
        gd.run(context, now=NOW, horizon=HORIZON)
    assert Recorder.calls == [] and not root.exists()


def test_caller_horizon_has_monotonic_equivalent(tmp_path, monkeypatch):
    context, clock, state, root = build(tmp_path, monkeypatch)

    def go():
        clock.mono = MONO + 100.0  # exactly the horizon allowance; wall rolled back
    state.after = go
    with pytest.raises(TimeoutError):
        gd.run(context, now=NOW, horizon=10100.0)
    assert Recorder.calls == []


@pytest.mark.parametrize("after", ORDER)
def test_expiry_between_output_operations_retains_partial_evidence(tmp_path, monkeypatch, after):
    context, clock, state, root = build(tmp_path, monkeypatch)
    Recorder.hook = lambda label: jump_mono(clock)() if label == after else None
    with pytest.raises(TimeoutError, match="partial evidence"):
        gd.run(context, now=NOW, horizon=HORIZON)
    assert Recorder.calls == ORDER[:ORDER.index(after) + 1]  # nothing after expiry, no cleanup call


@pytest.mark.parametrize("wall,mono", [(13500.0, MONO), (EPOCH, 8500.0), (13501.0, 9000.0)])
def test_epoch_expiry_and_equal_boundaries_still_refuse(tmp_path, monkeypatch, wall, mono):
    context, clock, state, root = build(tmp_path, monkeypatch)

    def go():
        clock.wall, clock.mono = wall, mono
    state.after = go
    with pytest.raises(TimeoutError):
        gd.run(context, now=NOW, horizon=HORIZON)
    assert Recorder.calls == []


def test_source_mismatch_still_refuses_before_output(tmp_path, monkeypatch):
    context, clock, state, root = build(tmp_path, monkeypatch)
    monkeypatch.setattr(gd.inventory, "inventory", lambda *a, **k: dict(
        sources=[dict(source_id="s1", source=dict(sha256="b" * 64, bytes=10))], usable_source_ids=[]))
    with pytest.raises(ValueError, match="differs from pinned"):
        gd.run(context, now=NOW, horizon=HORIZON)
    assert Recorder.calls == []
