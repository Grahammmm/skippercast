"""Acceptance runner for SC-SCHEMA-CLOSURE (scripts/coast_diagnostics/schema_closure.py).

    python3 scripts/accept_sc_schema_closure.py --suite {focused,contract,negative} --output <new-dir>

Runs the named unittest group from tests/unit/test_sc_schema_closure.py in-process with the
already-installed interpreter (stdlib unittest; no pytest needed). Before importing any project
module it suppresses bytecode, pins sys.path to THIS staged repository, redirects temporary files
and HOME into the run directory, and installs DNS/socket/HTTP/subprocess/model sentinels. The
sentinels are regression guards, not a hostile-code sandbox.

The output directory must not exist (write-once). Raw stdout/stderr, unittest output, counts,
argv/cwd, interpreter, git HEAD (read from .git files, no subprocess) and SHA256 of code and
fixtures are retained there in receipt.json. Exit 0 only when every assertion of the suite passes
with zero skips; the negative suite additionally proves that its completeness gate detects an
isolated broken control, that the gate is what decides, and that the positive control passes.
Local success is REVIEW REQUIRED, not full CI or semantic acceptance.
"""
import sys

sys.dont_write_bytecode = True

import hashlib  # noqa: E402
import importlib.util  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402
import platform  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "scripts" / "coast_diagnostics" / "schema_closure.py"
TESTS = REPO / "tests" / "unit" / "test_sc_schema_closure.py"
FIXTURES = REPO / "tests" / "fixtures" / "sc_schema_closure"
SUITES = {"focused": "TestFocusedClosure", "contract": "TestContractRealFamily", "negative": "TestNegativeClosure"}
BLOCKED_EVENTS = ("socket.", "subprocess.", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork",
                  "os.forkpty", "urllib.Request", "http.client.connect", "webbrowser.open", "ftplib.", "smtplib.",
                  "imaplib.", "poplib.", "nntplib.", "telnetlib.")
BLOCKED_MODULES = ("anthropic", "openai", "ollama", "requests", "httpx", "urllib3", "aiohttp", "jsonschema",
                   "referencing", "google", "boto3", "botocore")
FORBIDDEN_TARGET_IMPORTS = {"socket", "ssl", "http", "urllib", "subprocess", "multiprocessing", "asyncio",
                            "ctypes", "jsonschema", "referencing"} | set(BLOCKED_MODULES)
SENTINEL_HITS = []


class Tee(io.TextIOBase):
    def __init__(self, stream):
        self.stream, self.buffer_text = stream, io.StringIO()

    def write(self, text):
        self.buffer_text.write(text)
        return self.stream.write(text)

    def flush(self):
        self.stream.flush()


def audit(event, args):
    if event.startswith(BLOCKED_EVENTS):
        SENTINEL_HITS.append(event)
        raise RuntimeError(f"sentinel: blocked {event}")


class BlockModels:
    """Meta-path finder refusing network clients, model SDKs and schema engines."""

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED_MODULES:
            SENTINEL_HITS.append(f"import:{name}")
            raise ImportError(f"sentinel: blocked import {name}")
        return None


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_head():
    git = REPO / ".git"
    head = (git / "HEAD").read_text(encoding="utf-8").strip()
    if not head.startswith("ref: "):
        return head
    ref = head[5:]
    loose = git / ref
    if loose.is_file():
        return loose.read_text(encoding="utf-8").strip()
    packed = git / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split()[0]
    return "UNKNOWN"


def fixture_hashes():
    rows = {}
    for path in sorted(FIXTURES.rglob("*")):
        if path.is_symlink():
            raise SystemExit(f"fixture symlink refused: {path}")
        if path.is_file():
            rows[path.relative_to(REPO).as_posix()] = sha256_file(path)
    return rows


def write_new(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


def parse_args(argv):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", required=True, choices=sorted(SUITES))
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def negative_controls(sc, tests, receipt):
    """Isolated broken control for the closure-completeness gate, gate-disabled proof, positive control."""
    manifest = json.loads((FIXTURES / "real" / "pinned-manifest.json").read_text(encoding="utf-8"))
    oracle = json.loads((FIXTURES / "real" / "oracle-expected-refs.json").read_text(encoding="utf-8"))["references"]
    controls = {}
    # Positive control: the unmodified tool output satisfies the gate.
    report = sc.inspect_closure(manifest, REPO)
    tests.assert_closure_complete(report, oracle)
    controls["positive"] = {"edges": len(report["edges"]), "gate": "passed"}
    # Broken control: an in-memory callable double drops exactly one real edge inside the tool
    # (every other field, hash and count path left to the real code).
    victim_ref = sorted(report["edges"], key=tests.edge_key)[0]
    real_resolve = sc._resolve_reference

    def dropping_double(occurrence, *args, **kwargs):
        row = real_resolve(occurrence, *args, **kwargs)
        if (occurrence["source_path"], occurrence["pointer"]) == (victim_ref["source_path"], victim_ref["pointer"]):
            return dict(row, classification="unresolved_resource", resolution_target=None, edge=None)
        return row

    sc._resolve_reference = dropping_double
    try:
        broken = sc.inspect_closure(manifest, REPO)
    finally:
        sc._resolve_reference = real_resolve
    try:
        tests.assert_closure_complete(broken, oracle)
    except AssertionError as error:
        detected = str(error)
    else:
        raise AssertionError("broken control was NOT detected by the closure-completeness gate")
    if tests.missing_edges(broken, oracle) != [tests.edge_key(victim_ref)]:
        raise AssertionError("broken control detected for the wrong reason")
    controls["broken"] = {"victim": list(tests.edge_key(victim_ref)), "detected": detected[:400],
                          "broken_exit_code": broken["exit_code"], "edges": len(broken["edges"])}
    # Gate disabled: every other observable check is unchanged for the broken report (same pins,
    # exit code, status, findings), so with the completeness check replaced by a no-op it would be
    # accepted; the completeness gate, not another prerequisite, is what rejects it.
    no_op_gate = (lambda report, rows: None)
    no_op_gate(broken, oracle)
    same = {key: broken[key] == report[key] for key in
            ("schema", "execution_allowed", "exit_code", "status", "input", "findings", "nodes", "dialects")}
    if not all(same.values()):
        raise AssertionError(f"broken control is not isolated: {same}")
    controls["gate_disabled"] = {"broken_report_accepted_without_gate": True, "other_fields_identical": same}
    # Restore check: the real function is back and the positive control passes again.
    again = sc.inspect_closure(manifest, REPO)
    tests.assert_closure_complete(again, oracle)
    if json.dumps(again, sort_keys=True) != json.dumps(report, sort_keys=True):
        raise AssertionError("restored tool output differs from the positive control")
    controls["restored_positive"] = {"edges": len(again["edges"]), "gate": "passed", "identical": True}
    receipt["controls"] = controls


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    output = Path(os.path.abspath(args.output))
    if not output.parent.is_dir() or output.parent.is_symlink():
        print(f"output parent must be an existing non-symlink directory: {output.parent}", file=sys.stderr)
        return 2
    try:
        os.mkdir(output)
    except FileExistsError:
        print(f"output already exists (write-once): {output}", file=sys.stderr)
        return 2
    stdout, stderr = Tee(sys.stdout), Tee(sys.stderr)
    sys.stdout, sys.stderr = stdout, stderr
    receipt = {"schema": "sc-schema-closure-acceptance-v1", "suite": args.suite,
               "argv": [sys.executable] + sys.argv, "cwd": os.getcwd(),
               "python": {"executable": sys.executable, "version": platform.python_version()},
               "repo": str(REPO), "git_head": git_head(), "result": "FAIL",
               "review_required": True, "full_ci": False}
    status = 1
    try:
        # Redirect every writable default into the run directory BEFORE project imports.
        tmp, home = output / "tmp", output / "home"
        tmp.mkdir()
        home.mkdir()
        import tempfile
        tempfile.tempdir = str(tmp)
        os.environ.update({"TMPDIR": str(tmp), "TEMP": str(tmp), "TMP": str(tmp), "HOME": str(home),
                           "PYTHONDONTWRITEBYTECODE": "1", "SKIPPERCAST_NETWORK": "0"})
        sys.path[:] = [str(REPO)] + [p for p in sys.path if p and Path(p).resolve() != REPO and "site-packages" not in p]
        sys.meta_path.insert(0, BlockModels())
        sys.addaudithook(audit)
        # Sentinel self-checks use synthetic audit events only (no real outbound attempt or spawn).
        for event, event_args in (("socket.connect", (None, ("192.0.2.1", 9))),
                                  ("socket.getaddrinfo", ("example.invalid", 80, 0, 0, 0)),
                                  ("subprocess.Popen", ("/bin/false", ["false"], None, None)),
                                  ("urllib.Request", ("https://example.invalid/", None, {}, "GET"))):
            try:
                sys.audit(event, *event_args)
            except RuntimeError:
                continue
            raise AssertionError(f"sentinel inactive for {event}")
        try:
            importlib.util.find_spec("anthropic")
        except ImportError:
            pass
        else:
            raise AssertionError("model import sentinel inactive")
        self_check_hits = list(SENTINEL_HITS)
        SENTINEL_HITS.clear()
        receipt["sentinels"] = {"self_check_events_blocked": self_check_hits, "blocked_events": list(BLOCKED_EVENTS),
                                "blocked_modules": list(BLOCKED_MODULES)}

        before = set(sys.modules)
        spec = importlib.util.spec_from_file_location("sc_schema_closure_under_test", MODULE)
        sc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sc)
        new_modules = sorted(set(sys.modules) - before)
        bad = sorted(m for m in new_modules if m.split(".")[0] in FORBIDDEN_TARGET_IMPORTS)
        receipt["target_transitive_imports"] = new_modules
        if bad:
            raise AssertionError(f"target module imported forbidden modules: {bad}")
        import inspect
        defaults = {}
        for name, value in vars(sc).items():
            if inspect.isfunction(value) and value.__module__ == sc.__name__:
                for pname, param in inspect.signature(value).parameters.items():
                    if param.default is not inspect.Parameter.empty:
                        defaults[f"{name}.{pname}"] = repr(param.default)
            if (not name.startswith("__") and isinstance(value, (str, os.PathLike))
                    and os.path.isabs(os.fspath(value))):
                raise AssertionError(f"target constant {name} is an absolute path; redirect required")
        receipt["target_bound_defaults"] = defaults
        if any(os.sep in v or "/" in v for v in defaults.values()):
            raise AssertionError(f"target bound default looks like a path: {defaults}")

        spec = importlib.util.spec_from_file_location("test_sc_schema_closure_runner", TESTS)
        tests = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tests)
        import unittest
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(getattr(tests, SUITES[args.suite]))
        receipt["test_ids"] = [t.id() for t in suite]
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        write_new(output / "unittest.txt", stream.getvalue())
        counts = {"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                  "skipped": len(result.skipped), "expected_failures": len(result.expectedFailures),
                  "unexpected_successes": len(result.unexpectedSuccesses)}
        receipt["counts"] = counts
        print(stream.getvalue())
        ok = (result.wasSuccessful() and counts["skipped"] == 0 and counts["expected_failures"] == 0
              and counts["tests_run"] == len(receipt["test_ids"]) and counts["tests_run"] > 0)
        if ok and args.suite == "contract":
            manifest = json.loads((FIXTURES / "real" / "pinned-manifest.json").read_text(encoding="utf-8"))
            report = sc.inspect_closure(manifest, REPO)
            write_new(output / "real-report.json", sc.serialize(report))
            receipt["real_report"] = {"exit_code": report["exit_code"], "status": report["status"],
                                      "counts": report["counts"],
                                      "sha256": hashlib.sha256(sc.serialize(report).encode()).hexdigest()}
        if ok and args.suite == "negative":
            negative_controls(sc, tests, receipt)
        if SENTINEL_HITS:
            raise AssertionError(f"sentinel hits during suite: {SENTINEL_HITS}")
        receipt["sentinel_hits_during_suite"] = []
        if ok:
            receipt["result"] = "PASS_REVIEW_REQUIRED"
            status = 0
    except BaseException as error:  # noqa: BLE001 - recorded, never swallowed silently
        receipt["error"] = f"{type(error).__name__}: {error}"
        print(receipt["error"], file=sys.stderr)
        status = 1
    finally:
        receipt["code_sha256"] = {p.relative_to(REPO).as_posix(): sha256_file(p)
                                  for p in (MODULE, TESTS, Path(__file__).resolve()) if p.is_file()}
        receipt["fixture_sha256"] = fixture_hashes()
        receipt["exit"] = status
        print(f"suite={args.suite} result={receipt['result']} exit={status} counts={receipt.get('counts')}")
        sys.stdout, sys.stderr = stdout.stream, stderr.stream
        write_new(output / "stdout.txt", stdout.buffer_text.getvalue())
        write_new(output / "stderr.txt", stderr.buffer_text.getvalue())
        write_new(output / "receipt.json", json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
