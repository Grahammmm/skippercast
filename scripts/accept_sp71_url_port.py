"""Portable, offline, fail-closed scoped acceptance for SP71 (not full CI)."""
import argparse
import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WRITE_ROOT = ROOT.parent
MANIFEST = WRITE_ROOT / "SOURCE-MANIFEST.json"
BASE = "a1f648632e64561d82dcbeb20d9bda19f812560a"
SOURCE = ROOT / "src/skippercast/fleet/normalize.py"
BASE_SOURCE_HASH = "3bd6ae8fa023757f2bded051006d1205c7eae180bae2e649061a1b3afda6dcea"
TEST = ROOT / "tests/unit/test_sp71_url_port.py"
FIXTURES = ROOT / "tests/fixtures/sp71_url_port"
REGRESSION = ("tests.unit.test_fleet_resolve.NormalizeTests",)
PRIMARY = "tests.unit.test_sp71_url_port.CleanUrlAuthorityTests.test_primary_bad_port"
HEALTHY = "tests.unit.test_sp71_url_port.CleanUrlAuthorityTests.test_healthy_control"
SUITES = ("baseline", "focused", "regression", "repository")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def hashes():
    files = [SOURCE, TEST, Path(__file__).resolve(), *sorted(FIXTURES.rglob("*.json"))]
    return {str(path.relative_to(ROOT)): digest(path) for path in files}


def inspect_closure(selectors):
    """Inspect eager local imports without importing targets; retain calls/hashes.

    Conditional imports are included conservatively, except TYPE_CHECKING and
    __main__ branches. Lazy function bodies are not executed by module imports.
    The selected regression methods contain no child commands or lazy imports.
    """
    queue = [name.rsplit(".NormalizeTests", 1)[0] for name in selectors]
    seen, report = set(), {}
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        path = None
        for base in (ROOT, ROOT / "src"):
            for candidate in (base.joinpath(*name.split(".")).with_suffix(".py"),
                              base.joinpath(*name.split(".")) / "__init__.py"):
                if candidate.is_file():
                    path = candidate
                    break
            if path is not None:
                break
        if path is None:
            continue  # Standard-library/external imports are qualified at load.
        for index in range(1, len(name.split("."))):
            queue.append(".".join(name.split(".")[:index]))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        imports, calls = [], []

        def inspect(nodes):
            for node in nodes:
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    prefix = ".".join(package.split(".")[:len(package.split(".")) - node.level + 1]) if node.level else ""
                    target = ".".join(filter(None, (prefix, node.module)))
                    imports.append(target)
                    imports.extend(target + "." + alias.name for alias in node.names)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    # Function/class bodies retained in source hashes; not run by this walker.
                    continue
                elif isinstance(node, ast.If) and (ast.unparse(node.test) == "TYPE_CHECKING" or "__name__" in ast.unparse(node.test)):
                    continue
                else:
                    calls.extend({"line": c.lineno, "call": ast.unparse(c.func)}
                                 for c in ast.walk(node) if isinstance(c, ast.Call))
                    for field in ("body", "orelse", "finalbody"):
                        inspect(getattr(node, field, []))
                    for handler in getattr(node, "handlers", []):
                        inspect(handler.body)
        inspect(tree.body)
        queue.extend(imports)
        relative = str(path.relative_to(ROOT))
        # Original import closure is read-only, not just the chosen assertions.
        if path not in (TEST, SOURCE):
            old = subprocess.check_output(["git", "-C", str(ROOT), "show", BASE + ":" + relative])
            if hashlib.sha256(old).hexdigest() != digest(path):
                raise RuntimeError("unchanged import closure mismatch: " + relative)
        report[relative] = {"sha256": digest(path), "eager_imports": sorted(set(imports)), "module_calls": calls}
    return report


def install_offline_guards(run):
    """Child-only audit guard, installed before target imports; not a sandbox."""
    attempts = []

    def audit(event, args):
        denied = (event.startswith("socket.") and event != "socket.__new__") or event in {
            "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "pty.spawn", "sqlite3.connect"
        }
        if event == "open":
            path, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)))
            if writing and not isinstance(path, int):
                denied = not Path(path).resolve().is_relative_to(run)
        if denied:
            attempts.append(event)
            raise RuntimeError("SP71 offline sentinel: " + event)
    sys.addaudithook(audit)
    # Environment-selected roots are set before constants and default arguments bind.
    os.environ["SKIPPERCAST_ROOT"] = str(ROOT)
    os.environ["TMPDIR"] = str(run / "tmp")
    tempfile.tempdir = str(run / "tmp")
    return attempts


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.outcomes.append({"id": test.id(), "status": "passed"})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.outcomes.append({"id": test.id(), "status": "failed"})

    def addError(self, test, err):
        super().addError(test, err)
        self.outcomes.append({"id": test.id(), "status": "error"})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.outcomes.append({"id": test.id(), "status": "skipped", "reason": reason})


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test.id()


def child(suite, run):
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(ROOT), str(ROOT / "src")]
    attempts = install_offline_guards(run)
    data = {"runtime": {"executable": sys.executable, "version": sys.version}, "sentinel_attempts": attempts}
    code = 1
    try:
        if suite == "repository":
            target = ROOT / "scripts/check_repository.py"
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                try:
                    runpy.run_path(str(target), run_name="__main__")
                except SystemExit as error:
                    code = error.code if isinstance(error.code, int) else 1
            text = stream.getvalue()
            print(text, end="")
            match = re.fullmatch(r"Checked (\d+) text files: .+ passed\.\n", text)
            good = code == 0 and match is not None
            data.update(cases_run=1, cases_passed=int(good), cases_failed=int(not good),
                        cases_errors=0, cases_skipped=0, checked_files=int(match.group(1)) if match else None,
                        target_argv=[str(target)], outcomes=[{"id": "repository_scan", "status": "passed" if good else "failed"}])
            code = 0 if good else 1
        else:
            selectors = [PRIMARY, HEALTHY] if suite == "baseline" else (
                ["tests.unit.test_sp71_url_port"] if suite == "focused" else list(REGRESSION))
            loader = unittest.TestLoader()
            tests = loader.loadTestsFromNames(selectors)
            ids = list(flatten(tests))
            if loader.errors or not ids or len(ids) != len(set(ids)):
                raise RuntimeError("missing, duplicate or unavailable required selector")
            if suite == "baseline" and ids != [PRIMARY, HEALTHY]:
                raise RuntimeError("baseline must execute exactly primary and healthy control")
            result = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(tests)
            failed = {t.id() for t, _ in result.failures}
            errored = {t.id() for t, _ in result.errors}
            skipped = {t.id() for t, _ in result.skipped}
            data.update(selected_ids=ids, outcomes=result.outcomes, cases_run=result.testsRun,
                        cases_failed=len(failed), cases_errors=len(errored), cases_skipped=len(skipped),
                        cases_passed=result.testsRun - len(failed | errored | skipped))
            complete = result.testsRun == len(ids) and not result.skipped and not result.expectedFailures and not result.unexpectedSuccesses
            code = 0 if complete and result.wasSuccessful() else 1
    except Exception as error:
        import traceback
        traceback.print_exc()
        data["harness_error"] = str(error)
        code = 1
    if attempts:
        code = 1
    data["exit"] = code
    (run / "results.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=SUITES)
    parser.add_argument("--output")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--run", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        run = Path(args.run).resolve()
        if not run.is_relative_to(WRITE_ROOT / "out"):
            raise SystemExit("child output outside admitted out root")
        return child(args.suite, run)
    if not args.output:
        parser.error("--output is required")
    output = Path(args.output).resolve()
    if not output.is_relative_to(WRITE_ROOT / "out"):
        raise SystemExit("output must be under candidate out/")
    output.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="run-", dir=output))
    (run / "tmp").mkdir()
    receipt = {"schema_version": 1, "suite": args.suite, "phase": "FAILED", "staging_base": BASE,
               "wrapper_exit": 1, "wrapper_argv": [sys.executable, *sys.argv], "cwd": str(ROOT)}
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if manifest.get("head") != BASE:
            raise RuntimeError("manifest staging head mismatch")
        subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", BASE, "HEAD"], check=True)
        before = hashes()
        receipt.update(actual_head=git("rev-parse", "HEAD"), git_status=git("status", "--porcelain"),
                       manifest_sha256=digest(MANIFEST), hashes=before, source_sha256=digest(SOURCE), test_sha256=digest(TEST))
        if args.suite == "baseline" and digest(SOURCE) != BASE_SOURCE_HASH:
            raise RuntimeError("baseline requires complete unchanged pinned product module")
        scan = ROOT / "scripts/check_repository.py"
        scan_base = subprocess.check_output(["git", "-C", str(ROOT), "show", BASE + ":scripts/check_repository.py"])
        if hashlib.sha256(scan_base).hexdigest() != digest(scan):
            raise RuntimeError("repository scanner must remain unchanged")
        closure = inspect_closure(REGRESSION if args.suite == "regression" else ["tests.unit.test_sp71_url_port"])
        (run / "import-closure.json").write_text(json.dumps(closure, indent=2) + "\n", encoding="utf-8")
        runtime = Path(manifest["runtime"]["credential_scan_python3"]) if args.suite == "repository" else ROOT / ".venv/bin/python3"
        if not runtime.is_file() or not os.access(runtime, os.X_OK):
            raise RuntimeError("admitted interpreter unavailable; no fallback")
        version = subprocess.run([str(runtime), "--version"], cwd=ROOT, capture_output=True, text=True, check=True)
        argv = [str(runtime), "-B", str(Path(__file__).resolve()), "--suite", args.suite, "--child", "--run", str(run)]
        receipt.update(runtime={"argv0": str(runtime), "resolved": str(runtime.resolve()), "version": version.stdout.strip(),
                                "version_argv": [str(runtime), "--version"]}, argv=argv,
                       import_closure_path=str(run / "import-closure.json"), import_closure_sha256=digest(run / "import-closure.json"))
        env = os.environ.copy()
        env["TMPDIR"] = str(run / "tmp")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(argv, cwd=ROOT, env=env, text=True, capture_output=True)
        for label, text in (("stdout", completed.stdout), ("stderr", completed.stderr)):
            raw = run / (label + ".txt")
            raw.write_text(text, encoding="utf-8")
            receipt["raw_" + label] = str(raw)
            receipt["raw_" + label + "_sha256"] = digest(raw)
        data = json.loads((run / "results.json").read_text(encoding="utf-8"))
        receipt.update(child_exit=completed.returncode, results=data, results_sha256=digest(run / "results.json"))
        for key in ("cases_run", "cases_passed", "cases_failed", "cases_errors", "cases_skipped"):
            receipt[key] = data.get(key)
        valid = (not data.get("harness_error") and not data["sentinel_attempts"] and hashes() == before
                 and git("rev-parse", "HEAD") == receipt["actual_head"])
        if args.suite == "baseline":
            observations = [line.removeprefix("PRIMARY_OBSERVATION=") for line in completed.stdout.splitlines()
                            if line.startswith("PRIMARY_OBSERVATION=")]
            valid = valid and completed.returncode == 1 and data["cases_run"] == 2 and data["cases_failed"] == 1 and data["cases_passed"] == 1 and data["cases_errors"] == 0 and data["cases_skipped"] == 0
            valid = valid and data["outcomes"] == [{"id": PRIMARY, "status": "failed"}, {"id": HEALTHY, "status": "passed"}]
            valid = valid and len(observations) == 1 and json.loads(observations[0]) == {
                "exception": "ValueError", "message": "Port could not be cast to integer value as 'bad'"}
            phase = "BASELINE_DEFECT_REPRODUCED" if valid else "BASELINE_INVALID"
        else:
            valid = valid and completed.returncode == 0 and data["cases_run"] > 0 and data["cases_passed"] == data["cases_run"] and all(data[k] == 0 for k in ("cases_failed", "cases_errors", "cases_skipped"))
            phase = "GREEN" if valid else "FAILED"
        receipt.update(wrapper_exit=0 if valid else 1, phase=phase)
    except Exception as error:
        receipt["error"] = str(error)
    (run / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(run / "receipt.json"), **receipt}, indent=2))
    return receipt["wrapper_exit"]


if __name__ == "__main__":
    raise SystemExit(main())
