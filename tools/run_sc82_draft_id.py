"""Fresh-process, synthetic-only SC82 acceptance and immutable per-run receipts.

No native adapters, child execution or network access is needed. The audit hook
is a scoped defense-in-depth check, not a hostile-code sandbox. Regular pytest
imports do not install or activate a process-wide hook.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
import unittest
import uuid

BASE = "a1f648632e64561d82dcbeb20d9bda19f812560a"
BASE_DRAFT_SHA256 = "4d04aa67f6642ec6b7a832609826f3861faec87b5cd2a5877f108d7c413b67dc"
REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests/fixtures/sc82-draft-id"
AUTHORED = ("src/skippercast/seafloor/draft.py", "tests/unit/test_sc82_draft_id.py",
            "tools/run_sc82_draft_id.py", "tests/fixtures/sc82-draft-id/source-shape.json")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def no_symlinks(path):
    path = Path(os.path.abspath(path))
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError(f"Symlink in synthetic/output ancestry: {component}")
    return path


class IsolationGuard:
    """Only synthetic writes; code/runtime and authored fixture reads permitted."""

    def __init__(self, synthetic, repo=REPO):
        self.synthetic = no_symlinks(synthetic)
        self.repo = Path(repo).resolve()
        self.fixtures = self.repo / "tests/fixtures/sc82-draft-id"
        self.runtime = {Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()}
        self.active = False
        self.events = []
        self.unexpected = []

    def authorize(self, path, write=False, *, control=False):
        if isinstance(path, int):
            # Existing stdio and already-open descriptors; product uses Path APIs.
            return
        path = no_symlinks(os.fsdecode(path))
        allowed = path.is_relative_to(self.synthetic)
        if not write:
            allowed |= path.is_relative_to(self.fixtures)
            allowed |= path.is_relative_to(self.repo) and path.suffix in {".py", ".pyc"}
            allowed |= any(path.is_relative_to(root) for root in self.runtime)
        if not allowed:
            event = {"event": "file-denied", "path": str(path), "write": write,
                     "control": control}
            self.events.append(event)
            if not control:
                self.unexpected.append(event)
            raise PermissionError("SC82 synthetic file boundary")

    def audit(self, event, args):
        if not self.active:
            return
        if event.startswith("socket.") or event in {
                "subprocess.Popen", "os.system", "os.fork", "os.forkpty",
                "os.posix_spawn", "os.spawn", "pty.spawn", "os.exec"}:
            self.unexpected.append({"event": event})
            raise PermissionError("SC82 no-network/no-child boundary")
        if event == "open":
            path, mode, flags = args
            write = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            self.authorize(path, write)
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.truncate"}:
            self.authorize(args[0], True)
        elif event in {"os.rename", "os.link", "os.symlink"}:
            self.authorize(args[0], True)
            self.authorize(args[1], True)

    def start(self):
        sys.addaudithook(self.audit)
        self.active = True

    def stop(self):
        self.active = False


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def startTest(self, test):
        super().startTest(test)
        method = getattr(test, test._testMethodName)
        self.records.append({"id": test.id(), "assertion_class": method.assertion_class,
                             "outcome": "running"})

    def record(self, test, outcome):
        self.records[-1].update(outcome=outcome, preservation=getattr(test, "preservation", {}))

    def addSuccess(self, test):
        self.record(test, "passed")
        super().addSuccess(test)

    def addFailure(self, test, err):
        self.record(test, "failed")
        super().addFailure(test, err)

    def addError(self, test, err):
        self.record(test, "error")
        super().addError(test, err)

    def addSkip(self, test, reason):
        self.record(test, "skipped")
        super().addSkip(test, reason)


def git(*args):
    return subprocess.check_output(["git", "-C", str(REPO), *args], text=True).strip()


def preflight(manifest_path, out):
    manifest_path = no_symlinks(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    root = REPO.parent
    if manifest.get("schema") != "agentorange.source-manifest/v1":
        raise ValueError("Unadmitted manifest schema")
    if Path(manifest["write_root"]) != root or Path(manifest["repo"]) != REPO:
        raise ValueError("Candidate-root binding failed")
    if manifest["head"] != BASE:
        raise ValueError("Manifest baseline mismatch")
    runtime = manifest["runtime"]
    link = REPO / ".venv"
    if not link.is_symlink() or link.resolve() != Path(runtime["repo_venv"]):
        raise ValueError("Operator-linked runtime mismatch")
    if Path(sys.prefix).resolve() != link.resolve():
        raise ValueError("Acceptance interpreter is not the staged runtime")
    expected_scan = root.parents[1] / "tools/venv-fullsuite/bin/python3"
    if Path(runtime["credential_scan_python3"]) != expected_scan:
        raise ValueError("Credential scan interpreter mismatch")
    out = no_symlinks(out)
    if not out.is_relative_to(root / "out"):
        raise ValueError("Output prefix must be in candidate/out")
    baseline = subprocess.check_output(["git", "-C", str(REPO), "show",
                                        BASE + ":src/skippercast/seafloor/draft.py"])
    if hashlib.sha256(baseline).hexdigest() != BASE_DRAFT_SHA256:
        raise ValueError("Admitted baseline source hash mismatch")
    git("merge-base", "--is-ancestor", BASE, "HEAD")
    return manifest, out


def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True,
                        choices=("regression", "compatibility", "negative-control", "baseline-regression"))
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest, out = preflight(args.source_manifest, args.out)
    out.mkdir(parents=True, exist_ok=True)
    run = out / uuid.uuid4().hex
    run.mkdir(exist_ok=False)
    synthetic = run / "synthetic"
    synthetic.mkdir()
    head = git("rev-parse", "HEAD")
    source_before = {name: digest(REPO / name) for name in AUTHORED}
    fixture_before = {p.relative_to(FIXTURES).as_posix(): digest(p)
                      for p in sorted(FIXTURES.rglob("*")) if p.is_file()}
    manifest_before = digest(args.source_manifest)
    stdout, stderr = io.StringIO(), io.StringIO()
    guard = IsolationGuard(synthetic)
    result = None
    exit_code = 1
    old_tempdir = tempfile.tempdir
    old_sys_path = sys.path[:]
    path_module = None
    old_repo_root = None
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            guard.start()
            tempfile.tempdir = str(synthetic)
            sys.path[:0] = [str(REPO / "src"), str(REPO)]
            # Redirect before contracts REPO and default arguments are evaluated.
            from skippercast import paths as path_module
            old_repo_root = path_module.repo_root
            path_module.repo_root = lambda: synthetic
            from skippercast.platform import contracts
            if contracts.REPO != synthetic:
                raise RuntimeError("Pre-import root redirection failed")
            spec = importlib.util.spec_from_file_location(
                "sc82_tests", REPO / "tests/unit/test_sc82_draft_id.py")
            if spec is None or spec.loader is None:
                raise RuntimeError("Cannot load direct test module")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.DraftIDCases.external_root = synthetic
            module.DraftIDCases.external_guard = guard
            suite = module.load_suite(args.suite)
            runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=2,
                                             resultclass=RecordingResult)
            result = runner.run(suite)
            if not result.testsRun:
                raise RuntimeError("No required tests executed")
            if guard.unexpected:
                raise RuntimeError("Unexpected isolation stop recorded")
            if result.skipped or result.expectedFailures or result.unexpectedSuccesses:
                raise RuntimeError("No skipped/expected-failure acceptance is allowed")
            exit_code = 0 if result.wasSuccessful() else 1
    except Exception:
        with redirect_stderr(stderr):
            traceback.print_exc()
    finally:
        guard.stop()
        if path_module is not None and old_repo_root is not None:
            path_module.repo_root = old_repo_root
        tempfile.tempdir = old_tempdir
        sys.path[:] = old_sys_path
    source_after = {name: digest(REPO / name) for name in AUTHORED}
    fixture_after = {p.relative_to(FIXTURES).as_posix(): digest(p)
                     for p in sorted(FIXTURES.rglob("*")) if p.is_file()}
    if source_after != source_before or fixture_after != fixture_before:
        stderr.write("Authored source/fixture bytes changed\n")
        exit_code = 1
    if digest(args.source_manifest) != manifest_before or git("rev-parse", "HEAD") != head:
        stderr.write("Source manifest or HEAD changed\n")
        exit_code = 1
    tests_run = result.testsRun if result else 0
    stdout.write(f"SC82 {args.suite}: tests={tests_run} exit={exit_code} receipt={run / 'receipt.json'}\n")
    (run / "stdout.txt").write_text(stdout.getvalue())
    (run / "stderr.txt").write_text(stderr.getvalue())
    receipt = {
        "schema": "skippercast.sc82-receipt/v1", "suite": args.suite,
        "argv": [sys.executable, *sys.argv], "cwd": os.getcwd(),
        "interpreter": sys.executable, "head": head, "base": BASE,
        "run_id": run.name, "synthetic": str(synthetic),
        "source_manifest_sha256": manifest_before,
        "source_before": source_before, "source_after": source_after,
        "fixture_before": fixture_before, "fixture_after": fixture_after,
        "preflight": {"candidate_root_bound": True, "unique_output_root": True,
                      "linked_runtime": manifest["runtime"]["repo_venv"],
                      "pre_import_guards": True},
        "guards": {"events": guard.events, "unexpected": guard.unexpected},
        "tests_run": result.testsRun if result else 0,
        "tests": result.records if result else [],
        "failures": len(result.failures) if result else 0,
        "errors": len(result.errors) if result else 1,
        "skips": len(result.skipped) if result else 0,
        "exit": exit_code,
        "outputs": {name: digest(run / name) for name in ("stdout.txt", "stderr.txt")},
        "status": "REVIEW REQUIRED" if exit_code == 0 else "FAILED",
    }
    (run / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(stderr.getvalue(), end="", file=sys.stderr)
    print(stdout.getvalue(), end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
