#!/usr/bin/env python3
"""Acceptance launcher for SP1410-FORECAST-ENVELOPE (spec SP-14-v1).

A stdlib-only argv launcher. It derives the repository from its own location (this file is
<repo>/scripts/accept_sp1410_forecast_envelope.py) and the candidate root as the repository's
parent, where the operator's SOURCE-MANIFEST.json lives. It never installs anything, never uses
the network and never edits the repository; every invocation writes a NEW unique directory below
--output (which must be inside <candidate>/out) holding the receipt and the raw child output.

  --suite baseline    the A4 pair alone (SP1410_SUITE=baseline) against the pinned, unchanged
                      server/advisor/answers/feeds.ts. Success here is BASELINE_GAP_REPRODUCED:
                      the Node child exits 1 with exactly "primary regression" failing at its
                      frozen semantic assertion and "healthy control" passing. Not a fix pass.
  --suite focused     every A1-A4 test in tests/test_sp1410_forecast_envelope.mjs; also binds the
                      run to an earlier BASELINE_GAP_REPRODUCED receipt with identical test and
                      fixture bytes (the same A4 pair, frozen before the product change).
  --suite regression  the unchanged original files tests/test_advisor_tools.mjs and
                      tests/test_advisor_daily.mjs.
  --suite repository  the unchanged scripts/check_repository.py under the manifest's
                      runtime.credential_scan_python3.
  --suite typecheck   pnpm exec tsc --noEmit for tsconfig.json, web/tsconfig.json and
                      packages/coast/tsconfig.json, each a separate child.
  --suite build       the repository's own pnpm build (scripts/build-worker.mjs; no deploy).

Exit codes: 0 PASS_REVIEW_REQUIRED or BASELINE_GAP_REPRODUCED, 1 FAIL, 2 usage or preflight
refusal, 3 INPUT_UNAVAILABLE (a staged runtime is missing; the operator owns staging).
Green is REVIEW REQUIRED only: not whole-repository, semantic or release acceptance.
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
import time
import uuid
from pathlib import Path

SPEC = "SP-14-v1"
CARD = "SP1410-FORECAST-ENVELOPE"
RECEIPT_SCHEMA = "sp1410.acceptance-receipt/v1"
# The card's source pins (Grahammmm/skippercast main) and the primary file's pinned bytes.
BASE = "33734f90073a2150eac5a418564ea314c4a591ac"
PRIMARY = "server/advisor/answers/feeds.ts"
PRIMARY_BASE_SHA256 = "25ee2522e5bfb6e0c080bcfb620cfe80256f078c8542300407859ef2075082f0"
# Who authored the material this launcher ships with (each commit also carries a Material-Author trailer).
AUTHOR = {"model": "claude-opus-5-5", "provider": "anthropic", "profile": "opus-coder-bopus"}

HERE = Path(__file__).resolve()
REPO = HERE.parents[1]
CANDIDATE = REPO.parent
MANIFEST = CANDIDATE / "SOURCE-MANIFEST.json"
OUT_ROOT = CANDIDATE / "out"

TEST = "tests/test_sp1410_forecast_envelope.mjs"
HELPER = "scripts/accept_sp1410_forecast_envelope.py"
NOTE = "docs/engineering/sp1410_forecast_envelope.md"
FIXTURE_DIR = "tests/fixtures/sp1410_forecast_envelope"
OFFLINE = FIXTURE_DIR + "/offline.mjs"
REGRESSION = ["tests/test_advisor_tools.mjs", "tests/test_advisor_daily.mjs"]
CHECKER = "scripts/check_repository.py"
READ_ONLY = [*REGRESSION, CHECKER, "package.json", "pnpm-lock.yaml", "tsconfig.json", "CHANGELOG.md",
             "tests/fixtures/feeds/intelligence.json", "server/advisor/answers/conditions.ts", "server/advisor/answers/planning.ts",
             "server/advisor/tools/get_conditions.ts", "server/advisor/answers/confidence.ts", "server/feeds.ts"]
TSCONFIGS = ["tsconfig.json", "web/tsconfig.json", "packages/coast/tsconfig.json"]

BASELINE_TESTS = ["primary regression", "healthy control"]
FOCUSED_TESTS = [
    "primary regression",
    "healthy control",
    "A1 every malformed forecast container in an otherwise correct-region feed is unavailable (null)",
    "A1 get_conditions answers a malformed feed with an unavailable forecast and keeps the daily advisories",
    "A1 provider-error GFS records with keyed-object data and a malformed time are unavailable through windowConditions and get_conditions",
    "A2 the card-owned producer-shaped feed is admitted unchanged and gives the same conditions",
    "A2 the committed producer fixture tests/fixtures/feeds/intelligence.json is admitted and gives the same conditions",
    "A2 valid empty arrays, absent models, null points, absent containers and provider-error records keep the missing-data outcome",
    "A3 reader rejection, null and non-object input and a wrong or missing region stay null",
    "A3 the gate never mutates a feed and admits optional unrelated fields",
    "A3 sample values and units stay owned by readHour",
    "A3 dailyFeed and reader routing are unchanged",
    "offline boundary: no network, model or storage access in any case",
]
PRIMARY_MARKER = "SP1410_PRIMARY_SHAPE_REJECTION"
OBSERVED_BASELINE = "SP1410_OBSERVED gate=admitted windowConditions=TypeError"
OBSERVED_FIXED = "SP1410_OBSERVED gate=null windowConditions=no exception"

TAP_RESULT = re.compile(r"^(not ok|ok) \d+ - (.*?)(?: # (SKIP|TODO)\b.*)?$")
TAP_COUNT = re.compile(r"^# (tests|suites|pass|fail|cancelled|skipped|todo|duration_ms) ([\d.]+)$")


class Refusal(Exception):
    """A preflight refusal (exit 2) or, with unavailable=True, a missing staged runtime (exit 3)."""

    def __init__(self, message, unavailable=False):
        super().__init__(message)
        self.unavailable = unavailable


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def git(*args, check=True):
    proc = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False)
    if check and proc.returncode != 0:
        raise Refusal(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def no_symlink_between(top, path):
    """Refuse a symlink at `path` or at any directory between `top` (exclusive) and it."""
    path = Path(os.path.abspath(path))
    if path != top and top not in path.parents:
        raise Refusal(f"{path} is not inside {top}")
    node = path
    while node != top:
        if node.is_symlink():
            raise Refusal(f"symlink refused in evidence/fixture ancestry: {node}")
        node = node.parent


def owned_hashes():
    """SHA256 of this card's test, fixtures, helper and note, plus the primary file (absent files are None)."""
    files = [TEST, HELPER, NOTE, PRIMARY]
    fixture_root = REPO / FIXTURE_DIR
    if fixture_root.is_dir():
        for path in sorted(fixture_root.rglob("*")):
            no_symlink_between(REPO, path)
            if path.is_file():
                files.append(path.relative_to(REPO).as_posix())
    return {rel: (sha256_file(REPO / rel) if (REPO / rel).is_file() else None) for rel in files}


def frozen_inputs(hashes):
    """The A4 freeze identity: the test file and every fixture file (not the product, helper or note)."""
    return {rel: h for rel, h in hashes.items() if rel == TEST or rel.startswith(FIXTURE_DIR + "/")}


def scope_report():
    """Every path changed from BASE (committed, staged, unstaged or untracked) and those outside the card's scope."""
    changed = set(filter(None, git("diff", "--name-only", BASE).splitlines()))
    untracked = set(filter(None, git("ls-files", "--others", "--exclude-standard").splitlines()))
    allowed = lambda p: p in {PRIMARY, TEST, HELPER, NOTE} or p.startswith(FIXTURE_DIR + "/")
    paths = sorted(changed | untracked)
    return {"changed": paths, "untracked": sorted(untracked), "outside_scope": [p for p in paths if not allowed(p)]}


def material_commits():
    """Commits after BASE with their Material-Author trailers (the per-commit author disclosure)."""
    out = git("log", "--format=%H%x1f%an <%ae>%x1f%s%x1f%(trailers:key=Material-Author,valueonly,separator=%x3b)%x1f%(trailers:key=Signed-off-by,valueonly,separator=%x3b)%x1e", f"{BASE}..HEAD")
    commits = []
    for record in filter(None, (r.strip() for r in out.split("\x1e"))):
        sha, author, subject, material, signoff = (record.split("\x1f") + [""] * 5)[:5]
        commits.append({"sha": sha, "git_author": author, "subject": subject, "material_author": material.strip() or None, "signed_off_by": signoff.strip() or None})
    return commits


def tap(stdout):
    results, counts = [], {}
    for line in stdout.splitlines():
        m = TAP_RESULT.match(line)
        if m:
            results.append({"name": m.group(2).replace("\\#", "#"), "ok": m.group(1) == "ok", "directive": m.group(3)})
        m = TAP_COUNT.match(line)
        if m:
            counts[m.group(1)] = float(m.group(2)) if m.group(1) == "duration_ms" else int(m.group(2))
    return results, counts


def run_child(run_dir, label, argv, env_delta=None, parse_tap=False):
    env = os.environ.copy()
    env.update(env_delta or {})
    started = time.monotonic()
    proc = subprocess.run(argv, cwd=str(REPO), env=env, capture_output=True, check=False, timeout=1800)
    elapsed = round(time.monotonic() - started, 3)
    out_path, err_path = run_dir / f"{label}.stdout.txt", run_dir / f"{label}.stderr.txt"
    out_path.write_bytes(proc.stdout)
    err_path.write_bytes(proc.stderr)
    row = {"label": label, "argv": [str(a) for a in argv], "cwd": str(REPO), "env_delta": env_delta or {},
           "executable_resolved": str(Path(argv[0]).resolve()), "exit": proc.returncode, "seconds": elapsed,
           "stdout": out_path.name, "stdout_bytes": len(proc.stdout), "stdout_sha256": sha256_bytes(proc.stdout),
           "stderr": err_path.name, "stderr_bytes": len(proc.stderr), "stderr_sha256": sha256_bytes(proc.stderr)}
    text = proc.stdout.decode("utf-8", errors="replace")
    if parse_tap:
        row["results"], row["counts"] = tap(text)
    return row, text


def green(row, expected_names=None):
    """Problems with a test child that must be fully green: exit 0, every count clean, every named test ran."""
    c, problems = row.get("counts", {}), []
    if row["exit"] != 0:
        problems.append(f"{row['label']}: exit {row['exit']}")
    for key in ("fail", "cancelled", "skipped", "todo"):
        if c.get(key) != 0:
            problems.append(f"{row['label']}: {key}={c.get(key)}")
    if not c.get("tests") or c.get("pass") != c.get("tests"):
        problems.append(f"{row['label']}: pass {c.get('pass')} of {c.get('tests')}")
    if any(r["directive"] for r in row["results"]) or any(not r["ok"] for r in row["results"]):
        problems.append(f"{row['label']}: not ok or SKIP/TODO results {[r['name'] for r in row['results'] if r['directive'] or not r['ok']]}")
    if len(row["results"]) != c.get("tests"):
        problems.append(f"{row['label']}: {len(row['results'])} top-level results for tests={c.get('tests')}")
    if expected_names is not None and [r["name"] for r in row["results"]] != expected_names:
        problems.append(f"{row['label']}: test names/order differ from the frozen list: got {[r['name'] for r in row['results']]}")
    return problems


def node_runtime(explicit):
    found = explicit or shutil.which("node")
    node = Path(found) if found else None
    if node is None or not node.is_file():
        raise Refusal("no installed node runtime found (operator staging)", unavailable=True)
    proc = subprocess.run([str(node), "--version"], capture_output=True, text=True, check=False, timeout=60)
    version = proc.stdout.strip()
    m = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", version)
    # Node 22.18+ strips TypeScript types by default (package.json engines: node >= 22.18).
    if proc.returncode != 0 or not m or (int(m.group(1)), int(m.group(2))) < (22, 18):
        raise Refusal(f"node at {node} reports {version!r}; need >= v22.18 for type stripping", unavailable=True)
    return node, version


def preflight(args):
    """Refuse before any child runs: manifest identity, base ancestry, staged links, original-file drift, runtimes."""
    no_symlink_between(CANDIDATE, MANIFEST)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema") != "agentorange.source-manifest/v1":
        raise Refusal(f"SOURCE-MANIFEST.json schema {manifest.get('schema')!r}")
    if Path(manifest.get("repo", "")).resolve() != REPO or manifest.get("head") != BASE:
        raise Refusal("SOURCE-MANIFEST.json repo/head do not match this repository and the card's base")
    runtime = manifest.get("runtime") or {}
    if subprocess.run(["git", "-C", str(REPO), "merge-base", "--is-ancestor", BASE, "HEAD"], capture_output=True, check=False).returncode != 0:
        raise Refusal("HEAD does not descend from the staged base")
    if not (REPO / ".venv").is_symlink():
        raise Refusal("the operator's staged .venv link is missing (never recreated here)", unavailable=True)
    if not (REPO / "node_modules").is_dir():
        raise Refusal("staged node_modules missing (no install here)", unavailable=True)
    drift = [p for p in filter(None, git("diff", "--name-only", BASE, "--", *READ_ONLY).splitlines())]
    if drift:
        raise Refusal(f"read-only original files differ from the base: {drift}")
    node, version = node_runtime(args.node)
    pnpm = runtime.get("pnpm")
    cred = runtime.get("credential_scan_python3")
    if args.suite in ("typecheck", "build") and not (pnpm and Path(pnpm).is_file()):
        raise Refusal(f"manifest runtime.pnpm unavailable: {pnpm}", unavailable=True)
    if args.suite == "repository" and not (cred and Path(cred).is_file()):
        raise Refusal(f"manifest runtime.credential_scan_python3 unavailable: {cred}", unavailable=True)
    fixture_root = REPO / FIXTURE_DIR
    no_symlink_between(REPO, fixture_root)
    if not (fixture_root / "offline.mjs").is_file():
        raise Refusal("the card's offline boundary module is missing")
    return manifest, node, version, pnpm, cred


def prior_baselines(frozen):
    """Earlier BASELINE_GAP_REPRODUCED receipts in <candidate>/out whose frozen test/fixture bytes equal these."""
    found = []
    for path in sorted(OUT_ROOT.rglob("receipt.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("card") == CARD and data.get("suite") == "baseline" and data.get("verdict") == "BASELINE_GAP_REPRODUCED" \
                and data.get("frozen_inputs") == frozen and (data.get("hashes_before") or {}).get(PRIMARY) == PRIMARY_BASE_SHA256:
            found.append({"receipt": str(path), "sha256": sha256_file(path), "head": data.get("head")})
    return found


def main():
    parser = argparse.ArgumentParser(description=f"{CARD} acceptance launcher ({SPEC})")
    parser.add_argument("--suite", required=True, choices=["baseline", "focused", "regression", "repository", "typecheck", "build"])
    parser.add_argument("--output", required=True, help="parent directory inside <candidate>/out; each run makes a new unique child")
    parser.add_argument("--node", help="explicit installed node executable (default: the node on PATH)")
    args = parser.parse_args()

    started = datetime.datetime.now(datetime.timezone.utc)
    output = Path(os.path.abspath(args.output))
    if OUT_ROOT not in [output, *output.parents]:
        print(f"REFUSED: --output must be inside {OUT_ROOT}", file=sys.stderr)
        return 2
    try:
        no_symlink_between(CANDIDATE, output)
        manifest, node, node_version, pnpm, cred = preflight(args)
    except Refusal as refusal:
        print(("INPUT_UNAVAILABLE: " if refusal.unavailable else "REFUSED: ") + str(refusal), file=sys.stderr)
        return 3 if refusal.unavailable else 2

    output.mkdir(parents=True, exist_ok=True)
    run_dir = output / f"{started.strftime('%Y%m%dT%H%M%S.%fZ')}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(exist_ok=False)
    head = git("rev-parse", "HEAD").strip()
    hashes = owned_hashes()
    receipt = {
        "schema": RECEIPT_SCHEMA, "spec": SPEC, "card": CARD, "suite": args.suite, "phase": args.suite,
        "verdict": None, "problems": [], "started_at": started.isoformat(),
        "launcher": {"argv": [sys.executable, *sys.argv], "cwd": os.getcwd(), "python": sys.executable,
                     "python_resolved": str(Path(sys.executable).resolve()), "python_version": platform.python_version(),
                     "path": str(HERE), "sha256": sha256_file(HERE)},
        "repo": str(REPO), "run_dir": str(run_dir),
        "staged_base": BASE, "head": head, "git_status_before": git("status", "--porcelain").splitlines(),
        "source_manifest": {"path": str(MANIFEST), "sha256": sha256_file(MANIFEST), "head": manifest.get("head")},
        "runtime": {"node": str(node), "node_resolved": str(node.resolve()), "node_version": node_version,
                    "pnpm": pnpm, "credential_scan_python3": cred, "platform": platform.platform()},
        "material_author": AUTHOR, "material_commits": material_commits(),
        "primary": {"path": PRIMARY, "pinned_base_sha256": PRIMARY_BASE_SHA256, "sha256": hashes.get(PRIMARY),
                    "is_pinned_base": hashes.get(PRIMARY) == PRIMARY_BASE_SHA256},
        "hashes_before": hashes, "frozen_inputs": frozen_inputs(hashes),
        "read_only_sha256": {rel: sha256_file(REPO / rel) for rel in READ_ONLY if (REPO / rel).is_file()},
        "scope": scope_report(), "children": [],
    }
    problems = receipt["problems"]
    if receipt["scope"]["outside_scope"]:
        problems.append(f"changes outside the card's scope: {receipt['scope']['outside_scope']}")
    test_argv = lambda files: [str(node), "--import", (REPO / OFFLINE).as_uri(), "--test", "--test-reporter=tap", "--test-concurrency=1", *files]

    if args.suite == "baseline":
        if not receipt["primary"]["is_pinned_base"]:
            problems.append(f"baseline needs the unchanged {PRIMARY} (sha256 {PRIMARY_BASE_SHA256}); this tree has {hashes.get(PRIMARY)}. "
                            "The historical baseline stays tied to the old source.")
        else:
            row, text = run_child(run_dir, "baseline", test_argv([TEST]), {"SP1410_SUITE": "baseline"}, parse_tap=True)
            receipt["children"].append(row)
            c = row["counts"]
            got = [(r["name"], r["ok"], r["directive"]) for r in row["results"]]
            if row["exit"] != 1:
                problems.append(f"baseline child exit {row['exit']} (expected 1: the primary assertion fails)")
            if got != [("primary regression", False, None), ("healthy control", True, None)]:
                problems.append(f"baseline results {got}; expected primary regression not ok and healthy control ok, nothing else")
            if [c.get(k) for k in ("tests", "pass", "fail", "cancelled", "skipped", "todo")] != [2, 1, 1, 0, 0, 0]:
                problems.append(f"baseline counts {c}")
            if PRIMARY_MARKER not in text or "code: 'ERR_ASSERTION'" not in text:
                problems.append("the primary did not fail at its frozen semantic assertion (setup/import error or other failure)")
            if OBSERVED_BASELINE not in text:
                problems.append("the original windowConditions TypeError was not observed before the semantic assertion")
            if not problems:
                receipt["verdict"] = "BASELINE_GAP_REPRODUCED"
                receipt["observed"] = [line.strip() for line in text.splitlines() if "SP1410_OBSERVED" in line]
    elif args.suite == "focused":
        row, text = run_child(run_dir, "focused", test_argv([TEST]), {"SP1410_SUITE": "focused"}, parse_tap=True)
        receipt["children"].append(row)
        problems += green(row, FOCUSED_TESTS)
        if OBSERVED_FIXED not in text:
            problems.append("the primary regression did not observe the fixed path (gate null, no windowConditions exception)")
        receipt["baseline_receipts"] = prior_baselines(receipt["frozen_inputs"])
        if not receipt["baseline_receipts"]:
            problems.append("no BASELINE_GAP_REPRODUCED receipt under <candidate>/out has these exact test/fixture bytes against the pinned primary")
    elif args.suite == "regression":
        row, _ = run_child(run_dir, "regression", test_argv(REGRESSION), {"SP1410_SUITE": "regression"}, parse_tap=True)
        receipt["children"].append(row)
        problems += green(row)
    elif args.suite == "repository":
        row, text = run_child(run_dir, "check_repository", [cred, str(REPO / CHECKER)])
        receipt["children"].append(row)
        m = re.search(r"Checked (\d+) text files", text)
        row["text_files_checked"] = int(m.group(1)) if m else None
        if row["exit"] != 0 or m is None:
            problems.append(f"check_repository exit {row['exit']} (see {row['stderr']})")
    elif args.suite == "typecheck":
        for config in TSCONFIGS:
            row, _ = run_child(run_dir, "tsc-" + config.replace("/", "_"), [pnpm, "exec", "tsc", "--noEmit", "-p", config])
            receipt["children"].append(row)
            if row["exit"] != 0:
                problems.append(f"tsc -p {config} exit {row['exit']}")
    elif args.suite == "build":
        row, _ = run_child(run_dir, "build", [pnpm, "build"])
        receipt["children"].append(row)
        if row["exit"] != 0:
            problems.append(f"pnpm build exit {row['exit']}")

    after = owned_hashes()
    receipt["hashes_after"] = after
    if after != hashes:
        problems.append("the card's test/fixture/product/helper bytes changed during the run")
    head_after = git("rev-parse", "HEAD").strip()
    if head_after != head:
        problems.append(f"HEAD moved during the run: {head} -> {head_after}")
    receipt["git_status_after"] = git("status", "--porcelain").splitlines()
    for child in receipt["children"]:   # the raw logs on disk are the ones hashed in the receipt
        for kind in ("stdout", "stderr"):
            if sha256_file(run_dir / child[kind]) != child[kind + "_sha256"]:
                problems.append(f"{child[kind]} changed after capture")
    if receipt["verdict"] is None:
        receipt["verdict"] = "FAIL" if problems else "PASS_REVIEW_REQUIRED"
    elif problems:
        receipt["verdict"] = "FAIL"
    receipt["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    path = run_dir / "receipt.json"
    path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{CARD} {args.suite}: {receipt['verdict']}")
    for child in receipt["children"]:
        print(f"  {child['label']}: exit {child['exit']} {child.get('counts', '')}")
    for problem in problems:
        print("  problem: " + problem)
    print(f"  receipt {path} sha256 {sha256_file(path)}")
    return 0 if receipt["verdict"] in ("PASS_REVIEW_REQUIRED", "BASELINE_GAP_REPRODUCED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
