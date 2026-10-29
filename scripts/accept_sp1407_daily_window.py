"""Portable, offline SP1407 argv launcher. Green means REVIEW REQUIRED only."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
CANDIDATE = REPO.parent
BASE = "33734f90073a2150eac5a418564ea314c4a591ac"
PRIMARY = "server/advisor/answers/reports.ts"
PRIMARY_SHA = "8f8f5e8d134922ec89c3b805f0e14f370ab8ed44ee18c0fd19fb4c2b4761f5f3"
TEST = "tests/test_sp1407_daily_window.mjs"
FIXTURES = REPO / "tests/fixtures/sp1407_daily_window"
SPEC = {
    "version": "SP-14-v1",
    "card": "SP1407-DAILY-WINDOW",
    "amendment": "operator-standing-admission-2026-10-25-0441-PDT: remove only obsolete 2026-09-25 planning expectation",
    "A1": "today and preceding two calendar dates, descending; exclude future and fourth date",
    "A2": "retain status/port filters, anonymity and empty fallback",
    "A3": "calendar boundaries, hash/version/recompute, eight-row cap and downstream planning",
    "A4": "unchanged-module primary regression red and healthy control green; identical pair green after fix",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_ancestry(path):
    """Reject symlinks/non-directory existing ancestors before output access."""
    path = Path(os.path.abspath(path))
    for item in reversed([path, *path.parents]):
        try:
            mode = item.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise ValueError(f"not a plain directory: {item}")
    return path


def git(*args):
    return subprocess.check_output(["git", "-C", str(REPO), *args], text=True).strip()


def source_hashes():
    # Complete advisor module closure, migrations and selected fixture/test closure.
    # The pinned git tree identifies the remaining unchanged repository inputs.
    paths = {PRIMARY, TEST, "scripts/accept_sp1407_daily_window.py", "tests/_advisor_d1.mjs",
             "tests/test_advisor_daily.mjs", "tests/test_advisor_tools.mjs", "package.json", "pnpm-lock.yaml"}
    note = "docs/engineering/sp1407_daily_window.md"
    if (REPO / note).is_file():
        paths.add(note)
    for item in FIXTURES.rglob("*"):
        mode = item.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError("fixture contains a link or non-regular entry")
    for prefix in ["server/advisor", "drizzle", "tests/fixtures/sp1407_daily_window", "tests/fixtures/advisor/daily", "tests/fixtures/feeds"]:
        paths.update(p.relative_to(REPO).as_posix() for p in (REPO / prefix).rglob("*") if p.is_file())
    return {name: digest((REPO / name).read_bytes()) for name in sorted(paths)}


def counts(text):
    summary: dict[str, object] = {k: int(v) for k, v in re.findall(r"^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$", text, re.M)}
    summary["names"] = re.findall(r"^(?:not )?ok \d+ - (.+?)(?: #.*)?$", text, re.M)
    summary["failed_names"] = re.findall(r"^not ok \d+ - (.+?)(?: #.*)?$", text, re.M)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=["baseline", "focused", "regression", "repository", "typecheck", "build"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Do not resolve output before testing its original ancestry.
    out = safe_ancestry(args.output)
    allowed = safe_ancestry(CANDIDATE / "out")
    if not out.is_relative_to(allowed):
        raise ValueError("output must be beneath candidate/out")
    safe_ancestry(FIXTURES)
    run = out / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex)
    run.mkdir(parents=True, exist_ok=False)
    manifest_path = CANDIDATE / "SOURCE-MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != "agentorange.source-manifest/v1" or Path(manifest["repo"]).resolve() != REPO:
        raise ValueError("source admission schema/repository mismatch")
    base = manifest["head"]
    if base != BASE:
        raise ValueError("staged base changed; return for byte reconciliation")
    subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"], cwd=REPO, check=True)
    scan_python = manifest.get("runtime", {}).get("credential_scan_python3")
    if not scan_python or not Path(scan_python).is_file():
        raise ValueError("admitted credential scanner interpreter unavailable; no fallback")
    node = shutil.which("node")
    pnpm = shutil.which("pnpm")
    if not node or not pnpm:
        raise ValueError("staged Node/pnpm unavailable; no install/fallback")
    source = source_hashes()
    head = git("rev-parse", "HEAD")
    if args.suite == "baseline" and source[PRIMARY] != PRIMARY_SHA:
        raise ValueError("baseline requires pinned unchanged product bytes")
    receipt = {
        "schema": "sp1407.acceptance/v1", "spec": SPEC, "spec_sha256": digest(json.dumps(SPEC, sort_keys=True).encode()),
        "phase": args.suite, "staged_base": base, "head": head, "tree": git("rev-parse", "HEAD^{tree}"),
        "source_manifest_sha256": digest(manifest_path.read_bytes()), "sources": source,
        "status_before": git("status", "--porcelain"),
        "author_runtime": {"model": "gpt-6.1-sol", "provider": "openai-codex", "profile": "sol-reviewer", "run": "1962"},
        "material_commits": git("log", "--format=%H%n%B", f"{base}..HEAD"),
        "python": {"executable": sys.executable, "version": sys.version},
        "checks": [], "result": "UNVERIFIED",
    }
    diff = subprocess.check_output(["git", "diff", base, "--"], cwd=REPO)
    (run / "tracked.diff").write_bytes(diff)
    receipt["diff_sha256"] = digest(diff)

    def child(argv, label, env=None):
        result = subprocess.run(argv, cwd=REPO, env=env, capture_output=True)
        stdout, stderr = run / (label + ".stdout"), run / (label + ".stderr")
        stdout.write_bytes(result.stdout)
        stderr.write_bytes(result.stderr)
        item = {"label": label, "argv": argv, "cwd": str(REPO), "exit": result.returncode,
                "stdout": stdout.name, "stderr": stderr.name,
                "stdout_sha256": digest(result.stdout), "stderr_sha256": digest(result.stderr),
                "counts": counts(result.stdout.decode(errors="replace")),
                "reported_file_checks": re.findall(r"Checked (\d+) text files", result.stdout.decode(errors="replace")),
                "command_count": 1}
        receipt["checks"].append(item)
        return item, result.stdout.decode(errors="replace")

    version, version_text = child([node, "--version"], "node-version")
    receipt["node"] = {"executable": node, "version": version_text.strip()}
    ok = version["exit"] == 0
    if args.suite in {"baseline", "focused", "regression"}:
        names = [TEST] if args.suite != "regression" else ["tests/test_advisor_daily.mjs", "tests/test_advisor_tools.mjs"]
        environment = dict(os.environ, SP1407_SUITE=args.suite)
        check, text = child([node, "--experimental-strip-types", "--import", str(FIXTURES / "bootstrap.mjs"), "--test", "--test-reporter=tap", *names], "tests", environment)
        c = check["counts"]
        clean = all(c.get(k) == 0 for k in ["cancelled", "skipped", "todo"])
        if args.suite == "baseline":
            ok = ok and clean and check["exit"] == 1 and c.get("tests") == 2 and c.get("pass") == 1 and c.get("fail") == 1
            ok = ok and c["names"] == ["primary regression", "healthy control"] and c["failed_names"] == ["primary regression"]
            ok = ok and "SP1407_THREE_CALENDAR_DATES" in text and "ERR_ASSERTION" in text
            receipt["result"] = "BASELINE_GAP_REPRODUCED" if ok else "BASELINE_REJECTED"
        else:
            expected = (6 + len(json.loads((FIXTURES / "cases.json").read_text())["boundaries"])) if args.suite == "focused" else sum(
                len(re.findall(r"^(?:test|dbTest)\(", (REPO / name).read_text(), re.M)) for name in names)
            # Exact registered selected counts; no skip-based discovery loophole.
            ok = ok and clean and check["exit"] == 0 and c.get("tests") == expected and c.get("pass") == expected and c.get("fail") == 0
            receipt["result"] = "REVIEW_REQUIRED" if ok else "FAILED"
    else:
        if args.suite == "repository":
            commands = [[scan_python, str(REPO / "scripts/check_repository.py")]]
        elif args.suite == "typecheck":
            commands = [[pnpm, "exec", "tsc", "--noEmit", "-p", config] for config in ["tsconfig.json", "web/tsconfig.json", "packages/coast/tsconfig.json"]]
        else:
            commands = [[pnpm, "build"]]
        for index, argv in enumerate(commands):
            check, _ = child(argv, f"check-{index + 1}")
            ok = ok and check["exit"] == 0
        receipt["result"] = "REVIEW_REQUIRED" if ok else "FAILED"
    receipt["status_after"] = git("status", "--porcelain")
    receipt["sources_unchanged"] = source_hashes() == source
    if not receipt["sources_unchanged"] or git("rev-parse", "HEAD") != head:
        ok = False
        receipt["result"] = "SOURCE_DRIFT"
    receipt["completed_at"] = datetime.now(timezone.utc).isoformat()
    receipt_file = run / "receipt.json"
    receipt_file.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"result": receipt["result"], "receipt": str(receipt_file), "receipt_sha256": digest(receipt_file.read_bytes()),
                      "checks": [{"label": c["label"], "exit": c["exit"], "counts": c["counts"]} for c in receipt["checks"]]}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
