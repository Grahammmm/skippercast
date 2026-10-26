"""SP82 scoped offline acceptance. Historical expected-red is never final green."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO.parent
BASE = "a1f648632e64561d82dcbeb20d9bda19f812560a"
SOURCE = "dist/coastal-offline-core.js"
TEST = "tests/test_sp82_snapshot_length.mjs"
FIXTURES = "tests/fixtures/sp82_snapshot_length"
ORIGINAL = "tests/test_coastal_offline.mjs"
SCAN = "scripts/check_repository.py"
BASE_SOURCE = "bcb499097ad9b7014e30496ba376ed98d7c5d1844b2f591699d3461bd7603a45"
ORIGINAL_HASH = "81a5d72d87304da46f09784c18e12bfad13434a256ffd25c03acc2db5825d7fc"
SCAN_HASH = "cf39ee4dab44893fae58d4553c8a159942c5674f5ce33f22ca9c441d0a74dec8"
PRIMARY = "A4 primary: declared-one identity must reject valid complete products"
HEALTHY = "A4 healthy: matching-length complete products remain accepted"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def capture(argv, cwd=REPO, env=None):
    return subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True, check=False)


def checked(argv):
    result = capture(argv)
    require(result.returncode == 0, f"Prerequisite failed: {argv!r}: {result.stderr}")
    return result.stdout.strip()


def no_network(event, args):
    if event.startswith("socket.") and event not in {"socket.__new__"}:
        raise RuntimeError("SP82 offline socket refusal: " + event)


def scan_child():
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(REPO), str(REPO / "src")]
    sys.addaudithook(no_network)

    def no_child(event, args):
        if event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"}:
            raise RuntimeError("SP82 scanner child refusal: " + event)

    sys.addaudithook(no_child)
    runpy.run_path(str(REPO / SCAN), run_name="__main__")
    return 0


def focused_names():
    names = [PRIMARY, HEALTHY, "A1 fixture proves UTF-8 byte count differs from JavaScript character count"]
    for encoding in ["absent", "identity", "IDENTITY", " Identity "]:
        names += [f"A1 {encoding} declared length {d} rejects" for d in ["shorter", "longer"]]
        names += [f"A1 {encoding} matching length accepts", f"A1 {encoding} no length accepts"]
    names += ["A1 character count is not an acceptable declared byte length"]
    names += [f"A2 {e} encoded length may differ from decoded bytes" for e in ["gzip", "br"]]
    names += [f"A2 malformed or over-budget declared length {n} refuses" for n in ["-1", "1.5", "1e2", "invalid", "9007199254740992", str(8 * 1024 * 1024 + 1)]]
    names += ["A2 zero declaration disagrees with a nonempty valid product"]
    names += [f"A2 {e} streaming over budget still cancels" for e in ["absent", "gzip", "br"]]
    names += ["A2 wrong MIME refuses independently of matching byte length", "A2 offline-origin response refuses independently of matching byte length", "A2 read failure retains its actual refusal and removes candidate", "A2 abort during bounded consumption cancels without committing"]
    names += [f"A3 mismatch in product {i} preserves exact prior index and bytes" for i in [1, 2, 3]]
    names += [f"A3 reader returns null for tampered {e} length" for e in ["absent", "identity"]]
    return names


def tap_counts(text, expected):
    results = re.findall(r"^(ok|not ok) \d+ - (.+)$", text, re.M)
    require([name for _, name in results] == expected, "Missing, additional, reordered or unexecuted test selector")
    require(not re.search(r"^(?:ok|not ok) .* # (?:SKIP|TODO)\b", text, re.I | re.M), "Unexpected skip or TODO")
    values = {}
    for label in ["tests", "pass", "fail", "cancelled", "skipped", "todo"]:
        found = re.findall(r"^# " + label + r" (\d+)$", text, re.M)
        require(len(found) == 1, "Missing or ambiguous TAP summary: " + label)
        values[label] = int(found[0])
    require(values["tests"] == len(expected), "Wrong test count")
    require(values["cancelled"] == values["skipped"] == values["todo"] == 0, "Unexecuted tests")
    require(values["pass"] == sum(status == "ok" for status, _ in results), "Wrong pass count")
    require(values["fail"] == sum(status == "not ok" for status, _ in results), "Wrong fail count")
    require(text.count("SP82_OFFLINE_ATTEMPTS=0") == 1, "Offline guard completion missing")
    return {"passed": values["pass"], "failed": values["fail"], "errors": 0, "skips": 0}, results


def closure():
    # Literal selectors and their complete import/child closure were inspected before execution.
    require(sha(REPO / ORIGINAL) == ORIGINAL_HASH, "Existing regression selector changed")
    require(sha(REPO / SCAN) == SCAN_HASH, "Existing repository scanner changed")
    original = (REPO / ORIGINAL).read_text()
    imports = re.findall(r"from\s*['\"]([^'\"]+)['\"]", original)
    require(imports == ["node:test", "node:assert/strict", "../dist/coastal-offline-core.js"], "Unknown regression import closure")
    require(not re.search(r"\b(?:import\s*\(|require\s*\(|exec\w*\s*\(|spawn\w*\s*\(|fork\s*\()", original), "Unqualified regression child/import")
    source = (REPO / SOURCE).read_text()
    require(not re.search(r"\bimport\s*(?:\(|['\"{*])|\brequire\s*\(|\bprocess\s*[.\[]|\b(?:XMLHttpRequest|WebSocket)\s*\(", source), "Unqualified product import/side effect closure")
    # The product's only external effects are injected fetch/cache/locks at invocation.
    # Both test modules pass in-memory doubles; process-local guards precede imports.
    return {name: sha(REPO / name) for name in [ORIGINAL, SCAN, SOURCE, TEST]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=["baseline", "focused", "regression", "repository", "typecheck", "build", "diff", "status"])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    parent = args.output.resolve()
    require(parent.is_relative_to(ROOT / "out"), "Evidence must be under candidate out, never fixtures")
    parent.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix=args.suite + "-", dir=parent))
    (out / "tmp").mkdir()
    os.environ["TMPDIR"] = str(out / "tmp")
    tempfile.tempdir = str(out / "tmp")
    sys.addaudithook(no_network)
    receipt = {"schema_version": 1, "phase": args.suite, "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "cwd": str(REPO), "wrapper_argv": sys.argv, "output": str(out), "wrapper_exit": 1, "status": "UNVERIFIED", "cases": {"passed": 0, "failed": 0, "errors": 0, "skips": 0}, "commands": []}
    try:
        manifest_path = ROOT / "SOURCE-MANIFEST.json"
        manifest = json.loads(manifest_path.read_text())
        require(manifest.get("head") == BASE, "Staging manifest base mismatch")
        require(manifest.get("clean") is True, "Staging must attest clean base")
        receipt["manifest_sha256"] = sha(manifest_path)
        receipt["staging_base"] = BASE
        receipt["actual_head"] = checked(["git", "rev-parse", "HEAD"])
        checked(["git", "merge-base", "--is-ancestor", BASE, "HEAD"])
        require((REPO / ".venv/bin/python3").is_file(), "Missing operator-staged venv")
        require((REPO / "node_modules").is_dir(), "Missing staged pnpm dependencies")
        receipt["closure_hashes"] = closure()
        fixture_paths = sorted((REPO / FIXTURES).rglob("*"))
        receipt["test_fixture_hashes"] = {p.relative_to(REPO).as_posix(): sha(p) for p in [REPO / TEST] + fixture_paths if p.is_file()}
        require(len(receipt["test_fixture_hashes"]) > 1, "Missing synthetic fixture")
        receipt["source_hashes"] = {SOURCE: sha(REPO / SOURCE)}
        receipt["helper_sha256"] = sha(__file__)
        receipt["working_status"] = checked(["git", "status", "--porcelain"])
        node = shutil.which("node")
        require(node is not None, "Qualified node unavailable; no fallback")
        receipt["runtime"] = {"launcher": sys.executable, "launcher_version": sys.version, "node": node, "node_version": checked([node, "--version"])}
        if args.suite == "baseline":
            require(receipt["source_hashes"][SOURCE] == BASE_SOURCE, "Baseline source is not original pinned bytes")
            require(receipt["actual_head"] == BASE, "Baseline must run before repair")
        elif args.suite in {"focused", "regression"}:
            baselines = []
            for path in sorted((ROOT / "out").rglob("receipt.json")):
                old = json.loads(path.read_text())
                if old.get("status") == "BASELINE_DEFECT_REPRODUCED" and old.get("wrapper_exit") == 0 and old.get("source_hashes", {}).get(SOURCE) == BASE_SOURCE and old.get("test_fixture_hashes") == receipt["test_fixture_hashes"]:
                    baselines.append(str(path))
            require(bool(baselines), "No retained honest baseline for these exact tests/fixtures")
            receipt["historical_baselines"] = baselines
        expected = None
        if args.suite in {"baseline", "focused"}:
            argv = [node, "--experimental-strip-types", TEST, args.suite]
            expected = [PRIMARY, HEALTHY] if args.suite == "baseline" else focused_names()
        elif args.suite == "regression":
            argv = [node, "--experimental-strip-types", TEST, "regression", "tests/test_coastal_offline.mjs"]
            expected = re.findall(r"^test\('([^']+)'", (REPO / ORIGINAL).read_text(), re.M)
            require(bool(expected), "Absent original required selectors")
        elif args.suite == "repository":
            scanner = manifest.get("runtime", {}).get("credential_scan_python3")
            require(isinstance(scanner, str) and Path(scanner).is_file(), "Manifest-approved credential-scan interpreter unavailable")
            receipt["runtime"]["credential_scan_python3"] = scanner
            receipt["runtime"]["credential_scan_resolved"] = str(Path(scanner).resolve())
            receipt["runtime"]["credential_scan_version"] = checked([scanner, "--version"])
            argv = [scanner, str(Path(__file__).resolve()), "--scan-child"]
            receipt["scan_entry"] = [scanner, SCAN]
        elif args.suite in {"typecheck", "build"}:
            require(shutil.which("pnpm") == manifest.get("runtime", {}).get("pnpm"), "pnpm does not match staged qualified executable")
            receipt["runtime"]["pnpm"] = shutil.which("pnpm")
            receipt["runtime"]["pnpm_version"] = checked(["pnpm", "--version"])
            argv = ["pnpm", args.suite]
        elif args.suite == "diff":
            argv = ["git", "-C", str(REPO), "diff", "--check", BASE, "HEAD"]
        else:
            argv = ["git", "-C", str(REPO), "status", "--porcelain"]
        receipt["commands"].append({"argv": argv, "cwd": str(REPO), "tmpdir": str(out / "tmp")})
        result = capture(argv, env=os.environ.copy())
        receipt["child_exit"] = result.returncode
        for name, text in [("stdout", result.stdout), ("stderr", result.stderr)]:
            path = out / (name + ".txt")
            path.write_text(text)
            receipt[name] = {"path": str(path), "sha256": sha(path)}
        if expected is not None:
            receipt["cases"], results = tap_counts(result.stdout, expected)
            receipt["executed_selectors"] = expected
            require(not result.stderr.strip(), "Unexpected Node stderr")
            if args.suite == "baseline":
                require(result.returncode == 1 and results == [("not ok", PRIMARY), ("ok", HEALTHY)], "Wrong baseline failure/control")
                require("SP82_PRIMARY_IDENTITY_MISMATCH" in result.stdout and "code: 'ERR_ASSERTION'" in result.stdout and "actual: 'returned'" in result.stdout, "Baseline must be the named semantic assertion, not infrastructure")
                receipt["status"] = "BASELINE_DEFECT_REPRODUCED"
            else:
                require(result.returncode == 0 and receipt["cases"]["failed"] == 0, "Unexpected test failure")
                receipt["status"] = "GREEN_REVIEW_REQUIRED"
        else:
            require(result.returncode == 0, "Acceptance child failed")
            if args.suite == "repository":
                match = re.search(r"Checked (\d+) text files:.*passed\.", result.stdout)
                if match is None:
                    raise ValueError("Scanner completion missing")
                receipt["files_checked"] = int(match.group(1))
                receipt["cases"]["passed"] = 1
            if args.suite in {"status", "diff"}:
                require(result.stdout == "" and result.stderr == "", "Nonempty final status or diff diagnostic")
            receipt["status"] = "GREEN_REVIEW_REQUIRED"
        require(receipt["source_hashes"][SOURCE] == sha(REPO / SOURCE), "Source changed during acceptance")
        require(receipt["actual_head"] == checked(["git", "rev-parse", "HEAD"]), "HEAD changed during acceptance")
        for name, digest in receipt["test_fixture_hashes"].items():
            require(sha(REPO / name) == digest, "Test/fixture changed during acceptance")
        receipt["wrapper_exit"] = 0
    except Exception as error:
        receipt["error"] = str(error)
        receipt["status"] = "FAILED_UNVERIFIED"
        receipt["cases"]["errors"] += 1
    receipt["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    path = out / "receipt.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "receipt": str(path), "cases": receipt["cases"], "child_exit": receipt.get("child_exit"), "wrapper_exit": receipt["wrapper_exit"], "error": receipt.get("error")}, indent=2))
    return receipt["wrapper_exit"]


if __name__ == "__main__":
    if sys.argv[1:] == ["--scan-child"]:
        raise SystemExit(scan_child())
    raise SystemExit(main())
