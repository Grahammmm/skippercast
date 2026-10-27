"""Offline SP-16-v1 acceptance. Every child uses explicit argv, never a shell."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = "8a805820c30895f5f037e26af9079fd3dc015b0f"
PRIMARY = "server/trip-queue.ts"
TEST = "tests/test_sp1601_generated_settle.mjs"
FIXTURES = "tests/fixtures/sp1601_generated_settle"
PINS = {
    PRIMARY: "c8bb4c72952bcbbd0de675fd5b0204d741299b82c394f3bc934c20c278d60669",
    "tests/test_trip_queue.mjs": "8adcf9448e253852a83dbc56349c83968982440e0496e31bd96fa833ade4b1e7",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def baseline_inputs():
    paths = [ROOT / TEST, *sorted((ROOT / FIXTURES).rglob("*"))]
    return {path.relative_to(ROOT).as_posix(): digest(path.read_bytes())
            for path in paths if path.is_file() and path.name != "baseline-contract.json"}


def source_identity():
    names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
    hashes = {name: digest((ROOT / name).read_bytes()) for name in sorted(set(names))
              if name and (ROOT / name).is_file()}
    return {"head": git("rev-parse", "HEAD").decode().strip(),
            "status": git("status", "--porcelain=v1").decode(), "files_sha256": hashes}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["baseline", "focused", "regression", "repository", "typecheck", "build"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix=args.suite + "-", dir=args.output.resolve()))
    receipt = {"schema": "skippercast.sp1601.acceptance/v1", "spec": "SP-16-v1",
               "card": "SP1601-GENERATED-SETTLE", "suite": args.suite,
               "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "launcher_argv": sys.argv, "launcher_cwd": str(Path.cwd()),
               "python": {"executable": sys.executable, "version": sys.version},
               "children": [], "outcome": "FAILED", "passed": False}
    exit_code = 1
    try:
        require(Path.cwd().resolve() == ROOT, "acceptance cwd must be staged repository")
        manifest_path = ROOT.parent / "SOURCE-MANIFEST.json"
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        receipt["stage_manifest_sha256"] = digest(manifest_bytes)
        require(manifest.get("schema") == "agentorange.source-manifest/v1", "invalid stage schema")
        require(manifest.get("head") == BASE, "stage base mismatch")
        require(Path(manifest.get("repo", "")).resolve() == ROOT, "stage repository mismatch")
        require(manifest.get("card") == "SP1601-GENERATED-SETTLE", "stage card mismatch")
        runtime = manifest.get("runtime", {})
        scan_python = runtime.get("credential_scan_python3")
        require(isinstance(scan_python, str) and Path(scan_python).is_file() and os.access(scan_python, os.X_OK), "missing approved credential scan runtime")
        require((ROOT / ".venv").is_dir() and (ROOT / "node_modules").is_dir(), "missing standard staged dependencies")
        for name, expected in PINS.items():
            require(digest(git("show", f"{BASE}:{name}")) == expected, f"base source pin mismatch: {name}")
        require(digest((ROOT / "tests/test_trip_queue.mjs").read_bytes()) == PINS["tests/test_trip_queue.mjs"], "original regression changed")
        git("merge-base", "--is-ancestor", BASE, "HEAD")
        allowed_files = {PRIMARY, TEST, "scripts/accept_sp1601_generated_settle.py", "docs/engineering/sp1601_generated_settle.md"}
        changed = set(git("diff", "--name-only", BASE).decode().splitlines())
        changed.update(git("ls-files", "--others", "--exclude-standard").decode().splitlines())
        require(all(name in allowed_files or name.startswith(FIXTURES + "/") for name in changed), "out-of-scope repository changes")
        receipt["source_before"] = source_identity()
        receipt["baseline_inputs_sha256"] = baseline_inputs()
        node = shutil.which("node")
        pnpm = shutil.which("pnpm")
        require(node is not None and pnpm is not None, "installed Node/pnpm missing; no install permitted")

        def child(label, argv, kind, expected_tests=None):
            start = time.monotonic()
            record = {"label": label, "argv": argv, "cwd": str(ROOT), "kind": kind}
            receipt["children"].append(record)
            # A bounded timeout is test-only; it changes no operational limit.
            try:
                result = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=600, check=False)
                stdout, stderr, code = result.stdout, result.stderr, result.returncode
            except subprocess.TimeoutExpired as error:
                stdout, stderr, code = error.stdout or b"", error.stderr or b"", 124
            for stream, data in [("stdout", stdout), ("stderr", stderr)]:
                path = out / f"{label}.{stream}.txt"
                path.write_bytes(data)
                record[stream] = {"path": str(path), "sha256": digest(data), "bytes": len(data)}
            record.update(exit=code, duration_seconds=time.monotonic() - start)
            text = stdout.decode("utf-8", errors="replace")
            if kind == "node-tests":
                counts = {}
                for key in ["tests", "pass", "fail", "cancelled", "skipped", "todo"]:
                    values = re.findall(r"^# " + key + r" (\d+)$", text, re.M)
                    require(len(values) == 1, f"{label}: missing/ambiguous TAP {key}")
                    counts[key] = int(values[0])
                record["counts"] = counts
                require(counts["tests"] == expected_tests and counts["cancelled"] == counts["skipped"] == counts["todo"] == 0, f"{label}: incomplete test execution")
                if args.suite == "baseline":
                    require(code == 1 and counts["fail"] == 1 and counts["pass"] == 1, "baseline must have exactly one failing and one healthy test")
                    require(re.findall(r"^not ok \d+ - (.+)$", text, re.M) == ["primary regression"], "baseline wrong failing case")
                    require(re.findall(r"^ok \d+ - (.+)$", text, re.M) == ["healthy control"], "baseline healthy control not executed")
                    require("A1_GENERATED_RECENT_MUST_SETTLE" in text and "code: 'ERR_ASSERTION'" in text and "actual: 'enqueued'" in text and "expected: 'settling'" in text, "baseline wrong semantic mismatch")
                    require("failureType: 'testCodeFailure'" in text and text.count("failureType:") == 1, "baseline unexpected setup/hook failure")
                else:
                    require(code == 0 and counts["fail"] == 0 and counts["pass"] == expected_tests, f"{label}: test failure")
            else:
                record["counts"] = {"checks": 1, "passed": int(code == 0)}
                require(code == 0, f"{label}: child failed with exit {code}")
                if kind == "repository":
                    match = re.search(r"Checked (\d+) text files:", text)
                    if match is None:
                        raise RuntimeError("repository count missing")
                    record["counts"]["text_files"] = int(match.group(1))
            return record

        child("node-runtime", [node, "--version"], "runtime")
        child("pnpm-runtime", [pnpm, "--version"], "runtime")
        if args.suite == "baseline":
            require(digest((ROOT / PRIMARY).read_bytes()) == PINS[PRIMARY], "baseline product already modified")
            child("baseline", [node, TEST, "--baseline"], "node-tests", 2)
            (out / "baseline-contract.json").write_text(json.dumps({"spec": "SP-16-v1", "baseline_product_sha256": PINS[PRIMARY], "inputs_sha256": baseline_inputs()}, indent=2) + "\n")
            receipt["outcome"] = "BASELINE_GAP_REPRODUCED"
        elif args.suite == "focused":
            contract = json.loads((ROOT / FIXTURES / "baseline-contract.json").read_text())
            require(contract.get("spec") == "SP-16-v1" and contract.get("baseline_product_sha256") == PINS[PRIMARY], "invalid frozen baseline contract")
            # focused.mjs is never imported by --baseline. Its original snapshot
            # remains in the immutable historical contract for audit, but only
            # the actually executed baseline pair/dependency closure is frozen.
            nonbaseline = FIXTURES + "/focused.mjs"
            frozen_pair = {name: sha for name, sha in contract.get("inputs_sha256", {}).items() if name != nonbaseline}
            current_pair = {name: sha for name, sha in baseline_inputs().items() if name != nonbaseline}
            require(frozen_pair == current_pair, "baseline pair/dependency bytes changed")
            receipt["baseline_pair_sha256"] = current_pair
            receipt["supplemental_focused_original_sha256"] = contract["inputs_sha256"][nonbaseline]
            receipt["supplemental_focused_current_sha256"] = baseline_inputs()[nonbaseline]
            child("focused", [node, TEST], "node-tests", 22)
            receipt["outcome"] = "SCOPED_PASS_REVIEW_REQUIRED"
        elif args.suite == "regression":
            child("trip-queue-original", [node, "--import", "./" + FIXTURES + "/preload.mjs", "--test", "--test-reporter=tap", "tests/test_trip_queue.mjs"], "node-tests", 10)
            receipt["outcome"] = "SCOPED_PASS_REVIEW_REQUIRED"
        elif args.suite == "repository":
            child("repository", [scan_python, "scripts/check_repository.py"], "repository")
            receipt["outcome"] = "SCOPED_PASS_REVIEW_REQUIRED"
        elif args.suite == "typecheck":
            for label, config in [("server", "tsconfig.json"), ("web", "web/tsconfig.json"), ("coast", "packages/coast/tsconfig.json")]:
                child("tsc-" + label, [pnpm, "exec", "tsc", "--noEmit", "-p", config], "typecheck")
            receipt["outcome"] = "SCOPED_PASS_REVIEW_REQUIRED"
        elif args.suite == "build":
            child("build", [pnpm, "build"], "build")
            receipt["outcome"] = "SCOPED_PASS_REVIEW_REQUIRED"
        receipt["source_after"] = source_identity()
        require(receipt["source_before"] == receipt["source_after"], "tracked/untracked source changed during acceptance")
        receipt["passed"] = True
        exit_code = 0
    except Exception as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
        receipt["outcome"] = "FAILED"
        print(receipt["error"], file=sys.stderr)
    finally:
        receipt["wrapper_exit"] = exit_code
        receipt["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        path = out / "receipt.json"
        path.write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps({"outcome": receipt["outcome"], "exit": exit_code, "receipt": str(path), "receipt_sha256": digest(path.read_bytes()), "children": [{"label": c["label"], "exit": c.get("exit"), "counts": c.get("counts")} for c in receipt["children"]]}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
