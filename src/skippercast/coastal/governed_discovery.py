"""Opt-in 1 MiB managed discovery; JSON metadata reads and cache stat only."""
import argparse
import json
from pathlib import Path
import time

from . import cached_inventory as inventory
from .child_release import _canonical, _clock, _document, _plain
from .handoff.common import digest
from .coordinator.loop import implementation_hashes
from .output_writer import ManagedOutputs, DISCOVERY_PROFILE, validate_partition, validate_output_plan

SCHEMA = "coastal-governed-discovery-context-v1"
LIMIT = 512 * 1024

def validate(context, now, horizon):
    if not isinstance(context, dict) or context.get("schema") != SCHEMA:
        raise ValueError("typed discovery context required")
    grant = context.get("child_grant")
    if not isinstance(grant, dict) or grant.get("execution_authorized") is not True or grant.get("output_partition_role") != "discovery":
        raise ValueError("released discovery authority required")
    part = validate_partition(grant)
    if validate_output_plan(grant)["profile"] != DISCOVERY_PROFILE:
        raise ValueError("fixed discovery1MiB profile required")
    root = _canonical(grant["output_root"])
    runtime = _canonical(part["children"]["runtime"]["output_root"])
    native = _canonical(str(runtime / "execution"))
    mission = context.get("mission_id")
    if not mission or grant.get("mission_id") != mission or context.get("output_root") != str(root):
        raise ValueError("exact discovery mission/root required")
    owner_ref = context["owner_authorization"]
    owner = _document(owner_ref, native, "coastal-new-mission-owner-authorization-v1")
    parent = _document(context["runtime_grant"], native, "coastal-authenticated-policy-v1")
    validate_partition(parent)
    from .coordinator.saved_area import continuation_grant
    continuation_grant(parent)
    if (parent.get("execution_authorized") is not True or parent.get("output_partition") != part
        or parent.get("output_partition_role") != "runtime" or parent.get("mission_id") != mission
        or grant.get("parent_runtime_grant_sha256") != digest(parent)):
        raise ValueError("exact parent partition authority required")
    if (owner.get("execution_authorized") is not True or owner.get("mission_id") != mission
        or owner.get("output_root") != str(runtime) or owner.get("output_partition") != part
        or owner.get("global_wall_seconds") != 18000 or owner.get("mapping_wall_seconds") != 3600):
        raise ValueError("owner scope differs")
    expected = dict(source_bytes=220545408,source_admissions=6,
                    source_prior_effective_bytes=895006524,source_cumulative_limit_bytes=1115551932)
    if any(type(owner.get(k)) is not int or owner[k] != v for k,v in expected.items()):
        raise ValueError("owner source allowance differs")
    registry = _document(context["allocation_registry"], runtime, "coastal-single-mission-allocation-v1")
    if (context["allocation_registry"]["path"] != "control/allocation-registry.json"
        or registry.get("mission_id") != mission or registry.get("output_root") != str(runtime)
        or registry.get("output_partition") != part or registry.get("owner_sha256") != digest(owner)
        or registry.get("owner_authorization") != _plain(owner_ref)
        or registry.get("grant_sha256") != digest(parent) or registry.get("second_mission_allowed") is not False):
        raise ValueError("immutable registry authority differs")
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    actual, mono = time.time(), time.monotonic()
    global_doc = _document(context["global_clock"], runtime, "coastal-mission-global-clock-v1")
    stage_doc = _document(context["stage_clock"], runtime, "coastal-skill-stage-clock-v1")
    if context["stage_clock"]["path"] != "control/discovery-stage-clock.json" or stage_doc.get("skill") != "discovery":
        raise ValueError("exact discovery stage clock required")
    outer = _clock(global_doc, "coastal-mission-global-clock-v1", mission, _plain(owner_ref), boot, 18000, now, horizon, mono, actual)
    inner = _clock(stage_doc, "coastal-skill-stage-clock-v1", mission, _plain(owner_ref), boot, 3600, now, horizon, mono, actual)
    if not outer[0] <= inner[0] < inner[1] <= outer[1] or not outer[2] <= inner[2] < inner[3] <= outer[3]:
        raise ValueError("discovery extends global clock")
    code, deps = implementation_hashes(native)
    if any(doc.get("code_sha") != code or doc.get("deps_sha") != deps for doc in (context, parent, grant)):
        raise ValueError("current discovery software differs")
    input_root = _canonical(context["metadata_root"])
    policy_ref=context.get("discovery_policy")
    if not isinstance(policy_ref,dict) or owner.get("discovery_policy") != _plain(policy_ref) or grant.get("discovery_policy") != policy_ref:
        raise ValueError("exact owner/grant discovery policy required")
    policy=_document(policy_ref,native,"coastal-governed-discovery-policy-v1")
    if (policy_ref["path"]!="metadata/discovery-policy.json"
        or policy.get("mission_id")!=mission or policy.get("output_root")!=str(root)
        or policy.get("metadata_root")!=str(input_root) or policy.get("plan")!=context["plan"]
        or policy.get("code_sha")!=code or policy.get("deps_sha")!=deps
        or policy.get("original_source_reads")!=0 or policy.get("network_requests")!=0):
        raise ValueError("discovery input policy binding differs")
    sources=policy.get("source_specs")
    if not isinstance(sources,list) or not 1<=len(sources)<=40:
        raise ValueError("finite owner-pinned discovery source specs required")
    plan = _document(context["plan"], input_root, inventory.PLAN)
    return root, grant, input_root, plan, sources, min(outer[1], inner[1], horizon)

def run(context, *, now, horizon):
    root, grant, input_root, plan, sources, deadline = validate(context, now, horizon)
    manager=None
    if root.exists():
        if not (root/"managed-output.json").is_file():
            raise ValueError("existing discovery root is not managed")
        manager=ManagedOutputs(root,grant,digest(grant))
        if manager._read()["files"]:
            raise ValueError("discovery attempt already spent; no retry")
    # Existing inventory performs bounded JSON reads plus lstat; never source open.
    manifest = inventory.inventory(input_root, plan, now=now, horizon=horizon)
    observed=sorted([dict(source_id=row["source_id"],sha256=row["source"]["sha256"],
                         bytes=row["source"]["bytes"]) for row in manifest["sources"]],key=inventory.digest)
    if observed!=sorted(sources,key=inventory.digest):
        raise ValueError("metadata inventory differs from pinned source specs")
    binding = digest(dict(context=context, plan=plan))
    terminal = dict(schema="coastal-governed-discovery-terminal-v1",binding=binding,
                    state="USABLE_METADATA_ONLY" if manifest["usable_source_ids"] else "HELD_METADATA",
                    original_source_reads=0,source_hashes=0,network_requests=0,units_started=0,
                    native_quality_accepted=False,manifest_sha256=digest(manifest))
    docs = [("usable-inputs.json", manifest), ("terminal-discovery.json", terminal)]
    payloads = [(name, inventory.encoded(doc)) for name,doc in docs]
    if sum(len(raw) for _,raw in payloads) > LIMIT:
        raise ValueError("complete discovery payload exceeds512KiB")
    if time.time() >= deadline:
        raise TimeoutError("discovery deadline exhausted before output")
    if manager is None:
        if not root.parent.is_dir():
            raise ValueError("owned mission parent must exist")
        root.mkdir(mode=0o700)
        manager = ManagedOutputs.create(root,grant,digest(grant))
    # All exact serialized files admitted before first artifact write.
    for name,raw in payloads:
        manager.reserve_file(name,role="control",max_bytes=len(raw),intent="governed-discovery:"+name)
    for name,raw in payloads:
        if time.time() >= deadline:
            raise TimeoutError("discovery deadline exhausted; partial evidence retained")
        manager.write_bytes(name,raw,role="control",max_bytes=len(raw),intent="governed-discovery:"+name)
    manager.audit()
    return dict(schema="coastal-governed-discovery-result-v1",state=terminal["state"],
                output_root=str(root),payload_bytes=sum(len(raw) for _,raw in payloads),
                ledger_overhead_bytes=524288,original_source_reads=0,network_requests=0,units_started=0)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context",required=True,help="Pinned descriptor wrapper JSON")
    parser.add_argument("--now",required=True,type=float)
    parser.add_argument("--horizon",required=True,type=float)
    args=parser.parse_args(argv)
    if len(args.context)>131072: raise ValueError("context argument cap")
    wrapper=json.loads(args.context)
    context=_document(wrapper,_canonical(wrapper["root"]),SCHEMA)
    print(json.dumps(run(context,now=args.now,horizon=args.horizon),sort_keys=True))

if __name__ == "__main__":
    main()
