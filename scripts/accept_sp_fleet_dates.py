#!/usr/bin/env python3
"""Acceptance runner for SP-FLEET-DATES (public fleet heat cells need a real calendar last_date).

A small stdlib launcher: it runs the installed Node 22 test runner on literal test files of this
repository and keeps a raw receipt of every run. It executes the real product modules; it never
reimplements a check or manufactures a result.

  --suite focused     tests/test_sp_fleet_dates.mjs
  --suite regression  tests/test_fleet_public_heat.mjs tests/test_fleet_map.mjs
  --suite negative    a uniquely staged copy of the sources with only the date validation in
                      server/fleet/public-heat.ts reverted: the focused file must fail its A4
                      negative control there, while the unmodified and restored copies pass

Each invocation writes a new directory below --output (never reusing one) with receipt.json and
the raw stdout/stderr of every run. Exit 0 = PASS, 1 = FAIL, 3 = INPUT_UNAVAILABLE (a registered
dependency is not installed: the operator stages it; this script never installs anything).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FOCUSED = ["tests/test_sp_fleet_dates.mjs"]
REGRESSION = ["tests/test_fleet_public_heat.mjs", "tests/test_fleet_map.mjs"]
SOURCE = "server/fleet/public-heat.ts"
FIXTURE = "tests/fixtures/sp_fleet_dates/date_tokens.json"
# The exact top-level tests of the focused file; every one must run and pass.
FOCUSED_TESTS = [
    "A1 positive: delay, vessel floor, rights allowlist and cutoff arithmetic are unchanged",
    "A1 positive: valid leap days pass within the cutoff and fail past it",
    "A2 invalid calendar: every malformed or impossible last_date string is withheld",
    "A2 invalid calendar: dates that Date.parse rolls into another day are withheld",
    "A2 invalid calendar: a non-string last_date is withheld",
    "A3 consumer: publicHeat emits only the good row beside otherwise-qualified bad-date rows",
    "A3 consumer: paging follows the scanned rows, so withheld rows never stall a page",
    "A3 consumer: both enable flags stay off by default and the gate answers 404",
    "A4 negative control: an empty last_date with valid rights, vessels and geometry is withheld; its real-date twin is shown",
]
A4 = FOCUSED_TESTS[-1]
# With the date validation reverted these must still pass: a failure there is unrelated and is propagated.
MUTANT_MUST_PASS = [FOCUSED_TESTS[0], FOCUSED_TESTS[1], FOCUSED_TESTS[4], FOCUSED_TESTS[7]]
# The only change the negative control makes: the fixed predicate back to the baseline one.
MUTATION = ("calendarDate(row.last_date)", "typeof row.last_date === 'string'")
# What the negative stage copies (relative to the repository), with node_modules linked when present.
STAGE_TREES = ["server", "drizzle", "tests/fixtures/sp_fleet_dates"]
STAGE_FILES = ["package.json", "regions/morro-bay/region.json", "deployments/production.json", "tests/_advisor_d1.mjs", *FOCUSED]

TAP_RESULT = re.compile(r"^(not ok|ok) \d+ - (.*?)(?: # (SKIP|TODO)\b.*)?$")
TAP_COUNT = re.compile(r"^# (tests|suites|pass|fail|cancelled|skipped|todo) (\d+)$")


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def unique_dir(base: Path) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = base / f"{stamp}-{os.getpid()}-{secrets.token_hex(3)}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def node_runtime() -> dict:
    found = shutil.which("node")
    if not found:
        return {"error": "node not found"}
    out = subprocess.run([found, "--version"], capture_output=True, text=True, timeout=30)
    version = out.stdout.strip()
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", version)
    info = {"path": found, "realpath": os.path.realpath(found), "version": version}
    if not match or int(match.group(1)) != 22 or (int(match.group(1)), int(match.group(2))) < (22, 18):
        info["error"] = f"Node 22 (>= 22.18, package.json engines) is required, found {version or 'nothing'}"
    return info


def find_package(name: str, start: Path) -> Path | None:
    """Node's node_modules lookup from `start` upward: the package directory, or None."""
    for folder in [start, *start.parents]:
        candidate = folder / "node_modules" / name / "package.json"
        if candidate.is_file():
            return candidate.parent.resolve()
    return None


def dependencies(root: Path) -> tuple[dict, list]:
    """Every registered runtime dependency of package.json, resolved from `root`."""
    manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
    resolved, missing = {}, []
    for name in sorted(manifest.get("dependencies", {})):
        where = find_package(name, root)
        resolved[name] = str(where) if where else None
        if not where:
            missing.append(name)
    return resolved, missing


def git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=60)
    except OSError:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def parse_tap(stdout: str) -> tuple[dict, dict]:
    tests, counts = {}, {}
    for line in stdout.splitlines():
        result = TAP_RESULT.match(line)   # top level only: subtest lines are indented
        if result:
            status = result.group(3) or ("ok" if result.group(1) == "ok" else "fail")
            tests[result.group(2)] = status.lower()
        count = TAP_COUNT.match(line)
        if count:
            counts[count.group(1)] = int(count.group(2))
    return tests, counts


def run_node(node: str, files: list[str], cwd: Path, out: Path, label: str) -> dict:
    argv = [node, "--test", "--test-reporter=tap", *files]
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=900)
    stdout_file, stderr_file = out / f"{label}.stdout.txt", out / f"{label}.stderr.txt"
    stdout_file.write_text(proc.stdout, encoding="utf-8")
    stderr_file.write_text(proc.stderr, encoding="utf-8")
    tests, counts = parse_tap(proc.stdout)
    return {"label": label, "argv": argv, "cwd": str(cwd), "exit": proc.returncode, "counts": counts, "tests": tests,
            "stdout": stdout_file.name, "stdout_sha256": sha256(stdout_file),
            "stderr": stderr_file.name, "stderr_sha256": sha256(stderr_file)}


def clean(run: dict, expected: list[str] | None) -> list[str]:
    """Problems with a run that must pass: a nonzero exit, any failure, skip, todo or cancel, a missing test."""
    problems, counts = [], run["counts"]
    if run["exit"] != 0:
        problems.append(f"{run['label']}: exit {run['exit']}")
    for key in ("fail", "cancelled", "skipped", "todo"):
        if counts.get(key, -1) != 0:
            problems.append(f"{run['label']}: {key}={counts.get(key)}")
    if not counts.get("tests") or counts.get("pass") != counts.get("tests"):
        problems.append(f"{run['label']}: pass {counts.get('pass')} of {counts.get('tests')}")
    bad = sorted(name for name, status in run["tests"].items() if status != "ok")
    if bad:
        problems.append(f"{run['label']}: not ok {bad}")
    if expected is not None:
        missing = [name for name in expected if run["tests"].get(name) != "ok"]
        extra = sorted(set(run["tests"]) - set(expected))
        if missing:
            problems.append(f"{run['label']}: expected tests not passed {missing}")
        if extra:
            problems.append(f"{run['label']}: unexpected tests {extra}")
    return problems


def stage_copy(dest: Path) -> None:
    for tree in STAGE_TREES:
        shutil.copytree(REPO / tree, dest / tree)
    for name in STAGE_FILES:
        (dest / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / name, dest / name)
    if (REPO / "node_modules").exists():   # the same dependency closure, never a copy or an install
        (dest / "node_modules").symlink_to((REPO / "node_modules").resolve(), target_is_directory=True)


def negative(node: str, out: Path) -> tuple[list[dict], list[str], dict]:
    runs, problems = [], []
    stage = out / "stage"
    stage_copy(stage)
    target = stage / SOURCE
    original = target.read_bytes()
    detail: dict = {"stage": str(stage), "source_sha256": hashlib.sha256(original).hexdigest()}
    if detail["source_sha256"] != sha256(REPO / SOURCE):
        return runs, ["stage copy differs from the submitted source"], detail

    control = run_node(node, FOCUSED, stage, out, "control-before")
    runs.append(control)
    problems += clean(control, FOCUSED_TESTS)

    text = original.decode("utf-8")
    occurrences = text.count(MUTATION[0])
    detail["mutation"] = {"file": SOURCE, "from": MUTATION[0], "to": MUTATION[1], "occurrences": occurrences}
    if occurrences != 1:
        problems.append(f"mutation target found {occurrences} times in {SOURCE}, expected exactly once")
        return runs, problems, detail
    target.write_text(text.replace(MUTATION[0], MUTATION[1]), encoding="utf-8")
    detail["mutant_sha256"] = sha256(target)
    mutant = run_node(node, FOCUSED, stage, out, "mutant-date-validation-reverted")
    runs.append(mutant)
    if mutant["exit"] == 0:
        problems.append("mutant: the reverted date validation was not detected (exit 0)")
    if mutant["tests"].get(A4) != "fail":
        problems.append(f"mutant: the A4 negative control did not fail ({mutant['tests'].get(A4)})")
    for name in MUTANT_MUST_PASS:
        if mutant["tests"].get(name) != "ok":
            problems.append(f"mutant: unrelated test did not pass, propagated: {name} ({mutant['tests'].get(name)})")
    unknown = sorted(set(mutant["tests"]) - set(FOCUSED_TESTS))
    if unknown or any(mutant["counts"].get(k, -1) != 0 for k in ("cancelled", "skipped", "todo")):
        problems.append(f"mutant: unexpected tests {unknown} or counts {mutant['counts']}")
    detail["mutant_failed"] = sorted(name for name, status in mutant["tests"].items() if status != "ok")

    target.write_bytes(original)
    detail["restored_sha256"] = sha256(target)
    if detail["restored_sha256"] != detail["source_sha256"]:
        problems.append("restore did not reproduce the submitted source")
    restored = run_node(node, FOCUSED, stage, out, "control-restored")
    runs.append(restored)
    problems += clean(restored, FOCUSED_TESTS)
    return runs, problems, detail


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="SP-FLEET-DATES acceptance runner")
    parser.add_argument("--suite", required=True, choices=["focused", "regression", "negative"])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    out = unique_dir(args.output.resolve())
    watched = [SOURCE, FIXTURE, "scripts/accept_sp_fleet_dates.py", *FOCUSED, *REGRESSION, "tests/_advisor_d1.mjs"]
    receipt: dict = {"runner": str(Path(__file__).resolve()), "argv": [sys.executable, *sys.argv], "python": sys.executable,
               "python_version": sys.version.split()[0], "cwd": os.getcwd(), "repo": str(REPO), "suite": args.suite,
               "output": str(out), "started_at": now(), "git_head": git("rev-parse", "HEAD"),
               "git_dirty": git("status", "--porcelain", "--untracked-files=all"),
               "hashes_before": {name: sha256(REPO / name) for name in watched},
               "modules": {"public_heat": str((REPO / SOURCE).resolve())}}
    node = node_runtime()
    receipt["node"] = node
    resolved, missing = dependencies(REPO)
    receipt["dependencies"] = resolved
    runs, problems, status = [], [], None
    if "error" in node:
        status, problems = "INPUT_UNAVAILABLE", [node["error"]]
    elif args.suite == "regression" and missing:
        # The regression files load the whole Worker (server/index.ts), which imports these packages.
        status, problems = "INPUT_UNAVAILABLE", [f"registered dependencies not installed: {missing}"]
    elif args.suite == "focused":
        run = run_node(node["path"], FOCUSED, REPO, out, "focused")
        runs, problems = [run], clean(run, FOCUSED_TESTS)
    elif args.suite == "regression":
        run = run_node(node["path"], REGRESSION, REPO, out, "regression")
        runs, problems = [run], clean(run, None)
    else:
        runs, problems, receipt["negative"] = negative(node["path"], out)
    receipt["hashes_after"] = {name: sha256(REPO / name) for name in watched}
    if receipt["hashes_after"] != receipt["hashes_before"]:
        problems.append("a submitted file changed during the run")
        status = None
    status = status or ("PASS" if not problems else "FAIL")
    receipt.update({"runs": runs, "problems": problems, "status": status, "finished_at": now(),
                    "exit": {"PASS": 0, "FAIL": 1, "INPUT_UNAVAILABLE": 3}[status]})
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    for run in runs:
        print(f"{run['label']}: exit {run['exit']} {run['counts']}")
    for problem in problems:
        print(f"problem: {problem}", file=sys.stderr)
    print(f"{args.suite}: {status} ({out / 'receipt.json'})")
    return receipt["exit"]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
