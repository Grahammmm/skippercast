"""SP-MAP-NOW offline, retained, exact-source acceptance receipts (stdlib only)."""
from pathlib import Path, PurePosixPath
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "tests/fixtures/sp_map_now/contract.json"
NODE = Path.home() / ".local/bin/node"
BASELINE = "f8bc7d365c0c5aa4a2e59ba576a95146c92a0367"
FOCUSED = "tests/test_sp_map_now.mjs"
REGRESSION = ["tests/test_frames.mjs", "tests/test_security_headers.mjs"]
SOURCE_PATHS = ["packages/coast/src/map-sources.ts", "package.json", "pnpm-lock.yaml", "CHANGELOG.md",
                FOCUSED, "scripts/accept_sp_map_now.py", "tests/fixtures/sp_map_now/contract.json",
                "tests/fixtures/sp_map_now/regression-setup.mjs"]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"git {args!r} exited {result.returncode}: {result.stderr.decode(errors='replace')}")
    return result.stdout


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def source_hashes():
    return {p: sha((ROOT / p).read_bytes()) for p in SOURCE_PATHS + REGRESSION}


def materialize_baseline(target):
    """Copy COMPLETE baseline modules and recursively their relative import closure.

    Bare packages resolve only through the admitted installed dependency tree. No
    source slices, function reconstruction, mutation, downloads or installation.
    """
    pending = ["packages/coast/src/map-sources.ts", "web/map/frames.ts", "package.json"]
    hashes = {}
    bare = set()
    imports = re.compile(r"(?:\bfrom\s*|\bimport\s*\(?\s*)['\"]([^'\"]+)['\"]")
    while pending:
        name = pending.pop()
        if name in hashes:
            continue
        parts = PurePosixPath(name)
        if parts.is_absolute() or ".." in parts.parts:
            raise RuntimeError(f"unsafe baseline path: {name}")
        data = git("show", f"{BASELINE}:{name}")
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        hashes[name] = sha(data)
        if destination.suffix not in {".ts", ".js", ".mjs"}:
            continue
        for spec in imports.findall(data.decode()):
            if not spec.startswith("."):
                if not spec.startswith("node:"):
                    bare.add(spec)
                continue
            relative = os.path.normpath(str(parts.parent / spec))
            if relative.startswith("../") or relative == "..":
                raise RuntimeError(f"baseline import escapes root: {name}: {spec}")
            pending.append(relative)
    os.symlink((ROOT / "node_modules").resolve(), target / "node_modules", target_is_directory=True)
    write_json(target.parent / "baseline-closure.json", {
        "baseline_head": BASELINE, "files": hashes, "bare_imports": sorted(bare),
        "node_modules": str((ROOT / "node_modules").resolve()),
        "note": "Complete unchanged modules, including type-only imports; installed package resolution uses the operator-admitted dependency tree."})
    return hashes


def run_command(argv, run, commands, label):
    completed = subprocess.run(argv, cwd=ROOT, capture_output=True, check=False)
    stdout = f"{label}.stdout.txt"
    stderr = f"{label}.stderr.txt"
    (run / stdout).write_bytes(completed.stdout)
    (run / stderr).write_bytes(completed.stderr)
    commands.append({"argv": argv, "cwd": str(ROOT), "exit": completed.returncode,
                     "stdout_file": stdout, "stderr_file": stderr,
                     "stdout_sha256": sha(completed.stdout), "stderr_sha256": sha(completed.stderr)})
    return completed


def result_markers(text, prefix):
    return [json.loads(line.split(prefix, 1)[1]) for line in text.splitlines() if prefix in line]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["focused", "regression", "negative"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Runtime copies/receipts must not enter fixtures, another repo, or shared data.
    output = args.output.resolve()
    admitted_out = ROOT.parent / "out"
    if output != admitted_out and admitted_out not in output.parents:
        parser.error("output must be below this candidate's out root")
    output.mkdir(parents=True, exist_ok=True)
    run = output / (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex)
    run.mkdir()
    commands = []
    receipt = {"schema_version": 1, "suite": args.suite, "candidate_head": None, "baseline_head": BASELINE,
               "spec_sha256": None, "runtime": {"python": sys.version, "python_executable": sys.executable,
               "node_executable": str(NODE)}, "commands": commands,
               "counts": {"test_cases": 0, "assertion_checks": 0, "intended_negative_failures": 0,
                          "unexpected_failures": 0, "skips": 0},
               "verdict": "FAIL", "wrapper_exit": 1}
    try:
        contract = json.loads(CONTRACT.read_text())
        receipt["spec_sha256"] = contract["spec_sha256"]
        receipt["spec_version"] = contract["spec_version"]
        receipt["candidate_head"] = git("rev-parse", "HEAD").decode().strip()
        receipt["candidate_status"] = git("status", "--porcelain").decode()
        before = source_hashes()
        receipt["source_sha256"] = before
        receipt["baseline_primary_sha256"] = sha(git("show", f"{BASELINE}:packages/coast/src/map-sources.ts"))
        if not (ROOT / "node_modules").is_dir():
            raise RuntimeError("operator staging incomplete: node_modules absent; no test attempted")
        runtime = run_command([str(NODE), "--version"], run, commands, "node-runtime")
        version = runtime.stdout.decode().strip()
        receipt["runtime"]["node_version"] = version
        if runtime.returncode or version != contract["node_version"]:
            raise RuntimeError("installed Node differs from the frozen admitted runtime")
        argv = [str(NODE), "--experimental-strip-types"]
        if args.suite == "regression":
            argv += ["--import", "./tests/fixtures/sp_map_now/regression-setup.mjs", "--test", "--test-reporter=tap", *REGRESSION]
        else:
            argv += [FOCUSED]
            if args.suite == "negative":
                baseline_root = run / "baseline"
                baseline_root.mkdir()
                receipt["baseline_source_sha256"] = materialize_baseline(baseline_root)
                argv.append(f"--baseline-root={baseline_root}")
        child = run_command(argv, run, commands, "tests")
        text = child.stdout.decode(errors="replace")
        if args.suite == "regression":
            summaries = result_markers(text, "SP_MAP_NOW_REGRESSION_RESULT ")
            tests = re.findall(r"^# tests (\d+)$", text, re.MULTILINE)
            failures = re.findall(r"^# fail (\d+)$", text, re.MULTILINE)
            skips = re.findall(r"^# skipped (\d+)$", text, re.MULTILINE)
            if len(summaries) != 2 or len(tests) != 1 or len(failures) != 1 or len(skips) != 1:
                raise RuntimeError("missing/duplicate regression summaries or TAP totals")
            if {Path(x["script"]).name for x in summaries} != {Path(p).name for p in REGRESSION}:
                raise RuntimeError("wrong regression files executed")
            counts = {"test_cases": int(tests[0]), "assertion_checks": sum(x["assertion_checks"] for x in summaries),
                      "intended_negative_failures": 0, "unexpected_failures": int(failures[0]), "skips": int(skips[0])}
            if any(x["fetch_calls"] for x in summaries):
                raise RuntimeError("unexpected network attempt in offline regression")
            receipt["regression_summaries"] = summaries
        else:
            summaries = result_markers(text, "SP_MAP_NOW_RESULT ")
            if len(summaries) != 1:
                raise RuntimeError("missing/duplicate behavior summary (import/setup failure is not acceptance)")
            report = summaries[0]
            counts = report["counts"]
            write_json(run / "assertions.json", report)
            names = [row["name"] for row in report["outcomes"]]
            if len(names) != len(set(names)) or len(names) != counts["test_cases"] or report["fetch_calls"]:
                raise RuntimeError("duplicate/missing cases or offline sentinel called")
            intended = {row["name"] for row in report["outcomes"] if row["status"] == "INTENDED_NEGATIVE_FAILURE"}
            expected = {f"invalid-date/{label}/{api}" for label in ["label", "NaN", "Infinity", "finite-positive-out-of-range", "finite-negative-out-of-range"]
                        for api in ["cloud", "forecast", "cloudTiles", "currentFrame-forecast"]} if args.suite == "negative" else set()
            if intended != expected or counts["intended_negative_failures"] != len(expected):
                raise RuntimeError("negative failures are not exactly the specified non-null cloud/forecast outcomes")
            if report["negative"] != (args.suite == "negative"):
                raise RuntimeError("wrong module mode")
        receipt["counts"] = counts
        expected_cases = {"focused": 84, "negative": 60, "regression": 16}[args.suite]
        if counts["test_cases"] != expected_cases:
            raise RuntimeError("required named cases are missing or the frozen suite changed")
        if child.returncode or counts["unexpected_failures"] or counts["skips"] or not counts["test_cases"] or not counts["assertion_checks"]:
            raise RuntimeError("test contract failed; retain child output")
        if before != source_hashes() or receipt["candidate_head"] != git("rev-parse", "HEAD").decode().strip():
            raise RuntimeError("source identity changed during acceptance")
        receipt["verdict"] = "PASS_REVIEW_REQUIRED"
        receipt["wrapper_exit"] = 0
    except Exception as error:
        receipt["error"] = str(error)
        receipt["counts"]["unexpected_failures"] = max(1, receipt["counts"]["unexpected_failures"])
    receipt["output_hashes"] = {str(p.relative_to(run)): sha(p.read_bytes()) for p in sorted(run.glob("*")) if p.is_file()}
    write_json(run / "receipt.json", receipt)
    print(f"{receipt['verdict']} receipt={run / 'receipt.json'}")
    if "error" in receipt:
        print(receipt["error"], file=sys.stderr)
    return receipt["wrapper_exit"]


if __name__ == "__main__":
    sys.exit(main())
