"""SQLite WAL transitions, fenced leases and conservative crash recovery."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import socket
import shutil
import sqlite3
import time
import uuid

from .stages import NEXT, ORDER, digest, readiness, verify_ref

SCHEMA = """
CREATE TABLE IF NOT EXISTS segments(segment_id TEXT PRIMARY KEY, region TEXT NOT NULL, record_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY, segment_id TEXT NOT NULL REFERENCES segments,
 stage TEXT NOT NULL, idempotency_key TEXT UNIQUE NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 max_attempts INTEGER NOT NULL, created REAL NOT NULL, not_before REAL NOT NULL DEFAULT 0, record_json TEXT NOT NULL,
 result_sha TEXT, holds_json TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS leases(job_id TEXT PRIMARY KEY REFERENCES jobs, token TEXT UNIQUE NOT NULL,
 controller_json TEXT NOT NULL, child_json TEXT, expires REAL NOT NULL, heartbeat REAL NOT NULL);
CREATE TABLE IF NOT EXISTS artifacts(sha256 TEXT NOT NULL, path TEXT NOT NULL, bytes INTEGER NOT NULL,
 kind TEXT NOT NULL, produced_by_job TEXT REFERENCES jobs, PRIMARY KEY(sha256,path));
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, utc REAL NOT NULL, job_id TEXT, kind TEXT NOT NULL, detail_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS regions(region TEXT PRIMARY KEY, paused INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS charges(job_id TEXT PRIMARY KEY REFERENCES jobs, wall_s REAL NOT NULL DEFAULT 0,
 bytes INTEGER NOT NULL DEFAULT 0, requests INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS region_progress(region TEXT PRIMARY KEY REFERENCES regions,
 started REAL NOT NULL,last_progress REAL NOT NULL,observed_monotonic REAL NOT NULL,boot_id TEXT NOT NULL,stop_reason TEXT);
CREATE TABLE IF NOT EXISTS progress_evidence(region TEXT NOT NULL,stage TEXT NOT NULL,segment_id TEXT NOT NULL,evidence_sha TEXT NOT NULL,
 committed REAL NOT NULL,PRIMARY KEY(region,stage,segment_id,evidence_sha));
CREATE TABLE IF NOT EXISTS authenticated_missions(
 region TEXT PRIMARY KEY REFERENCES regions,source_sha TEXT NOT NULL,source_bytes INTEGER NOT NULL,
 started_utc REAL NOT NULL,started_monotonic REAL NOT NULL,boot_id TEXT NOT NULL,
 deadline_utc REAL NOT NULL,deadline_monotonic REAL NOT NULL,carry_sha TEXT NOT NULL,limits_sha TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS authenticated_artifacts(
 path TEXT NOT NULL,sha256 TEXT NOT NULL,bytes INTEGER NOT NULL,contract TEXT NOT NULL,
 job_id TEXT NOT NULL REFERENCES jobs,lease_token TEXT NOT NULL,committed_result_sha TEXT NOT NULL,
 PRIMARY KEY(path,sha256));
CREATE TABLE IF NOT EXISTS authenticated_phases(region TEXT NOT NULL REFERENCES authenticated_missions,
 stage TEXT NOT NULL,job_id TEXT UNIQUE NOT NULL REFERENCES jobs,PRIMARY KEY(region,stage));
CREATE TABLE IF NOT EXISTS authenticated_window_phases(
 region TEXT NOT NULL REFERENCES authenticated_missions,window_key TEXT NOT NULL,
 stage TEXT NOT NULL,job_id TEXT NOT NULL REFERENCES jobs,
 PRIMARY KEY(region,window_key,stage));
PRAGMA user_version=3;
"""


class FencedLease(ValueError):
    """A lost or expired claim cannot change durable state."""


def process_identity(pid=None):
    pid = pid or os.getpid()
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        start, state, group, session = fields[19], fields[0], int(fields[2]), int(fields[3])
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except (OSError, IndexError):
        start, boot, state, group, session = None, None, None, None, None
    return {"host": socket.gethostname(), "boot_id": boot, "pid": pid, "start_ticks": start,
            "state": state, "pgid": group, "sid": session}


def identity_stopped(identity):
    """False means live OR unverifiable; never silently replay that case."""
    if not identity or identity.get("host", socket.gethostname()) != socket.gethostname():
        return False
    current = process_identity(identity.get("pid"))
    if not identity.get("boot_id") or not identity.get("start_ticks"):
        return False
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return False
    if boot != identity["boot_id"]:
        return True
    if current["start_ticks"] == str(identity["start_ticks"]) and current["state"] not in {"Z", "X"}:
        return False
    # Leader death is insufficient: any remaining member of its process group
    # keeps the job uncertain. A reused group is conservatively held too.
    group, session = identity.get("pgid"), identity.get("sid")
    if group or session:
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                fields = (proc/"stat").read_text().rsplit(")", 1)[1].split()
                if (group and int(fields[2]) == int(group) or session and int(fields[3]) == int(session)) and fields[0] not in {"Z", "X"}:
                    return False
            except (FileNotFoundError, ProcessLookupError):
                continue
            except (OSError, ValueError, IndexError):
                return False
    return True


class Store:
    def __init__(self, path, *, root, clock=time.time, policy=None):
        self.path, self.root, self.clock = Path(path), Path(root).resolve(strict=True), clock
        if policy is None:
            from importlib.resources import files
            policy = json.loads(files("skippercast.coastal.coordinator").joinpath("policy.json").read_text())
        self.policy = policy
        self._budgets = {}
        self.progress_clock = time.monotonic if clock is time.time else clock
        marks = policy["watermarks"]
        if not 0 < marks["low"] < marks["high"] or marks["held_cap"] < 1 or policy.get("worker_network") is not False:
            raise ValueError("invalid private coordinator policy")
        self.managed_outputs=None
        managed_grant=policy.get("managed_output_grant")
        native_grant=policy.get("authenticated",{})
        if native_grant.get("ordered_scope_contract")=="coastal-ordered-four128-v2":
            if managed_grant is not None and managed_grant!=native_grant:
                raise ValueError("Store managed grant differs from native authority")
            managed_grant=native_grant
        if managed_grant is not None:
            from ..output_writer import ManagedOutputs
            if managed_grant.get("ordered_scope_contract")!="coastal-ordered-four128-v2":
                raise ValueError("managed Store requires explicit larger scope")
            self.managed_outputs=ManagedOutputs(managed_grant["output_root"],managed_grant,digest(managed_grant))
            if not self.root.is_relative_to(self.managed_outputs.root):
                raise ValueError("Store root outside immutable managed parent")
            self.db=self.managed_outputs.connect_sqlite(self.path,intent=digest(["coastal-store",str(self.path)]),max_db_bytes=524288)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(self.path, isolation_level=None, timeout=10)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        from .source_free import SCHEMA as SOURCEFREE_SCHEMA
        self.db.executescript(SOURCEFREE_SCHEMA)

    def close(self):
        self.db.close()
        managed=getattr(self,"managed_outputs",None)
        if managed is not None:managed.audit()

    def write_artifact(self,path,value,*,role="control",max_bytes=131072):
        if self.managed_outputs is None:
            from ..handoff.common import write
            return write(path,value)
        return self.managed_outputs.write_json(path,value,role=role,max_bytes=max_bytes,
            intent=digest(["coastal-artifact",str(Path(path).absolute())]))

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def event(self, job_id, kind, detail):
        self.db.execute("INSERT INTO events(utc,job_id,kind,detail_json) VALUES(?,?,?,?)",
                        (self.clock(), job_id, kind, json.dumps(detail, sort_keys=True)))

    def add_segment(self, record):
        from .segments import segment
        expected = segment(record["bbox"][0], record["bbox"][1], region=record["region"])
        if expected["segment_id"] != record["segment_id"] or expected["bbox"] != record["bbox"]:
            raise ValueError("geographic identity mismatch")
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO segments VALUES(?,?,?)", (record["segment_id"], record["region"], json.dumps(record)))
            existing = json.loads(self.db.execute("SELECT record_json FROM segments WHERE segment_id=?", (record["segment_id"],)).fetchone()[0])
            if existing != record:
                raise ValueError("existing segment identity cannot be overwritten")
            self.db.execute("INSERT OR IGNORE INTO regions(region) VALUES(?)", (record["region"],))
            identity = process_identity()
            self.db.execute("INSERT OR IGNORE INTO region_progress VALUES(?,?,?,?,?,NULL)",
                            (record["region"], self.progress_clock(), self.progress_clock(), self.progress_clock(), identity["boot_id"] or "unknown"))

    def _enqueue(self, segment_id, stage, *, code_sha, deps_sha, params=None, input_manifest=None,
                 budget=None, max_attempts=2, execution_contract=None, context=None):
        if stage not in ORDER or not 1 <= max_attempts <= 10:
            raise ValueError("invalid stage or attempt bound")
        if not self.db.execute("SELECT 1 FROM segments WHERE segment_id=?", (segment_id,)).fetchone():
            raise ValueError("unknown segment")
        for value in (code_sha, deps_sha):
            if not isinstance(value, str) or len(value) != 64 or any(x not in "0123456789abcdef" for x in value):
                raise ValueError("expected SHA256 implementation identity")
        params = params or {}
        budget = budget or {"wall_s": 60, "memory_bytes": 1073741824, "bytes": 0, "requests": 0}
        for key in ("wall_s", "memory_bytes", "bytes", "requests"):
            if key not in budget or not isinstance(budget[key], (int, float)) or not math.isfinite(budget[key]) or budget[key] < 0:
                raise ValueError("invalid bounded budget")
        if budget["wall_s"] <= 0 or budget["memory_bytes"] <= 0:
            raise ValueError("positive wall and memory limits required")
        input_sha = "0"*64
        input_identity = input_sha
        if input_manifest:
            # Dedicated metadata was just role/size/hash authenticated. Never
            # re-resolve it through the ordinary native-capable resolver.
            path = self.root/input_manifest["path"] if execution_contract else verify_ref(self.root, input_manifest)
            input_sha = input_manifest["sha256"]
            # Byte-identical deterministic packets from different producers
            # have different owned paths. Match the identity used by lineage,
            # while accepted path aliases remain one idempotent input.
            input_identity = {"schema": "coastal-owned-input-v1",
                              "path": path.relative_to(self.root).as_posix(),
                              "sha256": input_sha, "bytes": input_manifest["bytes"] if execution_contract else path.stat().st_size}
        params_sha = digest(params)
        key = digest([stage, segment_id, input_identity, code_sha, deps_sha, params_sha, digest(budget)])
        if execution_contract is not None:
            key=digest([key,execution_contract,digest(context)])
        job_id = "job:"+key[:24]
        record = dict(job_id=job_id, stage=stage, segment_id=segment_id, code_sha=code_sha,
                      deps_sha=deps_sha, params_sha=params_sha, input_manifest_sha=input_sha,
                      input_manifest=input_manifest, params=params, budget=budget)
        if execution_contract is not None:
            record.update(context or {})
            record["execution_contract"]=execution_contract
        self.db.execute("INSERT OR IGNORE INTO jobs(job_id,segment_id,stage,idempotency_key,state,max_attempts,created,record_json) VALUES(?,?,?,?,'queued',?,?,?)",
                        (job_id, segment_id, stage, key, max_attempts, self.clock(), json.dumps(record)))
        if self.db.execute("SELECT changes()").fetchone()[0]:
            self.event(job_id, "enqueued", {"identity": key})
        return job_id

    def enqueue(self, segment_id, stage, **kwargs):
        if self.policy.get("sourcefree_only"):raise ValueError("source-free mission forbids generic/native enqueue")
        if "execution_contract" in kwargs or "context" in kwargs:
            raise ValueError("dedicated authenticated enqueue API required")
        with self.transaction():
            return self._enqueue(segment_id, stage, **kwargs)

    def enqueue_authenticated(self, segment_id, stage, *, code_sha, deps_sha,
                              input_manifest, unit_ref, carry_ref):
        """Dedicated immutable grant: metadata gates precede Budget creation."""
        if self.policy.get("sourcefree_only"):raise ValueError("source-free mission forbids native enqueue")
        from .authenticated import (EXECUTION_CONTRACT, INPUT_CONTRACT, metadata_document,
                                    validate_input, unit_context, check_context, _source_identity)
        trusted=self.policy.get("authenticated")
        if not trusted or trusted.get("schema")!="coastal-authenticated-policy-v1":
            raise ValueError("authenticated mission policy unavailable")
        from skippercast.coastal.authenticated_v1.profiles import profile,grant_identity,validate_grant_packet
        domain=grant_identity(trusted);selected=profile(domain.get('execution_profile'),domain)
        from ..authenticated_v1.source_reuse import source_volume_cap
        source_cap=source_volume_cap(trusted) if trusted.get("saved_area_continuation_contract") is not None else selected["reservations"]*trusted["source"]["bytes"]
        source=trusted["source"];_source_identity(source)
        source_root=trusted["source_root"];relative=trusted["source_relative_path"]
        if Path(os.path.abspath(source_root)).is_relative_to(self.root) or self.root.is_relative_to(Path(os.path.abspath(source_root))):
            raise ValueError("minimal source and artifact domains must be disjoint")
        if (not isinstance(source_root,str) or source_root!=os.path.abspath(source_root)
            or not isinstance(relative,str) or Path(relative).name!=relative or Path(relative).suffix.lower()!=".bag"):
            raise ValueError("minimal exact source root/leaf required")
        if input_manifest["sha256"]==source["sha256"]:raise ValueError("native bytes cannot be metadata")
        packet=metadata_document(self.root,input_manifest,INPUT_CONTRACT)
        if packet.get("source")!=source or packet.get("source_root")!=source_root or packet.get("source_relative_path")!=relative:
            raise ValueError("input differs from immutable approved source grant")
        validate_grant_packet(trusted,packet)
        window=packet['fixed_center_plan'].get('native_window') if selected['name'] else None
        if selected['name'] and window not in domain['window_set']:raise ValueError('window outside immutable finite grant')
        window_key=digest(window) if selected['name'] else None
        if trusted.get("saved_area_continuation_contract") is not None:
            from .saved_area import registered_acceptance
            registered_acceptance(self,trusted,now=self.clock(),horizon=self.clock()+180)
            if window==domain["window_set"][0]:raise ValueError("adopted A native admission forbidden")
        with self.transaction():
            record=json.loads(self.db.execute("SELECT record_json FROM segments WHERE segment_id=?",(segment_id,)).fetchone()[0])
            if unit_ref["sha256"]==source["sha256"] or carry_ref["sha256"]==source["sha256"]:raise ValueError("native metadata alias")
            unit=unit_context(self.root,unit_ref,now=self.clock(),monotonic=self.progress_clock())
            carry=metadata_document(self.root,carry_ref,"coastal-authenticated-carry-v1")
            if (type(carry.get("cumulative_limit_bytes")) is not int or type(carry.get("prior_effective_bytes")) is not int
                or carry["prior_effective_bytes"]<0 or carry["remaining_bytes"]!=carry["cumulative_limit_bytes"]-carry["prior_effective_bytes"]
                or source_cap>carry["remaining_bytes"]):
                raise ValueError("immutable cumulative source-volume grant invalid")
            mission=self.db.execute("SELECT * FROM authenticated_missions WHERE region=?",(record["region"],)).fetchone()
            if mission is None:
                if stage!="acquire":raise ValueError("factual phase must create mission first")
                start_utc,start_mono,boot=unit["phase_unit_start_utc"],unit["phase_unit_start_monotonic"],unit["boot_id"]
            else:
                if (mission["source_sha"]!=source["sha256"] or mission["source_bytes"]!=source["bytes"]
                    or mission["carry_sha"]!=carry_ref["sha256"] or mission["limits_sha"]!=digest(domain)):
                    raise ValueError("existing mission origin/source/grant cannot change")
                start_utc,start_mono,boot=mission["started_utc"],mission["started_monotonic"],mission["boot_id"]
            context=dict(root=str(self.root),source_root=source_root,source_relative_path=relative,source_grant=source,
                store_path=str(self.path.absolute()),
                budget_ledger=str((self.path.parent/("budget-"+digest([self.path.name,record["region"]])+".json")).absolute()),
                mission_start_utc=start_utc,mission_start_monotonic=start_mono,
                overall_deadline_utc=start_utc+selected["mission_seconds"],overall_deadline_monotonic=start_mono+selected["mission_seconds"],
                mission_deadline_utc=start_utc+selected["mission_seconds"],boot_id=boot,unit_context=unit_ref,
                phase_unit_start_utc=unit["phase_unit_start_utc"],phase_unit_start_monotonic=unit["phase_unit_start_monotonic"],
                phase_deadline_utc=min(unit["phase_unit_start_utc"]+180,start_utc+selected["mission_seconds"]),
                phase_deadline_monotonic=min(unit["phase_unit_start_monotonic"]+180,start_mono+selected["mission_seconds"]),
                deadline_utc=min(unit["phase_unit_start_utc"]+120,start_utc+selected["mission_seconds"]-60),
                deadline_monotonic=min(unit["phase_unit_start_monotonic"]+120,start_mono+selected["mission_seconds"]-60),carry_ref=carry_ref)
            if domain.get('ordered_scope_contract')=='coastal-ordered-four128-v2':
                # Carry the full released bytes into the persisted job. The
                # managed ledger binds this exact grant, not its domain subset.
                context['managed_output_grant']=trusted
            if selected['name']:
                context.update(execution_profile=selected['name'],source_domain_grant=domain,window_key=window_key)
                if selected['name']=='coastal-contained-windows-v3':context.update(window_side=selected['side'],window_count=selected['window_count'])
                for earlier in domain['window_set'][:domain['window_set'].index(window)]:
                    if trusted.get("saved_area_continuation_contract") and earlier==domain["window_set"][0]:continue
                    completed=self.db.execute("SELECT p.stage,j.state FROM authenticated_window_phases p JOIN jobs j USING(job_id) WHERE p.region=? AND p.window_key=?",(record['region'],digest(earlier))).fetchall()
                    states={row['stage']:row['state'] for row in completed}
                    if states.get('acquire')!='held' and not (states.get('acquire')=='done' and states.get('qualify') in ('done','held')):
                        raise ValueError('earlier finite window has not reached terminal qualification/hold')
            check_context(dict(context,stage=stage),now=self.clock(),monotonic=self.progress_clock())
            validate_input(self.root,input_manifest,stage=stage,segment=record,code_sha=code_sha,deps_sha=deps_sha,
                now=self.clock(),mission_deadline=start_utc+selected["mission_seconds"],connection=self.db,expected_source=source,
                source_root=source_root,source_relative_path=relative)
            from .authenticated import actual_unit_check
            actual_unit_check(context)
            authority=self.budget_for(record["region"],origin=dict(boot_id=boot,utc=start_utc,monotonic=start_mono))
            if (authority.limits.wall_s!=selected["mission_seconds"] or authority.limits.reserve_s!=60
                or authority.limits.bytes!=source_cap or authority.limits.requests!=0
                or authority.limits.tokens not in (None,0) or authority.limits.attempts_per_candidate!=1):
                raise ValueError("authenticated Budget must bind exact two source caps and600s clock")
            # A SQL rollback can leave this ledger, but reopen cannot change its origin.
            ledger=json.loads(authority.path.read_text())
            if ledger["started_monotonic"]!=start_mono or ledger["boot_id"]!=boot:
                raise ValueError("existing Budget origin differs; no reset")
            if mission is None:
                self.db.execute("INSERT INTO authenticated_missions VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (record["region"],source["sha256"],source["bytes"],start_utc,start_mono,boot,start_utc+selected["mission_seconds"],start_mono+selected["mission_seconds"],
                     carry_ref["sha256"],digest(domain)))
            candidate=self._enqueue(segment_id,stage,code_sha=code_sha,deps_sha=deps_sha,input_manifest=input_manifest,
                budget=dict(wall_s=120,memory_bytes=1073741824,bytes=source["bytes"],requests=0),
                max_attempts=1,execution_contract=EXECUTION_CONTRACT,context=context)
            if selected['name']:
                prior=self.db.execute("SELECT job_id FROM authenticated_window_phases WHERE region=? AND window_key=? AND stage=?",(record['region'],window_key,stage)).fetchone()
                if prior and prior['job_id']!=candidate:raise ValueError('authorized native window phase cannot be restarted')
                self.db.execute("INSERT OR IGNORE INTO authenticated_window_phases VALUES(?,?,?,?)",(record['region'],window_key,stage,candidate))
                return candidate
            prior=self.db.execute("SELECT job_id FROM authenticated_phases WHERE region=? AND stage=?",(record["region"],stage)).fetchone()
            if prior and prior["job_id"]!=candidate:raise ValueError("authorized phase identity cannot be restarted")
            self.db.execute("INSERT OR IGNORE INTO authenticated_phases VALUES(?,?,?)",(record["region"],stage,candidate))
            return candidate

    def enqueue_sourcefree(self, manifest, index, *, code_sha, deps_sha):
        from .source_free import enqueue
        return enqueue(self,manifest,index,code_sha=code_sha,deps_sha=deps_sha)

    def _evidence_gate(self, job):
        if job.get("sourcefree_contract"):
            try:
                from .source_free import CONTRACT,validate_input,audit
                if job["sourcefree_contract"]!=CONTRACT or job["stage"]!="map":
                    raise ValueError("unknown source-free contract")
                audit(self)
                validate_input(self,job["input_manifest"],now=self.clock(),
                               horizon=self.clock()+job["budget"]["wall_s"])
                return True,[]
            except (ValueError,OSError,KeyError,TypeError,ImportError) as exc:
                return False,["sourcefree_evidence_invalid:"+str(exc)]
        if job.get("execution_contract"):
            try:
                from .authenticated import EXECUTION_CONTRACT, validate_input, check_context
                if job["execution_contract"]!=EXECUTION_CONTRACT:raise ValueError("unknown execution lane")
                check_context(job, now=self.clock(), monotonic=self.progress_clock())
                record=json.loads(self.db.execute("SELECT record_json FROM segments WHERE segment_id=?",(job["segment_id"],)).fetchone()[0])
                validate_input(self.root,job["input_manifest"],stage=job["stage"],segment=record,
                    code_sha=job["code_sha"],deps_sha=job["deps_sha"],now=self.clock(),
                    mission_deadline=job["overall_deadline_utc"],connection=self.db,expected_source=job["source_grant"],
                    source_root=job["source_root"],source_relative_path=job["source_relative_path"])
                return True,[]
            except (ValueError,OSError,KeyError,TypeError,ImportError) as exc:
                return False,["authenticated_evidence_invalid:"+str(exc)]
        if job["stage"] == "discover":
            return True, []
        if not job.get("input_manifest"):
            return False, ["input_manifest_missing"]
        try:
            manifest = json.loads(verify_ref(self.root, job["input_manifest"]).read_text())
            record = json.loads(self.db.execute("SELECT record_json FROM segments WHERE segment_id=?", (job["segment_id"],)).fetchone()[0])
            if manifest.get("segment_id") != job["segment_id"]:
                return False, ["segment_mismatch"]
            if manifest.get("synthetic") and not record.get("synthetic"):
                return False, ["synthetic_not_real_evidence"]
            if job["stage"] == "render" and manifest.get("schema") == "coastal-terrain-only-input-v1":
                from datetime import datetime, timedelta, timezone
                from ..render import terrain_only
                from ..handoff.common import validate_derived_geotiff
                params = job["params"]
                terrain_root = Path(params["terrain_root"]).resolve(strict=True)
                if not self.root.is_relative_to(terrain_root):
                    raise ValueError("terrain-only input root confinement")
                now = datetime.fromtimestamp(self.clock(), timezone.utc)
                checked = terrain_only.verify(terrain_root, manifest, now=now,
                    minimum_valid_until=now+timedelta(seconds=job["budget"]["wall_s"]))
                if terrain_only.context(checked) != params["terrain_context_digest"]:
                    raise ValueError("terrain-only context binding mismatch")
                # Hash and confine derived assets before spending a lease or a
                # worker attempt. No native reader or rendering is invoked.
                for name, contract in (("terrain", "coastal-normalized-terrain-v1"),
                                       ("mask", "coastal-native-support-v2"),
                                       ("uncertainty", "coastal-derived-uncertainty-m-v1")):
                    if name in checked:
                        validate_derived_geotiff(terrain_root, checked[name],
                            contract=contract, cap=terrain_only.MAX_FILE_BYTES)
                return True, []
            if job["stage"] == "map":
                from datetime import datetime, timedelta, timezone
                from skippercast.coastal.handoff.mapping_input import verify
                now = datetime.fromtimestamp(self.clock(), timezone.utc)
                result = verify(self.root, manifest, now=now, minimum_valid_until=now+timedelta(seconds=job["budget"]["wall_s"]))
                return result["ready"], result["holds"]
            if job["stage"] in {"acquire", "qualify"} and manifest.get("schema") == "coastal-native-job-v1":
                # Dispatch starts measurement; it is not scientific qualification.
                from skippercast.coastal.handoff.common import validate_native_source
                validate_native_source(self.root, manifest["source"], netcdf=True)
                window = manifest["window"]
                if len(window) != 4 or any(not isinstance(v, int) for v in window) or min(window) < 0 or not 0 < window[2]*window[3] <= 1048576:
                    return False, ["native_window_bound"]
                return True, []
            if job["stage"] == "render" and manifest.get("schema") == "coastal-mapping-run-v1":
                from skippercast.coastal.mapping import verify
                from datetime import datetime, timezone
                now = datetime.fromtimestamp(self.clock(), timezone.utc)
                from datetime import timedelta
                result = verify(self.root, manifest, now=now, minimum_valid_until=now+timedelta(seconds=job["budget"]["wall_s"]))
                return result["ready"], result["holds"]
            if job["stage"] == "render" and manifest.get("schema") == "render-handoff-v2.1":
                from datetime import datetime, timedelta, timezone
                from skippercast.coastal.handoff.render import verify
                now = datetime.fromtimestamp(self.clock(), timezone.utc)
                checked = verify(self.root, manifest, now=now, minimum_valid_until=now+timedelta(seconds=job["budget"]["wall_s"]))
                return checked["ready"], checked["holds"]
            return readiness(job["stage"], manifest, now=self.clock(), duration_s=job["budget"]["wall_s"],
                             code_sha=job["code_sha"], deps_sha=job["deps_sha"], synthetic=record.get("synthetic") is True)
        except (OSError, ValueError, KeyError, ImportError, TypeError) as exc:
            return False, ["evidence_invalid:"+type(exc).__name__]

    def pressure(self, region, *, high=None, low=None, held_cap=None):
        marks = self.policy["watermarks"]
        high, low, held_cap = high or marks["high"], low or marks["low"], held_cap or marks["held_cap"]
        rows = self.db.execute("SELECT j.*,s.region FROM jobs j JOIN segments s USING(segment_id) WHERE region=? ORDER BY created,j.rowid", (region,)).fetchall()
        latest = {}
        for row in rows:
            latest[(row["segment_id"], row["stage"])] = row["state"]
        ready = sum(state == "done" and latest.get((sid, "map"), "not_ready") in {"not_ready", "queued"}
                    for (sid, stage), state in latest.items() if stage == "qualify")
        held = len({sid for (sid, _), state in latest.items() if state == "held"})
        paused = bool(self.db.execute("SELECT paused FROM regions WHERE region=?", (region,)).fetchone()[0])
        if ready >= high or held >= held_cap:
            paused = True
        elif ready <= low and held < held_cap:
            paused = False
        self.db.execute("UPDATE regions SET paused=? WHERE region=?", (int(paused), region))
        return {"paused": paused, "qualified_unmapped": ready, "held_segments": held}

    def budget_for(self, region, *, origin=None):
        """The shared Budget file is authoritative; SQLite charges are audit telemetry."""
        from skippercast.coastal.budget import Budget, Limits
        managed_config=None
        if self.managed_outputs is not None:
            grant=self.policy.get('managed_output_grant') or self.policy['authenticated']
            managed_config=dict(grant=grant,grant_digest=digest(grant),role='control',max_bytes=65536)
        managed_kwargs={'managed_output':managed_config} if managed_config is not None else {}
        if region not in self._budgets:
            limits = Limits(**self.policy["budgets"], attempts_per_candidate=self.policy["max_attempts"])
            path = self.path.parent/("budget-"+digest([self.path.name, region])+".json")
            clock = None if self.clock is time.time else self.clock
            if path.exists():
                budget = Budget.open(path, clock=clock,**managed_kwargs)
                if budget.limits != limits:
                    raise ValueError("coordinator budget policy changed; new approved mission required")
            else:
                legacy = self.db.execute("SELECT 1 FROM charges c JOIN jobs j USING(job_id) JOIN segments s USING(segment_id) WHERE region=? LIMIT 1", (region,)).fetchone()
                if legacy:
                    raise ValueError("budget_migration_required: existing mission consumption cannot be reset")
                budget = Budget.create(path, limits, clock=clock, origin=origin,**managed_kwargs)
            self._budgets[region] = budget
        return self._budgets[region]

    def stagnation(self, region):
        row = self.db.execute("SELECT * FROM region_progress WHERE region=?", (region,)).fetchone()
        now = self.progress_clock()
        reason = row["stop_reason"]
        boot = process_identity()["boot_id"] or "unknown"
        if boot != row["boot_id"] or now < row["observed_monotonic"]:
            reason = "progress_clock_uncertain"
        elif now-row["last_progress"] >= self.policy.get("stagnation_s", 1800):
            reason = "semantic_stagnation"
        self.db.execute("UPDATE region_progress SET observed_monotonic=MAX(observed_monotonic,?),stop_reason=? WHERE region=?",
                        (now, reason, region))
        return reason

    def _progress(self, region, stage, segment_id, evidence_sha):
        if stage not in {"qualify", "map", "render"}:
            return False
        self.db.execute("INSERT OR IGNORE INTO progress_evidence VALUES(?,?,?,?,?)",
                        (region, stage, segment_id, evidence_sha, self.clock()))
        if not self.db.execute("SELECT changes()").fetchone()[0]:
            return False
        self.db.execute("UPDATE region_progress SET last_progress=?,observed_monotonic=? WHERE region=?",
                        (self.progress_clock(), self.progress_clock(), region))
        self.event(None, "semantic_progress", {"region": region, "stage": stage, "segment_id": segment_id, "evidence_sha": evidence_sha})
        return True

    def claim(self, controller, *, lease_s=30, stages=ORDER, current_identity=None, job_id=None):
        with self.transaction():
            for stage in stages:
                if stage not in ORDER:
                    raise ValueError("invalid stage")
                rows = self.db.execute("SELECT j.*,s.region FROM jobs j JOIN segments s USING(segment_id) WHERE stage=? AND state='queued' AND attempts<max_attempts AND not_before<=? ORDER BY created,job_id", (stage, self.clock())).fetchall()
                for row in rows:
                    if job_id is not None and row["job_id"]!=job_id:
                        continue
                    if self.db.execute("SELECT 1 FROM jobs WHERE segment_id=? AND state IN ('claimed','running','failed_uncertain')", (row["segment_id"],)).fetchone():
                        continue
                    if stage in {"discover", "acquire"} and self.pressure(row["region"])["paused"]:
                        continue
                    job = json.loads(row["record_json"])
                    if self.policy.get("sourcefree_only") and not job.get("sourcefree_contract"):
                        self.db.execute("UPDATE jobs SET state='held',holds_json=? WHERE job_id=?",
                                        (json.dumps(["sourcefree_only_mission"]),row["job_id"]))
                        continue
                    if current_identity and (job["code_sha"], job["deps_sha"]) != tuple(current_identity):
                        self.db.execute("UPDATE jobs SET state='stale' WHERE job_id=?", (row["job_id"],))
                        self.event(row["job_id"], "stale_before_dispatch", {})
                        continue
                    stagnation = self.stagnation(row["region"])
                    if stagnation:
                        self.db.execute("UPDATE jobs SET state='held',holds_json=? WHERE job_id=?", (json.dumps([stagnation]), row["job_id"]))
                        self.event(row["job_id"], "semantic_stop", {"reason": stagnation})
                        continue
                    ready, holds = self._evidence_gate(job)
                    if not ready:
                        self.db.execute("UPDATE jobs SET state='held',holds_json=? WHERE job_id=?", (json.dumps(holds), row["job_id"]))
                        self.event(row["job_id"], "held_before_dispatch", {"holds": holds})
                        continue
                    if shutil.disk_usage(self.root).free < self.policy["storage"]["minimum_free_bytes"]+self.policy["storage"]["job_output_bytes"]:
                        self.db.execute("UPDATE jobs SET state='held',holds_json=? WHERE job_id=?", (json.dumps(["storage_bound"]), row["job_id"]))
                        self.event(row["job_id"], "storage_bound", {})
                        continue
                    try:
                        authority = self.budget_for(row["region"])
                        decision = authority.decide()
                    except ValueError as exc:
                        self.db.execute("UPDATE jobs SET state='held',holds_json=? WHERE job_id=?", (json.dumps(["budget_authority_invalid:"+str(exc)]), row["job_id"]))
                        self.event(row["job_id"], "budget_authority_invalid", {"reason": str(exc)})
                        continue
                    if (decision.reason == "failed_uncertain" and not job.get("execution_contract")
                            and not job.get("sourcefree_contract")):
                        # Another generic execution awaits explicit recovery. That
                        # pauses the mission; it is no verdict on this job, which
                        # stays queued (unclaimed, unreserved) so recovery can
                        # resume it. Dedicated lanes keep their own stop rules.
                        self.event(row["job_id"], "budget_paused_uncertain", {"reason": decision.reason})
                        continue
                    if not decision.allowed or any(job["budget"][key] > decision.remaining[key]
                        for key in (("bytes","requests") if job.get("execution_contract") else ("wall_s","bytes","requests"))):
                        self.db.execute("UPDATE jobs SET state='held',holds_json=? WHERE job_id=?", (json.dumps([decision.reason or "budget_exhausted"]), row["job_id"]))
                        self.event(row["job_id"], "budget_exhausted", {"reason": decision.reason})
                        continue
                    token = uuid.uuid4().hex
                    if job.get('execution_profile'):
                        try:
                            from .authenticated import output_retention
                            retained,slot,intent,directory=output_retention(dict(job,root=str(self.root)),token,create=True)
                            retained.reserve(slot,intent,directory,role='native')
                            retained.audit()
                        except (ValueError,OSError,KeyError,TypeError) as exc:
                            holds=['retention_admission_invalid:'+str(exc)]
                            self.db.execute("UPDATE jobs SET state='held',holds_json=? WHERE job_id=?",(json.dumps(holds),row['job_id']))
                            self.event(row['job_id'],'retention_held_before_dispatch',{'reason':str(exc)})
                            continue
                    if job.get('managed_output_grant') is not None:
                        try:
                            from .authenticated import managed_native_outputs
                            from ..runner import admit_managed_runtime
                            grant=job['managed_output_grant']
                            role='native' if job.get('execution_contract') else 'mapping'
                            maximum=131072 if job.get('execution_contract') else 65536
                            cfg=dict(grant=grant,grant_digest=digest(grant),role=role,max_bytes=maximum)
                            directory=self.root/'var/coastal/jobs'/job['job_id'].replace(':','-')/token
                            self.managed_outputs.reserve_file(self.managed_outputs.relative_path(directory/'job.json'),
                                role=role,max_bytes=maximum,intent=digest(['coastal-artifact',str((directory/'job.json').absolute())]))
                            admit_managed_runtime(directory/'intent.json',cfg,scratch=directory/'runner',
                                stdout_path=directory/'stdout.log',stderr_path=directory/'stderr.log',
                                output_limit_bytes=16384)
                            if job.get('execution_contract'):
                                managed_native_outputs(dict(job,root=str(self.root)),token,reserve=True)
                        except (ValueError,OSError,KeyError,TypeError) as exc:
                            holds=['managed_output_admission_invalid:'+str(exc)]
                            self.db.execute("UPDATE jobs SET state='held',holds_json=? WHERE job_id=?",(json.dumps(holds),row['job_id']))
                            self.event(row['job_id'],'managed_output_held_before_dispatch',{'reason':str(exc)})
                            continue
                    # File reservation persists before SQL claim commit. A rollback
                    # can consume extra capacity but can never authorize a refund.
                    authority.reserve(token, bytes=job["budget"]["bytes"], requests=job["budget"]["requests"], candidate=job["job_id"])
                    prior = self.db.execute("SELECT wall_s,bytes,requests FROM charges WHERE job_id=?", (row["job_id"],)).fetchone()
                    reservation = [(prior[i] if prior else 0) + job["budget"][key] for i, key in enumerate(("wall_s", "bytes", "requests"))]
                    self.db.execute("INSERT OR REPLACE INTO charges VALUES(?,?,?,?)", (row["job_id"], *reservation))
                    self.db.execute("UPDATE jobs SET state='claimed',attempts=attempts+1 WHERE job_id=?", (row["job_id"],))
                    self.db.execute("INSERT INTO leases VALUES(?,?,?,NULL,?,?)", (row["job_id"], token, json.dumps(controller), self.clock()+lease_s, self.clock()))
                    self.event(row["job_id"], "claimed", {"token": token, "controller": controller})
                    job.update(lease_token=token, region=row["region"], root=str(self.root), segment=json.loads(self.db.execute("SELECT record_json FROM segments WHERE segment_id=?", (row["segment_id"],)).fetchone()[0]))
                    return job
            return None

    def _lease(self, job_id, token):
        row = self.db.execute("SELECT * FROM leases WHERE job_id=?", (job_id,)).fetchone()
        if not row or row["token"] != token or row["expires"] <= self.clock():
            raise FencedLease("expired or superseded lease")
        return row

    def running(self, job_id, token, child):
        if not all(child.get(k) is not None for k in ("boot_id", "pid", "start_ticks", "pgid")):
            raise ValueError("durable child process identity missing")
        with self.transaction():
            self._lease(job_id, token)
            self.db.execute("UPDATE leases SET child_json=? WHERE job_id=?", (json.dumps(child), job_id))
            self.db.execute("UPDATE jobs SET state='running' WHERE job_id=?", (job_id,))
            self.event(job_id, "running", child)

    def heartbeat(self, job_id, token, *, lease_s=30):
        with self.transaction():
            self._lease(job_id, token)
            self.db.execute("UPDATE leases SET expires=?,heartbeat=? WHERE job_id=?", (self.clock()+lease_s, self.clock(), job_id))

    def charge(self, job_id, usage):
        values = [usage.get(key, 0) for key in ("wall_s", "bytes", "requests")]
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values):
            raise ValueError("non-monotone usage")
        old = self.db.execute("SELECT wall_s,bytes,requests FROM charges WHERE job_id=?", (job_id,)).fetchone()
        total = [max(a, b) for a, b in zip(old or (0, 0, 0), values)]
        self.db.execute("INSERT OR REPLACE INTO charges VALUES(?,?,?,?)", (job_id, *total))

    def finish(self, job_id, token, result_ref, *, next_job=None, settle_budget=False):
        preliminary=self.db.execute("SELECT record_json FROM jobs WHERE job_id=?",(job_id,)).fetchone()
        preliminary=json.loads(preliminary[0]) if preliminary else {}
        if preliminary.get("execution_contract"):
            from .authenticated import owned_output_bytes
            result=json.loads(owned_output_bytes(self.root,preliminary,token,result_ref))
        else:result = json.loads(verify_ref(self.root, result_ref).read_text())
        with self.transaction():
            existing = self.db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if existing and existing["result_sha"] == result_ref["sha256"]:
                if preliminary.get("sourcefree_contract"):
                    from .source_free import verify_completion
                    verify_completion(self,preliminary,token,result)
                return False
            self._lease(job_id, token)
            job = json.loads(existing["record_json"])
            for field in ("job_id", "stage", "segment_id", "code_sha", "deps_sha", "params_sha", "input_manifest_sha"):
                if result.get(field) != job[field]:
                    raise ValueError("result identity mismatch: "+field)
            if job.get("sourcefree_contract") and result.get("state")=="done":
                if next_job or result.get("next_job"):raise ValueError("source-free lane forbids automatic successors")
                from .source_free import commit,verify_completion
                verify_completion(self,job,token,result)
                if settle_budget:self.budget_for(json.loads(self.db.execute("SELECT record_json FROM segments WHERE segment_id=?",(job["segment_id"],)).fetchone()[0])["region"]).charge(token,bytes=0,requests=0)
                return commit(self,job,token,result_ref,result)
            if job.get("execution_contract"):
                if next_job:raise ValueError("authenticated lane forbids automatic successors")
                return self._finish_authenticated(job,token,result_ref,result,existing)
            if result.get("schema") != "coastal-stage-result-v1" or result.get("lease_token") != token:
                raise ValueError("result commit identity mismatch")
            state = result.get("state")
            if state not in {"done", "held", "failed_retryable", "failed_terminal", "cancelled"}:
                raise ValueError("invalid result state")
            provenance = result.get("provenance", {})
            if not isinstance(provenance.get("libs"), dict) or not provenance["libs"] or not isinstance(provenance.get("synthetic"), bool):
                raise ValueError("provenance incomplete")
            record = json.loads(self.db.execute("SELECT record_json FROM segments WHERE segment_id=?", (job["segment_id"],)).fetchone()[0])
            if provenance["synthetic"] and not record.get("synthetic"):
                raise ValueError("synthetic result cannot qualify real segment")
            holds = result.get("holds", [])
            if not isinstance(holds, list) or any(not isinstance(v, str) or not v for v in holds) or state == "done" and holds:
                raise ValueError("invalid result holds")
            if state == "held" and not holds:
                raise ValueError("held result needs typed reason")
            artifacts = result.get("artifacts", [])
            if not isinstance(artifacts, list):
                raise ValueError("invalid artifacts")
            if state == "done" and job["stage"] in {"qualify", "map", "render"} and not artifacts:
                raise ValueError("scientific stage needs verified artifacts")
            for ref in artifacts:
                verify_ref(self.root, ref)
                self.db.execute("INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?,?)", (ref["sha256"], ref["path"], ref["bytes"], ref.get("kind", ref.get("contract", "artifact")), job_id))
            terrain_only_mode = state == "done" and job["stage"] == "render" and result.get("artifact",{}).get("contract") == "coastal-terrain-only-render-v1"
            if terrain_only_mode:
                from ..render import terrain_only
                from ..handoff.common import resolve as terrain_resolve
                from datetime import datetime, timezone
                terrain_job = job
                manifest = json.loads(verify_ref(self.root,terrain_job["input_manifest"]).read_text())
                terrain_root = Path(terrain_job["params"]["terrain_root"]).resolve()
                if not self.root.is_relative_to(terrain_root):
                    raise ValueError("terrain-only input root confinement")
                checked = terrain_only.verify(terrain_root,manifest,now=datetime.now(timezone.utc))
                if result.get("terrain_only_context_digest") != terrain_only.context(checked):
                    raise ValueError("terrain-only completion context mismatch")
                rendered = json.loads(verify_ref(self.root,result["artifact"]).read_text())
                if rendered.get("schema") != terrain_only.RESULT or rendered.get("publication_prohibited") is not True or rendered.get("source_accessed") is not False or rendered.get("imagery_used") is not False:
                    raise ValueError("terrain-only completion private scope invalid")
                assets=[terrain_resolve(terrain_root,a) for a in rendered["artifacts"]]
                if not assets or any(not p.is_relative_to(self.root) for p in assets) or len({p.parent for p in assets})!=1:
                    raise ValueError("terrain-only completion artifacts outside queue root")
                validated=terrain_only.preview(terrain_root,checked,output_dir=assets[0].parent.relative_to(terrain_root),
                    now=datetime.now(timezone.utc),style=terrain_job["params"].get("terrain_style"))
                if validated!=rendered:
                    raise ValueError("terrain-only completion bytes/binding mismatch")
            if state == "done" and job["stage"] in {"qualify", "map", "render"} and not terrain_only_mode:
                from datetime import datetime, timedelta, timezone
                now = datetime.fromtimestamp(self.clock(), timezone.utc)
                contract = {"qualify": "private-mapping-input-v2", "map": "coastal-mapping-run-v1", "render": "render-handoff-v2.1"}[job["stage"]]
                outputs = [a for a in artifacts if a.get("contract") == contract]
                if not outputs:
                    raise ValueError("scientific handoff missing")
                document = json.loads(verify_ref(self.root, outputs[0]).read_text())
                if document.get("segment_id") != job["segment_id"]:
                    raise ValueError("scientific handoff geographic identity mismatch")
                geography = document.get("segment") or document.get("mapping_input", {}).get("segment")
                if geography and any(geography.get(key) != record.get(key) for key in ("schema", "crs", "bbox", "segment_id", "region")):
                    raise ValueError("scientific handoff geographic record mismatch")
                if job["stage"] == "qualify":
                    from skippercast.coastal.handoff.mapping_input import verify
                    checked = verify(self.root, document, now=now)
                elif job["stage"] == "map":
                    from skippercast.coastal.mapping import verify
                    checked = verify(self.root, document, now=now)
                else:
                    from skippercast.coastal.handoff.render import verify
                    checked = verify(self.root, document, now=now)
                if not checked["ready"] or document.get("synthetic") is not (record.get("synthetic") is True):
                    raise ValueError("scientific readiness or provenance invalid")
                facts_sha = document.get("facts_digest") or document.get("mapping_input", {}).get("facts_digest")
                if not isinstance(facts_sha, str) or len(facts_sha) != 64:
                    # Render's source lineage is nested in the accepted slices;
                    # no generic stdout/artifact hash can reset stagnation.
                    facts_sha = digest(document.get("slices", []))
                self._progress(record["region"], job["stage"], job["segment_id"], facts_sha)
            usage = result.get("usage", {})
            normalized = dict(usage)
            normalized["bytes"] = max(usage.get("bytes", 0), usage.get("bytes_in", 0))
            self.charge(job_id, normalized)
            if settle_budget:
                self.budget_for(record["region"]).charge(token, bytes=job["budget"]["bytes"], requests=job["budget"]["requests"])
            self.db.execute("UPDATE jobs SET state=?,result_sha=?,holds_json=? WHERE job_id=?", (state, result_ref["sha256"], json.dumps(holds), job_id))
            self.db.execute("DELETE FROM leases WHERE job_id=?", (job_id,))
            self.event(job_id, "finished", {"state": state, "result_sha": result_ref["sha256"]})
            successor = next_job or result.get("next_job")
            if successor and state == "done":
                if successor["stage"] != NEXT.get(job["stage"]):
                    raise ValueError("invalid successor")
                # Automatic successors inherit the submitted chain ceiling and
                # the immutable mission cap. Result fields cannot grant or change
                # attempt policy; separately submitted jobs retain their own bound.
                max_attempts = min(existing["max_attempts"],
                                   self.budget_for(record["region"]).limits.attempts_per_candidate)
                self._enqueue(job["segment_id"], successor["stage"], code_sha=successor.get("code_sha", job["code_sha"]), deps_sha=successor.get("deps_sha", job["deps_sha"]),
                              input_manifest=successor["input_manifest"], params=successor.get("params"), budget=successor.get("budget"),
                              max_attempts=max_attempts)
            if state == "failed_retryable" and existing["attempts"] >= existing["max_attempts"]:
                self.db.execute("UPDATE jobs SET state='failed_terminal' WHERE job_id=?", (job_id,))
                self.event(job_id, "attempts_exhausted", {})
            elif state == "failed_retryable":
                self.db.execute("UPDATE jobs SET state='queued',not_before=? WHERE job_id=?", (self.clock()+min(3600, 60*2**existing["attempts"]), job_id))
            return True

    def _finish_authenticated(self,job,token,result_ref,result,existing):
        from .authenticated import validate_completion, EXECUTION_CONTRACT
        if job["execution_contract"]!=EXECUTION_CONTRACT:raise ValueError("unknown execution contract")
        segment=json.loads(self.db.execute("SELECT record_json FROM segments WHERE segment_id=?",(job["segment_id"],)).fetchone()[0])
        authority=self.budget_for(segment["region"])
        validate_completion(self,job,token,result_ref,result,authority)
        if job.get('execution_profile'):
            from .authenticated import require_output_retention
            retained,slot=require_output_retention(job,token)
            retained.settle(slot,completed=True)
        # Budget is authority and settles first. Exact already-settled replay is
        # accepted only after validating the original bound completion again.
        with authority._lock():
            entry=authority._read()["reservations"][token]
            settled=entry["state"]=="settled"
        if not settled:authority.charge(token,bytes=job["budget"]["bytes"],requests=0)
        for ref in result["artifacts"]:
            self.db.execute("INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?,?)",
                (ref["sha256"],ref["path"],ref["bytes"],ref["contract"],job["job_id"]))
            self.db.execute("INSERT INTO authenticated_artifacts VALUES(?,?,?,?,?,?,?)",
                (ref["path"],ref["sha256"],ref["bytes"],ref["contract"],job["job_id"],token,result_ref["sha256"]))
        self.db.execute("UPDATE jobs SET state=?,result_sha=?,holds_json=? WHERE job_id=?",
            (result["state"],result_ref["sha256"],json.dumps(result["holds"]),job["job_id"]))
        self.db.execute("DELETE FROM leases WHERE job_id=?",(job["job_id"],))
        self.event(job["job_id"],"authenticated_finished",dict(state=result["state"],result_sha=result_ref["sha256"],token=token))
        if result["state"]=="done" and job["stage"]=="qualify":
            self._progress(segment["region"],"qualify",job["segment_id"],result["facts_digest"])
        return True

    def uncertain(self, job_id, token, reason):
        with self.transaction():
            row = self.db.execute("SELECT token FROM leases WHERE job_id=?", (job_id,)).fetchone()
            if not row or row["token"] != token:
                raise FencedLease("superseded claim")
            self.db.execute("UPDATE jobs SET state='failed_uncertain',holds_json=? WHERE job_id=?", (json.dumps([reason]), job_id))
            self.event(job_id, "failed_uncertain", {"reason": reason})

    def expire(self):
        with self.transaction():
            rows = self.db.execute("SELECT * FROM leases WHERE expires<=?", (self.clock(),)).fetchall()
            for row in rows:
                # A dead parent can leave live grandchildren: explicit recovery always.
                self.db.execute("UPDATE jobs SET state='failed_uncertain',holds_json=? WHERE job_id=?", (json.dumps(["recovery_required"]), row["job_id"]))
                self.event(row["job_id"], "lease_expired_uncertain", dict(row))
            return len(rows)

    def recover(self, job_id, receipt_ref):
        receipt = json.loads(verify_ref(self.root, receipt_ref).read_text())
        with self.transaction():
            job = self.db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            lease = self.db.execute("SELECT * FROM leases WHERE job_id=?", (job_id,)).fetchone()
            if job and not lease:
                previous = self.db.execute("SELECT detail_json FROM events WHERE job_id=? AND kind='recovered' ORDER BY seq DESC LIMIT 1", (job_id,)).fetchone()
                if previous and json.loads(previous[0]).get("receipt", {}).get("sha256") == receipt_ref["sha256"]:
                    return False
            if not job or job["state"] != "failed_uncertain" or not lease:
                raise ValueError("job does not need recovery")
            if receipt.get("schema") != "coastal-coordinator-recovery-v1" or receipt.get("job_id") != job_id or receipt.get("lease_token") != lease["token"] or receipt.get("processes_stopped") is not True or not receipt.get("attested_by"):
                raise ValueError("recovery receipt identity")
            child = json.loads(lease["child_json"]) if lease["child_json"] else None
            if child and not identity_stopped(child):
                raise ValueError("child live or unverifiable")
            if not child and not identity_stopped(json.loads(lease["controller_json"])):
                raise ValueError("launch race unresolved: controller live or unverifiable")
            intent = self.root/"var/coastal/jobs"/job_id.replace(":", "-")/lease["token"]/"intent.json"
            if intent.exists():
                runtime_ref = receipt.get("runtime_recovery")
                if not runtime_ref:
                    raise ValueError("durable runner recovery evidence required")
                runtime_receipt = json.loads(verify_ref(self.root, runtime_ref).read_text())
                record = json.loads(self.db.execute("SELECT record_json FROM segments WHERE segment_id=?", (job["segment_id"],)).fetchone()[0])
                # One authority verifies its original bound launch and every
                # owned process group, then retains/charges the entire capacity.
                # Ledger mutation precedes SQL commit; repeated identical proof
                # is safe after a controller crash rolls the SQL transition back.
                self.budget_for(record["region"]).recover_uncertain(lease["token"], intent=intent, receipt=runtime_receipt)
            state = "queued" if job["attempts"] < job["max_attempts"] else "failed_terminal"
            self.db.execute("UPDATE jobs SET state=?,holds_json='[]' WHERE job_id=?", (state, job_id))
            self.db.execute("DELETE FROM leases WHERE job_id=?", (job_id,))
            self.event(job_id, "recovered", {"receipt": receipt_ref, "state": state})
            return True

    def invalidate(self, *, stage, code_sha, deps_sha):
        """Retire old implementations and their recorded output consumers.

        Independent jobs sharing geography or source inputs are not descendants.
        Previously stale producers remain lineage roots so a late-enqueued
        consumer cannot escape invalidation on a subsequent reconciliation.
        Artifact lineage uses the recorded path and byte identity: identical
        deterministic outputs from an independent current producer survive.
        An unregistered copied artifact alias is not inferred as a dependency;
        scientific readiness still verifies its contents and implementation.
        """
        def owned_path(value):
            # Verified refs reject symlinks and "..". Normalize their accepted
            # absolute/relative/"./" spellings without reopening native bytes.
            raw = Path(value)
            if ".." in raw.parts:
                return None
            try:
                return (raw.relative_to(self.root) if raw.is_absolute() else raw).as_posix()
            except ValueError:
                return None

        def references(value):
            if isinstance(value, dict):
                path, sha, size = (value.get(key) for key in ("path", "sha256", "bytes"))
                if (isinstance(path, str) and isinstance(sha, str) and len(sha) == 64
                        and all(char in "0123456789abcdef" for char in sha)
                        and isinstance(size, int) and not isinstance(size, bool) and size >= 0):
                    canonical = owned_path(path)
                    if canonical is not None:
                        yield (canonical, sha, size)
                for child in value.values():
                    yield from references(child)
            elif isinstance(value, list):
                for child in value:
                    yield from references(child)

        with self.transaction():
            rows = self.db.execute(
                "SELECT * FROM jobs WHERE state IN ('done','queued','held','failed_retryable','stale')"
            ).fetchall()
            records = {row["job_id"]: json.loads(row["record_json"]) for row in rows}
            pending = [row for row in rows if row["stage"] == stage
                       and (records[row["job_id"]]["code_sha"], records[row["job_id"]]["deps_sha"])
                       != (code_sha, deps_sha)]
            consumers = {}
            for row in rows:
                job = records[row["job_id"]]
                consumers[row["job_id"]] = set(references(
                    {"input_manifest": job.get("input_manifest"), "params": job.get("params")}
                ))
            visited, changed = set(), 0
            while pending:
                row = pending.pop()
                job_id = row["job_id"]
                if job_id in visited:
                    continue
                visited.add(job_id)
                if row["state"] != "stale":
                    self.db.execute("UPDATE jobs SET state='stale' WHERE job_id=?", (job_id,))
                    self.event(job_id, "implementation_stale",
                               {"code_sha": code_sha, "deps_sha": deps_sha,
                                "reason": "implementation_or_recorded_dependency"})
                    changed += 1
                outputs = {(owned_path(a["path"]), a["sha256"], a["bytes"]) for a in self.db.execute(
                    "SELECT path,sha256,bytes FROM artifacts WHERE produced_by_job=?", (job_id,)
                )}
                # Historical result references store only their exact byte hash.
                # Do not treat the producer's original inputs as its outputs.
                result_sha = row["result_sha"]
                for candidate in rows:
                    candidate_id = candidate["job_id"]
                    if candidate_id in visited:
                        continue
                    refs = consumers[candidate_id]
                    if outputs.intersection(refs) or result_sha and any(ref[1] == result_sha for ref in refs):
                        pending.append(candidate)
            return changed

    def status(self):
        return {"schema": "coastal-coordinator-status-v1", "jobs": [dict(r) for r in self.db.execute("SELECT job_id,segment_id,stage,state,attempts,max_attempts,holds_json FROM jobs ORDER BY created,job_id")],
                "events": self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                "charges": [dict(r) for r in self.db.execute("SELECT * FROM charges")],
                "progress": [dict(r) for r in self.db.execute("SELECT * FROM region_progress")],
                "last_tick_epoch": self.db.execute("SELECT MAX(utc) FROM events WHERE kind='tick'").fetchone()[0]}
