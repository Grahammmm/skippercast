#!/usr/bin/env python3
"""Acceptance launcher for SP-RULES-STATUS (no Verified badge on an unknown rules state).

A small stdlib argv launcher: it derives the repository from its own path and runs the operator-pinned
installed Node 22 with --test and literal test-file arguments against the real product modules
(web/regs.ts by Node type stripping). It never installs anything; a missing runtime or registered
package is reported as INPUT_UNAVAILABLE for the operator.

  --suite focused     tests/test_sp_rules_status.mjs
  --suite regression  tests/test_regulations.mjs tests/test_regs_wrapper.mjs
  --suite negative    a uniquely staged test-local copy of web/regs.ts with only the summary state gate
                      reverted to the baseline must fail exactly the unknown-with-fresh-checks tests while
                      every other test stays green; a restored valid staged copy must pass everything.
                      The submitted source is hashed before and after and never changes.

Each run writes a new directory below --output with raw argv/cwd/exit/counts/stdout/stderr and hashes.
Exit codes: 0 PASS, 1 FAIL, 2 usage, 3 INPUT_UNAVAILABLE.
"""

import argparse
import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FOCUSED = ["tests/test_sp_rules_status.mjs"]
REGRESSION = ["tests/test_regulations.mjs", "tests/test_regs_wrapper.mjs"]
SOURCE = "web/regs.ts"
REGISTRY = "tests/fixtures/regulations/fe61-v1.json"
FIXTURES = "tests/fixtures/sp_rules_status"
# Operator-pinned installed Node 22 (agent-work/tools); overridable only with an explicit --node argument.
PINNED_NODE = Path.home() / "agent-work" / "tools" / "node" / "bin" / "node"

FOCUSED_TESTS = [
    "A1 reviewed in-period open, closed, restricted and scheduled states keep their limits and Verified check date",
    "A2 expired and not-yet-valid rule periods are unknown with no Verified badge",
    "A2 a review time beyond the future tolerance is unknown with no Verified badge",
    "A2 a season that needs a fishing location is unknown with no Verified badge",
    "A2 absent registry, unknown target and unreviewed content show no Verified badge",
    "A2 changed and stale sources keep the last parseable check as checked only",
    "A2 combined reef with one unknown member is unknown with no Verified badge",
    "A3 unknown keeps the registry limits, withholds depth and is never turned open or closed",
    "A4 a future trip outside valid_through with fresh reviewed checks has empty issues, unknown state and no Verified badge",
    "A4 the same record inside its valid period still shows Verified",
    "no case performed network IO",
]
# Reverting only the summary state gate must fail exactly these (unknown state with an empty issue list).
MUTANT_FAILURES = {
    "A2 expired and not-yet-valid rule periods are unknown with no Verified badge",
    "A2 a review time beyond the future tolerance is unknown with no Verified badge",
    "A2 a season that needs a fishing location is unknown with no Verified badge",
    "A2 combined reef with one unknown member is unknown with no Verified badge",
    "A4 a future trip outside valid_through with fresh reviewed checks has empty issues, unknown state and no Verified badge",
}
VALID_CONTROLS = set(FOCUSED_TESTS) - MUTANT_FAILURES
GATE = "if (oldest && status !== 'unknown' && !state.issues?.length && data.rules_review_status === 'reviewed') summary.verified = short(oldest);"
BASELINE_GATE = "if (oldest && !state.issues?.length && data.rules_review_status === 'reviewed') summary.verified = short(oldest);"

TAP_RESULT = re.compile(r"^(not ok|ok) \d+ - (.*?)(?: # (SKIP|TODO).*)?$")
TAP_COUNT = re.compile(r"^# (tests|suites|pass|fail|cancelled|skipped|todo) (\d+)$")
RELATIVE_IMPORT = re.compile(r"""(from\s*)(['"])(\.{1,2}/[^'"]+)\2""")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tap(stdout):
    """Top-level results (zero indent) and the summary counts from node's TAP reporter."""
    results, counts = [], {}
    for line in stdout.splitlines():
        m = TAP_RESULT.match(line)
        if m:
            results.append({"name": m.group(2).replace("\\#", "#"), "ok": m.group(1) == "ok", "directive": m.group(3)})
        m = TAP_COUNT.match(line)
        if m:
            counts[m.group(1)] = int(m.group(2))
    return results, counts


def node_version(node):
    try:
        out = subprocess.run([str(node), "--version"], capture_output=True, text=True, timeout=30, check=False)
    except OSError:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def registered_packages():
    manifest = json.loads((REPO / "package.json").read_text(encoding="utf-8"))
    return sorted({**manifest.get("dependencies", {}), **manifest.get("devDependencies", {})})


def resolved_packages():
    """Each registered package's installed path and version under this repository's node_modules."""
    found = {}
    for name in registered_packages():
        pkg = REPO / "node_modules" / name / "package.json"
        if pkg.is_file():
            found[name] = {"path": str(pkg.parent.resolve()), "version": json.loads(pkg.read_text(encoding="utf-8")).get("version")}
        else:
            found[name] = None
    return found


def invoke(node, files, cwd, run_dir, label):
    argv = [str(node), "--test", "--test-reporter=tap", "--test-concurrency=1", *files]
    proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=900, check=False)
    out_path, err_path = run_dir / f"{label}.stdout.txt", run_dir / f"{label}.stderr.txt"
    out_path.write_text(proc.stdout)
    err_path.write_text(proc.stderr)
    results, counts = tap(proc.stdout)
    return {
        "label": label, "argv": argv, "cwd": str(cwd), "exit": proc.returncode, "counts": counts, "results": results,
        "stdout": out_path.name, "stdout_sha256": sha256(out_path), "stderr": err_path.name, "stderr_sha256": sha256(err_path),
    }


def all_green(inv, expected_names=None):
    """Exit 0, nothing failed/skipped/todo/cancelled, and (when named) every expected test ran and passed."""
    c, problems = inv["counts"], []
    if inv["exit"] != 0:
        problems.append(f"{inv['label']}: exit {inv['exit']}")
    for key in ("fail", "cancelled", "skipped", "todo"):
        if c.get(key, -1) != 0:
            problems.append(f"{inv['label']}: {key}={c.get(key)}")
    if not c.get("tests") or c.get("pass") != c.get("tests"):
        problems.append(f"{inv['label']}: pass {c.get('pass')} of {c.get('tests')}")
    if any(r["directive"] for r in inv["results"]):
        problems.append(f"{inv['label']}: a test carries a SKIP/TODO directive")
    if any(not r["ok"] for r in inv["results"]):
        problems.append(f"{inv['label']}: not ok {[r['name'] for r in inv['results'] if not r['ok']]}")
    if expected_names is not None:
        names = [r["name"] for r in inv["results"]]
        if sorted(names) != sorted(expected_names):
            problems.append(f"{inv['label']}: test names differ from the frozen list: missing {sorted(set(expected_names) - set(names))}, extra {sorted(set(names) - set(expected_names))}")
    return problems


def stage(run_dir, name):
    """A test-local copy of web/regs.ts, the focused test and the registry fixture; never the submitted tree.

    The staged module's relative imports point at the same repository modules by absolute file URL, and
    node_modules is a symlink to this repository's, so the dependency closure is the repository's own.
    """
    root = run_dir / name
    for rel in ["package.json", SOURCE, *FOCUSED, REGISTRY]:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, root / rel)
    if (REPO / FIXTURES).is_dir():
        shutil.copytree(REPO / FIXTURES, root / FIXTURES)
    (root / "node_modules").symlink_to((REPO / "node_modules").resolve(), target_is_directory=True)
    text = (root / SOURCE).read_text(encoding="utf-8")
    rewired = []

    def absolute(m):
        target = (REPO / Path(SOURCE).parent / m.group(3)).resolve()
        rewired.append({"from": m.group(3), "to": target.as_uri(), "exists": target.is_file()})
        return f"{m.group(1)}{m.group(2)}{target.as_uri()}{m.group(2)}"

    (root / SOURCE).write_text(RELATIVE_IMPORT.sub(absolute, text), encoding="utf-8")
    missing = [r["from"] for r in rewired if not r["exists"]]
    return root, rewired, (f"staged closure is missing {missing}" if missing else None)


def run(args):
    started = datetime.datetime.now(datetime.timezone.utc)
    output = Path(args.output).resolve()
    if output == REPO or REPO in output.parents:
        print("INPUT_UNAVAILABLE: --output must be outside the repository", file=sys.stderr)
        return 3
    run_dir = output / f"{started.strftime('%Y%m%dT%H%M%S.%fZ')}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    node = Path(args.node) if args.node else PINNED_NODE
    receipt = {
        "task": "SP-RULES-STATUS", "suite": args.suite, "argv": [sys.executable, *sys.argv], "cwd": os.getcwd(),
        "started_at": started.isoformat(), "repo": str(REPO), "run_dir": str(run_dir),
        "python": {"executable": sys.executable, "version": platform.python_version()},
        "node": {"path": str(node), "resolved": str(node.resolve()) if node.exists() else None, "version": None},
        "node_modules": {"path": str(REPO / "node_modules"), "resolved": str((REPO / "node_modules").resolve()) if (REPO / "node_modules").exists() else None},
        "packages": {}, "modules": {}, "invocations": [], "problems": [], "verdict": None,
    }
    status = None
    version = node_version(node) if node.exists() else None
    receipt["node"]["version"] = version
    if not version or not version.startswith("v22."):
        receipt["problems"].append(f"pinned Node 22 runtime unavailable at {node} (version {version})")
        status = "INPUT_UNAVAILABLE"
    receipt["packages"] = resolved_packages()
    absent = [name for name, info in receipt["packages"].items() if info is None]
    if absent:
        receipt["problems"].append(f"registered packages not installed in {REPO / 'node_modules'}: {absent} (operator-staged closure; no worker install)")
        status = "INPUT_UNAVAILABLE"
    for rel in [SOURCE, *FOCUSED, *REGRESSION, REGISTRY, "package.json", "pnpm-lock.yaml"]:
        p = REPO / rel
        receipt["modules"][rel] = {"path": str(p), "sha256": sha256(p) if p.is_file() else None}

    if status is None and args.suite == "focused":
        inv = invoke(node, FOCUSED, REPO, run_dir, "focused")
        receipt["invocations"].append(inv)
        receipt["problems"] += all_green(inv, FOCUSED_TESTS)
    elif status is None and args.suite == "regression":
        inv = invoke(node, REGRESSION, REPO, run_dir, "regression")
        receipt["invocations"].append(inv)
        receipt["problems"] += all_green(inv)
    elif status is None and args.suite == "negative":
        before = sha256(REPO / SOURCE)
        mutant, rewired, error = stage(run_dir, "stage-mutant")
        control, _, error2 = stage(run_dir, "stage-control")
        receipt["staged"] = {"mutant": str(mutant), "control": str(control), "rewired_imports": rewired}
        if error or error2:
            receipt["problems"].append(error or error2)
        else:
            text = (mutant / SOURCE).read_text(encoding="utf-8")
            if text.count(GATE) != 1:
                receipt["problems"].append(f"summary state gate {GATE!r} found {text.count(GATE)} times in {SOURCE}; expected exactly 1")
            else:
                (mutant / SOURCE).write_text(text.replace(GATE, BASELINE_GATE), encoding="utf-8")
                receipt["staged"]["mutant_source_sha256"] = sha256(mutant / SOURCE)
                receipt["staged"]["control_source_sha256"] = sha256(control / SOURCE)
                receipt["staged"]["reverted"] = {"from": GATE, "to": BASELINE_GATE}
                bad = invoke(node, FOCUSED, mutant, run_dir, "negative-mutant")
                receipt["invocations"].append(bad)
                failed = {r["name"] for r in bad["results"] if not r["ok"]}
                passed = {r["name"] for r in bad["results"] if r["ok"]}
                if bad["exit"] == 0:
                    receipt["problems"].append("reverted gate was NOT detected: the mutant run exited 0")
                if failed != MUTANT_FAILURES:
                    receipt["problems"].append(f"mutant failures differ: unexpected {sorted(failed - MUTANT_FAILURES)}, undetected {sorted(MUTANT_FAILURES - failed)}")
                if passed | failed != set(FOCUSED_TESTS):
                    receipt["problems"].append("mutant run did not execute every named test")
                if not VALID_CONTROLS <= passed:
                    receipt["problems"].append(f"valid controls did not pass on the mutant: {sorted(VALID_CONTROLS - passed)}")
                for key in ("cancelled", "skipped", "todo"):
                    if bad["counts"].get(key, -1) != 0:
                        receipt["problems"].append(f"negative-mutant: {key}={bad['counts'].get(key)}")
                good = invoke(node, FOCUSED, control, run_dir, "negative-control")
                receipt["invocations"].append(good)
                receipt["problems"] += all_green(good, FOCUSED_TESTS)
        after = sha256(REPO / SOURCE)
        receipt["submitted_source_sha256"] = {"before": before, "after": after}
        if before != after:
            receipt["problems"].append("submitted source changed during the negative suite")

    if status is None:
        status = "FAIL" if receipt["problems"] else "PASS"
    receipt["verdict"] = status
    receipt["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    path = run_dir / "receipt.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"SP-RULES-STATUS {args.suite}: {status}")
    for inv in receipt["invocations"]:
        print(f"  {inv['label']}: exit {inv['exit']} {inv['counts']}")
    for problem in receipt["problems"]:
        print("  problem: " + problem)
    print(f"  receipt {path} sha256 {sha256(path)}")
    return {"PASS": 0, "FAIL": 1, "INPUT_UNAVAILABLE": 3}[status]


def main():
    parser = argparse.ArgumentParser(description="SP-RULES-STATUS acceptance launcher")
    parser.add_argument("--suite", required=True, choices=["focused", "regression", "negative"])
    parser.add_argument("--output", required=True, help="parent directory; each run makes a new unique child")
    parser.add_argument("--node", help="explicit Node 22 executable (default: the operator-pinned install)")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
