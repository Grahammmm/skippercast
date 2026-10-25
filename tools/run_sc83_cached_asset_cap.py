#!/usr/bin/env python3
"""Offline, bounded SC83 cached-asset-cap acceptance runner.

Order of operations (each step precedes any product import):
  1. disable bytecode writes; validate the operator SOURCE-MANIFEST (read-only);
  2. validate the requested --out below <write_root>/out BEFORE creating anything,
     then create a fresh unique run directory;
  3. install an audit-hook guard: writes only inside the run directory, reads of
     repository fixtures only inside the card fixture tree, no network, no child
     processes; any denial outside the recorded inert probes fails acceptance;
  4. exercise that same guard with inert allowed/denied events via sys.audit
     (no real forbidden file, host or process is ever touched);
  5. point SKIPPERCAST_ROOT at a run-local synthetic repository, then import the
     real package from this checkout and run the selected tests.
The guard is defense in depth for this harness, not a hostile-code sandbox.
"""
import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import contextlib  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

ADMITTED_BASE = "a1f648632e64561d82dcbeb20d9bda19f812560a"
MANIFEST_SCHEMA = "agentorange.source-manifest/v1"
SOURCE = "src/skippercast/seafloor/io.py"
TEST = "tests/unit/test_sc83_cached_asset_cap.py"
RUNNER = "tools/run_sc83_cached_asset_cap.py"
FIXTURE = "tests/fixtures/sc83-cached-asset-cap"

SELECTED = {
    "regression": ["test_matching_cache_below_cap", "test_matching_cache_exact_cap",
                   "test_oversized_cache_rejected_before_hash_or_session", "test_invalid_caps",
                   "test_cache_checksum_mismatch_unchanged", "test_missing_offline_refusal_unchanged",
                   "test_small_download_remains_accepted",
                   "test_download_oversize_failure_preserves_absent_destination",
                   "test_download_hash_failure_preserves_absent_destination"],
    "compatibility": ["test_matching_cache_below_cap",
                      "test_cache_checksum_mismatch_unchanged", "test_missing_offline_refusal_unchanged",
                      "test_small_download_remains_accepted",
                      "test_download_oversize_failure_preserves_absent_destination",
                      "test_download_hash_failure_preserves_absent_destination"],
}
DECIDING = "test_oversized_cache_rejected_before_hash_or_session"
POSITIVE = "test_matching_cache_exact_cap"
INVALID_CAP_SUBTESTS = 7

WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
PATH_WRITE_EVENTS = {  # event -> indices of path arguments, and their dir_fd argument index
    "os.mkdir": ((0, 2),), "os.remove": ((0, 1),), "os.rmdir": ((0, 1),),
    "os.rename": ((0, 2), (1, 3)), "os.replace": ((0, 2), (1, 3)),
    "os.truncate": ((0, None),), "os.chmod": ((0, 2),), "os.chown": ((0, 3),),
    "os.symlink": ((1, 2),), "os.link": ((1, 3),), "os.utime": ((0, 3),),
    "shutil.rmtree": ((0, 1),), "shutil.copyfile": ((1, None),), "shutil.move": ((1, None),),
    "shutil.copytree": ((1, None),), "os.mkfifo": ((0, 2),), "os.mknod": ((0, 3),),
}
PROCESS_EVENTS = ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn",
                  "os.fork", "os.forkpty", "os.startfile", "os.kill", "os.killpg")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_path(path):
    return sha256_bytes(Path(path).read_bytes())


def git_head(repo):
    """Full HEAD commit read from the checkout's git metadata (no subprocess)."""
    git_dir = repo / ".git"
    if git_dir.is_file():
        git_dir = (repo / git_dir.read_text(encoding="utf-8").split(":", 1)[1].strip()).resolve()
    head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    if not head.startswith("ref: "):
        return head
    ref = head[5:]
    loose = git_dir / ref
    if loose.is_file():
        return loose.read_text(encoding="utf-8").strip()
    for line in (git_dir / "packed-refs").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == ref:
            return parts[0]
    raise SystemExit("unable to resolve HEAD")


def tree_hashes(root):
    return {str(path.relative_to(root)): sha256_path(path)
            for path in sorted(root.rglob("*")) if path.is_file()}


def preflight(args, repo):
    """Validate the staged manifest, interpreter and output root. Writes nothing."""
    manifest_path = Path(args.source_manifest)
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    problems = []
    if manifest.get("schema") != MANIFEST_SCHEMA:
        problems.append("manifest schema")
    candidate_root = Path(manifest.get("write_root") or "/nonexistent-write-root").resolve()
    if candidate_root != repo.parent:
        problems.append("manifest write_root is not this runner's candidate root")
    if Path(manifest.get("repo") or "/nonexistent-repo").resolve() != repo:
        problems.append("manifest repo is not this runner's repo")
    if manifest.get("head") != ADMITTED_BASE:
        problems.append("manifest head is not the admitted base")
    runtime = manifest.get("runtime") or {}
    staged_venv = repo / ".venv"
    if not runtime.get("repo_venv") or Path(runtime["repo_venv"]).resolve() != staged_venv.resolve():
        problems.append("runtime.repo_venv is not the linked staged venv")
    # The pinned scanner interpreter lives at <agent-work>/tools/venv-fullsuite/bin/python3,
    # where the write root is <agent-work>/candidates/<card>. Exact path equality, unresolved
    # (a venv interpreter is a symlink to its base interpreter).
    expected_scanner = candidate_root.parents[1] / "tools" / "venv-fullsuite" / "bin" / "python3"
    scanner = runtime.get("credential_scan_python3")
    if scanner != str(expected_scanner) or not Path(scanner).is_file():
        problems.append("runtime.credential_scan_python3 is not the pinned full-suite interpreter")
    interpreter = Path(os.path.abspath(sys.executable))
    if interpreter.parent.parent != staged_venv:
        problems.append("runner interpreter is not the staged repo venv")
    out_prefix = candidate_root / "out"
    requested_out = Path(args.out).resolve()
    if requested_out != out_prefix and out_prefix not in requested_out.parents:
        problems.append("--out is not below <write_root>/out")
    raw_out = Path(os.path.abspath(args.out))
    for ancestor in [raw_out, *raw_out.parents]:
        if ancestor == candidate_root:
            break
        if ancestor.is_symlink():
            problems.append("--out passes through a symlink below the write root")
            break
    if problems:
        raise SystemExit("SC83 preflight refused: " + "; ".join(problems))
    return {"manifest": manifest, "manifest_path": manifest_path,
            "manifest_sha256": sha256_bytes(manifest_bytes), "candidate_root": candidate_root,
            "requested_out": requested_out, "interpreter": str(interpreter),
            "scanner": scanner}


class Guard:
    """Audit-hook path/network/process policy. Records every decision."""

    def __init__(self, write_root, fixtures_dir, card_fixture):
        self.write_root = write_root
        self.fixtures_dir = fixtures_dir
        self.card_fixture = card_fixture
        self.phase = "setup"
        self.denials = []
        self.allowed_writes = 0
        self.card_fixture_reads = 0

    @staticmethod
    def _target(path, dir_fd=None):
        if isinstance(path, int) or path is None:
            return None
        text = os.fsdecode(path)
        if not os.path.isabs(text):
            if isinstance(dir_fd, int) and dir_fd >= 0:
                text = os.path.join(os.readlink(f"/proc/self/fd/{dir_fd}"), text)
            else:
                text = os.path.abspath(text)
        return Path(os.path.realpath(text))

    def _inside(self, target, root):
        return target == root or root in target.parents

    def _deny(self, event, detail):
        self.denials.append({"phase": self.phase, "event": event, "target": str(detail)})
        raise PermissionError(f"SC83 guard denied {event}")

    def _write(self, event, path, dir_fd=None):
        target = self._target(path, dir_fd)
        if target is None:
            return
        if not self._inside(target, self.write_root):
            self._deny(event, target)
        self.allowed_writes += 1

    def __call__(self, event, args):
        if event == "open":
            path, mode, flags = (list(args) + [None, None, None])[:3]
            target = self._target(path)
            if target is None:
                return
            writes = (isinstance(mode, str) and any(c in mode for c in "wax+")) or \
                     (isinstance(flags, int) and flags & WRITE_FLAGS)
            if writes:
                self._write(event, path)
            elif self._inside(target, self.fixtures_dir):
                if not self._inside(target, self.card_fixture):
                    self._deny("open(read)", target)
                self.card_fixture_reads += 1
        elif event in PATH_WRITE_EVENTS:
            for index, fd_index in PATH_WRITE_EVENTS[event]:
                if index < len(args):
                    dir_fd = args[fd_index] if fd_index is not None and fd_index < len(args) else None
                    self._write(event, args[index], dir_fd)
        elif event.startswith("socket.") or event.startswith(PROCESS_EVENTS):
            self._deny(event, args[0] if args else "")


def inert_probes(guard, run_dir, candidate_root, repo, fixtures_dir):
    """Drive the installed hook with sys.audit events only; no real operation happens."""
    rw = os.O_WRONLY | os.O_CREAT
    probes = [
        ("allowed-synthetic-write", False, ("open", str(run_dir / "guard-probe-allowed.txt"), "w", rw)),
        ("allowed-card-fixture-read", False, ("open", str(repo / FIXTURE / "payload.txt"), "r", os.O_RDONLY)),
        ("denied-write-outside-candidate", True,
         ("open", str(candidate_root.parent / "sc83-inert-denied-sentinel"), "w", rw)),
        ("denied-write-candidate-source", True, ("open", str(repo / "src" / "sc83-inert-denied-sentinel"), "w", rw)),
        ("denied-mkdir-outside-run", True, ("os.mkdir", str(candidate_root / "sc83-inert-denied-dir"), 0o777, -1)),
        ("denied-other-fixture-read", True,
         ("open", str(fixtures_dir / "sc83-inert-other-fixture.txt"), "r", os.O_RDONLY)),
        ("denied-network", True, ("socket.connect", None, ("192.0.2.1", 9))),
        ("denied-child-process", True, ("subprocess.Popen", "sc83-inert", ["sc83-inert"], None, None)),
    ]
    results = []
    for name, expect_denied, event in probes:
        guard.phase = "probe:" + name
        target = Path(event[1]) if isinstance(event[1], str) else None
        existed_before = target.exists() if target is not None else None
        try:
            sys.audit(*event)
            denied = False
        except PermissionError:
            denied = True
        existed_after = target.exists() if target is not None else None
        results.append({"probe": name, "event": event[0], "expect_denied": expect_denied,
                        "denied": denied, "target_existed_before": existed_before,
                        "target_existed_after": existed_after,
                        "passed": denied is expect_denied and existed_before == existed_after})
    guard.phase = "setup"
    return results


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def _record(self, test, outcome, err=None):
        entry = {"id": test.id(), "outcome": outcome}
        if err is not None:
            entry["exception"] = err[0].__name__
            entry["detail"] = self._exc_info_to_string(err, test)
        self.records.append(entry)

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "pass")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "fail", err)

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "error", err)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.records.append({"id": test.id(), "outcome": "skip", "detail": reason})

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._record(test, "error", err)

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.records.append({"id": test.id(), "outcome": "error", "detail": "unexpected success"})

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is None:
            self._record(subtest, "pass")
        elif issubclass(err[0], test.failureException):
            self._record(subtest, "fail", err)
        else:
            self._record(subtest, "error", err)


def run_phase(name, test_names, run_dir, module):
    """Run named tests once, capturing raw output; return execution-derived evidence."""
    module.EVIDENCE.clear()
    raw_out, raw_err = run_dir / f"{name}.stdout.txt", run_dir / f"{name}.stderr.txt"
    suite = unittest.TestSuite(module.CacheHitCapTests(test) for test in test_names)
    with raw_out.open("w", encoding="utf-8") as out_stream, raw_err.open("w", encoding="utf-8") as err_stream:
        with contextlib.redirect_stdout(out_stream), contextlib.redirect_stderr(err_stream):
            runner = unittest.TextTestRunner(stream=out_stream, verbosity=2, resultclass=RecordingResult)
            result = runner.run(suite)
    evidence = {item["test"]: item for item in module.EVIDENCE}
    tests = []
    for test in test_names:
        records = [r for r in result.records if r["id"].split(" ")[0].rsplit(".", 1)[-1] == test]
        top = [r for r in records if " " not in r["id"]]
        subtests = [r for r in records if " " in r["id"]]
        outcome = top[0]["outcome"] if top else ("fail" if any(r["outcome"] == "fail" for r in subtests)
                                                 else "error" if subtests else "missing")
        tests.append({"id": test, "assertion_class": module.ASSERTION_CLASSES.get(test),
                      "outcome": outcome, "records": records, "subtests": len(subtests),
                      "preservation": evidence.get(test)})
    return {"phase": name, "tests": tests, "tests_run": result.testsRun,
            "failures": len(result.failures), "errors": len(result.errors), "skips": len(result.skipped),
            "stdout": str(raw_out), "stdout_sha256": sha256_path(raw_out),
            "stderr": str(raw_err), "stderr_sha256": sha256_path(raw_err)}


def phase_all_pass(phase, expected):
    tests = phase["tests"]
    ok = (phase["tests_run"] == len(expected) and phase["failures"] == 0 and phase["errors"] == 0
          and phase["skips"] == 0 and [t["id"] for t in tests] == expected
          and all(t["outcome"] == "pass" and t["preservation"] is not None for t in tests))
    for test in tests:
        if test["id"] == "test_invalid_caps":
            ok = ok and test["subtests"] == INVALID_CAP_SUBTESTS and \
                all(r["outcome"] == "pass" for r in test["records"])
        if test["id"] in (DECIDING, "test_invalid_caps", "test_cache_checksum_mismatch_unchanged"):
            pres = test["preservation"] or {}
            ok = ok and pres.get("before") == pres.get("after") and \
                (pres.get("before") or {}).get("destination") is not None
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", required=True, choices=("regression", "compatibility", "negative-control"))
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    pre = preflight(args, repo)
    candidate_root = pre["candidate_root"]
    run_id = f"{time.time_ns()}-{os.getpid()}"
    run_dir = pre["requested_out"] / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    tmp_dir = run_dir / "tmp"
    tmp_dir.mkdir()
    authored = {path: sha256_path(repo / path) for path in (SOURCE, TEST, RUNNER)}
    fixture_root = repo / FIXTURE
    fixtures_dir = repo / "tests" / "fixtures"
    fixture_before = tree_hashes(fixture_root)

    guard = Guard(run_dir, fixtures_dir.resolve(), fixture_root.resolve())
    sys.addaudithook(guard)
    probes = inert_probes(guard, run_dir, candidate_root, repo, fixtures_dir)
    probe_denials = len(guard.denials)

    import tempfile
    tempfile.tempdir = str(tmp_dir)
    synthetic_repo = run_dir / "synthetic-repo"
    synthetic_repo.mkdir()
    os.environ["SKIPPERCAST_ROOT"] = str(synthetic_repo)
    preloaded = sorted(name for name in sys.modules if name == "skippercast" or name.startswith("skippercast."))
    sys.path.insert(0, str(repo / "src"))
    sys.path.insert(0, str(repo / "tests" / "unit"))
    import test_sc83_cached_asset_cap as module
    from skippercast import paths
    from skippercast.seafloor import io
    binding = {
        "preloaded_skippercast_modules": preloaded,
        "io_module": str(Path(io.__file__).resolve()),
        "io_from_candidate": Path(io.__file__).resolve() == (repo / SOURCE).resolve(),
        "repo_root": str(paths.repo_root()),
        "repo_root_redirected": paths.repo_root() == synthetic_repo.resolve(),
        "test_module_from_candidate": Path(module.__file__).resolve() == (repo / TEST).resolve(),
    }

    phases = []
    mutant_detected = positive_control_passed = None
    if args.suite == "negative-control":
        from unittest.mock import patch
        original_stat = Path.stat
        hits = {"count": 0}
        tmp_real = os.path.realpath(tmp_dir)

        def no_size_gate_stat(path, *stat_args, **stat_kwargs):
            # In-memory control equivalent to the old cache-hit branch: verified_file's size
            # preflight sees st_size 0 for the card's synthetic cached asset, so no cap applies.
            # Bytes on disk and the expected hash stay exactly as in the ordinary test.
            result = original_stat(path, *stat_args, **stat_kwargs)
            real = os.path.realpath(os.fspath(path))
            if os.path.basename(real) == "asset.bin" and real.startswith(tmp_real + os.sep):
                hits["count"] += 1
                values = list(result)
                values[6] = 0
                return os.stat_result(values)
            return result

        controls = {}
        for name, test in (("control-deciding", DECIDING), ("control-positive", POSITIVE)):
            hits["count"] = 0
            with patch.object(Path, "stat", no_size_gate_stat):
                phase = run_phase(name, [test], run_dir, module)
            phase["control_hits"] = hits["count"]
            controls[name] = phase
            phases.append(phase)
        restored = Path.stat is original_stat
        phases.append(run_phase("restored", [POSITIVE, DECIDING], run_dir, module))
        deciding = controls["control-deciding"]
        deciding_records = deciding["tests"][0]["records"]
        mutant_detected = (deciding["tests_run"] == 1 and deciding["failures"] == 1 and deciding["errors"] == 0
                           and deciding["control_hits"] > 0 and len(deciding_records) == 1
                           and deciding_records[0]["outcome"] == "fail"
                           and deciding_records[0].get("exception") == "AssertionError"
                           and "AssertionError: ValueError not raised" in deciding_records[0].get("detail", ""))
        positive_control_passed = (restored and phase_all_pass(controls["control-positive"], [POSITIVE])
                                   and controls["control-positive"]["control_hits"] > 0
                                   and phase_all_pass(phases[-1], [POSITIVE, DECIDING]))
        suite_passed = mutant_detected and positive_control_passed
        expected_ids = [DECIDING, POSITIVE, POSITIVE, DECIDING]
    else:
        phases.append(run_phase("ordinary", SELECTED[args.suite], run_dir, module))
        suite_passed = phase_all_pass(phases[0], SELECTED[args.suite])
        expected_ids = SELECTED[args.suite]

    guard.phase = "teardown"
    fixture_after = tree_hashes(fixture_root)
    authored_after = {path: sha256_path(repo / path) for path in (SOURCE, TEST, RUNNER)}
    unexpected_denials = guard.denials[probe_denials:]
    isolation = {
        "candidate_root": str(candidate_root), "run_dir": str(run_dir),
        "run_dir_unique": True, "write_boundary": str(run_dir),
        "probes": probes, "probes_passed": all(p["passed"] for p in probes),
        "denials": guard.denials, "unexpected_denials": unexpected_denials,
        "allowed_writes": guard.allowed_writes, "card_fixture_reads": guard.card_fixture_reads,
        "binding": binding,
        "fixture_hashes_before": fixture_before, "fixture_hashes_after": fixture_after,
        "fixture_unchanged": fixture_before == fixture_after,
        "authored_hashes_before": authored, "authored_hashes_after": authored_after,
        "authored_unchanged": authored == authored_after,
    }
    isolation["passed"] = bool(
        isolation["probes_passed"] and not unexpected_denials and isolation["fixture_unchanged"]
        and isolation["authored_unchanged"] and guard.card_fixture_reads > 0 and not preloaded
        and binding["io_from_candidate"] and binding["repo_root_redirected"]
        and binding["test_module_from_candidate"])
    executed_ids = [t["id"] for phase in phases for t in phase["tests"]]
    ordinary = [p for p in phases if not p["phase"].startswith("control-")]
    control = [p for p in phases if p["phase"].startswith("control-")]
    exit_code = 0 if (suite_passed and isolation["passed"] and executed_ids == expected_ids) else 1
    receipt = {
        "schema": "skippercast.sc83-cached-asset-cap.receipt/v2",
        "suite": args.suite, "run_id": run_id, "argv": sys.argv, "cwd": os.getcwd(),
        "interpreter": pre["interpreter"], "credential_scan_python3": pre["scanner"],
        "admitted_base": ADMITTED_BASE, "head": git_head(repo),
        "manifest": str(pre["manifest_path"]), "manifest_sha256": pre["manifest_sha256"],
        "source_sha256": authored[SOURCE], "test_sha256": authored[TEST], "runner_sha256": authored[RUNNER],
        "executed_test_ids": executed_ids,
        "tests_run": sum(p["tests_run"] for p in ordinary),
        "failures": sum(p["failures"] for p in ordinary), "errors": sum(p["errors"] for p in ordinary),
        "skips": sum(p["skips"] for p in ordinary),
        "control_tests_run": sum(p["tests_run"] for p in control),
        "control_failures": sum(p["failures"] for p in control),
        "control_errors": sum(p["errors"] for p in control),
        "control_skips": sum(p["skips"] for p in control),
        "phases": phases, "mutant_detected": mutant_detected,
        "positive_control_passed": positive_control_passed,
        "suite_passed": bool(suite_passed), "isolation": isolation,
        "isolation_passed": isolation["passed"], "exit": exit_code,
        "status": "REVIEW REQUIRED" if exit_code == 0 else "FAILED",
    }
    (run_dir / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in (
        "suite", "run_id", "head", "tests_run", "failures", "errors", "skips", "control_tests_run",
        "control_failures", "control_errors", "mutant_detected",
        "positive_control_passed", "isolation_passed", "exit", "status")}, sort_keys=True))
    print("receipt: " + str(run_dir / "receipt.json"))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
