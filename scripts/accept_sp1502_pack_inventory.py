#!/usr/bin/env python3
"""SP-15-v1 bounded offline acceptance; explicit argv, immutable per-run receipts.

No publication or release gate. The sibling SOURCE-MANIFEST.json is operator
staging input, never a committed runtime fixture. Other paths derive from this clone.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT.parent
BASE = "8a805820c30895f5f037e26af9079fd3dc015b0f"
PRIMARY_HASH = "74a01390d124d3181a83a2f28ae908d0b5303fb6d9987600099a81ff36bd5d21"
TEST = "tests/test_sp1502_pack_inventory.mjs"
FIXTURES = "tests/fixtures/sp1502_pack_inventory"
REGRESSIONS = {
    "tests/test_trip.mjs": "6b98cf0be21363f035f6cd69c98dbf6be7576d6bb6bf79facfcc378b1128bb50",
    "tests/test_offline.mjs": "02cc753b017367e21ecee91e21cc4dc7e28c3facc348196e7a7fe671ded33ae0",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def run(argv, out, label, env=None):
    start = time.monotonic()
    before = datetime.now(timezone.utc).isoformat()
    stdout, stderr = out / f"{label}.stdout.txt", out / f"{label}.stderr.txt"
    with stdout.open("xb") as so, stderr.open("xb") as se:
        result = subprocess.run(argv, cwd=ROOT, env=env, stdout=so, stderr=se, check=False, timeout=900)
    row = {"argv": argv, "cwd": str(ROOT), "exit": result.returncode,
           "started_at": before, "elapsed_seconds": time.monotonic() - start,
           "stdout": str(stdout), "stderr": str(stderr),
           "stdout_sha256": digest(stdout), "stderr_sha256": digest(stderr)}
    (out / f"{label}.json").write_text(json.dumps(row, indent=2) + "\n")
    return row, stdout.read_text(), stderr.read_text()


def identity(out, phase):
    rows = {}
    for label, argv in {
        "head": ["git", "rev-parse", "HEAD"],
        "status": ["git", "status", "--porcelain", "--untracked-files=all"],
        "index": ["git", "ls-files", "--stage"],
    }.items():
        row, text, _ = run(argv, out, f"{phase}-{label}")
        checked(row["exit"] == 0, f"cannot read git {label}")
        rows[label] = text.strip()
    paths = ["web/app/Trip.tsx", "web/trip.ts", "dist/offline-core.js", "dist/offline-pack.js",
             TEST, "scripts/accept_sp1502_pack_inventory.py", "scripts/check_repository.py",
             "docs/engineering/sp1502_pack_inventory.md", *REGRESSIONS]
    paths += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / FIXTURES).rglob("*")) if p.is_file()]
    hashes = {p: digest(ROOT / p) for p in paths if (ROOT / p).is_file()}
    return {"head": rows["head"], "status": rows["status"], "git_index_sha256": hashlib.sha256(rows["index"].encode()).hexdigest(),
            "sha256": hashes}


def tap(text):
    counts = {}
    for key in ("tests", "pass", "fail", "cancelled", "skipped", "todo"):
        match = re.search(rf"^# {key} (\d+)$", text, re.M)
        if match is None:
            raise RuntimeError(f"missing TAP {key} summary")
        counts[key] = int(match.group(1))
    checked(all(counts[k] == 0 for k in ("cancelled", "skipped", "todo")), "TAP cancelled/skipped/todo")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=["baseline", "focused", "regression", "repository", "typecheck", "build"])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    checked(output.is_relative_to(CANDIDATE / "out"), "output must be inside this candidate's out directory")
    output.mkdir(parents=True, exist_ok=True)
    out = output / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex)
    out.mkdir()
    report = {"spec": "SP-15-v1", "card": "SP1502-PACK-INVENTORY", "suite": args.suite,
              "launcher_argv": [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
              "cwd": str(ROOT), "staged_base": BASE, "runtime": {}, "commands": [], "status": "FAIL"}
    try:
        manifest_path = CANDIDATE / "SOURCE-MANIFEST.json"
        stage = json.loads(manifest_path.read_text())
        checked(stage.get("schema") == "agentorange.source-manifest/v1", "invalid source manifest schema")
        checked(Path(stage["repo"]).resolve() == ROOT and stage["head"] == BASE, "stage repo/head mismatch")
        report["source_manifest_sha256"] = digest(manifest_path)
        report["source_before"] = identity(out, "before")
        for path, expected in REGRESSIONS.items():
            checked(digest(ROOT / path) == expected, f"unchanged regression hash mismatch: {path}")
        node, pnpm = shutil.which("node"), shutil.which("pnpm")
        checked(node is not None and pnpm is not None, "installed node/pnpm missing; no install permitted")
        for label, argv in {"node": [node, "--version"], "pnpm": [pnpm, "--version"], "python": [sys.executable, "--version"]}.items():
            row, text, err = run(argv, out, f"runtime-{label}")
            report["commands"].append(row)
            checked(row["exit"] == 0, f"runtime unavailable: {label}")
            report["runtime"][label] = {"executable": argv[0], "version": (text + err).strip()}
        env = os.environ.copy()
        env.pop("SP1502_BASELINE_PAIR", None)
        env["SP1502_TEST_OUTPUT"] = str(out / "rendered-modules")
        commands = []
        if args.suite in {"baseline", "focused"}:
            if args.suite == "baseline":
                checked(digest(ROOT / "web/app/Trip.tsx") == PRIMARY_HASH, "baseline requires unchanged pinned product")
                checked(report["source_before"]["head"] == BASE, "baseline HEAD must be admitted base")
                env["SP1502_BASELINE_PAIR"] = "1"
            commands.append(("inventory", [node, "--test", "--test-reporter=tap", TEST]))
        elif args.suite == "regression":
            for i, path in enumerate(REGRESSIONS):
                commands.append((f"regression-{i}", [node, "--import", f"./{FIXTURES}/regression-guard.mjs", "--test", "--test-reporter=tap", path]))
        elif args.suite == "repository":
            python = stage["runtime"]["credential_scan_python3"]
            checked(Path(python).is_file() and os.access(python, os.X_OK), "admitted scan interpreter unavailable; no fallback")
            row, text, err = run([python, "--version"], out, "runtime-credential-scan-python")
            report["commands"].append(row)
            checked(row["exit"] == 0, "scan interpreter unavailable")
            report["runtime"]["credential_scan_python3"] = {"executable": python, "version": (text + err).strip()}
            commands.append(("repository", [python, str(ROOT / "scripts/check_repository.py")]))
        elif args.suite == "typecheck":
            for i, config in enumerate(["tsconfig.json", "web/tsconfig.json", "packages/coast/tsconfig.json"]):
                commands.append((f"typecheck-{i}", [pnpm, "exec", "tsc", "--noEmit", "-p", config]))
        else:
            commands.append(("build", [pnpm, "build"]))
        for label, argv in commands:
            row, text, err = run(argv, out, label, env)
            report["commands"].append(row)
            if args.suite in {"baseline", "focused", "regression"}:
                counts = tap(text)
                row["counts"] = counts
                if args.suite == "baseline":
                    checked(row["exit"] == 1 and counts == {"tests": 2, "pass": 1, "fail": 1, "cancelled": 0, "skipped": 0, "todo": 0}, "unexpected baseline result")
                    checked(re.search(r"^not ok 1 - primary regression$", text, re.M) is not None, "wrong baseline failing test")
                    checked(re.search(r"^ok 2 - healthy control$", text, re.M) is not None, "healthy control did not pass")
                    checked("A1_INITIAL_REJECTION_IS_UNKNOWN_NOT_EMPTY" in text and "ERR_ASSERTION" in text, "missing semantic regression failure")
                    checked("offline sentinel:" not in text + err and "ERR_MODULE" not in text + err, "baseline setup/guard failure")
                else:
                    expected = 9 if args.suite == "focused" else len(re.findall(r"^test\(", (ROOT / argv[-1]).read_text(), re.M))
                    checked(row["exit"] == 0 and counts["tests"] == expected and counts["pass"] == expected and counts["fail"] == 0, f"{label}: not all assertions green")
            else:
                checked(row["exit"] == 0, f"{label} failed; inspect retained raw output")
                if args.suite == "repository":
                    match = re.search(r"Checked (\d+) text files:", text)
                    if match is None:
                        raise RuntimeError("repository check did not report coverage")
                    row["checked_text_files"] = int(match.group(1))
                else:
                    row["checks"] = 1
        report["source_after"] = identity(out, "after")
        checked(report["source_before"] == report["source_after"], "source identity changed during acceptance")
        report["status"] = "BASELINE_GAP_REPRODUCED" if args.suite == "baseline" else "SCOPED_GREEN_REVIEW_REQUIRED"
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
    receipt = out / "receipt.json"
    receipt.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "receipt": str(receipt), "sha256": digest(receipt),
                      "results": [{k: row[k] for k in ("argv", "exit", "counts", "checked_text_files", "checks") if k in row} for row in report["commands"]],
                      "error": report.get("error")}, indent=2))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
