"""Fault-injection harness for the coastal coordinator operation tests (T12).

The tests drive the real ``Store``, ``Coordinator``, ``Budget`` ledger and the
detached ``run_bounded`` supervisor. Only the stage executable is replaced: a
stdlib-only worker script whose behaviour per attempt comes from the job
parameters (``modes``), so a test can crash, hang, orphan a grandchild or
misreport usage on purpose.

The supervisor starts through ``_runner_bootstrap.py``, which refuses a package
tree containing compiled bytecode. A test process has already imported (and
cached) ``skippercast``, so every dispatching controller runs as a separate
``python -B`` process from a clean, byte-identical export of ``src/skippercast``
-- the source-only deployment shape the supervisor requires. That process is
also what a test kills to simulate a controller crash.

Every store, ledger and marker lives under the test's own ``tmp_path``; nothing
is shared between tests except the read-only package export.

The queue's code/dependency identity (``implementation_hashes``) is computed by
a child process started exactly like a controller, never in the pytest process:
that function hashes whatever ``sys.path`` and the installed distributions
expose, and other tests on the same xdist worker legitimately change both (some
research scripts prepend host-local dependency directories to ``sys.path`` on
import). An in-process identity then differs from the controller's, every job
is invalidated as stale, and every controller run returns ``idle``.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

SOURCE = Path(__file__).resolve().parents[1] / "src" / "skippercast"

POLICY = {
    "schema": "coastal-coordinator-policy-v1",
    "segment": {"crs": "EPSG:3310", "size_m": 5000, "planning_cell_m": 250},
    "watermarks": {"high": 3, "low": 1, "held_cap": 5},
    "max_attempts": 2,
    "lease_s": 2,
    "worker_network": False,
    "slots": {"discover": 1, "acquire": 1, "qualify": 1, "map": 1, "render": 1},
    "budgets": {"wall_s": 3600, "bytes": 250, "requests": 0},
    "reprocess_stale": False,
    "publication": False,
    "stagnation_s": 10**7,
    "storage": {"minimum_free_bytes": 1, "job_output_bytes": 1048576},
}

REGION = "t12-operations"
JOB_BUDGET = {"wall_s": 30, "memory_bytes": 1073741824, "bytes": 100, "requests": 0}

WORKER = r'''
"""Stdlib-only fault-injection stage worker (see tests/_coastal_operations.py)."""
import json, os, signal, subprocess, sys, time
from pathlib import Path

job = json.loads(Path(sys.argv[1]).read_text())
out = Path(sys.argv[2])
params = job["params"]
markers = Path(params["markers"])
markers.mkdir(parents=True, exist_ok=True)
name = params["name"]
attempt = len(list(markers.glob(name + ".*.launch"))) + 1
(markers / f"{name}.{attempt}.launch").write_text(json.dumps(
    {"pid": os.getpid(), "token": job["lease_token"]}))
modes = params["modes"]
mode = modes[min(attempt, len(modes)) - 1]
CODES = {"done": 0, "held": 3, "failed_retryable": 4}


def finish(state, holds=(), bytes_in=0):
    result = {"schema": "coastal-stage-result-v1", "stage": job["stage"], "job_id": job["job_id"],
              "segment_id": job["segment"]["segment_id"], "lease_token": job["lease_token"],
              "code_sha": job["code_sha"], "deps_sha": job["deps_sha"],
              "input_manifest_sha": job["input_manifest_sha"], "params_sha": job["params_sha"],
              "state": state, "holds": list(holds), "artifacts": [],
              "usage": {"requests": 0, "bytes_in": bytes_in},
              "provenance": {"libs": {"python": sys.version.split()[0]}, "synthetic": False}}
    out.mkdir(parents=True, exist_ok=True)
    temporary = out / ".result.json.tmp"
    temporary.write_text(json.dumps(result))
    os.replace(temporary, out / "result.json")
    raise SystemExit(CODES[state])


if mode == "done":
    finish("done")
if mode == "underreport":
    finish("done", bytes_in=0)
if mode == "overreport":
    finish("done", bytes_in=10**9)
if mode == "held":
    finish("held", ["fault_injected_hold"])
if mode == "retryable":
    finish("failed_retryable", ["fault_injected_transient"])
if mode == "crash":
    os._exit(9)
if mode == "block":
    release = markers / (name + ".release")
    end = time.monotonic() + 60
    while not release.exists() and time.monotonic() < end:
        time.sleep(0.02)
    finish("done")
if mode == "orphan":
    child = subprocess.Popen([sys.executable, params["sleeper"]], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (markers / f"{name}.{attempt}.orphan").write_text(json.dumps({"pid": child.pid}))
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(0.05)
raise SystemExit("unknown fault mode " + mode)
'''

SLEEPER = "import time\ntime.sleep(120)\n"

IDENTITY = r'''
"""Prints the (code, deps) identity exactly as a controller process computes it."""
import json, sys
from pathlib import Path

import skippercast
if not Path(skippercast.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve()):
    raise SystemExit("identity probe did not import the clean package export")
import skippercast.coastal.coordinator.loop as loop

print(json.dumps(loop.implementation_hashes(sys.argv[2])), flush=True)
'''

CONTROLLER = r'''
"""Out-of-process controller (clean package export) that a test may SIGKILL."""
import json, sys, time
from pathlib import Path

config = json.loads(Path(sys.argv[1]).read_text())
import skippercast
if not Path(skippercast.__file__).resolve().is_relative_to(Path(config["export"]).resolve()):
    raise SystemExit("controller did not import the clean package export")
import skippercast.coastal.coordinator.loop as loop
from skippercast.coastal.coordinator.store import Store

worker = config["worker"]
if worker:  # otherwise the real fixed stage CLI runs
    loop.argv_for = lambda job, job_path, out: [sys.executable, worker, str(job_path), str(out)]
offset = config["offset"]
kwargs = {} if offset is None else {"clock": lambda: time.time() + offset}
store = Store(config["store"], root=config["root"], policy=config["policy"], **kwargs)
coordinator = loop.Coordinator(store, **kwargs)
now = time.time() + (offset or 0)
print(json.dumps(coordinator.run(until=now + config["seconds"], max_jobs=config["max_jobs"])), flush=True)
'''


def policy(**changes):
    value = copy.deepcopy(POLICY)
    for key, update in changes.items():
        if isinstance(update, dict):
            value[key].update(update)
        else:
            value[key] = update
    return value


def export_package(destination):
    """Byte-identical source-only copy of src/skippercast (no bytecode, no links)."""
    target = Path(destination) / "skippercast"
    shutil.copytree(SOURCE, target, symlinks=False,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    return Path(destination)


class Harness:
    """One isolated queue root, store, ledger and fault-injection worker.

    ``offset`` (seconds, or None for the real clocks) injects a monotone fault
    clock shared by the in-process store and every controller process.
    ``real_stages`` dispatches the repository's fixed stage CLI instead of the
    fault-injection worker.
    """

    def __init__(self, tmp_path, export, *, policy_value=None, offset=None, real_stages=False):
        from skippercast.coastal.coordinator.store import Store
        self.real_stages = real_stages
        self.base = Path(tmp_path)
        self.export = Path(export)
        self.root = self.base / "queue"
        self.root.mkdir()
        self.markers = self.base / "markers"
        self.markers.mkdir()
        self.worker = self.base / "worker.py"
        self.worker.write_text(WORKER)
        self.sleeper = self.base / "sleeper.py"
        self.sleeper.write_text(SLEEPER)
        self.controller = self.base / "controller.py"
        self.controller.write_text(CONTROLLER)
        self.policy = policy_value or policy()
        self.store_path = self.root / "var/coastal/coordinator.sqlite"
        self.offset = offset
        self.Store = Store
        self.store = self.open()
        self.identity = self.base / "identity.py"
        self.identity.write_text(IDENTITY)
        self.code, self.deps = self._implementation_identity()
        self._segments = 0
        self._runs = 0

    def _implementation_identity(self):
        done = subprocess.run([sys.executable, "-B", str(self.identity), str(self.export), str(self.root)],
                              env=self.environment(), capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr[-4000:]
        code, deps = json.loads(done.stdout.strip().splitlines()[-1])
        return code, deps

    def open(self):
        kwargs = {} if self.offset is None else {"clock": lambda: time.time() + self.offset}
        return self.Store(self.store_path, root=self.root, policy=self.policy, **kwargs)

    def job(self, name, *modes, budget=None):
        from skippercast.coastal.coordinator.segments import segment
        record = segment(5000 * self._segments, 0, region=REGION)
        self._segments += 1
        self.store.add_segment(record)
        job_id = self.store.enqueue(
            record["segment_id"], "discover", code_sha=self.code, deps_sha=self.deps,
            params={"name": name, "modes": list(modes), "markers": str(self.markers),
                    "sleeper": str(self.sleeper)},
            budget=dict(JOB_BUDGET, **(budget or {})), max_attempts=self.policy["max_attempts"])
        time.sleep(0.002)  # strictly ordered `created` so claim order is deterministic
        return job_id

    def _config(self, seconds, max_jobs):
        self._runs += 1
        path = self.base / f"controller-{self._runs}.json"
        path.write_text(json.dumps({"export": str(self.export),
                                    "worker": None if self.real_stages else str(self.worker),
                                    "store": str(self.store_path), "root": str(self.root),
                                    "policy": self.policy, "offset": self.offset,
                                    "seconds": seconds, "max_jobs": max_jobs}))
        return [sys.executable, "-B", str(self.controller), str(path)]

    def environment(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self.export)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    def start(self, *, seconds=60, max_jobs=10):
        """Launch a controller process without waiting (for kill tests)."""
        return subprocess.Popen(self._config(seconds, max_jobs), env=self.environment(),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def run(self, *, seconds=60, max_jobs=10):
        done = subprocess.run(self._config(seconds, max_jobs), env=self.environment(),
                              capture_output=True, text=True, timeout=seconds + 30)
        assert done.returncode == 0, done.stderr[-4000:]
        return json.loads(done.stdout.strip().splitlines()[-1])

    def launches(self, name=None):
        return sorted(p.name for p in self.markers.glob((name or "*") + ".*.launch"))

    def jobs(self):
        rows = self.store.db.execute(
            "SELECT job_id,state,attempts,holds_json,result_sha FROM jobs").fetchall()
        return {row["job_id"]: dict(row, holds=json.loads(row["holds_json"])) for row in rows}

    def ledger(self):
        paths = list(self.store_path.parent.glob("budget-*.json"))
        assert len(paths) == 1, paths
        return json.loads(paths[0].read_text())

    def effective_bytes(self):
        state = self.ledger()
        total = state["charged"]["bytes"]
        for entry in state["reservations"].values():
            if entry["state"] != "settled":
                total += entry["reserved"]["bytes"] - entry["charged"]["bytes"]
        return total

    def events(self, kind):
        return [(row["job_id"], json.loads(row["detail_json"])) for row in self.store.db.execute(
            "SELECT job_id,detail_json FROM events WHERE kind=? ORDER BY seq", (kind,))]

    def lease(self, job_id):
        return self.store.db.execute("SELECT * FROM leases WHERE job_id=?", (job_id,)).fetchone()

    def job_dir(self, job_id, token=None):
        base = self.root / "var/coastal/jobs" / job_id.replace(":", "-")
        return base if token is None else base / token

    def intent(self, job_id, token):
        return json.loads((self.job_dir(job_id, token) / "intent.json").read_text())

    def recovery_receipts(self, job_id):
        """Write the operator's two recovery receipts for one stopped execution."""
        from skippercast.coastal.coordinator.loop import byte_ref
        from skippercast.coastal.receipts import digest
        token = self.lease(job_id)["token"]
        receipts = self.root / "var/coastal/recovery" / token
        receipts.mkdir(parents=True, exist_ok=True)
        runtime = receipts / "runtime.json"
        runtime.write_text(json.dumps({"schema": "coastal-recovery-v1",
                                       "checkpoint_sha256": digest(self.intent(job_id, token)),
                                       "processes_stopped": True, "attested_by": "t12-operations-test"}))
        coordinator = receipts / "coordinator.json"
        coordinator.write_text(json.dumps({
            "schema": "coastal-coordinator-recovery-v1", "job_id": job_id, "lease_token": token,
            "processes_stopped": True, "attested_by": "t12-operations-test",
            "runtime_recovery": byte_ref(self.root, runtime, kind="recovery", contract="coastal-recovery-v1")}))
        return byte_ref(self.root, coordinator, kind="recovery", contract="coastal-coordinator-recovery-v1")

    def close(self):
        self.store.close()


def wait_for(predicate, *, timeout=20, message="condition"):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("timed out waiting for " + message)


def alive(pid):
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return False
    return state not in {"Z", "X"}
