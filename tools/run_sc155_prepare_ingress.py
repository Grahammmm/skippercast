"""SC155 standalone offline acceptance runner for prepare_round --inputs ingress.

Suites: preflight, baseline (unchanged product; expected red), regression (A1),
compatibility (A2, includes the exact original pytest selector via pytest.main) and
negative-control (A3). Literal read-only git checks run before the offline guard;
product imports happen only after the guard is installed. Writes stay under the
invocation root. Exit 0 only when every required assertion ran and passed.
"""
import sys
sys.dont_write_bytecode = True

import argparse
import ast
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sysconfig
import tempfile
import time
import unittest
import uuid
from contextlib import redirect_stdout, redirect_stderr

REPO = Path(__file__).resolve().parents[1]
CANDIDATE = REPO.parent
PRODUCT = "skills/coast-sign-off/scripts/prepare_round.py"
TEST = "tests/unit/test_sc155_prepare_ingress.py"
FIXTURE = "tests/fixtures/sc155-prepare-ingress/constructors.py"
RUNNER = "tools/run_sc155_prepare_ingress.py"
ALLOWED = {PRODUCT, TEST, FIXTURE, RUNNER}
UNCHANGED = ("skills/coast-sign-off/scripts/review_common.py", "skills/coast-campaign-shared/scripts/coast_refs.py",
             "skills/coast-campaign-shared/scripts/validate_coast_receipt.py", "tests/unit/test_coast_sign_off.py",
             "tests/coast_contract_factory.py", "tests/gis/test_coast_sign_off_graph.py", "conftest.py",
             "tests/conftest.py", "pyproject.toml")
NEW_HELPERS = {"_CHUNK", "_snapshot", "_stable", "_open_component", "_read_inputs"}
PRODUCT_IMPORTS = {"errno", "os", "pathlib", "stat", "review_common", "json"}
SELECTOR = "tests/unit/test_coast_sign_off.py::test_prepare_round_requests_shared_v2_contracts"
CLASS = "PrepareIngressTests"
SUITES = {"baseline": ["test_positive_contract", "test_rejects_malformed"],
          "regression": ["test_positive_contract", "test_rejects_malformed"],
          "compatibility": ["test_baseline_compatibility", "test_isolation_and_discovery"],
          "negative-control": ["test_deciding_negative_control"]}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-C", str(REPO), *args])


def require(condition, message):
    if not condition:
        raise ValueError(message)


def top_level(source):
    tree = ast.parse(source)
    names = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names[node.name] = ast.dump(node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names[target.id] = ast.dump(node)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module)
    return names, imports


def preflight(manifest_path, suite):
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    spec_path = CANDIDATE / "ACCEPTANCE-SPEC.json"
    spec = json.loads(spec_path.read_bytes())
    initial = json.loads((CANDIDATE / "INITIAL-STAGE.json").read_bytes())
    base = spec["base"]
    require(manifest["schema"] == "agentorange.source-manifest/v1", "manifest schema")
    require(Path(manifest["write_root"]).resolve() == CANDIDATE, "write_root identity")
    require(Path(manifest["repo"]).resolve() == REPO, "repo identity")
    require(manifest["card"] == CANDIDATE.name, "card identity")
    require(manifest["head"] == base == initial["head"], "staged base identity")
    require(manifest["clean"] is True and initial["clean"] is True, "initial stage cleanliness")
    require(manifest["tree"] == initial["tree"] == git("rev-parse", base + "^{tree}").decode().strip(), "staged tree")
    require(sha(raw) == initial["manifest_sha256"] == spec["manifest_sha256"], "manifest changed")
    runtime = manifest["runtime"]
    require(Path(runtime["repo_venv"]).resolve() == (REPO / ".venv").resolve() == Path(sys.prefix).resolve(),
            "admitted repo interpreter unavailable or mismatched")
    require(runtime["credential_scan_python3"] == spec["credential_scan_python3"], "scan interpreter mismatch")
    require(Path(runtime["credential_scan_python3"]).is_file(), "scan interpreter absent")
    require(manifest["inputs"] == [], "unexpected source inputs")
    head = git("rev-parse", "HEAD").decode().strip()
    subprocess.run(["git", "-C", str(REPO), "merge-base", "--is-ancestor", base, head], check=True)
    changed = set(git("diff", "--name-only", base).decode().splitlines())
    changed.update(git("ls-files", "--others", "--exclude-standard").decode().splitlines())
    require(changed <= ALLOWED, "out-of-scope changes: " + repr(sorted(changed - ALLOWED)))
    base_product = git("show", base + ":" + PRODUCT)
    require(sha(base_product) == spec["product_base_sha256"] == initial["product_sha256"], "base product pin")
    current = (REPO / PRODUCT).read_bytes()
    if suite == "baseline":
        require(current == base_product, "baseline suite requires the unchanged product bytes")
    base_names, _ = top_level(base_product)
    names, imports = top_level(current)
    preservation = dict(
        unchanged_files={p: sha(git("show", base + ":" + p)) == sha((REPO / p).read_bytes()) for p in UNCHANGED},
        prepare_ast_identical=base_names["prepare"] == names["prepare"],
        other_base_defs_identical={k: names.get(k) == v for k, v in base_names.items() if k != "main"},
        new_top_level=sorted(set(names) - set(base_names)),
        product_imports=sorted(imports))
    require(all(preservation["unchanged_files"].values()), "a protected neighbour file changed")
    require(preservation["prepare_ast_identical"], "prepare changed")
    require(all(preservation["other_base_defs_identical"].values()), "a non-main product definition changed")
    require(set(preservation["new_top_level"]) <= NEW_HELPERS, "unadmitted new product definitions")
    require(imports <= PRODUCT_IMPORTS, "unadmitted product import closure")
    return dict(head=head, base=base, initial_stage=initial, manifest_sha256=sha(raw),
                acceptance_spec_sha256=sha(spec_path.read_bytes()), runtime=runtime,
                tracked_status=git("status", "--porcelain", "--untracked-files=all").decode().splitlines(),
                base_preservation=preservation,
                declared_data_closure="No product data roots; main receives explicit synthetic --roots/--inputs/--out "
                                      "below the invocation root. skippercast package is never imported.",
                source_hashes={p: sha((REPO / p).read_bytes()) for p in sorted(ALLOWED)})


def install_guard(root):
    """Process-scoped audit guard for this runner only (not a hostile-code sandbox)."""
    root = root.resolve()
    readable = [REPO, root] + [Path(p).resolve() for p in {sys.prefix, sys.base_prefix, sys.exec_prefix,
                                                            sysconfig.get_path("stdlib"),
                                                            sysconfig.get_path("platstdlib")}]
    events = dict(writes=0, reads_outside_code=0, active=True)

    def checked(path, write):
        if isinstance(path, int) or path is None:
            return
        text = os.fsdecode(path)
        if not write and "/" not in text:
            return  # component name opened relative to a descriptor (no-follow walks)
        p = Path(text).resolve() if text.startswith("/") else (Path.cwd() / text).resolve()
        if p.is_relative_to(root):
            events["writes" if write else "reads_outside_code"] += 1
            return
        if p == Path("/dev/null"):
            return  # pytest's logging plugin opens the null device as its default log file
        if not write and any(p.is_relative_to(b) for b in readable):
            return
        raise RuntimeError("SC155 offline file boundary: " + ("write " if write else "read ") + str(p))

    def audit(event, args):
        if not events["active"]:
            return
        if event.startswith(("socket.", "subprocess.", "os.exec", "os.spawn", "os.posix_spawn")) or event in {
                "os.system", "os.fork", "os.forkpty", "pty.spawn", "ctypes.dlopen", "urllib.Request",
                "http.client.connect"}:
            raise RuntimeError("SC155 no-network/no-model/no-child-execution: " + event)
        if event == "open":
            path, mode, flags = args
            write = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool(
                (flags or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if not write and (flags or 0) & os.O_DIRECTORY:
                return
            checked(path, write)
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.truncate", "os.utime"}:
            checked(args[0], True)
        elif event in {"os.rename", "os.link", "os.symlink"}:
            checked(args[0] if event != "os.symlink" else args[1], True)
            checked(args[1], True)

    tempfile.tempdir = str(root)
    sys.addaudithook(audit)
    return events


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.executed_ids, self.subtests = [], []

    def startTest(self, test):
        self.executed_ids.append(test.id())
        super().startTest(test)

    def addSubTest(self, test, subtest, err):
        self.subtests.append(dict(id=subtest.id(), params=dict(subtest.params),
                                  outcome="pass" if err is None else
                                  ("fail" if issubclass(err[0], test.failureException) else "error")))
        super().addSubTest(test, subtest, err)


def run_tests(tests, names, run, stem):
    stream = io.StringIO()
    suite = unittest.TestSuite(getattr(tests, CLASS)(name) for name in names)
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=RecordedResult).run(suite)
    text = stream.getvalue()
    (run / (stem + ".txt")).write_text(text)
    return result, dict(executed_ids=result.executed_ids, count=result.testsRun, subtests=result.subtests,
                        subtest_count=len(result.subtests), skips=len(result.skipped),
                        failures=[f[0].id() for f in result.failures], errors=[e[0].id() for e in result.errors],
                        raw_file=stem + ".txt", raw_sha256=sha(text.encode()),
                        success=result.wasSuccessful() and not result.skipped and result.testsRun == len(names))


def required_cases(tests, details, wanted):
    seen = {s["params"].get("case"): s["outcome"] for s in details["subtests"]}
    return {case: seen.get(case) for case in wanted}


class Collector:
    def __init__(self):
        self.reports = []

    def pytest_runtest_logreport(self, report):
        self.reports.append(dict(nodeid=report.nodeid, when=report.when, outcome=report.outcome))

    def pytest_collectreport(self, report):
        if report.outcome != "passed":
            self.reports.append(dict(nodeid=report.nodeid, when="collect", outcome=report.outcome))


def run_selector(run):
    import pytest
    collector = Collector()
    environ, path, modules = dict(os.environ), list(sys.path), set(sys.modules)
    # The selector's validate_coast_receipt imports sibling coast_native by name; in the full
    # suite an earlier review_common import puts the shared scripts directory on sys.path.
    # Supply that same candidate path here (restored below) instead of editing the original test.
    sys.path.insert(0, str(REPO / "skills/coast-campaign-shared/scripts"))
    stream = io.StringIO()
    with redirect_stdout(stream), redirect_stderr(stream):
        code = pytest.main([str(REPO / SELECTOR.split("::")[0]) + "::" + SELECTOR.split("::")[1],
                            "-p", "no:cacheprovider", "--disable-plugin-autoload", "-q", "--rootdir", str(REPO),
                            "-c", str(REPO / "pyproject.toml")],
                           plugins=[collector])
    env_changes = sorted(k for k in set(environ) | set(os.environ) if environ.get(k) != os.environ.get(k))
    os.environ.clear()
    os.environ.update(environ)
    sys.path[:] = path
    text = stream.getvalue()
    (run / "pytest-selector.txt").write_text(text)
    calls = [r for r in collector.reports if r["when"] == "call"]
    passed = [r["nodeid"] for r in calls if r["outcome"] == "passed"]
    other = [r for r in collector.reports if r["outcome"] not in ("passed",)]
    return dict(selector=SELECTOR, exit=int(code), calls=calls, passed=passed, non_passed=other,
                raw_file="pytest-selector.txt", raw_sha256=sha(text.encode()),
                environ_restored_keys=env_changes, new_modules=len(set(sys.modules) - modules),
                success=int(code) == 0 and passed == [SELECTOR] and len(calls) == 1 and not other)


def load_tests_module():
    spec = importlib.util.spec_from_file_location("sc155_tests", REPO / TEST)
    module = importlib.util.module_from_spec(spec)
    sys.modules["sc155_tests"] = module
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=["preflight", *SUITES])
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    identity = preflight(args.source_manifest.resolve(), args.suite)
    require(args.out.resolve().is_relative_to(CANDIDATE / "out"), "output prefix outside candidate out/")
    run = args.out.resolve() / (args.suite + "-" + uuid.uuid4().hex)
    run.mkdir(parents=True, exist_ok=False)
    report = dict(suite=args.suite, argv=sys.argv, cwd=str(Path.cwd()), interpreter=sys.executable,
                  python=sys.version, run_root=str(run), **identity)
    started = time.monotonic()
    import pytest  # noqa: F401  (runtime dependency imported before the guard, not product code)
    guard = install_guard(run)
    tests = load_tests_module()
    tests.RUN_ROOT = run
    ok = False
    if args.suite == "preflight":
        report["checks"] = ["manifest", "candidate/repo/base/tree", "initial-stage", "runtime", "descendant-head",
                            "allowed-write-set", "base-preservation", "import-closure", "guard-installed"]
        ok = True
    elif args.suite in ("baseline", "regression"):
        result, details = run_tests(tests, SUITES[args.suite], run, "tests")
        report["tests"] = details
        cases = required_cases(tests, details, tests.POSITIVE_CASES + tests.MALFORMED_CASES)
        report["required_cases"] = cases
        complete = all(v is not None for v in cases.values())
        if args.suite == "regression":
            ok = details["success"] and complete and all(v == "pass" for v in cases.values())
        else:
            red = [c for c, v in cases.items() if v != "pass"]
            prefix = tests.__name__ + "." + CLASS + ".test_rejects_malformed"
            report["baseline_red_cases"] = red
            report["baseline_expected_failure_observed"] = (
                complete and bool(details["failures"]) and all(f.startswith(prefix) for f in details["failures"])
                and not details["errors"] and all(cases[c] == "pass" for c in tests.POSITIVE_CASES) and bool(red)
                and all(cases[c] == "fail" for c in red))
            ok = False  # the baseline is expected red; exit nonzero
    elif args.suite == "compatibility":
        result, details = run_tests(tests, SUITES[args.suite], run, "tests")
        report["tests"] = details
        report["original_selector"] = run_selector(run)
        ok = details["success"] and report["original_selector"]["success"]
    else:
        result, details = run_tests(tests, SUITES[args.suite], run, "tests")
        report["tests"] = details
        summary = [r for r in tests.RECORDS if r.get("case") == "negative-control-summary"]
        mutants = [r for r in tests.RECORDS if str(r.get("label", "")).startswith("mutant")]
        restored = [r for r in tests.RECORDS if str(r.get("label", "")).startswith("restored")]
        detected = summary[0]["detected"] if summary else {}
        report["mutants"] = mutants
        report["mutant_detected"] = (len(detected) == 3 and len(mutants) == 3 and
                                     mutants[0]["requests"][:1] == [tests.UNBOUNDED] and
                                     all(m["outcome"] == "prepare" for m in mutants))
        report["positive_passed"] = details["success"] and any(r["label"] == "restored-positive" and
                                                               r["outcome"] == "prepare" for r in restored)
        ok = details["success"] and report["mutant_detected"] and report["positive_passed"]
    report["duration_seconds"] = time.monotonic() - started
    # Test execution finished: the guard is switched off before candidate-level identity rechecks.
    guard["active"] = False
    report["cases"] = tests.RECORDS
    report["guard_events"] = guard
    report["skippercast_imported"] = any(m == "skippercast" or m.startswith("skippercast.") for m in sys.modules)
    report["sys_path_outside_repo_and_runtime"] = [p for p in sys.path if p and not any(
        Path(p).resolve().is_relative_to(b) for b in (REPO, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()))]
    report["loaded_runtime_code"] = sorted({str(Path(m.__file__).resolve()) for m in tuple(sys.modules.values())
                                            if getattr(m, "__file__", None) and not str(m.__file__).startswith("<")})
    report["fixture_sha256"] = sha((REPO / FIXTURE).read_bytes())
    report["source_hashes_after"] = {p: sha((REPO / p).read_bytes()) for p in sorted(ALLOWED)}
    require(report["source_hashes_after"] == report["source_hashes"], "source mutated during acceptance")
    require(sha(args.source_manifest.read_bytes()) == identity["manifest_sha256"], "manifest mutated")
    if report["skippercast_imported"]:
        ok = False
    report["success"] = ok
    report["limits"] = ["Synthetic evidence only; machine validity is REVIEW REQUIRED, not semantic acceptance.",
                        "Scoped direct-API rows plus one original selector; full original CI is OWED at exact head.",
                        "Special files are modeled through an inert stat seam; no FIFO/device is created.",
                        "The audit guard constrains this cooperative runner, not hostile code."]
    raw = json.dumps(report, indent=2, default=str).encode() + b"\n"
    (run / "receipt.json").write_bytes(raw)
    print(json.dumps(dict(receipt=str(run / "receipt.json"), receipt_sha256=sha(raw), success=ok,
                          head=identity["head"], count=report.get("tests", {}).get("count"),
                          subtests=report.get("tests", {}).get("subtest_count"),
                          failures=report.get("tests", {}).get("failures"),
                          baseline_red_cases=report.get("baseline_red_cases"),
                          baseline_expected_failure_observed=report.get("baseline_expected_failure_observed"),
                          selector=(report.get("original_selector") or {}).get("success"),
                          mutant_detected=report.get("mutant_detected"),
                          positive_passed=report.get("positive_passed")), indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
