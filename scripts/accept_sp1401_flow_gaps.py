#!/usr/bin/env python3
"""SP1401-FLOW-GAPS (SP-14-v1) offline acceptance launcher.

Stdlib-only argv launcher. Repository and candidate paths are derived from this
file's location; nothing here names a machine-specific home, plan or live path.
Every invocation writes a fresh unique child of --output (which must sit under
<candidate>/out) and never overwrites earlier evidence. Success is a scoped
machine verdict only: REVIEW REQUIRED, not whole-repository, semantic or release
acceptance. Explicit exit checks decide the verdict, never a bare assert.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
CANDIDATE = REPO.parent
SPEC = "SP-14-v1"
CARD = "SP1401-FLOW-GAPS"
MANIFEST_SCHEMA = "agentorange.source-manifest/v1"
PRIMARY = "web/map/flow.ts"
# Frozen SHA-256 of the pinned, unchanged primary file at the staged base.
PRIMARY_BASE_SHA256 = "d49ca52211025475ca104a5436d2a1b63470c82b6b3ae5c77e8e9ddaede58505"
NEW_TEST = "tests/test_sp1401_flow_gaps.mjs"
FIXTURE_DIR = "tests/fixtures/sp1401_flow_gaps"
NOTE = "docs/engineering/sp1401_flow_gaps.md"
REGRESSION_FILES = ["tests/test_flow.mjs"]
BASELINE_NAMES = {"primary regression": False, "healthy control": True}  # name -> expected to pass
FOCUSED_NAMES = [
    "primary regression",
    "healthy control",
    "A1: no emitted segment crosses a one-pixel gap: east/west, north/south and diagonal cells",
    "A1: the gap ends the path at its last supported vertex and leaves the other seed untouched",
    "A2: a fully supported constant vector keeps the baseline points, speed, fast flag and direction",
    "A2: the seed grid and MAX_PATHS cap are unchanged on a large screen",
    "A2: still water and a broad gap the probes already caught keep their baseline results",
    "A3: each five-pixel segment is sampled a constant bounded number of times at most one pixel apart",
    "A3: zero support, short paths and the viewport edge keep their existing results",
    "A3: the vector function, its field and masks are not mutated",
]
REGRESSION_COUNT = {"tests/test_flow.mjs": 14}
TYPECHECK_PROJECTS = ["tsconfig.json", "web/tsconfig.json", "packages/coast/tsconfig.json"]
STRIP_ENV = {"NODE_OPTIONS", "NODE_PATH", "PYTHONPATH", "PYTHONHOME", "LD_PRELOAD", "LD_LIBRARY_PATH"}
SECRET_ENV = re.compile(r"(TOKEN|SECRET|PASSWORD|API_KEY|CLOUDFLARE|WRANGLER)", re.I)

# Written into each run directory and loaded with node --import before any test
# module: offline sentinels for network globals and sockets, and a marker file so
# the launcher can prove the bootstrap ran in the test process.
BOOTSTRAP = """// SP1401 offline bootstrap (generated per run by scripts/accept_sp1401_flow_gaps.py).
import {writeFileSync} from 'node:fs';
import net from 'node:net';
const denied = name => function () { throw new Error(`SP1401 bootstrap: ${name} is disabled offline`); };
globalThis.fetch = denied('fetch');
globalThis.WebSocket = denied('WebSocket');
globalThis.XMLHttpRequest = denied('XMLHttpRequest');
net.connect = denied('net.connect');
net.createConnection = denied('net.createConnection');
net.Socket.prototype.connect = denied('net.Socket.connect');
writeFileSync(process.env.SP1401_MARKER, JSON.stringify({pid: process.pid, node: process.version, argv: process.argv}) + '\\n');
"""


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str | None:
    return sha_bytes(path.read_bytes()) if path.is_file() else None


def refuse(message: str) -> int:
    print("SP1401 acceptance refused: " + message, file=sys.stderr)
    return 2


def has_symlink(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            return True
    return False


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args], text=True, capture_output=True)


def run(argv: list[str], cwd: Path, env: dict, run_dir: Path, label: str, timeout: int = 1800) -> dict:
    try:
        cp = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, timeout=timeout)
        out, err, code = cp.stdout, cp.stderr, cp.returncode
    except subprocess.TimeoutExpired as exc:
        out, err, code = exc.stdout or b"", (exc.stderr or b"") + b"\nSP1401: child timed out\n", 124
    (run_dir / f"{label}.stdout.txt").write_bytes(out)
    (run_dir / f"{label}.stderr.txt").write_bytes(err)
    return {"label": label, "argv": argv, "cwd": str(cwd), "exit": code,
            "stdout_path": f"{label}.stdout.txt", "stderr_path": f"{label}.stderr.txt",
            "stdout_sha256": sha_bytes(out), "stderr_sha256": sha_bytes(err),
            "stdout_bytes": len(out), "stderr_bytes": len(err),
            "_text": out.decode("utf-8", "replace") + "\n" + err.decode("utf-8", "replace")}


def child_env(run_dir: Path, extra: dict) -> tuple[dict, list[str]]:
    removed = sorted(k for k in os.environ if k in STRIP_ENV or SECRET_ENV.search(k))
    env = {k: v for k, v in os.environ.items() if k not in removed}
    tmp = run_dir / "tmp"
    tmp.mkdir(exist_ok=True)
    env.update({"TMPDIR": str(tmp), "TMP": str(tmp), "TEMP": str(tmp), **extra})
    return env, removed


def tap(text: str) -> dict:
    """Top-level node:test TAP results: names with ok/not ok, summary counters."""
    results = []
    for m in re.finditer(r"^(not ok|ok) \d+ - (.*?)(?: # (SKIP|TODO).*)?$", text, re.M):
        results.append({"name": m.group(2).strip(), "ok": m.group(1) == "ok", "directive": m.group(3)})
    summary = {}
    for key in ("tests", "suites", "pass", "fail", "cancelled", "skipped", "todo"):
        m = re.search(rf"^# {key} (\d+)$", text, re.M)
        summary[key] = int(m.group(1)) if m else None
    return {"results": results, "summary": summary}


def node_suite(suite: str, run_dir: Path, node: str) -> tuple[bool, dict, list[dict]]:
    bootstrap = run_dir / "bootstrap.mjs"
    bootstrap.write_text(BOOTSTRAP, encoding="utf-8")
    files = [NEW_TEST] if suite in ("baseline", "focused") else REGRESSION_FILES
    children, checks = [], {}
    ok = True
    for index, rel in enumerate(files):
        marker = run_dir / f"bootstrap-marker-{index}.json"
        env, removed = child_env(run_dir, {"SP1401_SUITE": suite, "SP1401_MARKER": str(marker)})
        argv = [node, "--import", bootstrap.resolve().as_uri(), "--test-reporter=tap", str(REPO / rel)]
        child = run(argv, REPO, env, run_dir, f"node-{index}")
        child["env_removed"] = removed
        child["env_set"] = {"SP1401_SUITE": suite, "SP1401_MARKER": str(marker), "TMPDIR": env["TMPDIR"]}
        parsed = tap(child["_text"])
        child["tap"] = parsed
        child["bootstrap_marker"] = json.loads(marker.read_text()) if marker.is_file() else None
        s, names = parsed["summary"], [r["name"] for r in parsed["results"]]
        c = {"bootstrap_ran": child["bootstrap_marker"] is not None,
             "no_skips": s["skipped"] == 0 and s["todo"] == 0 and s["cancelled"] == 0
             and all(r["directive"] is None for r in parsed["results"]),
             "unique_names": len(names) == len(set(names))}
        if suite == "baseline":
            got = {r["name"]: r["ok"] for r in parsed["results"]}
            failure = child["_text"]
            c.update({
                "child_exit_1": child["exit"] == 1,
                "exactly_the_pair": got == BASELINE_NAMES and s["tests"] == 2 and s["pass"] == 1 and s["fail"] == 1,
                "semantic_assertion_failure": "ERR_ASSERTION" in failure
                and "no emitted segment crosses the one-pixel null strip" in failure,
                "no_product_exception_or_setup_error": "product exception observed" not in failure
                and "ERR_MODULE_NOT_FOUND" not in failure and "SyntaxError" not in failure
                and failure.count("failureType: 'testCodeFailure'") == 1
                and "hookFailure" not in failure and "fileFailure" not in failure,
            })
        elif suite == "focused":
            c.update({"child_exit_0": child["exit"] == 0,
                      "all_required_names_passed": sorted(names) == sorted(FOCUSED_NAMES)
                      and all(r["ok"] for r in parsed["results"]),
                      "counts": s["tests"] == len(FOCUSED_NAMES) and s["pass"] == len(FOCUSED_NAMES) and s["fail"] == 0})
        else:
            want = REGRESSION_COUNT[rel]
            c.update({"child_exit_0": child["exit"] == 0,
                      "all_passed": all(r["ok"] for r in parsed["results"]) and len(names) == want,
                      "counts": s["tests"] == want and s["pass"] == want and s["fail"] == 0})
        checks[rel] = c
        ok = ok and all(c.values())
        children.append(child)
    return ok, checks, children


def main() -> int:
    parser = argparse.ArgumentParser(description="SP1401-FLOW-GAPS offline acceptance launcher")
    parser.add_argument("--suite", required=True,
                        choices=("baseline", "focused", "regression", "repository", "typecheck", "build"))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    out_root = (CANDIDATE / "out").resolve()
    requested = Path(args.output).absolute()
    if has_symlink(CANDIDATE) or has_symlink(requested):
        return refuse("symlink in candidate or output ancestry")
    requested = requested.resolve()
    if not requested.is_relative_to(out_root):
        return refuse("--output must be inside <candidate>/out")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = requested / f"{stamp}-{args.suite}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    if run_dir.exists():
        return refuse("run directory already exists; prior evidence is preserved")
    run_dir.mkdir(parents=True)

    manifest_path = CANDIDATE / "SOURCE-MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    runtime = manifest.get("runtime", {})
    base = manifest.get("head", "")
    preflight = {
        "manifest_schema": manifest.get("schema") == MANIFEST_SCHEMA,
        "manifest_card": manifest.get("card") == CARD,
        "manifest_repo": Path(manifest.get("repo", "")).resolve() == REPO,
        "manifest_write_root": Path(manifest.get("write_root", "")).resolve() == CANDIDATE,
        "credential_scan_python3_declared": bool(runtime.get("credential_scan_python3")),
        "base_is_ancestor": git("merge-base", "--is-ancestor", base, "HEAD").returncode == 0 if base else False,
    }
    base_primary = subprocess.run(["git", "-C", str(REPO), "show", f"{base}:{PRIMARY}"], capture_output=True)
    preflight["primary_base_bytes_pinned"] = (base_primary.returncode == 0
                                              and sha_bytes(base_primary.stdout) == PRIMARY_BASE_SHA256)

    head = git("rev-parse", "HEAD").stdout.strip()
    status = git("status", "--porcelain", "--untracked-files=all").stdout
    log = git("log", "--format=%H%x1f%s%x1f%(trailers:key=Material-Author,valueonly,separator=%x2c)%x1f%(trailers:key=Signed-off-by,valueonly,separator=%x2c)",
              f"{base}..HEAD").stdout if base else ""
    commits = []
    for line in log.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            commits.append({"commit": parts[0], "subject": parts[1], "material_author": parts[2].strip(),
                            "signed_off_by": parts[3].strip()})
    primary_now = sha_file(REPO / PRIMARY)
    fixtures = {str(p.relative_to(REPO)): sha_file(p) for p in sorted((REPO / FIXTURE_DIR).rglob("*")) if p.is_file()}
    node = shutil.which("node")
    pnpm = runtime.get("pnpm") or shutil.which("pnpm")
    identity = {
        "specification": SPEC, "card": CARD, "suite": args.suite,
        "phase": "baseline-before-product-edit" if args.suite == "baseline" else "candidate",
        "staged_base": base, "head": head, "worktree_clean": status == "", "worktree_status": status,
        "commits_since_base": commits,
        "hashes": {"source_manifest": sha_file(manifest_path), PRIMARY: primary_now,
                   "primary_matches_base": primary_now == PRIMARY_BASE_SHA256,
                   NEW_TEST: sha_file(REPO / NEW_TEST), "scripts/accept_sp1401_flow_gaps.py": sha_file(Path(__file__).resolve()),
                   NOTE: sha_file(REPO / NOTE), "fixtures": fixtures,
                   **{rel: sha_file(REPO / rel) for rel in REGRESSION_FILES}},
        "runtime": {"launcher_python": sys.executable, "launcher_version": sys.version.split()[0],
                    "node": node, "pnpm": pnpm, "credential_scan_python3": runtime.get("credential_scan_python3"),
                    "launcher_argv": sys.argv, "launcher_cwd": os.getcwd()},
    }
    children: list[dict] = []
    checks: dict = {"preflight": preflight}
    ok = all(preflight.values())
    if args.suite == "baseline":
        checks["preflight_baseline_source"] = {"primary_unchanged_from_base": primary_now == PRIMARY_BASE_SHA256}
        ok = ok and primary_now == PRIMARY_BASE_SHA256

    if not ok:
        verdict = "PREFLIGHT_REFUSED"
    elif args.suite in ("baseline", "focused", "regression"):
        if not node:
            return refuse("installed node runtime not found; no fallback")
        identity["runtime"]["node_version"] = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
        suite_ok, suite_checks, children = node_suite(args.suite, run_dir, node)
        checks["suite"] = suite_checks
        ok = suite_ok
        verdict = ("BASELINE_GAP_REPRODUCED" if args.suite == "baseline" else "SCOPED_GREEN_REVIEW_REQUIRED") if ok else "FAILED"
    elif args.suite == "repository":
        python = runtime["credential_scan_python3"]
        if not Path(python).is_file():
            return refuse("SOURCE-MANIFEST runtime.credential_scan_python3 is missing; no system-python fallback")
        env, removed = child_env(run_dir, {})
        child = run([python, "scripts/check_repository.py"], REPO, env, run_dir, "check-repository")
        child["env_removed"] = removed
        child["resolved_interpreter"] = str(Path(python).resolve())
        children = [child]
        checks["suite"] = {"check_repository_exit_0": child["exit"] == 0}
        ok = child["exit"] == 0
        verdict = "SCOPED_GREEN_REVIEW_REQUIRED" if ok else "FAILED"
    else:
        if not pnpm or not Path(pnpm).is_file():
            return refuse("pnpm runtime not found; no install or fallback")
        env, removed = child_env(run_dir, {})
        commands = ([(f"tsc-{i}", [pnpm, "exec", "tsc", "--noEmit", "-p", project]) for i, project in enumerate(TYPECHECK_PROJECTS)]
                    if args.suite == "typecheck" else [("build", [pnpm, "build"])])
        for label, argv in commands:
            child = run(argv, REPO, env, run_dir, label)
            child["env_removed"] = removed
            children.append(child)
        checks["suite"] = {c["label"]: c["exit"] == 0 for c in children}
        if args.suite == "build":
            after = git("status", "--porcelain", "--untracked-files=all").stdout
            checks["suite"]["tracked_tree_unchanged_by_build"] = after == status
            identity["worktree_status_after_build"] = after
        ok = all(checks["suite"].values())
        verdict = "SCOPED_GREEN_REVIEW_REQUIRED" if ok else "FAILED"

    for child in children:
        child.pop("_text", None)
    receipt = {
        "schema": "skippercast.sp1401-acceptance/v1", **identity,
        "material_author_claim": {"profile": "opus-coder-bopus", "model": "claude-opus-5-5", "provider": "anthropic",
                                  "note": "per-commit Material-Author trailers are listed in commits_since_base"},
        "children": children, "checks": checks, "accepted": bool(ok), "verdict": verdict,
        "meaning": ("BASELINE_GAP_REPRODUCED is an expected-red baseline observation, not a fix pass"
                    if args.suite == "baseline" else
                    "scoped machine verdict only; REVIEW REQUIRED; not whole-repository, semantic or release acceptance"),
        "full_discovery": "operator-run",
    }
    data = json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    (run_dir / "receipt.json").write_bytes(data)
    (run_dir / "receipt.sha256").write_text(sha_bytes(data) + "  receipt.json\n", encoding="ascii")
    print(json.dumps({"suite": args.suite, "verdict": verdict, "accepted": bool(ok), "head": head,
                      "run_dir": str(run_dir), "receipt_sha256": sha_bytes(data),
                      "children": [{"label": c["label"], "exit": c["exit"]} for c in children]}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
