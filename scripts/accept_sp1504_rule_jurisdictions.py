"""SP-15-v1 acceptance: explicit offline argv, immutable per-run raw receipts.

Run from this clone. No shell execution, dependency installation, source copying,
network acquisition, deployment, or fallback credential-scan interpreter.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT.parent
BASE = "8a805820c30895f5f037e26af9079fd3dc015b0f"
PRIMARY = "server/advisor/pages/species.ts"
PRIMARY_SHA = "fe8d2c223190eb157e0aaff171fa465350d9c898409fb8e2e1d2cfebc88b1071"
REGRESSION = "tests/test_advisor_pages.mjs"
REGRESSION_SHA = "58b1afab399577e6043b1e974e43b2a5208114204d873c857d8d1defdbf47170"
FIXTURE = "tests/fixtures/sp1504_rule_jurisdictions"
TEST = "tests/test_sp1504_rule_jurisdictions.mjs"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def git(*args):
    child = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)
    require(child.returncode == 0, f"git metadata failed: {args!r}")
    return child.stdout.decode()


def source_identity():
    names = sorted(set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")) - {""})
    hashes = {name: digest(ROOT / name) for name in names if (ROOT / name).is_file()}
    return {"head": git("rev-parse", "HEAD").strip(), "tree": git("rev-parse", "HEAD^{tree}").strip(),
            "status": git("status", "--porcelain"), "sha256": hashes}


def safe_output(raw):
    path = Path(os.path.abspath(raw))
    require(path.is_relative_to(CANDIDATE / "out"), "output must be under this candidate's out directory")
    for part in [path, *path.parents]:
        if part.exists() or part.is_symlink():
            mode = part.lstat().st_mode
            require(not stat.S_ISLNK(mode) and stat.S_ISDIR(mode), f"non-directory/symlink output ancestor: {part}")
    path.mkdir(parents=True, exist_ok=True)
    run = path / (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex)
    run.mkdir(exist_ok=False)
    return run


def tap_result(text):
    counts = {}
    for key in ("tests", "pass", "fail", "cancelled", "skipped", "todo"):
        matches = re.findall(rf"^# {key} (\d+)$", text, re.M)
        require(len(matches) == 1, f"missing/ambiguous TAP count: {key}")
        counts[key] = int(matches[0])
    counts["passed_names"] = re.findall(r"^ok \d+ - (.+)$", text, re.M)
    counts["failed_names"] = re.findall(r"^not ok \d+ - (.+)$", text, re.M)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=["baseline", "focused", "regression", "repository", "typecheck", "build"])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    require(Path.cwd().resolve() == ROOT, "cwd must be this staged clone")
    run = safe_output(args.output)
    receipt = {"schema": "skippercast.sp1504-acceptance/v1", "spec": "SP-15-v1", "card": "SP1504-RULE-JURISDICTIONS",
               "suite": args.suite, "launcher_argv": [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
               "cwd": str(ROOT), "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "python_runtime": sys.version, "children": [], "status": "FAIL", "run": str(run)}

    def child(label, argv, env=None):
        start = time.monotonic()
        stdout, stderr = run / f"{label}.stdout.txt", run / f"{label}.stderr.txt"
        entry = {"label": label, "argv": argv, "cwd": str(ROOT), "environment_delta": env or {},
                 "stdout": stdout.name, "stderr": stderr.name}
        receipt["children"].append(entry)
        with stdout.open("xb") as out, stderr.open("xb") as err:
            completed = subprocess.run(argv, cwd=ROOT, env={**os.environ, **(env or {})}, stdout=out, stderr=err, check=False)
        entry.update({"exit": completed.returncode, "duration_seconds": time.monotonic() - start,
                      "stdout_sha256": digest(stdout), "stderr_sha256": digest(stderr)})
        return entry, stdout.read_text(errors="replace"), stderr.read_text(errors="replace")

    try:
        stage = json.loads((CANDIDATE / "SOURCE-MANIFEST.json").read_text())
        require(stage["schema"] == "agentorange.source-manifest/v1", "wrong stage schema")
        require(Path(stage["repo"]).resolve() == ROOT and stage["head"] == BASE, "wrong stage identity")
        require(stage["runtime"]["credential_scan_python3"], "missing credential-scan interpreter")
        receipt["stage_manifest_sha256"] = digest(CANDIDATE / "SOURCE-MANIFEST.json")
        receipt["source_before"] = source_identity()
        require(receipt["source_before"]["sha256"][REGRESSION] == REGRESSION_SHA, "original regression changed")
        if args.suite == "baseline":
            require(receipt["source_before"]["head"] == BASE, "baseline must run before product commits")
            require(receipt["source_before"]["sha256"][PRIMARY] == PRIMARY_SHA, "baseline product differs from pin")
        node, pnpm = shutil.which("node"), shutil.which("pnpm")
        require(node and pnpm, "installed Node/pnpm required; no installation permitted")
        for name, argv in [("node-version", [node, "--version"]), ("pnpm-version", [pnpm, "--version"])]:
            entry, out, err = child(name, argv)
            require(entry["exit"] == 0, f"runtime identification failed: {name}")
            receipt[name] = out.strip()
        guard = str(ROOT / FIXTURE / "offline.mjs")
        if args.suite in {"baseline", "focused", "regression"}:
            selector = REGRESSION if args.suite == "regression" else TEST
            argv = [node, "--import", guard, "--test", "--test-reporter=tap", selector]
            entry, out, err = child(args.suite, argv, {"SP1504_MODE": args.suite})
            counts = tap_result(out)
            entry["counts"] = counts
            require(all(counts[key] == 0 for key in ("cancelled", "skipped", "todo")), "incomplete/skipped tests")
            if args.suite == "baseline":
                require(entry["exit"] == 1 and counts["tests"] == 2 and counts["pass"] == counts["fail"] == 1, "unexpected baseline counts/exit")
                require(counts["failed_names"] == ["primary regression"] and counts["passed_names"] == ["healthy control"], "unexpected baseline test identities")
                require("A1_JURISDICTION_FALLBACK: southern own must not hide northern parent" in out and "ERR_ASSERTION" in out and "deepStrictEqual" in out, "baseline was not the exact semantic assertion")
                require(not re.search(r"(?:ERR_MODULE_NOT_FOUND|SyntaxError|ReferenceError|hookFailed|SP1504_OFFLINE_BOUNDARY)", out + err), "baseline setup/boundary error")
                receipt["status"] = "BASELINE_GAP_REPRODUCED"
            else:
                expected_count = 8 if args.suite == "focused" else len(re.findall(r"^(?:test|dbTest)\(", (ROOT / REGRESSION).read_text(), re.M))
                require(entry["exit"] == 0 and counts["tests"] == counts["pass"] == expected_count and counts["fail"] == 0, "selected suite failed or test count changed")
                receipt["status"] = "SCOPED_GREEN_REVIEW_REQUIRED"
        elif args.suite == "repository":
            interpreter = stage["runtime"]["credential_scan_python3"]
            require(Path(interpreter).is_file(), "pinned credential-scan runtime missing; no fallback")
            entry, out, err = child("credential-python-version", [interpreter, "--version"])
            require(entry["exit"] == 0, "credential-scan runtime unavailable")
            entry, out, err = child("repository", [interpreter, str(ROOT / "scripts/check_repository.py")])
            require(entry["exit"] == 0, "repository check failed")
            count = re.search(r"Checked (\d+) text files", out)
            require(count is not None, "repository check summary missing")
            entry["text_files_checked"] = int(count.group(1))
            receipt["status"] = "SCOPED_GREEN_REVIEW_REQUIRED"
        elif args.suite == "typecheck":
            for number, config in enumerate(["tsconfig.json", "web/tsconfig.json", "packages/coast/tsconfig.json"], 1):
                entry, out, err = child(f"typecheck-{number}", [pnpm, "exec", "tsc", "--noEmit", "-p", config])
                require(entry["exit"] == 0, f"typecheck failed: {config}")
                entry["configurations_checked"] = 1
            receipt["status"] = "SCOPED_GREEN_REVIEW_REQUIRED"
        else:
            entry, out, err = child("build", [pnpm, "build"])
            require(entry["exit"] == 0 and "Built shared regional Worker and public assets" in out, "candidate-local build failed")
            entry["builds_completed"] = 1
            receipt["status"] = "SCOPED_GREEN_REVIEW_REQUIRED"
        receipt["source_after"] = source_identity()
        require(receipt["source_after"] == receipt["source_before"], "source bytes/identity changed during acceptance")
    except Exception as error:
        receipt["status"] = "FAIL"
        receipt["error"] = f"{type(error).__name__}: {error}"
    finally:
        receipt["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        target = run / "receipt.json"
        target.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        print(f"{receipt['status']}: {target}")
        print(f"receipt_sha256: {digest(target)}")
        if "error" in receipt:
            print(receipt["error"], file=sys.stderr)
    return 1 if receipt["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
