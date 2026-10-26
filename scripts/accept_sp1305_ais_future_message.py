"""Portable offline acceptance for SP-13-v2 / SP1305-AIS-FUTURE-MESSAGE.

No network, installs, operational data, mutable evidence reuse, or acceptance by
Python assert. Run each mode separately; an existing output path is an error.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import re
import runpy
import shutil
import socket
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
CANDIDATE = REPO.parent
BASE = "2979d59bfbb7d724eb83b34a48102b914ee8eaa3"
PRIMARY = "server/fleet/admin/ais-health.ts"
PRIMARY_HASH = "3f40bf588faa0f22db6a69f8e1819834ccddf42d1a62af76e2917c0092b87c06"
TEST = "tests/test_sp1305_ais_future_message.mjs"
FIXTURES = "tests/fixtures/sp1305_ais_future_message"
REGRESSION = "tests/test_fleet_coverage.mjs"
REGRESSION_HASH = "c7d1305b216fe6329d50a762f9bfac639bc59d03c85413801a71f781552f8c7b"
PAIR = ["primary regression", "healthy control"]
FOCUSED = PAIR + [
    "A2 future instants offsets flooring and exact stale threshold",
    "A2 missing null non-string and malformed clocks preserve a healthy peer",
    "A2 shared heartbeat and processor future-age behavior stays unchanged",
    "A3 admin route preserves stores reports and authorization gates",
]
ORIGINAL = [
    "acceptance 1: coverage percentages by port and class match hand-computed values",
    'acceptance 2: boats with no AIS are "not-seen", and nothing in the report or the views speaks of compliance',
    "acceptance 3: ais/health gives uptime, gaps over 10 minutes and last-message age from fleet_ais_hours and job_state",
    "acceptance 4: both routes 404 for non-admins and with FLEET_ENABLED off; admins get the reports",
]
CASE_MAP = {"A1": PAIR, "A2": FOCUSED[2:5], "A3": [FOCUSED[5]], "A4": PAIR}
PROVENANCE = {"model": "gpt-6.1-sol", "provider": "openai-codex", "profile": "sol-reviewer", "effort": "high", "task": "t_3c7b5c38", "run": 1778}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def no_symlinks(path):
    for component in [path, *path.parents]:
        require(not component.is_symlink(), f"symlink refused: {component}")


def git(*args):
    return subprocess.check_output(["git", "-C", str(REPO), *args], text=True).strip()


def frozen_inputs():
    root = REPO / FIXTURES
    no_symlinks(root)
    paths = [REPO / TEST, *sorted(root.rglob("*"))]
    result = {}
    for path in paths:
        no_symlinks(path)
        if path.is_file():
            result[str(path.relative_to(REPO))] = sha(path)
    return result


def repository_child():
    # A file-based bootstrap under the manifest interpreter; no editable-install
    # imports or operational CLI. Install tripwires BEFORE loading the checker.
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(REPO), str(REPO / "src")]
    def deny(*args, **kwargs):
        raise RuntimeError("SP1305 Python offline network/model-call tripwire")
    socket.socket.connect = deny
    socket.socket.connect_ex = deny
    socket.socket.bind = deny
    socket.create_connection = deny
    socket.getaddrinfo = deny
    def audit(event, args):
        if event in {"socket.connect", "socket.bind", "socket.getaddrinfo", "subprocess.Popen", "os.system"}:
            deny()
    sys.addaudithook(audit)
    target = (REPO / "scripts/check_repository.py").resolve()
    require(target.is_relative_to(REPO), "checker resolves outside staged repository")
    print(json.dumps({"bootstrap_interpreter": sys.executable, "version": sys.version, "target_file": str(target), "effective_argv": [sys.executable, str(target)]}), flush=True)
    sys.argv = [str(target)]
    runpy.run_path(str(target), run_name="__main__")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["baseline", "focused", "regression", "repository", "typecheck"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.absolute()
    require(output == args.output and ".." not in output.parts, "output must be canonical absolute path")
    require(output.parent == CANDIDATE / "out", "output must be a fresh direct child of candidate/out")
    no_symlinks(output)
    require(not output.exists(), "output already exists; prior evidence is immutable")
    source_manifest = CANDIDATE / "SOURCE-MANIFEST.json"
    require(source_manifest.is_file(), "operator source manifest missing")
    manifest = json.loads(source_manifest.read_text())
    require(manifest.get("schema") == "agentorange.source-manifest/v1", "wrong manifest schema")
    require(manifest.get("card") == "SP1305-AIS-FUTURE-MESSAGE", "wrong card")
    require(manifest.get("repo") == str(REPO) and manifest.get("write_root") == str(CANDIDATE), "wrong staged roots")
    require(manifest.get("head") == BASE, "wrong staged base")
    scan_python = manifest.get("runtime", {}).get("credential_scan_python3")
    require(scan_python and Path(scan_python).is_file(), "credential-scan interpreter unavailable")
    require(git("merge-base", BASE, "HEAD") == BASE, "candidate not based on admitted pin")
    require(sha(REPO / REGRESSION) == REGRESSION_HASH, "original regression source drift")
    inputs = frozen_inputs()
    head = git("rev-parse", "HEAD")
    baselines = []
    if args.suite == "baseline":
        require(head == BASE and sha(REPO / PRIMARY) == PRIMARY_HASH, "baseline requires untouched pinned product")
    else:
        baselines = []
        for path in sorted((CANDIDATE / "out").glob("*/receipt.json")):
            no_symlinks(path)
            receipt = json.loads(path.read_text())
            if receipt.get("status") == "BASELINE_GAP_REPRODUCED" and receipt.get("inputs") == inputs:
                require(receipt.get("head") == BASE and receipt.get("source_hash") == PRIMARY_HASH, "historical baseline identity mismatch")
                baselines.append({"path": str(path), "sha256": sha(path)})
        require(bool(baselines), "no historical red baseline with unchanged tests/fixtures")
    output.mkdir(parents=True, exist_ok=False)
    temporary = output / "tmp"
    temporary.mkdir()
    # Pass no ambient credentials/provider settings into children.
    env = {key: os.environ[key] for key in ["PATH", "HOME", "LANG", "LC_ALL", "TZ", "SYSTEMROOT"] if key in os.environ}
    env.update({"TMPDIR": str(temporary), "TMP": str(temporary), "TEMP": str(temporary),
                "PYTHONDONTWRITEBYTECODE": "1", "SP1305_TEMP": str(output), "SP1305_SUITE": args.suite,
                "CI": "1", "NO_COLOR": "1"})
    fixture = REPO / FIXTURES / "offline.mjs"
    node = shutil.which("node")
    require(bool(node), "installed Node missing")
    records = []
    receipt = {"specification": "SP-13-v2", "card": "SP1305-AIS-FUTURE-MESSAGE", "phase": args.suite,
               "staged_base": BASE, "head": head, "source_hash": sha(REPO / PRIMARY),
               "source_manifest_sha256": sha(source_manifest), "inputs": inputs,
               "helper_hash": sha(Path(__file__)), "case_map": CASE_MAP,
               "material_author": PROVENANCE, "commits": git("log", "--format=%H%n%B", f"{BASE}..HEAD"),
               "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "parent_argv": sys.argv, "parent_cwd": os.getcwd(), "parent_interpreter": sys.executable,
               "parent_version": sys.version, "status_before": git("status", "--porcelain"),
               "baseline_evidence": [] if args.suite == "baseline" else baselines,
               "commands": records, "status": "FAILED"}
    def child(argv, label, child_env=None):
        completed = subprocess.run(argv, cwd=REPO, env=child_env or env, capture_output=True, timeout=300)
        stdout, stderr = output / f"{label}.stdout", output / f"{label}.stderr"
        stdout.write_bytes(completed.stdout)
        stderr.write_bytes(completed.stderr)
        record = {"argv": argv, "cwd": str(REPO), "exit": completed.returncode,
                  "stdout": str(stdout), "stdout_sha256": sha(stdout), "stderr": str(stderr), "stderr_sha256": sha(stderr)}
        records.append(record)
        print(f"{label}: exit {completed.returncode}; stdout={stdout}; stderr={stderr}", flush=True)
        return completed, record
    try:
        version, _ = child([node, "--version"], "node-version")
        require(version.returncode == 0, "cannot measure Node runtime")
        if args.suite in {"baseline", "focused", "regression"}:
            target = REGRESSION if args.suite == "regression" else TEST
            completed, record = child([node, "--import", str(fixture), "--experimental-strip-types", "--test", "--test-reporter=tap", target], "tests")
            text = completed.stdout.decode("utf-8", errors="replace")
            results = re.findall(r"^(not ok|ok) \d+ - (.*)$", text, re.MULTILINE)
            counts = {key: int(value) for key, value in re.findall(r"^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$", text, re.MULTILINE)}
            record.update({"tests": [{"name": name, "outcome": outcome} for outcome, name in results], "counts": counts})
            expected = PAIR if args.suite == "baseline" else ORIGINAL if args.suite == "regression" else FOCUSED
            require([name for _, name in results] == expected, "native runner names/order differ from frozen selected tests")
            require(all(counts.get(key) == 0 for key in ["cancelled", "skipped", "todo"]), "cancelled/skipped/todo selected test")
            require(counts.get("tests") == len(expected), "incorrect selected test count")
            require("SP1305 offline tripwire" not in text + completed.stderr.decode(errors="replace"), "offline tripwire fired")
            if args.suite == "baseline":
                require(completed.returncode == 1 and results == [("not ok", PAIR[0]), ("ok", PAIR[1])], "baseline must have exactly the named semantic failure and healthy pass")
                require(counts.get("fail") == 1 and counts.get("pass") == 1, "wrong baseline failure counts")
                require("code: 'ERR_ASSERTION'" in text and "future message must have unknown age" in text and "failureType: 'testCodeFailure'" in text, "baseline failure is not expected semantic assertion")
                require('"last_message_age_s":0,"stale":false' in text, "baseline observation missing")
                receipt["status"] = "BASELINE_GAP_REPRODUCED"
            else:
                require(completed.returncode == 0 and counts.get("fail") == 0 and counts.get("pass") == len(expected), "selected assertions did not all pass")
                receipt["status"] = "PASS_REVIEW_REQUIRED"
        elif args.suite == "repository":
            version, _ = child([scan_python, "--version"], "scan-python-version")
            require(version.returncode == 0, "cannot measure scan interpreter")
            completed, _ = child([scan_python, "-B", str(Path(__file__).resolve()), "--repository-child"], "repository")
            require(completed.returncode == 0, "unchanged repository check failed")
            receipt["status"] = "PASS_REVIEW_REQUIRED"
        else:
            pnpm = manifest.get("runtime", {}).get("pnpm")
            require(pnpm and Path(pnpm).is_file(), "manifest pnpm missing")
            node_env = {**env, "NODE_OPTIONS": f"--import={fixture}"}
            codes = []
            for index, program in enumerate(["tsconfig.json", "web/tsconfig.json", "packages/coast/tsconfig.json"]):
                completed, _ = child([pnpm, "exec", "tsc", "--noEmit", "-p", program], f"typecheck-{index + 1}", node_env)
                codes.append(completed.returncode)
            require(codes == [0, 0, 0], "one or more declared TypeScript programs failed")
            receipt["status"] = "PASS_REVIEW_REQUIRED"
        require(frozen_inputs() == inputs and sha(REPO / PRIMARY) == receipt["source_hash"], "inputs mutated during execution")
        require(git("rev-parse", "HEAD") == head, "HEAD changed during execution")
    except Exception as error:
        receipt["status"] = "FAILED"
        receipt["error"] = str(error)
    receipt["status_after"] = git("status", "--porcelain")
    receipt["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    path = output / "receipt.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "receipt": str(path), "sha256": sha(path), "error": receipt.get("error")}))
    return 0 if receipt["status"] in {"BASELINE_GAP_REPRODUCED", "PASS_REVIEW_REQUIRED"} else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--repository-child"]:
        repository_child()
    else:
        try:
            raise SystemExit(main())
        except RuntimeError as error:
            print(str(error), file=sys.stderr)
            raise SystemExit(1)
