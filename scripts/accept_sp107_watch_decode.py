#!/usr/bin/env python3
"""Portable, offline, per-run acceptance recorder for SP-10-v1 / SP107."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

SPEC = "SP-10-v1"
ITEM = "SP107-WATCH-DECODE"
BASE = "2979d59bfbb7d724eb83b34a48102b914ee8eaa3"
BASE_SOURCE_SHA256 = "04d5cd5eaaa076d5c4cbb34b40d384bc4af61d665631dceca292387812d9b234"
PRIMARY = "src/skippercast/fleet/ais/watch.py"
TEST = "tests/unit/test_sp107_watch_decode.py"
FIXTURE_DIR = "tests/fixtures/sp107_watch_decode"
TEST_CLASS = "tests.unit.test_sp107_watch_decode.RegressionTests"
BASELINE_TESTS = [TEST_CLASS + ".test_primary_regression", TEST_CLASS + ".test_healthy_control"]
FOCUSED_TESTS = sorted(TEST_CLASS + "." + name for name in (
    "test_primary_regression", "test_healthy_control",
    "test_invalid_sequences_preserve_prior_state_and_repeat_is_bounded",
    "test_invalid_initial_read_and_recovery",
    "test_malformed_json_and_schema_rejection_still_retain_state",
    "test_read_error_still_retains_state",
))
REGRESSION_CLASS = "tests.unit.test_fleet_listener.WatchTest"
REGRESSION_TESTS = sorted(REGRESSION_CLASS + "." + name for name in (
    "test_format_round_trip_and_rejections", "test_bad_file_keeps_the_previous_list",
    "test_reload_changes_routing_and_resubscribes_in_filter_mode",
))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def no_symlinks(path):
    """Check the leaf and every lexical ancestor BEFORE accessing that path."""
    path = Path(os.path.abspath(path))
    for entry in (path, *path.parents):
        require(not entry.is_symlink(), f"symlink ancestry refused: {entry}")
    return path


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def source_hashes(repo):
    fixtures = no_symlinks(repo / FIXTURE_DIR)
    require(fixtures.is_dir(), "synthetic fixtures missing")
    paths = [repo / PRIMARY, repo / TEST, Path(__file__),
             repo / "docs/engineering/sp107_watch_decode.md",
             repo / "tests/unit/test_fleet_listener.py", repo / "scripts/check_repository.py"]
    for path in sorted(fixtures.rglob("*")):
        no_symlinks(path)
        require(path.is_file() or path.is_dir(), "fixture is not a regular file/directory")
        if path.is_file():
            paths.append(path)
    for path in paths:
        no_symlinks(path)
        require(path.is_file(), f"required source missing: {path}")
    return {str(path.relative_to(repo)): sha256(path) for path in paths}


def child_tests(repo, suite_name, run_dir):
    # This hook lives ONLY in this dedicated child, not in imported test modules.
    # The socket pair used internally by asyncio is allowed; network/DNS/bind and
    # subprocess/model execution are not. These tripwires are not a sandbox.
    def tripwire(event, args):
        if event in {"socket.connect", "socket.bind", "socket.getaddrinfo",
                     "socket.gethostbyname", "socket.sendto", "subprocess.Popen", "os.system"}:
            raise RuntimeError(f"offline acceptance tripwire: {event}")
        if event == "import" and args[0].split(".")[0] in {"openai", "anthropic", "ollama", "litellm"}:
            raise RuntimeError("offline acceptance model-import tripwire")
    sys.addaudithook(tripwire)
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(repo), str(repo / "src")]
    os.environ["SKIPPERCAST_ROOT"] = str(repo)
    os.environ["SKIPPERCAST_FLEET_VAR"] = str(run_dir / "var/fleet")
    os.environ["SKIPPERCAST_VAR"] = str(run_dir / "var")
    os.environ["SKIPPERCAST_CACHE"] = str(run_dir / "cache")
    import tempfile
    tempfile.tempdir = str(no_symlinks(run_dir / "tmp"))
    import unittest
    from skippercast.fleet.ais import watch
    require(Path(watch.__file__).resolve() == repo / PRIMARY, "watch import escaped staged repo")
    from skippercast.paths import repo_root
    require(repo_root() == repo, "package root redirect failed")
    from skippercast.fleet.ais.store import fleet_var
    require(fleet_var() == run_dir / "var/fleet", "fleet root redirect failed")

    class Result(unittest.TextTestResult):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.named = []
            self.started = []
            self.subtests = []

        def startTest(self, test):
            self.started.append(test.id())
            super().startTest(test)

        def addSuccess(self, test):
            self.named.append({"test": test.id(), "status": "passed"})
            super().addSuccess(test)

        def addFailure(self, test, err):
            self.named.append({"test": test.id(), "status": "failed",
                               "exception": err[0].__name__, "message": str(err[1])})
            super().addFailure(test, err)

        def addError(self, test, err):
            self.named.append({"test": test.id(), "status": "error", "exception": err[0].__name__})
            super().addError(test, err)

        def addSkip(self, test, reason):
            self.named.append({"test": test.id(), "status": "skipped", "reason": reason})
            super().addSkip(test, reason)

        def addSubTest(self, test, subtest, err):
            self.subtests.append({"test": subtest.id(), "status": "passed" if err is None else "failed"})
            super().addSubTest(test, subtest, err)

    selectors = {"baseline": BASELINE_TESTS, "focused": [TEST_CLASS],
                 "regression": [REGRESSION_CLASS]}[suite_name]
    suite = unittest.defaultTestLoader.loadTestsFromNames(selectors)
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2, resultclass=Result).run(suite)
    imported = {}
    for name, module in list(sys.modules.items()):
        if name == "skippercast" or name.startswith("skippercast.") or name.startswith("tests."):
            filename = getattr(module, "__file__", None)
            if filename:
                path = Path(filename).resolve()
                require(path.is_relative_to(repo), f"import escaped staged repo: {name}")
                imported[name] = {"file": str(path), "sha256": sha256(path)}
    counts = {"run": result.testsRun, "passed": sum(row["status"] == "passed" for row in result.named),
              "failed": len(result.failures), "error": len(result.errors), "skipped": len(result.skipped),
              "expected_failures": len(result.expectedFailures), "unexpected_successes": len(result.unexpectedSuccesses)}
    write_json(run_dir / "test-results.json", {"counts": counts, "named": result.named,
               "started": result.started, "subtests": result.subtests, "imported": imported,
               "runtime": {"executable": sys.executable, "version": sys.version}})
    return 0 if result.wasSuccessful() and not result.skipped and not result.expectedFailures else 1


def capture(argv, repo, env, raw_dir, label):
    started = time.monotonic()
    result = subprocess.run(argv, cwd=repo, env=env, capture_output=True)
    paths = {}
    for stream in ("stdout", "stderr"):
        path = raw_dir / f"{label}-{stream}.txt"
        with path.open("xb") as handle:
            handle.write(getattr(result, stream))
        paths[stream + "_path"] = str(path)
        paths[stream + "_sha256"] = sha256(path)
    return {"argv": argv, "cwd": str(repo), "exit": result.returncode,
            "elapsed_seconds": time.monotonic() - started, **paths}


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=("baseline", "focused", "regression", "repository"), required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--child-suite", choices=("baseline", "focused", "regression"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    script = no_symlinks(Path(__file__).absolute())
    repo = script.parents[1]
    candidate = repo.parent
    if args.child_suite:
        return child_tests(repo, args.child_suite, no_symlinks(Path(args.output)))

    manifest_path = no_symlinks(candidate / "SOURCE-MANIFEST.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("schema") == "agentorange.source-manifest/v1", "invalid source-manifest schema")
    require(manifest.get("write_root") == str(candidate) and manifest.get("repo") == str(repo), "manifest root mismatch")
    require(manifest.get("head") == BASE, "manifest base mismatch")
    base_bytes = subprocess.run(["git", "show", f"{BASE}:{PRIMARY}"], cwd=repo, capture_output=True, check=True).stdout
    require(hashlib.sha256(base_bytes).hexdigest() == BASE_SOURCE_SHA256, "pinned base source mismatch")
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "merge-base", "--is-ancestor", BASE, "HEAD")
    hashes = source_hashes(repo)
    if args.suite == "baseline":
        require(hashes[PRIMARY] == BASE_SOURCE_SHA256, "baseline requires unchanged pinned product bytes")
    else:
        require(not git(repo, "status", "--porcelain"), "final acceptance requires clean staged status")

    output_root = no_symlinks(Path(args.output))
    require(output_root.is_relative_to(candidate / "out"), "output must be inside candidate out")
    output_root.mkdir(parents=True, exist_ok=True)
    run_dir = output_root / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex}"
    run_dir.mkdir()
    raw_dir = run_dir / "raw"
    raw_dir.mkdir()
    (run_dir / "tmp").mkdir()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for key in ("TMPDIR", "TMP", "TEMP"):
        env[key] = str(run_dir / "tmp")
    env["SKIPPERCAST_ROOT"] = str(repo)
    env["SKIPPERCAST_FLEET_VAR"] = str(run_dir / "var/fleet")
    python = repo / ".venv/bin/python3"  # The one explicitly admitted staging symlink.
    if args.suite == "repository":
        python = Path(manifest["runtime"]["credential_scan_python3"])
        require(python.is_absolute(), "scanner interpreter must be absolute")
    require(python.is_file() and os.access(python, os.X_OK), "manifest/staged interpreter unavailable")
    version = capture([str(python), "--version"], repo, env, raw_dir, "version")
    require(version["exit"] == 0, "interpreter version check failed")
    argv = ([str(python), "scripts/check_repository.py"] if args.suite == "repository" else
            [str(python), str(script), "--suite", args.suite, "--output", str(run_dir), "--child-suite", args.suite])
    record = capture(argv, repo, env, raw_dir, "child")
    details = None
    counts = None
    if args.suite != "repository":
        results = run_dir / "test-results.json"
        if results.is_file():
            details = json.loads(results.read_text(encoding="utf-8"))
            counts = details["counts"]
        expected = {"baseline": BASELINE_TESTS, "focused": FOCUSED_TESTS, "regression": REGRESSION_TESTS}[args.suite]
        complete = bool(details and sorted(details["started"]) == sorted(expected)
                        and counts["run"] == len(expected) and not counts["error"] and not counts["skipped"]
                        and not counts["expected_failures"] and not counts["unexpected_successes"])
        if args.suite == "baseline":
            failures = [row for row in details["named"] if row["status"] == "failed"] if details else []
            passed = [row["test"] for row in details["named"] if row["status"] == "passed"] if details else []
            accepted = bool(complete and record["exit"] == 1 and counts["failed"] == 1 and counts["passed"] == 1
                            and passed == [BASELINE_TESTS[1]] and len(failures) == 1
                            and failures[0]["test"] == BASELINE_TESTS[0]
                            and failures[0]["exception"] == "AssertionError"
                            and "poll raised UnicodeDecodeError" in failures[0]["message"])
        else:
            accepted = bool(complete and record["exit"] == 0 and counts["failed"] == 0
                            and counts["passed"] == len(expected)
                            and all(row["status"] == "passed" for row in details["subtests"]))
    else:
        accepted = record["exit"] == 0
    stable = hashes == source_hashes(repo) and head == git(repo, "rev-parse", "HEAD")
    accepted = bool(accepted and stable)
    phase = ("BASELINE_DEFECT_REPRODUCED" if accepted else "BASELINE_CONTRACT_FAILURE") if args.suite == "baseline" else ("PASS" if accepted else "FAIL")
    receipt = {
        "specification": SPEC, "item": ITEM, "suite": args.suite, "phase": phase,
        "base": BASE, "head": head, "git_status": git(repo, "status", "--porcelain"),
        "invocation": {"argv": [sys.executable, *sys.argv], "cwd": os.getcwd(), "python_version": sys.version},
        "source_manifest": str(manifest_path), "source_manifest_sha256": sha256(manifest_path),
        "source_test_fixture_sha256": hashes, "sources_stable_during_run": stable,
        "material_authors": [
            {"model": "gpt-6-luna", "provider": "openai-codex", "profile": "luna-worker", "effort": "medium",
             "commit": "91e1ffb35a1d6b72e366a2f745354d2bb7462bba", "scope": "original candidate"},
            {"model": "gpt-6.1-sol", "provider": "openai-codex", "profile": "sol-reviewer", "effort": "high",
             "scope": "continuation tests/helper/docs; retained original product repair"}],
        "runtime": {"python": str(python), "resolved_python": str(python.resolve()), "version": version},
        "child": record, "counts": counts, "test_results": details, "accepted_by_runner": accepted,
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if details:
        receipt["test_results_file"] = {"path": str(results), "sha256": sha256(results)}
    write_json(run_dir / "receipt.json", receipt)
    print(json.dumps({"phase": phase, "accepted_by_runner": accepted, "receipt": str(run_dir / "receipt.json"),
                      "child_exit": record["exit"], "counts": counts}, sort_keys=True))
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
