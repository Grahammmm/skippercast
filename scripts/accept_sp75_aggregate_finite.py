"""File-based, fail-closed offline acceptance for SP75. No installed-runtime fallback."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

BASE = "a1f648632e64561d82dcbeb20d9bda19f812560a"
BASE_SOURCE = "16410edbc37ddd23b7d13020ea03540e9fe5afd589d42b65fd3f0c3cef9fffa9"
PRODUCT = "src/skippercast/fleet/ais/aggregate/base.py"
TEST = "tests/unit/test_sp75_aggregate_finite.py"
FOCUSED = "tests.unit.test_sp75_aggregate_finite.AggregateFiniteTests"
PRIMARY = FOCUSED + ".test_A4_primary_nan_delay"
HEALTHY = FOCUSED + ".test_A4_healthy_control"
SELECTORS = (
    "tests.unit.test_fleet_events.AggregateTest",
    "tests.unit.test_fleet_aggregate.ResolutionByKind",
    "tests.unit.test_fleet_aggregate.LegacyKinds",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def inspect_closure(repo, selectors):
    """Resolve local imports without importing targets; retain hashes and dormant process sites.

    Test modules cannot launch children. Product imports include forecast.local's dormant
    node sampler through config adapters; the runtime process sentinel forbids that path.
    External packages remain the operator-qualified staged dependency closure.
    """
    def path_for(name):
        for root in (repo, repo / "src"):
            path = root.joinpath(*name.split("."))
            if path.with_suffix(".py").is_file():
                return path.with_suffix(".py")
            if (path / "__init__.py").is_file():
                return path / "__init__.py"
        return None

    queue = []
    for selector in selectors:
        module_name, _, class_name = selector.rpartition(".")
        if selector in (PRIMARY, HEALTHY):
            module_name, _, class_name = FOCUSED.rpartition(".")
        path = path_for(module_name)
        if path is None:
            raise ValueError("missing selector module: " + selector)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name]
        if len(classes) != 1 or not any(isinstance(n, ast.FunctionDef) and n.name.startswith("test_") for n in classes[0].body):
            raise ValueError("required selector absent: " + selector)
        queue.append(module_name)
    closure = {}
    process_names = {"run", "Popen", "call", "check_call", "check_output", "system", "popen",
                     "spawn", "fork", "execv", "execve", "Process", "ProcessPoolExecutor",
                     "create_subprocess_exec", "create_subprocess_shell", "spawnv", "spawnve"}
    while queue:
        name = queue.pop()
        path = path_for(name)
        if name in closure or path is None:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        process_sites = []
        imports = []
        for index in range(1, len(name.split("."))):
            queue.append(".".join(name.split(".")[:index]))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = importlib.util.resolve_name("." * node.level + (node.module or ""), package) if node.level else node.module
                if base:
                    imports.append(base)
                    imports.extend(base + "." + alias.name for alias in node.names)
            elif isinstance(node, ast.Call):
                func = node.func
                called = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
                if called in process_names:
                    process_sites.append({"line": node.lineno, "call": ast.unparse(node)})
        if name.startswith("tests.") and process_sites:
            raise ValueError("unadmitted test child-command site: " + name)
        closure[name] = {"path": path.relative_to(repo).as_posix(), "sha256": digest(path),
                         "imports": sorted(set(imports)), "dormant_process_sites": process_sites}
        queue.extend(imports)
    return closure


def install_sentinels(run):
    """Fresh child only: defense in depth, not a hostile-code sandbox."""
    import tempfile
    tempfile.tempdir = str(run / "tmp")
    attempts = []

    def audit(event, args):
        forbidden = event.startswith(("subprocess.", "os.exec", "os.spawn")) or event in {
            "os.system", "os.fork", "os.forkpty", "socket.connect", "socket.bind",
            "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.sendto",
        }
        if event == "import" and str(args[0]).split(".")[0] in {"openai", "anthropic", "ollama", "litellm"}:
            forbidden = True
        if event == "open" and not isinstance(args[0], int):
            mode, flags = args[1], args[2]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing and not Path(args[0]).resolve().is_relative_to(run):
                forbidden = True
        if event in {"os.remove", "os.rmdir", "os.mkdir", "os.rename"}:
            paths = args[:2] if event == "os.rename" else args[:1]
            if any(not Path(p).resolve().is_relative_to(run) for p in paths):
                forbidden = True
        if forbidden:
            attempts.append(event)
            raise RuntimeError("SP75_OFFLINE_BOUNDARY: " + event)
    sys.addaudithook(audit)
    return attempts


def child(phase, run):
    repo = Path(__file__).resolve().parents[1]
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(repo), str(repo / "src")]
    attempts = install_sentinels(run)
    if phase == "repository":
        import runpy
        # File-based invocation of the unchanged scanner, under its manifest runtime.
        sys.argv = [str(repo / "scripts/check_repository.py")]
        exit_code = 0
        try:
            runpy.run_path(sys.argv[0], run_name="__main__")
        except SystemExit as error:
            exit_code = error.code if isinstance(error.code, int) else 1
        save(run / "child-summary.json", {"scan_exit": exit_code, "boundary_attempts": attempts})
        return exit_code if not attempts else 2

    # This inspected module has declarations only at import time. The audit
    # sentinel is already active before its import; deny fetch/cache APIs too.
    import skippercast.http as http

    def no_fetch(*args, **kwargs):
        attempts.append("skippercast.http.fetch_or_cache")
        raise RuntimeError("SP75_OFFLINE_BOUNDARY: fetch/cache")

    for method in ("request", "get", "post", "head", "download"):
        setattr(http.Session, method, no_fetch)
    http.default_session = no_fetch
    http.HTTPCache.__init__ = no_fetch

    import unittest
    selectors = (PRIMARY, HEALTHY) if phase == "baseline" else SELECTORS if phase == "regression" else (FOCUSED,)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    selected_counts = {}
    for selector in selectors:
        selected = loader.loadTestsFromName(selector)
        selected_counts[selector] = selected.countTestCases()
        if not selected_counts[selector] or loader.errors:
            raise ValueError("required selector unavailable: " + selector)
        suite.addTests(selected)

    class Result(unittest.TextTestResult):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.successes = []

        def addSuccess(self, test):
            self.successes.append(test.id())
            super().addSuccess(test)

    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    summary = {
        "selected_counts": selected_counts, "tests_run": result.testsRun,
        "passed": result.successes, "failed": [test.id() for test, _ in result.failures],
        "errors": [test.id() for test, _ in result.errors],
        "skips": [test.id() for test, _ in result.skipped],
        "unexpected_successes": [test.id() for test in result.unexpectedSuccesses],
        "expected_failures": [test.id() for test, _ in result.expectedFailures],
        "boundary_attempts": attempts,
    }
    save(run / "child-summary.json", summary)
    return 0 if result.wasSuccessful() and not attempts and not result.skipped and not result.expectedFailures else 1


def main():
    if len(sys.argv) == 5 and sys.argv[1] == "--child":
        return child(sys.argv[2], Path(sys.argv[4]).resolve()) if sys.argv[3] == "--run" else 2
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", required=True, choices=("baseline", "focused", "regression", "repository"))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    script = Path(__file__).resolve()
    repo, root = script.parents[1], script.parents[2]
    parent = Path(args.output).resolve()
    if not parent.is_relative_to(root / "out"):
        raise ValueError("output must be inside candidate out/")
    run = parent / (args.suite + "-" + str(time.time_ns()) + "-" + uuid.uuid4().hex[:8])
    run.mkdir(parents=True, exist_ok=False)
    (run / "tmp").mkdir()
    receipt = {"schema_version": 1, "phase": args.suite, "status": "HARNESS_FAILED", "wrapper_exit": 2,
               "wrapper_argv": [sys.executable, str(script), *sys.argv[1:]], "wrapper_cwd": str(Path.cwd()),
               "staging_base": BASE, "cwd": str(repo), "child_exit": None,
               "cases_passed": 0, "cases_failed": 0, "cases_errors": 0, "cases_skips": 0}
    try:
        manifest_path = root / "SOURCE-MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("head") != BASE or manifest.get("repo") != str(repo):
            raise ValueError("staging manifest mismatch")
        receipt["manifest_sha256"] = digest(manifest_path)
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()
        subprocess.run(["git", "merge-base", "--is-ancestor", BASE, head], cwd=repo, check=True)
        receipt["actual_head"] = head
        receipt["source_sha256"] = digest(repo / PRODUCT)
        receipt["test_sha256"] = digest(repo / TEST)
        receipt["launcher_sha256"] = digest(script)
        fixture_root = repo / "tests/fixtures/sp75_aggregate_finite"
        receipt["fixture_sha256"] = {p.relative_to(repo).as_posix(): digest(p) for p in sorted(fixture_root.rglob("*")) if p.is_file()}
        if not receipt["fixture_sha256"]:
            raise ValueError("missing synthetic fixtures")
        if args.suite == "baseline" and receipt["source_sha256"] != BASE_SOURCE:
            raise ValueError("baseline requires unchanged pinned product bytes")
        selectors = SELECTORS if args.suite == "regression" else (FOCUSED,)
        if args.suite != "repository":
            closure = inspect_closure(repo, selectors)
            save(run / "import-closure.json", closure)
            receipt["closure_path"] = str(run / "import-closure.json")
            receipt["closure_sha256"] = digest(run / "import-closure.json")
            # Unowned dependency/test sources must match the staged base, not ambient main.
            for entry in closure.values():
                if entry["path"] in (PRODUCT, TEST):
                    continue
                pinned = subprocess.run(["git", "show", BASE + ":" + entry["path"]], cwd=repo, capture_output=True, check=True).stdout
                if hashlib.sha256(pinned).hexdigest() != entry["sha256"]:
                    raise ValueError("changed unowned import closure: " + entry["path"])
        else:
            pinned = subprocess.run(["git", "show", BASE + ":scripts/check_repository.py"], cwd=repo, capture_output=True, check=True).stdout
            if hashlib.sha256(pinned).hexdigest() != digest(repo / "scripts/check_repository.py"):
                raise ValueError("repository scanner changed")
        interpreter = Path(manifest["runtime"]["credential_scan_python3"]) if args.suite == "repository" else repo / ".venv/bin/python3"
        if not interpreter.is_file():
            raise ValueError("required staged interpreter unavailable")
        version = subprocess.run([str(interpreter), "--version"], cwd=repo, text=True, capture_output=True, check=True)
        argv = [str(interpreter), str(script), "--child", args.suite, "--run", str(run)]
        receipt["runtime"] = {"argv0": str(interpreter), "resolved_executable": str(interpreter.resolve()),
                              "version": (version.stdout + version.stderr).strip()}
        receipt["child_argv"] = argv
        if args.suite == "repository":
            receipt["scanner_argv"] = [str(interpreter), str(repo / "scripts/check_repository.py")]
        env = dict(os.environ, TMPDIR=str(run / "tmp"), PYTHONDONTWRITEBYTECODE="1")
        # Confine inherited project roots/cache settings before target imports and default binding.
        env["SKIPPERCAST_ROOT"] = str(repo)
        for key in tuple(env):
            if key.startswith("SKIPPERCAST_") and key != "SKIPPERCAST_ROOT":
                del env[key]
        completed = subprocess.run(argv, cwd=repo, text=True, capture_output=True, env=env)
        for channel in ("stdout", "stderr"):
            path = run / ("child." + channel)
            path.write_text(getattr(completed, channel), encoding="utf-8")
            receipt[channel + "_path"] = str(path)
            receipt[channel + "_sha256"] = digest(path)
        receipt["child_exit"] = completed.returncode
        summary = json.loads((run / "child-summary.json").read_text(encoding="utf-8"))
        receipt["summary_path"] = str(run / "child-summary.json")
        receipt["summary_sha256"] = digest(run / "child-summary.json")
        if args.suite == "repository":
            match = re.fullmatch(r"Checked (\d+) text files: local Markdown links, release privacy rules and the Text Advisor and charter fleet fixture scans passed\.\n", completed.stdout)
            valid = completed.returncode == 0 and summary["scan_exit"] == 0 and not summary["boundary_attempts"] and match is not None
            receipt["text_files_checked"] = int(match.group(1)) if match else 0
        else:
            for key in ("passed", "failed", "errors", "skips"):
                receipt["cases_" + key] = len(summary[key])
            receipt["tests_run"] = summary["tests_run"]
            clean = not any(summary[k] for k in ("errors", "skips", "unexpected_successes", "expected_failures", "boundary_attempts"))
            complete = summary["tests_run"] == sum(summary["selected_counts"].values()) and summary["tests_run"] > 0
            if args.suite == "baseline":
                outcomes = [json.loads(line.split("=", 1)[1]) for line in completed.stdout.splitlines() if line.startswith("SP75_PRIMARY_OUTCOME=")]
                valid = completed.returncode == 1 and clean and complete and summary["tests_run"] == 2 and summary["failed"] == [PRIMARY] and summary["passed"] == [HEALTHY] and "SP75_PRIMARY_NAN_ACCEPTED" in completed.stderr and len(outcomes) == 1 and outcomes[0]["kind"] == "returned"
            else:
                valid = completed.returncode == 0 and clean and complete and not summary["failed"] and len(summary["passed"]) == summary["tests_run"]
        receipt["wrapper_exit"] = 0 if valid else 1
        receipt["status"] = ("BASELINE_DEFECT_REPRODUCED" if args.suite == "baseline" else "GREEN") if valid else "CONTRACT_FAILED"
    except Exception as error:
        receipt["harness_error"] = type(error).__name__ + ": " + str(error)
    save(run / "receipt.json", receipt)
    print(json.dumps(receipt, sort_keys=True))
    return receipt["wrapper_exit"]


if __name__ == "__main__":
    raise SystemExit(main())
