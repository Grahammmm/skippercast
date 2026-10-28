"""SP61 offline acceptance. Every invocation retains its own raw evidence.

No installs, shell bodies, copied modules or network. Negative control extracts
only the already-staged complete base git tree into a fresh run directory.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = "f8bc7d365c0c5aa4a2e59ba576a95146c92a0367"
TEST = "tests/test_sp61_spear_daylight.mjs"
SPEC = "tests/fixtures/sp61_spear_daylight/contract.json"
CASES = [
    "A1 primary: known daylight night-only best is null",
    "A3 positive control: unknown daylight retains all-hour fallback",
    "A2 boundaries: sunrise and sunset equality qualify; crossing sunset does not",
    "A2 mixed: a better night cannot set best, surge range, clarity or basis",
    "A2 empty: no readings are invented",
    "A3 missing or unparsable sun clocks preserve fallback",
    "A3 normal ordering, early ties and Rough/Unknown exclusions remain",
    "A3 buildDaily: night-only summary withholds best and hazard windows stay screened",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def snapshot(root, names):
    entries = {}
    for name in sorted(names):
        path = root / name
        if path.is_symlink():
            entries[name] = {"symlink": os.readlink(path)}
        else:
            entries[name] = {"sha256": sha(path)}
    return entries


def extract_tree(archive, dest):
    """Validate every name/link and symlink ancestry before writing anything."""
    with tarfile.open(archive, "r:") as tf:
        members = tf.getmembers()
        seen = set()
        links = set()
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or not name.parts:
                raise ValueError("Unsafe archive member")
            normalized = str(name)
            if normalized in seen:
                raise ValueError("Duplicate archive member")
            seen.add(normalized)
            if not (member.isdir() or member.isfile() or member.issym()):
                raise ValueError("Unsupported archive member type")
            if member.issym():
                links.add(normalized)
                target = PurePosixPath(member.linkname)
                if target.is_absolute() or not member.linkname:
                    raise ValueError("Unsafe archive symlink")
                resolved = (dest / str(name.parent) / member.linkname).resolve()
                if not resolved.is_relative_to(dest):
                    raise ValueError("Archive symlink escapes baseline")
        for member in members:
            if any(str(parent) in links for parent in PurePosixPath(member.name).parents):
                raise ValueError("Archive member traverses symlink")
        dest.mkdir()
        for member in members:
            path = dest / member.name
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                if member.issym():
                    path.symlink_to(member.linkname)
                else:
                    source = tf.extractfile(member)
                    if source is None:
                        raise ValueError("Missing archive file content")
                    with source, path.open("xb") as output:
                        shutil.copyfileobj(source, output)
                    path.chmod(member.mode & 0o777)
        return snapshot(dest, [m.name for m in members if not m.isdir()])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=("focused", "regression", "negative"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    parent = args.output.resolve()
    # Evidence must never contaminate test discovery, fixtures or candidate bytes.
    if parent.is_relative_to(ROOT):
        parser.error("Output must be outside the candidate repository")
    parent.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
    receipt = {"schema_version": 1, "suite": args.suite, "candidate_head": None,
               "baseline_head": BASE, "spec_sha256": sha(ROOT / SPEC),
               "wrapper_argv": [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
               "wrapper_cwd": str(Path.cwd()),
               "runtime": {"python": sys.version, "python_executable": sys.executable,
                           "platform": platform.platform()},
               "commands": [], "counts": {"test_cases": 0, "assertion_checks": None,
               "expected_negative_failures": 0, "unexpected_failures": 0, "skips": 0},
               "verdict": "FAIL", "wrapper_exit": 1}

    def command(argv, cwd=ROOT):
        index = len(receipt["commands"])
        stdout_file, stderr_file = f"command-{index}.stdout", f"command-{index}.stderr"
        started = time.monotonic()
        with (run / stdout_file).open("xb") as out, (run / stderr_file).open("xb") as err:
            completed = subprocess.run(argv, cwd=cwd, stdout=out, stderr=err, check=False)
        receipt["commands"].append({"argv": [str(a) for a in argv], "cwd": str(cwd),
                                    "elapsed_seconds": time.monotonic() - started,
                                    "exit": completed.returncode, "stdout_file": stdout_file,
                                    "stderr_file": stderr_file, "stdout_sha256": sha(run / stdout_file),
                                    "stderr_sha256": sha(run / stderr_file)})
        return completed.returncode, (run / stdout_file).read_text(errors="replace")

    def require(ok, message):
        if not ok:
            raise ValueError(message)

    try:
        code, head = command(["git", "rev-parse", "HEAD"])
        require(code == 0, "Cannot identify candidate head")
        receipt["candidate_head"] = head.strip()
        code, names = command(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"])
        require(code == 0, "Cannot inventory candidate source")
        names = set(filter(None, names.split("\0")))
        before = snapshot(ROOT, names)
        dump(run / "source-manifest.json", before)
        receipt["source_manifest_sha256"] = sha(run / "source-manifest.json")
        node = shutil.which("node")
        if node is None:
            raise ValueError("Operator-staged Node unavailable; no installation permitted")
        node = str(Path(node).resolve())
        code, version = command([node, "--version"])
        require(code == 0 and version.strip() == "v22.23.2", "Unqualified Node runtime")
        receipt["runtime"].update({"node": node, "node_version": version.strip(), "node_sha256": sha(Path(node))})
        baseline = run / "baseline"
        baseline_manifest = {}
        if args.suite == "negative":
            archive = run / "baseline.tar"
            code, _ = command(["git", "archive", "--format=tar", f"--output={archive}", BASE])
            require(code == 0, "Full baseline archive failed")
            baseline_manifest = extract_tree(archive, baseline)
            dump(run / "baseline-source-manifest.json", baseline_manifest)
            receipt["baseline_archive_sha256"] = sha(archive)
            receipt["baseline_source_manifest_sha256"] = sha(run / "baseline-source-manifest.json")
            # Use the existing dependency closure without installing or writing it.
            (baseline / "node_modules").symlink_to((ROOT / "node_modules").resolve(), target_is_directory=True)
            code, output = command([node, "--experimental-strip-types", str(ROOT / TEST),
                                    "--source-root", str(baseline), "--scenario", "baseline-control"])
        elif args.suite == "focused":
            code, output = command([node, "--experimental-strip-types", TEST])
        else:
            code, output = command([node, "--experimental-strip-types", "--test",
                                    "tests/test_spear.mjs", "tests/test_window_hazards.mjs"])
        if args.suite in {"negative", "focused"}:
            cases = [json.loads(line.split("@SP61_CASE ", 1)[1]) for line in output.splitlines() if line.startswith("@SP61_CASE ")]
            guards = [json.loads(line.split("@SP61_OFFLINE ", 1)[1]) for line in output.splitlines() if line.startswith("@SP61_OFFLINE ")]
            expected = CASES[:2] if args.suite == "negative" else CASES
            dump(run / "case-results.json", cases)
            receipt["counts"].update({"test_cases": len(cases), "assertion_checks": sum(c["checks"] for c in cases) + sum(g["checks"] for g in guards)})
            require([c["name"] for c in cases] == expected, "Missing, duplicate or unexpected case")
            require(guards == [{"fetchCalls": 0, "storageCalls": 0, "checks": 2}], "Offline guard missing or failed")
            tests = re.findall(r"^# tests (\d+)$", output, re.M)
            skips = re.findall(r"^# skipped (\d+)$", output, re.M)
            fails = re.findall(r"^# fail (\d+)$", output, re.M)
            require(tests == [str(len(expected))] and skips == ["0"], "Node test count or skip contract failed")
            if args.suite == "negative":
                require(code == 1 and fails == ["1"], "Baseline must have raw exit 1 and exactly one failure")
                first, control = cases
                require(first["status"] == "fail" and first.get("code") == "ERR_ASSERTION"
                        and first["checks"] == 1 and first.get("message", "").startswith("SP61_A4_NIGHT_BEST_MUST_BE_NULL")
                        and control["status"] == "pass" and control["checks"] == 5,
                        "Not the specific non-null-best baseline failure plus healthy control")
                receipt["counts"]["expected_negative_failures"] = 1
                require(snapshot(baseline, baseline_manifest) == baseline_manifest, "Baseline source mutated")
            else:
                require(code == 0 and fails == ["0"] and all(c["status"] == "pass" for c in cases), "Focused assertions failed")
        else:
            totals = {key: re.findall(rf"^# {key} (\d+)$", output, re.M) for key in ("tests", "pass", "fail", "skipped", "cancelled", "todo")}
            require(all(len(v) == 1 for v in totals.values()), "Missing Node regression totals")
            total = int(totals["tests"][0])
            receipt["counts"]["test_cases"] = total
            require(code == 0 and total == 18 and totals["pass"] == [str(total)]
                    and all(totals[k] == ["0"] for k in ("fail", "skipped", "cancelled", "todo")), "Regression failed or skipped")
            receipt["assertion_count_note"] = "Original unchanged suites expose case counts, not individual assertion instrumentation."
        require(snapshot(ROOT, names) == before, "Candidate source changed during suite")
        receipt.update(verdict="PASS_REVIEW_REQUIRED", wrapper_exit=0)
    except Exception as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
        receipt["counts"]["unexpected_failures"] = 1
    receipt["output_hashes"] = {str(p.relative_to(run)): sha(p) for p in run.iterdir() if p.is_file()}
    dump(run / "receipt.json", receipt)
    print(json.dumps({"receipt": str(run / "receipt.json"), "verdict": receipt["verdict"], "counts": receipt["counts"]}))
    return receipt["wrapper_exit"]


if __name__ == "__main__":
    raise SystemExit(main())
