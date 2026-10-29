#!/usr/bin/env python3
"""Portable SP101 offline acceptance; receipts are evidence, never release authority."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
SPEC = "SP-10-v1"
ITEM = "SP101-BEACH-CACHE-CLOCK"
BASE = "2979d59bfbb7d724eb83b34a48102b914ee8eaa3"
BASE_SOURCE = "0f75ae255919e0b02541a9364501186b2dda1bd1407eb66251e976f7cbb356bd"
PRIMARY = "src/skippercast/pipeline/beach_health.py"
TEST = "tests/unit/test_sp101_beach_cache_clock.py"
FIXTURES = "tests/fixtures/sp101_beach_cache_clock"
PAIR = ["tests.unit.test_sp101_beach_cache_clock.RegressionTests.test_primary_regression",
        "tests.unit.test_sp101_beach_cache_clock.RegressionTests.test_healthy_control"]
ORIGINAL = ["tests.unit.test_beach_health.PublishTests", "tests.unit.test_beach_health.CollectTests"]
AUTHORS = [{"model": "gpt-6-luna", "provider": "openai-codex", "profile": "luna-worker",
            "scope": "inherited uncommitted initial implementation"},
           {"model": "gpt-6.1-sol", "provider": "openai-codex", "profile": "sol-reviewer",
            "scope": "continued build, final material commit and acceptance"}]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_path(path):
    """Check lexical ancestry BEFORE mkdir, resolve, hash or access."""
    path = Path(os.path.abspath(path))
    for entry in [*reversed(path.parents), path]:
        if entry.is_symlink():
            raise RuntimeError(f"symlink in synthetic ancestry: {entry}")
    return path


def hashes(repo):
    fixture = checked_path(repo / FIXTURES)
    paths = [repo / PRIMARY, repo / TEST, Path(__file__),
             repo / "docs/engineering/sp101_beach_cache_clock.md",
             repo / "tests/unit/test_beach_health.py", repo / "scripts/check_repository.py"]
    for entry in sorted(fixture.rglob("*")):
        checked_path(entry)
        if entry.is_file():
            paths.append(entry)
    return {str(p.relative_to(repo)): sha(p) for p in paths}


def tool(command, repo):
    return subprocess.run(command, cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def child_main(phase, out):
    """Only this process installs irreversible hooks; imported tests leave peers alone."""
    import tempfile
    repo = Path(__file__).resolve().parents[1]
    out = checked_path(out)
    if not out.is_relative_to(checked_path(repo.parent / "out")):
        raise RuntimeError("child evidence must be inside candidate out")
    tmp = out / "tmp"
    tmp.mkdir()
    tempfile.tempdir = str(tmp)
    os.environ["TMPDIR"] = str(tmp)
    os.environ["SKIPPERCAST_ROOT"] = str(repo)
    os.environ["SKIPPERCAST_HTTP_CACHE"] = str(tmp / "http-cache")
    sys.path[:0] = [str(repo), str(repo / "src")]
    trips = []

    def audit(event, args):
        if event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "os.fork", "os.posix_spawn"}:
            trips.append(event)
            raise RuntimeError("offline acceptance tripwire: " + event)
        if event == "import" and str(args[0]).split(".")[0] in {"openai", "anthropic", "ollama", "litellm", "hermes_tools"}:
            trips.append("model-import")
            raise RuntimeError("model SDK import prohibited in offline acceptance")

    sys.addaudithook(audit)
    details = {"runtime": {"executable": sys.executable, "version": sys.version,
                            "prefix": sys.prefix}, "tripwires": trips, "synthetic_tmp": str(tmp)}
    if phase == "repository":
        import runpy
        sys.argv = ["scripts/check_repository.py"]
        try:
            runpy.run_path(str(repo / "scripts/check_repository.py"), run_name="__main__")
            code = 0
        except SystemExit as error:
            code = error.code if isinstance(error.code, int) else 1
        details.update(target_argv=list(sys.argv), exit=code)
    else:
        import inspect
        import unittest
        from skippercast.pipeline import beach_health as bh
        from skippercast.platform import contracts
        if not Path(bh.__file__).resolve().is_relative_to(repo / "src"):
            raise RuntimeError("target imported outside staged repo")
        if contracts.REPO != repo or contracts.load_catalogs.__defaults__[0] != repo:
            raise RuntimeError("package root or bound contract default is not staged repo")
        for func, required in ((bh.due, ("path", "now")), (bh.publish, ("root", "session"))):
            for name in required:
                if inspect.signature(func).parameters[name].default is not inspect.Parameter.empty:
                    raise RuntimeError("unexpected filesystem/session default")
        details["target_file"] = str(Path(bh.__file__).resolve())
        details["package_root"] = str(contracts.REPO)
        details["filesystem_defaults"] = "due(path, now) and publish(root, session) require explicit arguments"
        if phase == "regression":
            from tests.unit import test_beach_health as original
            if original.ROOT != repo or original.ALL_FIXTURES != repo / "tests/fixtures":
                raise RuntimeError("original fixture root outside staged repo")
            # One original missing-file assertion uses this fixed sentinel. Keep
            # original test bytes/selectors intact, but route its nonexistent path
            # to a fresh synthetic missing path before it reaches due().
            def synthetic_path(*parts):
                path = Path(*parts)
                return tmp / "missing/beach-health.json" if str(path) == "/nonexistent/beach-health.json" else path
            original.Path = synthetic_path
            details["path_redirects"] = {"original missing-file sentinel": str(tmp / "missing/beach-health.json")}
        selectors = PAIR if phase == "baseline" else ORIGINAL if phase == "regression" else ["tests.unit.test_sp101_beach_cache_clock"]
        suite = unittest.defaultTestLoader.loadTestsFromNames(selectors)

        def names(node):
            for test in node:
                if isinstance(test, unittest.TestSuite):
                    yield from names(test)
                else:
                    yield test.id()

        selected = list(names(suite))
        outcomes, subtests = [], []

        class Result(unittest.TextTestResult):
            def addSuccess(self, test):
                outcomes.append({"name": test.id(), "status": "pass"})
                super().addSuccess(test)

            def addFailure(self, test, err):
                outcomes.append({"name": test.id(), "status": "failure", "exception": err[0].__name__, "message": str(err[1])})
                super().addFailure(test, err)

            def addError(self, test, err):
                outcomes.append({"name": test.id(), "status": "error", "exception": err[0].__name__})
                super().addError(test, err)

            def addSkip(self, test, reason):
                outcomes.append({"name": test.id(), "status": "skip", "reason": reason})
                super().addSkip(test, reason)

            def addSubTest(self, test, subtest, err):
                subtests.append({"name": subtest.id(), "status": "pass" if err is None else "failure"})
                super().addSubTest(test, subtest, err)

        result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
        counts = {"tests": result.testsRun, "passes": sum(o["status"] == "pass" for o in outcomes),
                  "failures": len(result.failures), "errors": len(result.errors), "skips": len(result.skipped),
                  "expected_failures": len(result.expectedFailures), "unexpected_successes": len(result.unexpectedSuccesses),
                  "subtests": len(subtests)}
        complete = result.testsRun == len(selected) and len(set(selected)) == len(selected) and bool(selected)
        code = 0 if complete and result.wasSuccessful() and not (result.skipped or result.expectedFailures or result.unexpectedSuccesses) else 1
        details.update(selectors=selectors, selected=selected, outcomes=outcomes, subtests=subtests, counts=counts, exit=code)
    (out / "child.json").write_text(json.dumps(details, indent=2) + "\n", encoding="utf-8")
    return 1 if trips else code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=("baseline", "focused", "regression", "repository"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = checked_path(Path(__file__).absolute().parents[1])
    candidate = repo.parent
    manifest_path = candidate / "SOURCE-MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("schema") != "agentorange.source-manifest/v1" or manifest.get("write_root") != str(candidate)
            or manifest.get("repo") != str(repo) or manifest.get("head") != BASE):
        raise RuntimeError("SOURCE-MANIFEST identity mismatch")
    git = shutil.which("git")
    if not git:
        raise RuntimeError("installed git missing")
    head = tool([git, "rev-parse", "HEAD"], repo)
    subprocess.run([git, "merge-base", "--is-ancestor", BASE, head], cwd=repo, check=True)
    py = manifest.get("runtime", {}).get("credential_scan_python3") if args.suite == "repository" else str(repo / ".venv/bin/python3")
    if not py or not Path(py).is_file() or not os.access(py, os.X_OK):
        raise RuntimeError("required manifest/staged interpreter missing; no fallback")
    output = checked_path(args.output)
    if not output.is_relative_to(candidate / "out") or output == candidate / "out":
        raise RuntimeError("output must be a child of candidate out")
    current = hashes(repo)
    if args.suite == "baseline" and (head != BASE or current[PRIMARY] != BASE_SOURCE):
        raise RuntimeError("baseline requires pinned original HEAD and source bytes")
    output.mkdir(parents=True, exist_ok=True)
    out = output / (args.suite + "-" + uuid.uuid4().hex)
    out.mkdir()
    command = [py, "-B", str(Path(__file__).absolute()), "--child", args.suite, str(out)]
    version = tool([py, "--version"], repo)
    child = subprocess.run(command, cwd=repo, capture_output=True)
    (out / "stdout.txt").write_bytes(child.stdout)
    (out / "stderr.txt").write_bytes(child.stderr)
    detail_path = out / "child.json"
    details = json.loads(detail_path.read_text()) if detail_path.is_file() else {}
    clean_counts = details.get("counts", {})
    if args.suite == "baseline":
        outcomes = details.get("outcomes", [])
        failures = [o for o in outcomes if o["status"] == "failure"]
        accepted = (child.returncode == 1 and details.get("selected") == PAIR
                    and clean_counts.get("tests") == 2 and clean_counts.get("passes") == 1
                    and clean_counts.get("failures") == 1 and clean_counts.get("errors") == 0
                    and clean_counts.get("skips") == 0 and clean_counts.get("expected_failures") == 0
                    and clean_counts.get("unexpected_successes") == 0 and len(failures) == 1
                    and failures[0]["name"] == PAIR[0] and failures[0]["exception"] == "AssertionError"
                    and "TypeError" in failures[0]["message"] and "naive successful fetchedAt must be due" in failures[0]["message"]
                    and {"name": PAIR[1], "status": "pass"} in outcomes)
        verdict = "BASELINE_DEFECT_REPRODUCED" if accepted else "FAIL"
    elif args.suite == "repository":
        match = re.search(rb"Checked (\d+) text files:.*passed\.", child.stdout)
        accepted = child.returncode == 0 and bool(match) and int(match[1]) > 0
        clean_counts = {"text_files": int(match[1]) if match else 0}
        verdict = "REVIEW_REQUIRED" if accepted else "FAIL"
    else:
        accepted = (child.returncode == 0 and clean_counts.get("tests", 0) > 0
                    and clean_counts.get("passes") == clean_counts.get("tests")
                    and all(clean_counts.get(k) == 0 for k in ("failures", "errors", "skips", "expected_failures", "unexpected_successes")))
        verdict = "REVIEW_REQUIRED" if accepted else "FAIL"
    accepted = accepted and not details.get("tripwires") and current == hashes(repo)
    if not accepted:
        verdict = "FAIL"
    receipt = {"specification": SPEC, "item_id": ITEM, "phase": args.suite, "staged_base": BASE,
               "head": head, "source_sha256": current[PRIMARY], "file_sha256": current,
               "source_manifest_sha256": sha(manifest_path), "material_authors": AUTHORS,
               "acceptance_runtime": "gpt-6.1-sol/openai-codex/sol-reviewer", "argv": command,
               "orchestrator_argv": [sys.executable, *sys.argv], "cwd": str(repo),
               "interpreter": {"path": py, "realpath": str(Path(py).resolve()), "version": version},
               "git": git, "child_exit": child.returncode, "wrapper_exit": 0 if accepted else 1,
               "counts": clean_counts, "details": details, "verdict": verdict,
               "raw": {name: {"path": str(out / name), "sha256": sha(out / name)}
                       for name in ("stdout.txt", "stderr.txt", "child.json") if (out / name).is_file()}}
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(out / "receipt.json"), "verdict": verdict,
                      "child_exit": child.returncode, "counts": clean_counts}))
    return 0 if accepted else 1


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        raise SystemExit(child_main(sys.argv[2], Path(sys.argv[3])))
    raise SystemExit(main())
