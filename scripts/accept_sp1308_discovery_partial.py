"""Portable offline acceptance/evidence runner for SP-13-v2, SP1308.

The parent uses declared python3; file-based children use the staged venv or
operator-declared credential scanner. Guards are confined to those children.
Evidence is append-only in unique output children; this is not a sandbox or a
shipping/full-suite approval. Baseline red evidence is never final acceptance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
CANDIDATE = REPO.parent
BASE = "2979d59bfbb7d724eb83b34a48102b914ee8eaa3"
PRIMARY = "src/skippercast/fleet/ingest.py"
PRIMARY_BASE_HASH = "10c91f45c83c2be4fae5c5d1a237df76291be40a3a925661ed629ba2cb22c8e7"
TEST = "tests.unit.test_sp1308_discovery_partial"
PAIR = [TEST + ".RegressionTests.test_primary_regression", TEST + ".RegressionTests.test_healthy_control"]
SELECTORS = {
    "baseline": PAIR,
    "focused": [TEST],
    "regression": ["tests.unit.test_fleet_ingest.IngestTests", "tests.unit.test_fleet_refresh.RefreshTests"],
    "repository": [],
}
PINNED = {
    "tests/unit/test_fleet_ingest.py": "57d99b3a9a8572a09612283d25f3e862c256aa285f3cc53ad18c2f945ccbc198",
    "tests/unit/test_fleet_refresh.py": "54fd6aa59a0c1a40c62eed97f24244ac7b3e11d59cf8e54871a9a7c37b08752b",
}
OWNED = [PRIMARY, "tests/unit/test_sp1308_discovery_partial.py",
         "scripts/accept_sp1308_discovery_partial.py", "docs/engineering/sp1308_discovery_partial.md"]
FIXTURES = REPO / "tests/fixtures/sp1308_discovery_partial"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def no_symlinks(path):
    path = Path(os.path.abspath(path))
    for ancestor in [*reversed(path.parents), path]:
        require(not ancestor.is_symlink(), f"symlinked authored ancestry: {ancestor}")


def dump(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def clean_env(out):
    # Deliberately do not inherit credentials, model settings or Python search paths.
    return {"PATH": os.defpath, "LANG": "C.UTF-8", "HOME": str(out / "home"),
            "TMPDIR": str(out / "tmp"), "TEMP": str(out / "tmp"), "TMP": str(out / "tmp"),
            "PYTHONDONTWRITEBYTECODE": "1", "SKIPPERCAST_ROOT": str(REPO),
            "SKIPPERCAST_FLEET_VAR": str(out / "fleet")}


def git(*args):
    process = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False)
    require(process.returncode == 0, f"git {args} failed: {process.stderr}")
    return process.stdout.strip()


def hashes():
    no_symlinks(FIXTURES)
    paths = [REPO / name for name in OWNED if (REPO / name).exists()]
    for path in sorted(FIXTURES.rglob("*")):
        no_symlinks(path)
        if path.is_file():
            paths.append(path)
    paths += [REPO / name for name in PINNED] + [REPO / "scripts/check_repository.py"]
    return {str(path.relative_to(REPO)): sha(path) for path in paths}


def child_guards(out):
    import tempfile
    sys.dont_write_bytecode = True
    os.environ.clear()
    os.environ.update(clean_env(out))
    tempfile.tempdir = str(out / "tmp")
    sys.path[:0] = [str(REPO), str(REPO / "src")]
    violations = []

    def reject(event):
        violations.append(event)
        raise RuntimeError("offline acceptance tripwire: " + event)

    def audit(event, args):
        if event in {"socket.__new__", "socket.connect", "socket.bind", "socket.getaddrinfo",
                     "urllib.Request", "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"}:
            reject(event)
        if event == "sqlite3.connect" and str(args[0]) != ":memory:":
            target = Path(args[0]).absolute()
            if not target.resolve().is_relative_to(out):
                reject("sqlite outside synthetic output")
        if event == "open" and not isinstance(args[0], int):
            mode, flags = args[1], args[2]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)))
            if writing:
                target = Path(args[0]).absolute()
                if not target.resolve().is_relative_to(out):
                    reject("write outside synthetic output")
                no_symlinks(target)

    sys.addaudithook(audit)
    return violations


def child(out, suite):
    import platform
    import runpy
    import traceback
    import unittest
    violations = child_guards(out)
    record = {"argv": sys.argv, "cwd": str(Path.cwd()), "runtime": sys.executable,
              "python_version": platform.python_version(), "selectors": SELECTORS[suite]}
    try:
        if suite == "repository":
            target = REPO / "scripts/check_repository.py"
            record["target_argv"] = [str(target)]
            sys.argv = [str(target)]
            try:
                runpy.run_path(str(target), run_name="__main__")
            except SystemExit as error:
                code = error.code
                require(type(code) is int, "repository checker did not return an integer exit")
            else:
                code = 0
            record.update(exit=code, checks=["unchanged scripts/check_repository.py"])
        else:
            from skippercast import paths
            from skippercast.fleet import ingest, runs
            import inspect
            require(paths.repo_root() == REPO, "wrong repository root")
            require(runs.fleet_var() == out / "fleet", "wrong fleet default root")
            require(inspect.signature(runs.Run).parameters["var"].default is None, "unexpected bound Run.var")
            # All admitted stateful APIs receive explicit synthetic paths. No
            # import-time path default points at a live store in these modules.
            record["defaults_checked"] = {"repo_root": str(paths.repo_root()),
                                           "fleet_var": str(runs.fleet_var()), "Run.var": None}
            loader = unittest.TestLoader()
            tests = loader.loadTestsFromNames(SELECTORS[suite])
            require(not loader.errors, "unittest selector/import error: " + repr(loader.errors))

            def flatten(group):
                for item in group:
                    if isinstance(item, unittest.TestSuite):
                        yield from flatten(item)
                    else:
                        yield item.id()

            names = list(flatten(tests))
            require(bool(names) and len(names) == len(set(names)), "empty/duplicate selected tests")
            if suite == "baseline":
                require(names == PAIR, "baseline registered more than the exact pair")
            if suite in {"focused", "baseline"}:
                module = sys.modules[TEST]
                record["case_map"] = module.CASE_MAP
                if suite == "focused":
                    for row, cases in module.CASE_MAP.items():
                        require(all(TEST + "." + name in names for name in cases), f"missing {row} tests")

            class Result(unittest.TextTestResult):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.passed, self.failure_info = [], []

                def addSuccess(self, test):
                    super().addSuccess(test)
                    self.passed.append(test.id())

                def addFailure(self, test, err):
                    super().addFailure(test, err)
                    self.failure_info.append({"name": test.id(), "exception": err[0].__name__, "message": str(err[1])})

            result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(tests)
            provenance = {name: str(Path(module.__file__).resolve()) for name, module in list(sys.modules.items())
                          if (name == "skippercast" or name.startswith("skippercast.") or name in SELECTORS["focused"])
                          and getattr(module, "__file__", None)}
            require(all(Path(path).is_relative_to(REPO) for path in provenance.values()), "shared editable import escaped staging")
            record.update(names=names, tests_run=result.testsRun, passed=result.passed,
                          failures=[name.id() for name, _ in result.failures], failure_info=result.failure_info,
                          errors=[name.id() for name, _ in result.errors], skipped=[name.id() for name, _ in result.skipped],
                          expected_failures=[name.id() for name, _ in result.expectedFailures],
                          unexpected_successes=[name.id() for name in result.unexpectedSuccesses], imports=provenance)
            require(result.testsRun == len(names), "not every selected test ran")
            code = 0 if result.wasSuccessful() else 1
        if violations:
            code = 2
        record.update(exit=code, tripwires=violations)
    except Exception:
        traceback.print_exc()
        record.update(exit=2, tripwires=violations, harness_error=traceback.format_exc())
    dump(out / "child.json", record)
    return record["exit"]


def parent(args):
    no_symlinks(CANDIDATE)
    manifest_path = CANDIDATE / "SOURCE-MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("schema") == "agentorange.source-manifest/v1", "missing operator manifest schema")
    require(manifest.get("head") == BASE and Path(manifest["repo"]) == REPO
            and Path(manifest["write_root"]) == CANDIDATE, "operator staging identity mismatch")
    for name, expected in PINNED.items():
        require(sha(REPO / name) == expected, "original regression test drift: " + name)
    out_parent = Path(os.path.abspath(args.output))
    require(out_parent.is_relative_to(CANDIDATE / "out"), "output must be in candidate/out")
    no_symlinks(out_parent)
    out_parent.mkdir(parents=True, exist_ok=True)
    out = out_parent / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12])
    out.mkdir()
    for name in ("tmp", "home", "fleet"):
        (out / name).mkdir()
    before = hashes()
    head = git("rev-parse", "HEAD")
    if args.suite == "baseline":
        require(head == BASE and before[PRIMARY] == PRIMARY_BASE_HASH, "baseline source drift: operator disposition required")
    interpreter = (Path(manifest["runtime"]["credential_scan_python3"]) if args.suite == "repository"
                   else REPO / ".venv/bin/python3")
    require(interpreter.is_file(), "staged interpreter missing")
    argv = [str(interpreter), "-B", str(Path(__file__).resolve()), "--child", "--suite", args.suite, "--output", str(out)]
    process = subprocess.run(argv, cwd=REPO, env=clean_env(out), capture_output=True, check=False)
    (out / "stdout.txt").write_bytes(process.stdout)
    (out / "stderr.txt").write_bytes(process.stderr)
    child_path = out / "child.json"
    data = json.loads(child_path.read_text()) if child_path.is_file() else {}
    clean_tests = bool(data) and not any(data.get(key) for key in (
        "errors", "skipped", "expected_failures", "unexpected_successes", "harness_error", "tripwires"))
    if args.suite == "baseline":
        valid = (process.returncode == 1 and data.get("exit") == 1 and clean_tests and data.get("names") == PAIR
                 and data.get("tests_run") == 2 and data.get("passed") == [PAIR[1]]
                 and data.get("failures") == [PAIR[0]] and len(data.get("failure_info", [])) == 1
                 and data["failure_info"][0]["exception"] == "AssertionError"
                 and "A1: usable candidate plus skipped layout is incomplete" in data["failure_info"][0]["message"])
        verdict = "BASELINE_GAP_REPRODUCED" if valid else "BASELINE_REJECTED_OPERATOR_DISPOSITION_REQUIRED"
    else:
        valid = process.returncode == 0 and data.get("exit") == 0 and clean_tests and not data.get("failures")
        if args.suite != "repository":
            valid = valid and data.get("tests_run", 0) > 0 and data.get("passed") == data.get("names")
        verdict = "PASS_REVIEW_REQUIRED" if valid else "FAIL"
    require(hashes() == before and git("rev-parse", "HEAD") == head, "source changed during acceptance")
    receipt = {"specification": "SP-13-v2", "card": "SP1308-DISCOVERY-PARTIAL", "phase": args.suite,
               "staged_base": BASE, "head": head, "source_manifest_sha256": sha(manifest_path),
               "author": {"model": "gpt-6.1-sol", "provider": "openai-codex", "profile": "sol-reviewer"},
               "material_commits": git("log", "--format=%H%n%B", BASE + "..HEAD"),
               "working_tree": git("status", "--porcelain"), "source_hashes": before,
               "parent_argv": sys.argv, "parent_cwd": str(Path.cwd()), "parent_python": sys.executable,
               "parent_version": sys.version, "child_argv": argv, "child_cwd": str(REPO),
               "child_exit": process.returncode, "child": data, "valid": bool(valid), "verdict": verdict,
               "evidence_hashes": {name: sha(out / name) for name in ("stdout.txt", "stderr.txt", "child.json")
                                   if (out / name).is_file()},
               "limits": "Scoped offline only. Independent Opus review and operator full-suite/CI/release remain OWED."}
    dump(out / "receipt.json", receipt)
    print(json.dumps({"verdict": verdict, "receipt": str(out / "receipt.json"), "receipt_sha256": sha(out / "receipt.json"),
                      "child_exit": process.returncode, "tests_run": data.get("tests_run"), "valid": bool(valid)}, sort_keys=True))
    if process.stdout:
        print(process.stdout.decode(errors="replace"), end="")
    if process.stderr:
        print(process.stderr.decode(errors="replace"), file=sys.stderr, end="")
    return 0 if valid else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=SELECTORS)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        return child(args.output.resolve(), args.suite)
    return parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
