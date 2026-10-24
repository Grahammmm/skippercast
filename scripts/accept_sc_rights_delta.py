#!/usr/bin/env python3
"""Acceptance runner for SC-RIGHTS-DELTA (docs/engineering/sc_rights_delta.md).

    python3 scripts/accept_sc_rights_delta.py --suite focused|contract|negative --output <new-run-dir>

Runs the plain test functions in tests/unit/test_sc_rights_delta.py in this process with a
stdlib harness (no skip path), after installing offline sentinels and pinning the import
path to this staged repository. Every run writes a write-once receipt directory; the exit
status is 0 only when every selected test passes, no sentinel fired unexpectedly and, for
the negative suite, every isolated mutation control is detected by its exact regression.
A green run is REVIEW REQUIRED, not CI, source qualification or semantic acceptance.

Sentinels are regression guards for this trusted test code, not a hostile-code sandbox.
"""
import sys

sys.dont_write_bytecode = True

import os  # noqa: E402

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import argparse  # noqa: E402
import contextlib  # noqa: E402
import hashlib  # noqa: E402
import importlib  # noqa: E402
import importlib.util  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import platform  # noqa: E402
import stat  # noqa: E402
import sysconfig  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
TEST_FILE = REPO / "tests" / "unit" / "test_sc_rights_delta.py"
TARGET = REPO / "scripts" / "coast_diagnostics" / "rights_delta.py"
RIGHTS = SRC / "skippercast" / "seafloor" / "rights.py"
FIXTURES = REPO / "tests" / "fixtures" / "sc_rights_delta"
RUNNER = Path(__file__).resolve()
PIN_BASE = "59fca09b2cc7f5c81a4796902504e263d7f06960"
PIN_RIGHTS_SHA256 = "7411657fefaea64f73bbd566ba1d37eb0f4d787b83a2afcec117d882e579ee0d"
SUITES = {"focused": "test_a1_", "contract": "test_a2_", "negative": "test_a3_"}
# Read access inside the repository is limited to the code and tests this card owns or
# imports. Deployment policy, catalog, regions and every other tree are denied.
REPO_READ_ROOTS = (SRC / "skippercast", REPO / "scripts", REPO / "tests")
DENIED_PROBES = (REPO / "deployments" / "production.json", REPO / "catalog" / "surveys.json")
MODEL_MODULES = {"openai", "anthropic", "ollama", "requests", "httpx", "urllib3", "boto3",
                 "botocore", "litellm", "transformers", "google", "aiohttp"}
NETWORK_EVENTS = {"socket.__new__", "socket.connect", "socket.bind", "socket.getaddrinfo",
                  "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo",
                  "socket.sendto", "socket.sendmsg", "urllib.Request", "http.client.connect",
                  "ftplib.connect", "smtplib.connect", "webbrowser.open"}
PROCESS_EVENTS = {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn",
                  "os.fork", "os.forkpty", "os.startfile", "pty.spawn", "ctypes.dlopen"}
DELETE_EVENTS = {"os.remove", "os.rmdir", "os.rename", "os.replace", "shutil.rmtree",
                 "os.truncate", "os.chown", "os.chflags", "os.lchflags"}
WRITE_EVENTS = {"os.mkdir": 0, "os.symlink": 1, "os.link": 1, "os.chmod": 0, "os.utime": 0}
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


class Sentinel(PermissionError):
    """Raised by an offline sentinel before the guarded operation happens."""


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_git_head():
    """HEAD from .git files only (no git subprocess); a detached or branch HEAD."""
    git = REPO / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
    except OSError as error:
        return {"error": type(error).__name__}
    if not head.startswith("ref: "):
        return {"head": head, "ref": None}
    ref = head[5:]
    loose = git / ref
    if loose.is_file():
        return {"head": loose.read_text(encoding="utf-8").strip(), "ref": ref}
    packed = git / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            parts = line.split(" ")
            if len(parts) == 2 and parts[1] == ref:
                return {"head": parts[0], "ref": ref}
    return {"head": None, "ref": ref}


def check_no_symlink_ancestry(path):
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            return
        if stat.S_ISLNK(mode):
            raise SystemExit(f"refused: symlink in run-root ancestry: {current}")


def make_run_root(raw):
    # A '..' component would let lexical normalization cancel a preceding symlink before
    # the ancestry check, so such run roots are refused outright.
    if os.pardir in os.fsdecode(raw).split(os.sep):
        raise SystemExit(f"refused: run root has a '..' component: {raw}")
    path = Path(os.path.abspath(raw))
    check_no_symlink_ancestry(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir()
    except FileExistsError:
        raise SystemExit(f"refused: run root already exists (write-once): {path}")
    (path / "tmp").mkdir()
    return path


def _under(path, roots):
    return any(path == root or root in path.parents for root in roots)


class Guard:
    def __init__(self, run_root):
        self.run_root = run_root
        stdlib = {Path(sysconfig.get_paths()[k]).resolve() for k in ("stdlib", "platstdlib")}
        self.read_roots = tuple(r.resolve() for r in REPO_READ_ROOTS) + (run_root,) + tuple(stdlib)
        self.write_roots = (run_root,)
        self.events = []      # unexpected sentinel denials (any => run fails)
        self.expected = []    # denials provoked deliberately by a recorded probe
        self.probe = None
        self.active = False
        self._inside = False

    def deny(self, event, detail):
        record = {"event": event, "detail": detail, "probe": self.probe}
        (self.expected if self.probe else self.events).append(record)
        raise Sentinel(f"SENTINEL denied {event}: {detail}")

    def hook(self, event, args):
        if not self.active or self._inside:
            return
        self._inside = True
        try:
            self._check(event, args)
        finally:
            self._inside = False

    def _path(self, value):
        if isinstance(value, int) or value is None:
            return None
        return Path(os.path.realpath(os.fsdecode(value)))

    def _check(self, event, args):
        if event in NETWORK_EVENTS:
            self.deny(event, "network")
        if event in PROCESS_EVENTS:
            self.deny(event, "process")
        if event in DELETE_EVENTS:
            self.deny(event, "delete/rename/ownership")
        if event == "import":
            top = str(args[0]).split(".")[0]
            if top in MODEL_MODULES:
                self.deny(event, top)
            return
        if event in WRITE_EVENTS:
            target = self._path(args[WRITE_EVENTS[event]])
            if target is not None and not _under(target, self.write_roots):
                self.deny(event, str(target))
            return
        if event == "open":
            target = self._path(args[0])
            if target is None:
                return
            mode, flags = args[1], args[2]
            writing = bool((flags or 0) & WRITE_FLAGS) or (isinstance(mode, str) and any(c in mode for c in "wax+"))
            roots = self.write_roots if writing else self.read_roots
            if not _under(target, roots):
                self.deny("open-write" if writing else "open-read", str(target))


def _raiser(name, guard):
    def blocked(*args, **kwargs):
        guard.deny(name, "patched callable")
    blocked.__name__ = "sentinel_" + name.replace(".", "_")
    return blocked


def install_sentinels(guard):
    import http.client
    import socket
    import subprocess
    import urllib.request
    patched = {}
    for owner, names in ((socket, ("socket", "create_connection", "getaddrinfo", "gethostbyname",
                                   "gethostbyaddr", "socketpair", "fromfd")),
                         (subprocess, ("Popen", "run", "call", "check_call", "check_output",
                                       "getoutput", "getstatusoutput")),
                         (os, ("system", "popen", "fork", "execv", "execve", "execvp", "posix_spawn",
                               "posix_spawnp")),
                         (urllib.request, ("urlopen", "urlretrieve"))):
        for name in names:
            if hasattr(owner, name):
                full = f"{owner.__name__}.{name}"
                setattr(owner, name, _raiser(full, guard))
                patched[full] = getattr(owner, name).__name__
    http.client.HTTPConnection.connect = _raiser("http.client.HTTPConnection.connect", guard)
    patched["http.client.HTTPConnection.connect"] = "sentinel"
    sys.addaudithook(guard.hook)
    guard.active = True
    return patched


def pin_import_path():
    keep = {sysconfig.get_paths()[k] for k in ("stdlib", "platstdlib")}
    dynload = [p for p in sys.path if p.endswith("lib-dynload") or p.endswith(".zip")]
    sys.path[:] = [str(REPO), str(SRC)] + [p for p in sys.path if p in keep or p in dynload]
    return list(sys.path)


def classify_module(module, stdlib_roots):
    origin = getattr(module, "__file__", None)
    if origin is None:
        locations = list(getattr(module, "__path__", []) or [])
        if not locations:
            return "builtin", None
        origin = locations[0]
    path = Path(origin).resolve()
    if _under(path, (REPO.resolve(),)):
        return "repository", str(path.relative_to(REPO.resolve()))
    if _under(path, stdlib_roots):
        return "stdlib", str(path)
    return "OUTSIDE", str(path)


def run_test(function):
    out, err = io.StringIO(), io.StringIO()
    started = time.monotonic()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            function()
    except AssertionError as error:
        outcome, detail = "failed", "".join(traceback.format_exception(error))[-4000:]
    except Exception as error:  # noqa: BLE001 - recorded, never swallowed as a pass
        outcome, detail = "error", "".join(traceback.format_exception(error))[-4000:]
    else:
        outcome, detail = "passed", None
    return {"name": function.__name__, "outcome": outcome, "detail": detail,
            "stdout": out.getvalue(), "stderr": err.getvalue(),
            "seconds": round(time.monotonic() - started, 4)}


def mutation_controls(rd, tests):
    """In-memory callable doubles; each must make its exact regression fail, then restore."""
    import re

    def normalizing_same_value(a, b):
        def norm(value):
            return re.sub(r"\s+", " ", value).strip().casefold() if isinstance(value, str) else value
        return type(a) is type(b) and norm(a) == norm(b)

    controls = [
        ("M1-normalize-credit-notice", "_same_value", normalizing_same_value,
         "test_a3_whitespace_or_case_only_credit_change_is_reported", "test_a1_unchanged_rows_give_no_changes"),
        ("M2-disable-producer-binding", "_binding_mismatches", lambda *a, **k: [],
         "test_a3_mismatched_producer_with_identical_rows_is_unverified", "test_a1_unchanged_rows_give_no_changes"),
        ("M3-disable-unknown-field-gate", "_unknown_keys", lambda *a, **k: [],
         "test_a3_unknown_authority_bearing_fields_are_invalid", "test_a1_unchanged_rows_give_no_changes"),
        ("M4-disable-parent-reference-refusal", "_has_parent_reference", lambda *a, **k: False,
         "test_a3_cancelled_symlink_component_paths_are_refused", "test_a3_symlink_fifo_and_special_inputs_are_refused"),
    ]
    results = []
    for name, attribute, double, regression, unaffected in controls:
        original = getattr(rd, attribute)
        setattr(rd, attribute, double)
        try:
            broken = run_test(tests[regression])
            bystander = run_test(tests[unaffected])
        finally:
            setattr(rd, attribute, original)
        restored = run_test(tests[regression])
        ok = (broken["outcome"] == "failed" and bystander["outcome"] == "passed"
              and restored["outcome"] == "passed" and getattr(rd, attribute) is original)
        results.append({"control": name, "patched": f"rights_delta.{attribute}", "regression": regression,
                        "broken_outcome": broken["outcome"], "broken_detail": broken["detail"],
                        "unaffected_test": unaffected, "unaffected_outcome_under_mutation": bystander["outcome"],
                        "restored_outcome": restored["outcome"], "detected": ok})
    return results


def denial_probes(guard):
    """Prove deployment-policy/catalog opens are refused BEFORE the open happens (local files only)."""
    results = []
    for path in DENIED_PROBES:
        guard.probe = f"open {path.relative_to(REPO)}"
        try:
            with open(path, "rb"):
                outcome = "OPENED"
        except Sentinel:
            outcome = "denied-by-sentinel"
        except OSError as error:
            outcome = f"os-error-{type(error).__name__}"
        finally:
            guard.probe = None
        results.append({"path": str(path.relative_to(REPO)), "outcome": outcome})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", choices=sorted(SUITES), required=True)
    parser.add_argument("--output", required=True, help="new, write-once run directory")
    args = parser.parse_args()
    started = time.time()
    run_root = make_run_root(args.output)
    console = []

    def say(line):
        console.append(line)
        print(line)

    receipt = {"schema": "sc-rights-delta-acceptance-v1", "suite": args.suite,
               "argv": [sys.executable] + sys.argv, "cwd": os.getcwd(),
               "python": {"executable": sys.executable, "version": sys.version,
                          "implementation": platform.python_implementation()},
               "repository": str(REPO), "git": read_git_head(), "pinned_base": PIN_BASE,
               "status": "REVIEW REQUIRED", "semantic_acceptance": False,
               "started_unix": round(started, 3)}
    owned = [RUNNER, TARGET, TEST_FILE, RIGHTS] + sorted(p for p in FIXTURES.iterdir() if p.is_file())
    receipt["input_hashes_before"] = {str(p.relative_to(REPO)): sha256_file(p) for p in owned if p.exists()}
    receipt["missing_inputs"] = [str(p.relative_to(REPO)) for p in owned if not p.exists()]

    guard = Guard(run_root.resolve())
    receipt["sentinels"] = install_sentinels(guard)
    tempfile.tempdir = str(run_root / "tmp")
    receipt["sys_path"] = pin_import_path()
    receipt["read_roots"] = [str(r) for r in guard.read_roots]

    failures = []
    before_modules = set(sys.modules)
    tests = {}
    try:
        spec = importlib.util.spec_from_file_location("sc_rights_delta_acceptance_tests", TEST_FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        rd = importlib.import_module("scripts.coast_diagnostics.rights_delta")
        rights = importlib.import_module("skippercast.seafloor.rights")
        tests = {n: f for n, f in vars(module).items() if n.startswith("test_") and callable(f)}
        receipt["module_files"] = {"rights_delta": str(Path(rd.__file__).resolve()),
                                   "rights": str(Path(rights.__file__).resolve())}
        if Path(rd.__file__).resolve() != TARGET.resolve() or Path(rights.__file__).resolve() != RIGHTS.resolve():
            failures.append("target modules were not imported from this staged repository")
        defaults = []
        for owner in (rd, rights):
            for name, value in vars(owner).items():
                code_defaults = getattr(value, "__defaults__", None) or ()
                kw_defaults = tuple((getattr(value, "__kwdefaults__", None) or {}).values())
                for default in code_defaults + kw_defaults:
                    if isinstance(default, (str, os.PathLike)) and ("/" in os.fspath(default)):
                        defaults.append(f"{owner.__name__}.{name}={default!r}")
        receipt["path_like_bound_defaults"] = defaults
        if defaults:
            failures.append("target modules carry path-like bound defaults that would need redirecting")
    except Exception as error:  # noqa: BLE001 - the red result is evidence
        failures.append("import failed: " + "".join(traceback.format_exception_only(error)).strip())
        receipt["import_traceback"] = "".join(traceback.format_exception(error))[-4000:]
        rd = None

    stdlib_roots = tuple(Path(sysconfig.get_paths()[k]).resolve() for k in ("stdlib", "platstdlib"))
    trace = {}
    for name in sorted(set(sys.modules) - before_modules):
        kind, where = classify_module(sys.modules[name], stdlib_roots)
        trace[name] = {"kind": kind, "location": where}
    receipt["import_trace"] = trace
    outside = [n for n, v in trace.items() if v["kind"] == "OUTSIDE"]
    if outside:
        failures.append(f"imports outside repository/stdlib: {outside}")

    prefix = SUITES[args.suite]
    selected = sorted(n for n in tests if n.startswith(prefix))
    results = [run_test(tests[n]) for n in selected]
    if rd is not None and not selected:
        failures.append(f"no tests collected for prefix {prefix}")
    if args.suite == "contract":
        measured = sha256_file(RIGHTS)
        receipt["rights_module_sha256"] = measured
        if measured != PIN_RIGHTS_SHA256:
            failures.append(f"rights.py sha256 {measured} != pinned {PIN_RIGHTS_SHA256}")
        receipt["denial_probes"] = denial_probes(guard)
        if any(p["outcome"] != "denied-by-sentinel" for p in receipt["denial_probes"]):
            failures.append("deployment/catalog open probe was not denied by the sentinel")
    if args.suite == "negative" and rd is not None and selected:
        receipt["mutation_controls"] = mutation_controls(rd, tests)
        if not all(c["detected"] for c in receipt["mutation_controls"]):
            failures.append("a mutation control was not detected by its exact regression")
    guard.active = False

    receipt["input_hashes_after"] = {str(p.relative_to(REPO)): sha256_file(p) for p in owned if p.exists()}
    if receipt["input_hashes_after"] != receipt["input_hashes_before"]:
        failures.append("an owned input/fixture changed during the run")
    counts = {k: sum(r["outcome"] == k for r in results) for k in ("passed", "failed", "error")}
    counts.update({"collected": len(results), "skipped": 0})
    receipt.update({"counts": counts, "results": results, "unexpected_sentinel_events": guard.events,
                    "expected_sentinel_events": guard.expected})
    if counts["failed"] or counts["error"]:
        failures.append(f"{counts['failed']} failed, {counts['error']} errored")
    if guard.events:
        failures.append(f"{len(guard.events)} unexpected sentinel denials")
    receipt["failures"] = failures
    receipt["exit"] = 1 if failures else 0
    receipt["finished_unix"] = round(time.time(), 3)

    for result in results:
        say(f"{result['outcome'].upper():7} {result['name']}")
        if result["detail"]:
            say(result["detail"].rstrip())
    for control in receipt.get("mutation_controls", []):
        say(f"MUTATION {control['control']}: broken={control['broken_outcome']} "
            f"unaffected={control['unaffected_outcome_under_mutation']} restored={control['restored_outcome']} "
            f"detected={control['detected']}")
    for probe in receipt.get("denial_probes", []):
        say(f"PROBE   {probe['path']}: {probe['outcome']}")
    say(f"suite={args.suite} collected={counts['collected']} passed={counts['passed']} failed={counts['failed']} "
        f"error={counts['error']} skipped=0 exit={receipt['exit']}")
    for failure in failures:
        say("FAIL: " + failure)
    say("REVIEW REQUIRED: local scoped acceptance only; not CI, source qualification or semantic acceptance.")
    say(f"receipt: {run_root / 'receipt.json'}")

    body = json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False).encode() + b"\n"
    with open(run_root / "receipt.json", "xb") as handle:
        handle.write(body)
    with open(run_root / "console.txt", "x", encoding="utf-8") as handle:
        handle.write("\n".join(console) + "\n")
    return receipt["exit"]


if __name__ == "__main__":
    raise SystemExit(main())
