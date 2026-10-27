import hashlib
import json
from pathlib import Path
import time
from skippercast.coastal import child_release as cr
from skippercast.coastal.handoff.common import digest
from skippercast.coastal.output_writer import partition_declarations

def fixture(tmp_path, role="render"):
    mission = tmp_path / "mission"
    runtime = mission / "runtime"
    native = runtime / "execution"
    (native / "metadata").mkdir(parents=True)
    (runtime / "control").mkdir()
    partition = partition_declarations(0, 65*1024*1024, str(mission))
    code, deps = cr.implementation_hashes(native)
    parent = dict(schema="coastal-authenticated-policy-v1", mission_id="child-test", execution_authorized=True,
                  output_partition_role="runtime", output_partition=partition, **partition["children"]["runtime"],
                  code_sha=code, deps_sha=deps, saved_area_continuation_contract="coastal-saved-area-continuation-v1",
                  window_count=4, window_side=128, source={"bytes":36757568},
                  larger_runtime_contract="coastal-managed-eight-copy-four128-v1", source_volume_cap_bytes=220545408,
                  prior_effective_bytes=895006524, cumulative_limit_bytes=1115551932)
    owner = dict(schema="coastal-new-mission-owner-authorization-v1", mission_id="child-test", execution_authorized=True,
                 output_root=str(runtime), output_partition=partition, source_bytes=220545408, source_admissions=6,
                 source_prior_effective_bytes=895006524, source_cumulative_limit_bytes=1115551932,
                 global_wall_seconds=18000, mapping_wall_seconds=3600)
    def put(root, name, doc):
        path = root / name
        data = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
        path.write_bytes(data)
        return dict(root=str(root), path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), contract=doc["schema"])
    owner_ref = put(native,"metadata/owner.json",owner)
    plain = cr._plain(owner_ref)
    registry = dict(schema="coastal-single-mission-allocation-v1", mission_id="child-test", output_root=str(runtime),
                    output_partition=partition, owner_authorization=plain, owner_sha256=digest(owner),
                    grant_sha256=digest(parent), second_mission_allowed=False)
    now, mono = time.time(), time.monotonic()
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    global_clock = dict(schema="coastal-mission-global-clock-v1",mission_id="child-test",owner_authorization=plain,
                        boot_id=boot,start_epoch=now-10,deadline_epoch=now-10+18000,
                        start_monotonic=mono-10,deadline_monotonic=mono-10+18000,wall_seconds=18000)
    stage_clock = dict(schema="coastal-skill-stage-clock-v1",mission_id="child-test",owner_authorization=plain,
                       skill=role,boot_id=boot,start_epoch=now-1,deadline_epoch=now-1+3600,
                       start_monotonic=mono-1,deadline_monotonic=mono-1+3600,wall_seconds=3600)
    child = dict(schema="coastal-child-output-grant-v1", mission_id="child-test", execution_authorized=True,
                 output_partition_role=role,output_partition=partition,**partition["children"][role],
                 code_sha=code,deps_sha=deps,parent_runtime_grant_sha256=digest(parent))
    ctx = dict(schema="coastal-child-release-context-v1",mission_id="child-test",output_root=child["output_root"],
               child_grant=child,code_sha=code,deps_sha=deps,owner_authorization=owner_ref,
               runtime_grant=put(native,"metadata/grant.json",parent),
               allocation_registry=put(runtime,"control/allocation-registry.json",registry),
               global_clock=put(runtime,"control/global-clock.json",global_clock),
               stage_clock=put(runtime,"control/"+role+"-stage-clock.json",stage_clock),
               mapping_stop=put(runtime,"control/mapping-stop.json",dict(schema="coastal-four128-stop-proof-v1",
                   mission_id="child-test",boot_id=boot,runtime_grant_sha256=digest(parent),
                   descendants_empty=True,stop_exit_code=0,query_exit_code=0,
                   properties={"ActiveState":"inactive","ControlGroup":""},observed_monotonic=mono-2)))
    def mutate(key, field, value):
        ref=ctx[key]
        doc=json.loads((Path(ref["root"])/ref["path"]).read_bytes())
        doc[field]=value
        ctx[key]=put(Path(ref["root"]),ref["path"],doc)
    return ctx,now,mutate




def observed_clocks():
    return time.time(),time.monotonic()
