#!/usr/bin/env python3
"""SP1301-EVENT-SEGMENT (SP-13-v2) offline acceptance helper.

    python3 scripts/accept_sp1301_event_segment.py --suite {baseline,focused,regression,repository,typecheck} --output DIR

The repository is derived from this file's location and the candidate is its parent, which
must hold the operator-written SOURCE-MANIFEST.json (schema agentorange.source-manifest/v1).
Every run creates a fresh unique child of DIR (never reused, never a symlink) holding the raw
child stdout/stderr, a JUnit report for Node runs and manifest.json with argv, cwd, exits,
runtime versions, test names/counts, file hashes and per-commit material authorship, plus
manifest.json.sha256. Gates are explicit exit conditions, not Python asserts.

Modes:
  baseline    only the A4 pair ('primary regression', 'healthy control') with
              SP1301_SUITE=baseline; passes (exit 0, BASELINE_GAP_REPRODUCED) only when the
              primary fails by assertion, the control passes, the child exits 1 and nothing
              errors or skips, on unchanged base bytes of server/fleet/activity.ts.
  focused     the whole new test file: every named A1-A4 case runs and passes, zero skips.
  regression  tests/test_fleet_activity.mjs unchanged from the base; all its tests pass, zero skips.
  repository  unchanged scripts/check_repository.py under the manifest's
              runtime.credential_scan_python3 (no system-Python fallback).
  typecheck   pnpm exec tsc --noEmit -p for each of the three programs, separately.

Node children get a scratch HOME/TMPDIR inside the run directory, no inherited credentials,
and tests/fixtures/sp1301_event_segment/tripwire.mjs preloaded to fail any network attempt.
Scoped success is REVIEW REQUIRED, not full-suite or shipping approval.
"""
import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import platform  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CANDIDATE = REPO.parent
SPEC = "SP-13-v2"
CARD = "SP1301-EVENT-SEGMENT"
MANIFEST_SCHEMA = "agentorange.source-manifest/v1"
PRIMARY = "server/fleet/activity.ts"
TEST = "tests/test_sp1301_event_segment.mjs"
FIXTURE_DIR = "tests/fixtures/sp1301_event_segment"
TRIPWIRE = FIXTURE_DIR + "/tripwire.mjs"
HELPER = "scripts/accept_sp1301_event_segment.py"
NOTE = "docs/engineering/sp1301_event_segment.md"
REGRESSION = ["tests/test_fleet_activity.mjs"]
CHECKER = "scripts/check_repository.py"
TYPECHECK = ["tsconfig.json", "web/tsconfig.json", "packages/coast/tsconfig.json"]
PAIR = ["primary regression", "healthy control"]
CASE_MAP = {
    "A1": ["A1: cross-trip segment refused 400 with the indexed event error and no D1 call, either direction"],
    "A2": ["A2: correctly paired two-trip request stores each event with its own segment and trip, order-independent and idempotent"],
    "A3": ["A3: missing trip, missing segment, duplicate derived segment and isolated cross-trip segment refuse before side effects"],
    "A4": PAIR,
}
AUTHORED = [PRIMARY, TEST, HELPER, NOTE]
PRIVATE_PATH = re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/")


class Gate(Exception):
    """An acceptance precondition or gate that did not hold."""


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    return sha256_bytes(Path(path).read_bytes())


def git(*args, check=True):
    proc = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True)
    if check and proc.returncode != 0:
        raise Gate(f"git {' '.join(args)} exited {proc.returncode}: {proc.stderr.decode(errors='replace').strip()}")
    return proc


def no_symlink_ancestry(path, root):
    """Every component from `root` (exclusive) down to `path` exists only as a real entry."""
    path, root = Path(path), Path(root)
    rel = path.relative_to(root)
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise Gate(f"symlink in ancestry: {current}")


def load_manifest():
    path = CANDIDATE / "SOURCE-MANIFEST.json"
    if path.is_symlink() or not path.is_file():
        raise Gate(f"missing operator SOURCE-MANIFEST.json at {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    if manifest.get("schema") != MANIFEST_SCHEMA:
        problems.append("schema")
    if manifest.get("card") != CARD:
        problems.append("card")
    if Path(manifest.get("repo", "")).resolve() != REPO:
        problems.append("repo")
    if not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("head", ""))):
        problems.append("head")
    scan = (manifest.get("runtime") or {}).get("credential_scan_python3")
    if not scan or not Path(scan).is_file():
        problems.append("runtime.credential_scan_python3")
    if problems:
        raise Gate(f"SOURCE-MANIFEST.json mismatch: {', '.join(problems)}")
    if git("cat-file", "-e", manifest["head"] + "^{commit}", check=False).returncode != 0:
        raise Gate("manifest head is not a commit in the staged repository")
    return manifest, sha256_file(path)


def make_run_dir(output):
    output = Path(output).absolute()
    out_root = CANDIDATE / "out"
    try:
        output.relative_to(out_root)
    except ValueError:
        raise Gate(f"--output must be under {out_root}") from None
    output.mkdir(parents=True, exist_ok=True)
    no_symlink_ancestry(output, CANDIDATE)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run = output / f"run-{stamp}-{os.getpid()}-{secrets.token_hex(3)}"
    os.mkdir(run)  # exclusive: an existing child is never reused
    (run / "tmp" / "home").mkdir(parents=True)
    return run


def child_env(run, extra=None):
    tmp = run / "tmp"
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp / "home"),
        "TMPDIR": str(tmp),
        "LANG": "C.UTF-8",
        "NO_COLOR": "1",
        "FORCE_COLOR": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "npm_config_update_notifier": "false",
        "CI": "1",
    }
    env.update(extra or {})
    return env


class Runner:
    def __init__(self, run):
        self.run = run
        self.children = []

    def __call__(self, name, argv, env, cwd=REPO):
        started = time.time()
        proc = subprocess.run([str(a) for a in argv], cwd=str(cwd), env=env, capture_output=True)
        out, err = self.run / f"{name}.stdout", self.run / f"{name}.stderr"
        out.write_bytes(proc.stdout)
        err.write_bytes(proc.stderr)
        record = {"name": name, "argv": [str(a) for a in argv], "cwd": str(cwd), "exit": proc.returncode,
                  "seconds": round(time.time() - started, 3),
                  "env_keys": sorted(env), "stdout": out.name, "stdout_sha256": sha256_bytes(proc.stdout),
                  "stderr": err.name, "stderr_sha256": sha256_bytes(proc.stderr)}
        self.children.append(record)
        if b"SP1301_TRIPWIRE" in proc.stderr:
            record["tripwire"] = True
        return proc, record


def parse_junit(path):
    """[{name, outcome, assertion, detail}] for every testcase (outcome pass/fail/skip/todo/cancelled)."""
    if not path.is_file():
        raise Gate(f"no JUnit report at {path}")
    tests = []
    for case in ET.parse(path).getroot().iter("testcase"):
        outcome, assertion, detail = "pass", None, ""
        for child in case:
            tag = child.tag.lower()
            text = (child.get("message") or "") + "\n" + (child.text or "")
            if tag == "skipped":
                outcome = "todo" if "todo" in (child.get("type") or child.get("message") or "").lower() else "skip"
            elif tag in ("failure", "error"):
                outcome = "cancelled" if (child.get("type") or "").lower().startswith("cancelled") else "fail"
                assertion = child.get("type") == "testCodeFailure" and ("ERR_ASSERTION" in text or "AssertionError" in text)
                detail = text.strip()[:2000]
        tests.append({"name": case.get("name"), "outcome": outcome, "assertion": assertion, "detail": detail})
    return tests


def counts(tests):
    out = {"registered": len(tests)}
    for t in tests:
        out[t["outcome"]] = out.get(t["outcome"], 0) + 1
    return out


def node_run(runner, run, name, files, extra_env=None):
    node = shutil.which("node")
    if not node:
        raise Gate("node is not installed")
    junit = run / f"{name}.junit.xml"
    argv = [node, "--import", (REPO / TRIPWIRE).as_uri(), "--test", "--test-concurrency=1",
            "--test-reporter=spec", "--test-reporter-destination=stdout",
            "--test-reporter=junit", f"--test-reporter-destination={junit}", *files]
    proc, record = runner(name, argv, child_env(run, extra_env))
    tests = parse_junit(junit)
    record["junit"] = junit.name
    record["junit_sha256"] = sha256_file(junit)
    record["tests"] = tests
    record["counts"] = counts(tests)
    if record.get("tripwire"):
        raise Gate(f"{name}: network tripwire fired")
    return proc, record, tests


def unchanged_from_base(base, path):
    return git("diff", "--quiet", base, "--", path, check=False).returncode == 0 and not git("status", "--porcelain", "--", path).stdout.strip()


def suite_baseline(runner, run, base):
    base_bytes = git("show", f"{base}:{PRIMARY}").stdout
    if (REPO / PRIMARY).read_bytes() != base_bytes:
        raise Gate("SOURCE_DRIFT: server/fleet/activity.ts differs from the staged base; baseline is historical test-first evidence only")
    proc, record, tests = node_run(runner, run, "node-baseline", [TEST], {"SP1301_SUITE": "baseline"})
    by_name = {t["name"]: t for t in tests}
    problems = []
    if sorted(by_name) != sorted(PAIR) or len(tests) != 2:
        problems.append(f"registered {sorted(by_name)} instead of exactly {PAIR}")
    primary, control = by_name.get(PAIR[0]), by_name.get(PAIR[1])
    if not primary or primary["outcome"] != "fail" or primary["assertion"] is not True:
        problems.append("primary regression did not fail by semantic assertion")
    if not control or control["outcome"] != "pass":
        problems.append("healthy control did not pass")
    if proc.returncode != 1:
        problems.append(f"child exit {proc.returncode}, expected 1")
    if any(t["outcome"] in ("skip", "todo", "cancelled") for t in tests):
        problems.append("skip/todo/cancelled present")
    return ("BASELINE_GAP_REPRODUCED", []) if not problems else ("BASELINE_NOT_REPRODUCED", problems)


def suite_focused(runner, run, base):
    proc, record, tests = node_run(runner, run, "node-focused", [TEST])
    names = [t["name"] for t in tests]
    expected = [n for group in CASE_MAP.values() for n in group]
    problems = [f"missing case {n}" for n in expected if n not in names]
    problems += [f"unexpected test {n}" for n in names if n not in expected]
    problems += [f"{t['name']}: {t['outcome']}" for t in tests if t["outcome"] != "pass"]
    if proc.returncode != 0:
        problems.append(f"child exit {proc.returncode}")
    record["case_map"] = CASE_MAP
    return ("FOCUSED_PASS", []) if not problems else ("FOCUSED_FAIL", problems)


def suite_regression(runner, run, base):
    problems = [f"{p} differs from the base" for p in REGRESSION if not unchanged_from_base(base, p)]
    proc, record, tests = node_run(runner, run, "node-regression", REGRESSION)
    if not tests:
        problems.append("no tests registered")
    problems += [f"{t['name']}: {t['outcome']}" for t in tests if t["outcome"] != "pass"]
    if proc.returncode != 0:
        problems.append(f"child exit {proc.returncode}")
    record["selectors"] = REGRESSION
    record["not_executed"] = []  # file selectors: every registration in the file is selected
    return ("REGRESSION_PASS", []) if not problems else ("REGRESSION_FAIL", problems)


def suite_repository(runner, run, base, manifest):
    scan = manifest["runtime"]["credential_scan_python3"]
    problems = [] if unchanged_from_base(base, CHECKER) else [f"{CHECKER} differs from the base"]
    env = child_env(run)
    _, version = runner("interpreter-version", [scan, "--version"], env)
    proc, record = runner("check-repository", [scan, str(REPO / CHECKER)], env)
    record["interpreter"] = scan
    record["interpreter_version"] = (run / version["stdout"]).read_text().strip() or (run / version["stderr"]).read_text().strip()
    if proc.returncode != 0:
        problems.append(f"check_repository exit {proc.returncode}")
    return ("REPOSITORY_PASS", []) if not problems else ("REPOSITORY_FAIL", problems)


def suite_typecheck(runner, run, base, manifest):
    pnpm = (manifest.get("runtime") or {}).get("pnpm") or shutil.which("pnpm")
    if not pnpm or not Path(pnpm).is_file():
        raise Gate("pnpm from runtime.pnpm is not available")
    problems = []
    for i, cfg in enumerate(TYPECHECK):
        proc, _ = runner(f"tsc-{i}", [pnpm, "exec", "tsc", "--noEmit", "-p", cfg], child_env(run))
        if proc.returncode != 0:
            problems.append(f"tsc -p {cfg} exit {proc.returncode}")
    return ("TYPECHECK_PASS", []) if not problems else ("TYPECHECK_FAIL", problems)


def provenance(base):
    log = git("log", "--format=%H%x1f%an <%ae>%x1f%(trailers:key=Material-Author,valueonly,separator=; )%x1f%(trailers:key=Signed-off-by,valueonly,separator=; )%x1e", f"{base}..HEAD").stdout.decode()
    commits = []
    for entry in filter(None, (e.strip() for e in log.split("\x1e"))):
        sha, author, material, signoff = (entry.split("\x1f") + ["", "", ""])[:4]
        commits.append({"commit": sha, "git_author": author, "material_author": material.strip() or "UNDECLARED",
                        "signed_off_by": signoff.strip() or None})
    return commits


def file_hashes():
    hashes = {}
    for rel in AUTHORED + REGRESSION + [CHECKER]:
        p = REPO / rel
        hashes[rel] = sha256_file(p) if p.is_file() else None
    for p in sorted((REPO / FIXTURE_DIR).rglob("*")):
        if p.is_file():
            hashes[str(p.relative_to(REPO))] = sha256_file(p)
    return hashes


def authored_checks():
    problems = []
    for rel in [TEST, HELPER, NOTE] + [str(p.relative_to(REPO)) for p in (REPO / FIXTURE_DIR).rglob("*") if p.is_file()]:
        p = REPO / rel
        if not p.exists():
            continue
        no_symlink_ancestry(p, REPO)
        if PRIVATE_PATH.search(p.read_text(encoding="utf-8", errors="replace")):
            problems.append(f"{rel}: box-only home path")
    return problems


def main():
    parser = argparse.ArgumentParser(description="SP1301-EVENT-SEGMENT offline acceptance helper")
    parser.add_argument("--suite", required=True, choices=["baseline", "focused", "regression", "repository", "typecheck"])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    run = runner = manifest_sha = base = None
    try:
        manifest, manifest_sha = load_manifest()
        base = manifest["head"]
        run = make_run_dir(args.output)
        runner = Runner(run)
        problems = authored_checks()
        suites = {"baseline": suite_baseline, "focused": suite_focused, "regression": suite_regression}
        if args.suite in suites:
            verdict, more = suites[args.suite](runner, run, base)
        elif args.suite == "repository":
            verdict, more = suite_repository(runner, run, base, manifest)
        else:
            verdict, more = suite_typecheck(runner, run, base, manifest)
        problems += more
        if problems and not verdict.endswith(("FAIL", "NOT_REPRODUCED")):
            verdict = args.suite.upper() + "_FAIL"
    except Gate as gate:
        verdict, problems = "PRECONDITION_FAIL", [str(gate)]
        if run is None:
            print(json.dumps({"spec": SPEC, "card": CARD, "suite": args.suite, "verdict": verdict, "problems": problems}, indent=2))
            return 2

    head = git("rev-parse", "HEAD").stdout.decode().strip()
    status = git("status", "--porcelain").stdout.decode()
    ok = not problems
    record = {
        "spec": SPEC, "card": CARD, "phase": args.suite, "verdict": verdict, "ok": ok, "problems": problems,
        "acceptance": "historical test-first evidence, not acceptance" if args.suite == "baseline" else "REVIEW REQUIRED (scoped offline evidence; full repository suites and exact-head CI remain OWED to the operator)",
        "staged_base": base, "head": head, "worktree_clean": status == "", "worktree_status": status.splitlines(),
        "source_manifest_sha256": manifest_sha, "commits": provenance(base) if base else [],
        "argv": [sys.executable, *sys.argv], "cwd": os.getcwd(), "repo": str(REPO), "run_dir": str(run),
        "runtime": {"python": sys.version.split()[0], "python_executable": sys.executable, "platform": platform.platform(),
                    "node": subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip() if shutil.which("node") else None},
        "hashes": file_hashes(),
        "children": runner.children if runner else [],
        "started_utc": run.name.split("-")[1],
        "full_discovery": "operator-run",
    }
    manifest_path = run / "manifest.json"
    data = json.dumps(record, indent=2, sort_keys=True).encode() + b"\n"
    manifest_path.write_bytes(data)
    (run / "manifest.json.sha256").write_text(f"{sha256_bytes(data)}  manifest.json\n")
    summary = {"verdict": verdict, "ok": ok, "problems": problems, "head": head, "run_dir": str(run),
               "manifest_sha256": sha256_bytes(data),
               "children": [{k: c.get(k) for k in ("name", "exit", "counts")} for c in record["children"]]}
    for c in record["children"]:
        for t in c.get("tests", []):
            print(f"  [{c['name']}] {t['outcome']:9} {t['name']}")
    print(json.dumps(summary, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
