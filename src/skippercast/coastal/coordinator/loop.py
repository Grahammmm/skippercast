"""Bounded host-side ticks. The durable runner owns subprocess lifetimes."""
from contextlib import contextmanager
import fcntl
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import threading
import time
import shutil

from .stages import ORDER, argv_for, digest, verify_ref
from ..client_policy import heartbeat_detail
from .store import FencedLease, Store, process_identity


def implementation_hashes(root):
    # Artifact roots may be outside a checkout. Identity comes from the code
    # actually imported by this Python environment, including installed wheels.
    evidence = []
    for name in ("skippercast.coastal", "skippercast.seafloor"):
        package = importlib.import_module(name)
        for directory in package.__path__:
            directory = Path(directory)
            evidence.extend((name+":"+path.relative_to(directory).as_posix(),
                             hashlib.sha256(path.read_bytes()).hexdigest())
                            for path in directory.rglob("*")
                            if path.is_file() and path.suffix in {".py", ".c", ".h", ".json", ".yaml", ".yml"}
                            and "__pycache__" not in path.parts)
    if not evidence:
        raise ValueError("current executable package identity unavailable")
    versions = {}
    for name in ("rasterio", "pyproj", "shapely", "h5py", "numpy", "jsonschema"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "unavailable"
    return digest(sorted(evidence)), digest({"libs": versions})


def byte_ref(root, path, *, kind="result", contract="coastal-stage-result-v1"):
    path = Path(path)
    ref = {"path": path.relative_to(Path(root)).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
           "bytes": path.stat().st_size, "kind": kind, "contract": contract}
    verify_ref(root, ref)
    return ref


def atomic_json(path, value):
    # Use unique temporary files: a crash residue must not fence a later attempt.
    from ..handoff.common import write
    write(path, value)



def check_storage(job_dir, root, storage):
    """Observe aggregate bytes and free reserve; per-file limit is separately hard.

    The parent polls while workers run and checks immediately before launch and
    commit. This is not a filesystem quota: aggregate overshoot between polls
    remains possible, and the durable supervisor independently enforces only
    wall time, cancellation and per-file limits.
    """
    size = 0
    for directory, dirs, files in os.walk(job_dir, followlinks=False):
        for name in [*dirs, *files]:
            path = Path(directory)/name
            if path.is_symlink():
                raise ValueError("job output symlink")
            if path.is_file():
                size += path.stat().st_size
    free = shutil.disk_usage(root).free
    if size > storage["job_output_bytes"] or free < storage["minimum_free_bytes"]:
        raise ValueError("aggregate_storage_bound")
    return {"observed_job_bytes": size, "free_bytes": free}


@contextmanager
def controller_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another controller owns this store") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class Coordinator:
    def __init__(self, store, *, dispatcher=None, clock=time.time):
        self.store, self.clock = store, clock
        self.dispatcher = dispatcher or self._dispatch

    def _dispatch(self, job, job_path, out, identity_callback, deadline):
        budget = self.store.budget_for(job["region"])
        authenticated=bool(job.get("execution_contract"))
        if authenticated:
            from .authenticated import argv_for as authenticated_argv
        command=authenticated_argv(job,job_path,out) if authenticated else argv_for(job,job_path,out)
        managed_kwargs={}
        if job.get('managed_output_grant') is not None:
            grant=job['managed_output_grant']
            managed_kwargs=dict(managed_output=dict(grant=grant,grant_digest=digest(grant),
                role='native' if authenticated else 'mapping',max_bytes=131072 if authenticated else 65536),
                output_limit_bytes=16384)
        return budget.execute(job["lease_token"], command, intent=job_path.parent/"intent.json",
                           completed_exit_codes=(0, 3, 4, 5, 6, 7),
                           deadline_utc=deadline, rlimits={"memory_bytes": job["budget"]["memory_bytes"], "file_bytes": max(job["budget"]["bytes"],4194304) if authenticated else self.store.policy["storage"]["job_output_bytes"]},
                           cancel=self._cancel,
                           cwd=Path(__file__).parent if authenticated else self.store.root, env={"COASTAL_AUTH_REQUEST_SHA256":hashlib.sha256(job_path.read_bytes()).hexdigest(),
                                "COASTAL_DEADLINE_EPOCH": str(deadline), "OPENBLAS_NUM_THREADS": "1",
                                "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "GDAL_NUM_THREADS": "1"},
                           stdout_path=job_path.parent/"stdout.log", stderr_path=job_path.parent/"stderr.log",
                           scratch=job_path.parent/"runner", identity_callback=identity_callback,**managed_kwargs)

    def tick(self, *, until=None, reconcile=True, job_id=None):
        now = self.clock()
        if until is not None and until <= now+1:
            return {"state": "deadline"}
        if reconcile:
            code, deps = implementation_hashes(self.store.root)
            for stage in ORDER:
                self.store.invalidate(stage=stage, code_sha=code, deps_sha=deps)
        self.store.expire()
        with self.store.transaction():
            self.store.event(None, "tick", heartbeat_detail(
                self.store.root, self.store.path,
                (code, deps) if reconcile else implementation_hashes(self.store.root)))
        job = self.store.claim(process_identity(), lease_s=self.store.policy["lease_s"],
                               current_identity=(code, deps) if reconcile else None, job_id=job_id)
        if not job:
            return {"state": "idle"}
        deadline = min(now+job["budget"]["wall_s"], until-1) if until else now+job["budget"]["wall_s"]
        if job.get("execution_contract"):
            deadline=min(deadline,job["deadline_utc"])
            # Preserve the authoritative persisted phase deadline in the request.
        else:job["deadline_utc"] = deadline
        job_dir = self.store.root/"var/coastal/jobs"/job["job_id"].replace(":", "-")/job["lease_token"]
        job_path, out = job_dir/"job.json", job_dir/"output"
        storage_policy=dict(self.store.policy["storage"])
        if job.get("execution_contract"):storage_policy["job_output_bytes"]=min(storage_policy["job_output_bytes"],4194304)
        if job.get('managed_output_grant') is not None:
            self.store.write_artifact(job_path,job,
                role='native' if job.get('execution_contract') else 'mapping',
                max_bytes=131072 if job.get('execution_contract') else 65536)
        else:atomic_json(job_path, job)
        stopped = threading.Event()
        self._cancel = threading.Event()
        lease_error = []

        def heartbeat():
            store = Store(self.store.path, root=self.store.root, clock=self.clock,policy=self.store.policy)
            try:
                while not stopped.wait(min(5, self.store.policy["lease_s"]/3)):
                    try:
                        check_storage(job_dir, self.store.root, storage_policy)
                        store.heartbeat(job["job_id"], job["lease_token"], lease_s=self.store.policy["lease_s"])
                    except Exception as exc:
                        lease_error.append(str(exc))
                        self._cancel.set()
                        return
            finally:
                store.close()

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            check_storage(job_dir, self.store.root, storage_policy)
            outcome = self.dispatcher(job, job_path, out,
                                      lambda child: self.store.running(job["job_id"], job["lease_token"], child), deadline)
            storage = check_storage(job_dir, self.store.root, storage_policy)
            result_path = out/"result.json"
            rc = getattr(outcome, "rc", None)
            if rc not in {0, 3, 4, 5, 6, 7} or lease_error or not result_path.exists():
                raise ValueError("missing trustworthy runner completion")
            from .authenticated import captured_result_ref,owned_output_bytes
            if job.get("execution_contract"):
                result_ref=captured_result_ref(self.store.budget_for(job["region"]),job,job["lease_token"])
                result=json.loads(owned_output_bytes(self.store.root,job,job["lease_token"],result_ref))
            else:
                result_ref=byte_ref(self.store.root,result_path)
                result=json.loads(result_path.read_text())
            expected_rc = {"done": 0, "held": 3, "failed_retryable": 4, "failed_terminal": 5, "cancelled": 7}
            if rc != expected_rc.get(result.get("state")):
                raise ValueError("exit status disagrees with commit")
            self.store.finish(job["job_id"], job["lease_token"], result_ref, settle_budget=self.dispatcher == self._dispatch)
            return {"state": result["state"], "job_id": job["job_id"], "result": result_ref, "storage": storage}
        except BaseException as exc:
            if self.dispatcher == self._dispatch:
                try:
                    self.store.budget_for(job["region"]).fail_uncertain(job["lease_token"], reason=type(exc).__name__+":"+str(exc))
                except ValueError:
                    pass
            self.store.uncertain(job["job_id"], job["lease_token"], type(exc).__name__+":"+str(exc))
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            return {"state": "failed_uncertain", "job_id": job["job_id"], "reason": str(exc)}
        finally:
            stopped.set()
            thread.join(timeout=6)

    def run(self, *, until, max_jobs=50):
        if until <= self.clock() or max_jobs < 1:
            raise ValueError("bounded future deadline and job count required")
        results = []
        with controller_lock(self.store.path.with_suffix(".lock")):
            for _ in range(max_jobs):
                outcome = self.tick(until=until)
                results.append(outcome)
                if outcome["state"] in {"idle", "deadline", "failed_uncertain"}:
                    break
        return results
