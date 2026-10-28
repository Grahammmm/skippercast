"""Portable SP-10-v1 offline acceptance; no installation or live CLI invocation.

The orchestration process may use system Python. Test execution always uses the
staged .venv interpreter; repository scanning uses only the manifest interpreter.
All paths in committed code are derived, not operator-machine dependencies.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid

BASE = "2979d59bfbb7d724eb83b34a48102b914ee8eaa3"
PRIMARY = "src/skippercast/pipeline/ndbc_history.py"
PRIMARY_BASE_HASH = "0640f6dc16517126369333ecdb6d91228fb0bfb2b9e68ee935d682a6d3fccff5"
ORIGINAL = "tests/unit/test_ndbc_history.py"
ORIGINAL_HASH = "5dcfccecce157a615215d03cfbe034499d57f12e2f6429864732e5fb5b66405d"
TEST = "tests/unit/test_sp106_history_receipt.py"
FIXTURE = "tests/fixtures/sp106_history_receipt"
AUTHOR = {"model": "gpt-6.1-sol", "provider": "openai-codex", "profile": "sol-reviewer",
          "run_id": 1712, "basis": "actual author session runtime; no delegated edits"}
PAIR = ["tests.unit.test_sp106_history_receipt.RegressionTests.test_primary_regression",
        "tests.unit.test_sp106_history_receipt.RegressionTests.test_healthy_control"]
REGRESSION = [
    "tests.unit.test_ndbc_history.NdbcHistoryTests.test_unchanged_archives_download_nothing",
    "tests.unit.test_ndbc_history.NdbcHistoryTests.test_corrupt_gzip_fails_only_its_year",
    "tests.unit.test_ndbc_history.NdbcHistoryTests.test_recent_mode_keeps_published_baseline_and_fetches_only_recent",
]
REPO = Path(__file__).absolute().parents[1]
CANDIDATE = REPO.parent


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def no_links(path):
    """Check existing ancestry without first resolving away a symlink."""
    path = Path(os.path.abspath(path))
    for part in [*reversed(path.parents), path]:
        try:
            mode = part.lstat().st_mode
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(mode), f"Symlink refused: {part}")
    return path


def digest(path):
    path = no_links(path)
    require(stat.S_ISREG(path.stat().st_mode), f"Not a regular evidence/input file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    no_links(path)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def new_run(output):
    output = no_links(output)
    require(output.is_relative_to(CANDIDATE / "out"), "Output must be beneath candidate/out")
    output.mkdir(parents=True, exist_ok=True)
    run = output / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex)
    run.mkdir(mode=0o700)
    return run


def capture(argv, cwd=REPO):
    started = time.monotonic()
    result = subprocess.run([str(a) for a in argv], cwd=cwd, capture_output=True, check=False)
    return {"argv": [str(a) for a in argv], "cwd": str(cwd), "exit": result.returncode,
            "elapsed_seconds": time.monotonic() - started,
            "stdout": result.stdout.decode("utf-8", errors="replace"),
            "stderr": result.stderr.decode("utf-8", errors="replace")}


def git(*args):
    executable = shutil.which("git")
    require(executable is not None, "Installed git required")
    result = capture([executable, "-C", REPO, *args])
    require(result["exit"] == 0, f"git failed: {result}")
    return result


def staged():
    no_links(REPO)
    path = no_links(CANDIDATE / "SOURCE-MANIFEST.json")
    manifest = json.loads(path.read_text())
    require(manifest.get("schema") == "agentorange.source-manifest/v1", "Manifest schema mismatch")
    require(manifest.get("write_root") == str(CANDIDATE), "Manifest write_root mismatch")
    require(manifest.get("repo") == str(REPO), "Manifest repo mismatch")
    require(manifest.get("head") == BASE, "Manifest base mismatch")
    require(manifest.get("clean") is True, "Operator clean staging attestation required")
    git("merge-base", "--is-ancestor", BASE, "HEAD")
    runtime = manifest["runtime"]
    for key in ("system_python3", "credential_scan_python3", "detect_secrets"):
        tool = Path(runtime[key])
        require(tool.is_absolute() and tool.is_file() and os.access(tool, os.X_OK),
                f"Missing executable manifest runtime: {key}")
    child_python = REPO / ".venv/bin/python3"
    require(child_python.is_file() and os.access(child_python, os.X_OK), "Staged venv Python missing")
    # The operator explicitly admits the shared venv link. It is NOT a fixture/output link.
    require((REPO / ".venv").resolve() == Path(runtime["repo_venv"]).resolve(), "Venv staging mismatch")
    require(digest(REPO / ORIGINAL) == ORIGINAL_HASH, "Original compatibility tests changed")
    fixture_root = no_links(REPO / FIXTURE)
    require(fixture_root.is_dir(), "Committed synthetic fixture definitions required")
    for path in fixture_root.rglob("*"):
        no_links(path)
    return manifest, digest(CANDIDATE / "SOURCE-MANIFEST.json"), child_python


def hashes():
    names = [PRIMARY, TEST, ORIGINAL, "scripts/accept_sp106_history_receipt.py",
             "src/skippercast/http.py", "src/skippercast/paths.py", "tests/_support.py",
             "scripts/check_repository.py"]
    note = "docs/engineering/sp106_history_receipt.md"
    if (REPO / note).exists():
        names.append(note)
    for root in (FIXTURE, "tests/fixtures/ndbc-history"):
        names.extend(p.relative_to(REPO).as_posix() for p in sorted((REPO / root).rglob("*")) if p.is_file())
    return {name: digest(REPO / name) for name in names}


class OfflineViolation(BaseException):
    """Cannot become an expected product ValueError/OSError/AssertionError."""


def child_boundary(run):
    """Only called in this runner's isolated child, never during test discovery."""
    no_links(run)
    require(run.is_relative_to(CANDIDATE / "out") and run.is_dir(), "Invalid child run root")
    temp = no_links(run / "tmp")
    temp.mkdir()
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["TMPDIR"] = str(temp)
    tempfile.tempdir = str(temp)
    os.environ["SKIPPERCAST_ROOT"] = str(REPO)
    os.environ["SKIPPERCAST_HTTP_CACHE"] = ""
    # Set paths in file-based code, never with search-path environment overrides.
    sys.path[:0] = [str(REPO), str(REPO / "src")]
    violations = []

    def audit(event, args):
        if (event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "os.fork", "os.forkpty", "pty.spawn"}
                or event.startswith("os.exec") or event.startswith("os.spawn")):
            violations.append(event)
            raise OfflineViolation(f"Offline child refused event {event}")
    sys.addaudithook(audit)
    return violations


def run_child(mode, run):
    violations = child_boundary(run)  # Before ANY target/test imports.
    if mode == "repository":
        import runpy
        scanner = REPO / "scripts/check_repository.py"
        sys.argv = [str(scanner)]
        try:
            runpy.run_path(str(scanner), run_name="__main__")
        except SystemExit as error:
            code = error.code if isinstance(error.code, int) else 1
        else:
            code = 0
        write_json(run / "child-result.json", {
            "exit": code, "entrypoint_argv": [str(scanner)], "runtime": sys.version,
            "executable": sys.executable, "offline_violations": violations,
        })
        return code if not violations else 2

    import inspect
    import unittest
    from skippercast import http
    from skippercast.paths import repo_root
    from skippercast.pipeline import ndbc_history as target
    expected = REPO / PRIMARY
    require(Path(target.__file__).resolve() == expected, "Wrong target imported")
    require(Path(http.__file__).resolve() == REPO / "src/skippercast/http.py", "Wrong HTTP module imported")
    require(repo_root() == REPO, "Package root was not redirected")
    # Inspected constructors: no disk/network at import, no bound path defaults
    # in annual_receipt/collect; collect requires its synthetic cache argument.
    require(inspect.signature(target.annual_receipt).parameters["cache"].default is inspect.Parameter.empty,
            "Unexpected bound cache default")
    require(inspect.signature(target.collect).parameters["cache"].default is inspect.Parameter.empty,
            "Unexpected collect cache default")

    def no_real_request(*args, **kwargs):
        violations.append("skippercast.http.Session.request")
        raise OfflineViolation("Real HTTP Session refused; FakeSession only")
    http.Session.request = no_real_request
    loader = unittest.TestLoader()
    selectors = PAIR if mode == "baseline" else REGRESSION if mode == "regression" else ["tests.unit.test_sp106_history_receipt"]
    suite = loader.loadTestsFromNames(selectors)
    require(not loader.errors, f"Test selector/import error: {loader.errors}")
    from tests import _support
    require(_support.ROOT == REPO and _support.FIXTURES == REPO / "tests/fixtures", "Wrong original fixtures")

    class Result(unittest.TextTestResult):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.started_names, self.passed_names = [], []

        def startTest(self, test):
            self.started_names.append(test.id())
            super().startTest(test)

        def addSuccess(self, test):
            self.passed_names.append(test.id())
            super().addSuccess(test)

    from typing import cast
    result = cast(Result, unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite))
    record = {
        "tests_run": result.testsRun, "started": result.started_names, "passed": result.passed_names,
        "failures": [{"name": test.id(), "traceback": trace} for test, trace in result.failures],
        "errors": [{"name": test.id(), "traceback": trace} for test, trace in result.errors],
        "skips": [{"name": test.id(), "reason": reason} for test, reason in result.skipped],
        "expected_failures": len(result.expectedFailures), "unexpected_successes": len(result.unexpectedSuccesses),
        "runtime": sys.version, "executable": sys.executable, "imported_target": str(target.__file__),
        "synthetic_temp_root": tempfile.tempdir, "offline_violations": violations,
    }
    write_json(run / "child-result.json", record)
    return 0 if result.wasSuccessful() and not violations else 1


def acceptance(mode, output, actor):
    manifest, manifest_hash, child_python = staged()
    head = git("rev-parse", "HEAD")["stdout"].strip()
    before = hashes()
    if mode == "baseline":
        require(head == BASE and before[PRIMARY] == PRIMARY_BASE_HASH, "Baseline requires untouched pinned product/base")
    status_at_start = git("status", "--porcelain")["stdout"]
    run = new_run(output)
    interpreter = Path(manifest["runtime"]["credential_scan_python3"]) if mode == "repository" else child_python
    version = capture([interpreter, "--version"])
    require(version["exit"] == 0, "Cannot measure required interpreter")
    argv = [interpreter, Path(__file__).absolute(), "--child", mode, "--run-dir", run]
    execution = capture(argv)
    for stream in ("stdout", "stderr"):
        with (run / (stream + ".txt")).open("x", encoding="utf-8") as handle:
            handle.write(execution.pop(stream))
    result_path = run / "child-result.json"
    result = json.loads(result_path.read_text()) if result_path.exists() else {}
    common = (hashes() == before and not result.get("offline_violations")
              and result_path.is_file())
    if mode == "baseline":
        valid = (common and execution["exit"] == 1 and result.get("tests_run") == 2
                 and result.get("started") == PAIR and result.get("passed") == [PAIR[1]]
                 and [f["name"] for f in result.get("failures", [])] == [PAIR[0]]
                 and "AssertionError" in result["failures"][0]["traceback"]
                 and not result.get("errors") and not result.get("skips")
                 and result.get("expected_failures") == 0 and result.get("unexpected_successes") == 0)
        status = "BASELINE_DEFECT_REPRODUCED" if valid else "BASELINE_REJECTED"
    elif mode == "repository":
        stdout = (run / "stdout.txt").read_text()
        matched = re.search(r"Checked (\d+) text files:", stdout)
        result["checked_text_files"] = int(matched[1]) if matched else None
        valid = common and execution["exit"] == 0 and result.get("exit") == 0 and matched is not None
        status = "REVIEW_REQUIRED" if valid else "FAILED"
    else:
        names = result.get("started", [])
        cases = json.loads((REPO / FIXTURE / "metadata.json").read_text())
        required_focused = [
            "test_primary_regression", "test_healthy_control", "test_missing_body_refills",
            "test_corrupt_body_refills", "test_revalidate_fetches",
            "test_failure_never_returns_mismatched_bytes", "test_revalidate_failure_records_error",
            "test_missing_body_failure_records_error", "test_corrupt_body_failure_records_error",
            "test_refill_checkpoint_restart_is_zero_request", "test_gzip_fetch_and_cache_decode_unchanged",
            "test_bad_fetched_gzip_records_error", "test_integrity_valid_bad_cached_decode_preserves_error_behavior",
        ]
        required_focused += ["test_metadata_" + row[0] for row in cases["mutations"]]
        required_focused += ["test_metadata_missing_" + field for field in cases["missing"]]
        required_focused += ["test_metadata_receipt_" + row[0] for row in cases["nonobjects"]]
        required_focused = ["tests.unit.test_sp106_history_receipt.RegressionTests." + name for name in sorted(required_focused)]
        valid = (common and execution["exit"] == 0 and result.get("tests_run", 0) == len(names)
                 and result.get("passed") == names and len(names) == len(set(names))
                 and not result.get("errors") and not result.get("failures") and not result.get("skips")
                 and result.get("expected_failures") == 0 and result.get("unexpected_successes") == 0
                 and names == (REGRESSION if mode == "regression" else required_focused))
        status = "REVIEW_REQUIRED" if valid else "FAILED"
    receipt = {
        "schema": "agentorange.sp106-acceptance/v1", "specification": "SP-10-v1",
        "item_id": "SP106-HISTORY-RECEIPT", "phase": mode, "status": status,
        "staged_base": BASE, "head": head, "source_manifest_sha256": manifest_hash,
        "hashes": before, "material_author": AUTHOR, "invocation_actor_declared": actor,
        "orchestrator_runtime": {"executable": sys.executable, "version": sys.version},
        "child_runtime_version_command": version, "execution": execution,
        "git_status_at_start": status_at_start,
        "counts_and_names": result,
        "raw": {name: {"path": str(run / name), "sha256": digest(run / name)}
                for name in ("stdout.txt", "stderr.txt")},
        "remaining_gates": ["independent Opus review", "operator full suite", "exact-head shipping CI", "operator publication"],
    }
    if result_path.exists():
        receipt["child_result_sha256"] = digest(result_path)
    write_json(run / "receipt.json", receipt)
    print(json.dumps({"status": status, "receipt": str(run / "receipt.json"),
                      "receipt_sha256": digest(run / "receipt.json"), "child_exit": execution["exit"],
                      "counts": {k: result.get(k) for k in ("tests_run", "checked_text_files")}}))
    return 0 if valid else 1


def freeze(output, paths, actor):
    _, manifest_hash, _ = staged()
    require(len(paths) == 4, "Freeze requires baseline and all three final-mode receipts")
    records = []
    for path in paths:
        path = no_links(path)
        require(path.is_relative_to(CANDIDATE / "out"), "Receipt outside candidate outputs")
        record = json.loads(path.read_text())
        require(record["specification"] == "SP-10-v1", "Wrong specification")
        for raw in record["raw"].values():
            raw_path = no_links(raw["path"])
            require(raw_path.parent == path.parent and digest(raw_path) == raw["sha256"], "Raw output mismatch")
        require(digest(path.parent / "child-result.json") == record["child_result_sha256"], "Child result mismatch")
        records.append((path, record))
    require({r["phase"] for _, r in records} == {"baseline", "focused", "regression", "repository"}, "Missing acceptance phase")
    head = git("rev-parse", "HEAD")["stdout"].strip()
    current = hashes()
    for _, record in records:
        require(record["source_manifest_sha256"] == manifest_hash, "Staging changed")
        for name in [TEST, *[p for p in current if p.startswith(FIXTURE + "/")]]:
            require(record["hashes"][name] == current[name], "Test/fixture bytes changed since baseline")
        if record["phase"] == "baseline":
            require(record["status"] == "BASELINE_DEFECT_REPRODUCED" and record["head"] == BASE
                    and record["hashes"][PRIMARY] == PRIMARY_BASE_HASH, "Invalid historical baseline")
        else:
            require(record["status"] == "REVIEW_REQUIRED" and record["head"] == head
                    and record["hashes"] == current and record["git_status_at_start"] == "", "Final run not clean exact-head")
    status = git("status", "--porcelain")
    require(status["stdout"] == "", "Final HEAD must be clean")
    diff_check = git("diff", "--check", BASE, "HEAD")
    diff = git("diff", BASE, "HEAD")
    commits = git("log", "--format=fuller", f"{BASE}..HEAD")
    run = new_run(output)
    for name, command in (("diff.txt", diff), ("commits.txt", commits)):
        with (run / name).open("x", encoding="utf-8") as handle:
            handle.write(command["stdout"])
    write_json(run / "evidence-manifest.json", {
        "specification": "SP-10-v1", "item_id": "SP106-HISTORY-RECEIPT", "head": head,
        "staged_base": BASE, "status": "REVIEW_REQUIRED", "material_author": AUTHOR,
        "invocation_actor_declared": actor, "source_manifest_sha256": manifest_hash,
        "hashes": current, "git_status": status, "git_diff_check": diff_check,
        "receipts": [{"path": str(p), "sha256": digest(p), "phase": r["phase"], "status": r["status"]} for p, r in records],
        "artifacts": {name: digest(run / name) for name in ("diff.txt", "commits.txt")},
        "remaining_gates": ["independent Opus review", "operator full suite", "exact-head shipping CI", "operator publication"],
    })
    print(json.dumps({"manifest": str(run / "evidence-manifest.json"),
                      "sha256": digest(run / "evidence-manifest.json"), "head": head, "status": "REVIEW_REQUIRED"}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--suite", choices=("baseline", "focused", "regression", "repository"))
    mode.add_argument("--child", choices=("baseline", "focused", "regression", "repository"))
    mode.add_argument("--freeze", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--receipt", action="append", default=[], type=Path)
    parser.add_argument("--actor", default="gpt-6.1-sol/openai-codex (author run 1712)")
    args = parser.parse_args()
    if args.child:
        require(args.run_dir is not None, "Child run directory required")
        return run_child(args.child, args.run_dir)
    require(args.output is not None, "Output directory required")
    if args.freeze:
        return freeze(args.output, args.receipt, args.actor)
    return acceptance(args.suite, args.output, args.actor)


if __name__ == "__main__":
    raise SystemExit(main())
