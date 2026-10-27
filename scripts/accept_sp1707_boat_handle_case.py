"""Offline SP-17-v1 acceptance receipts. Success always remains REVIEW REQUIRED."""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
BASE = "8a805820c30895f5f037e26af9079fd3dc015b0f"
CARD = "SP1707-BOAT-HANDLE-CASE"
TEST = "tests/test_sp1707_boat_handle_case.mjs"
FIXTURE = "tests/fixtures/sp1707_boat_handle_case"
PRIMARY = "A1 primary regression: verified mixed-case-only contact renders"
CONTROL = "CONTROL healthy lowercase-only contact renders"
PINNED = {
    "server/advisor/pages/boat.ts": "94c034e7eb3129cf64a35d5fbf844d35bf01db95bb7340b167b2764c4694191d",
    "tests/test_advisor_pages.mjs": "58b1afab399577e6043b1e974e43b2a5208114204d873c857d8d1defdbf47170",
    "scripts/check_repository.py": "cf39ee4dab44893fae58d4553c8a159942c5674f5ce33f22ca9c441d0a74dec8",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def counts(stdout):
    text = stdout.decode("utf-8", errors="replace")
    result = {}
    for key in ("tests", "suites", "pass", "fail", "cancelled", "skipped", "todo"):
        found = re.findall(rf"^# {key} (\d+)$", text, flags=re.MULTILINE)
        if found:
            result[key] = int(found[-1])
    scan = re.search(r"Checked (\d+) text files:", text)
    if scan:
        result["repository_text_files"] = int(scan.group(1))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=["baseline", "focused", "regression", "repository", "typecheck", "build"])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    # New output every invocation: no author's or reviewer's prior evidence is overwritten.
    output = args.output.resolve() / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex)
    if output.is_relative_to(ROOT):
        parser.error("evidence must be outside repository/fixture inputs")
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": "sp1707.acceptance/v1", "spec": "SP-17-v1", "card": CARD,
               "phase": args.phase, "cwd": str(ROOT), "output": str(output),
               "runner_python": {"executable": sys.executable, "version": sys.version},
               "children": [], "result": "FAIL"}

    def run(label, argv):
        child = {"label": label, "argv": [str(item) for item in argv], "cwd": str(ROOT)}
        receipt["children"].append(child)
        try:
            result = subprocess.run(child["argv"], cwd=ROOT, capture_output=True, timeout=600, check=False)
            stdout, stderr, code = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr, code = error.stdout or b"", error.stderr or b"", 124
            child["error"] = "child timeout"
        except OSError as error:
            stdout, stderr, code = b"", str(error).encode(), 127
            child["error"] = type(error).__name__
        child.update({"exit": code, "counts": counts(stdout)})
        for stream, data in (("stdout", stdout), ("stderr", stderr)):
            path = output / f"{label}.{stream}.txt"
            path.write_bytes(data)
            child[stream] = {"path": str(path), "sha256": digest(data), "bytes": len(data)}
        print(f"{label}: exit={code} counts={child['counts']}", flush=True)
        return child, stdout, stderr

    def require(ok, message):
        if not ok:
            raise ValueError(message)

    def green(child, expected=None):
        c = child["counts"]
        require(child["exit"] == 0, f"{child['label']}: child failed")
        require(c.get("tests", 0) > 0 and c.get("pass") == c["tests"], "missing or incomplete TAP tests")
        require(all(c.get(key) == 0 for key in ("fail", "cancelled", "skipped", "todo")), "non-green TAP status")
        if expected is not None:
            require(c["tests"] == expected, "unexpected test count")

    try:
        manifest_path = ROOT.parent / "SOURCE-MANIFEST.json"
        manifest = json.loads(manifest_path.read_text())
        require(manifest.get("schema") == "agentorange.source-manifest/v1", "invalid stage manifest schema")
        require(manifest.get("head") == BASE and manifest.get("card") == CARD, "wrong admitted base/card")
        require(Path(manifest["repo"]).resolve() == ROOT, "wrong stage repository")
        require(Path(manifest["write_root"]).resolve() == ROOT.parent, "wrong write root")
        require(manifest.get("runtime", {}).get("credential_scan_python3"), "scanner runtime not supplied")
        require(git("rev-parse", f"{BASE}^{{tree}}").decode().strip() == manifest.get("tree"), "wrong stage tree")
        require(subprocess.run(["git", "merge-base", "--is-ancestor", BASE, "HEAD"], cwd=ROOT, check=False).returncode == 0, "base is not an ancestor")
        for name in ("tests/test_advisor_pages.mjs", "scripts/check_repository.py"):
            require(digest((ROOT / name).read_bytes()) == PINNED[name], f"original changed: {name}")
        files = [*PINNED, TEST, "scripts/accept_sp1707_boat_handle_case.py"]
        files += [path.relative_to(ROOT).as_posix() for path in sorted((ROOT / FIXTURE).rglob("*")) if path.is_file()]
        note = "docs/engineering/sp1707_boat_handle_case.md"
        if (ROOT / note).exists():
            files.append(note)
        receipt["identity"] = {"head": git("rev-parse", "HEAD").decode().strip(), "base": BASE,
                               "status": git("status", "--porcelain").decode(),
                               "diff_sha256": digest(git("diff", "--binary", BASE)),
                               "source_manifest_sha256": digest(manifest_path.read_bytes()),
                               "files": {name: digest((ROOT / name).read_bytes()) for name in files}}
        node, pnpm = shutil.which("node"), shutil.which("pnpm")
        require(node is not None, "installed Node missing")
        runtime, _, _ = run("node-runtime", [node, "--version"])
        require(runtime["exit"] == 0, "Node runtime unavailable")
        node_args = [node, "--experimental-strip-types", "--import", str(ROOT / FIXTURE / "offline-preload.mjs"), "--test", "--test-reporter=tap"]
        if args.phase == "baseline":
            require(not git("diff", BASE, "--", "server", "web", "packages").strip(), "baseline product source must be unchanged")
            require(receipt["identity"]["files"]["server/advisor/pages/boat.ts"] == PINNED["server/advisor/pages/boat.ts"], "wrong baseline product bytes")
            red, stdout, _ = run("primary-red", [*node_args, f"--test-name-pattern=^{re.escape(PRIMARY)}$", TEST])
            control, _, _ = run("healthy-control", [*node_args, f"--test-name-pattern=^{re.escape(CONTROL)}$", TEST])
            require(red["exit"] == 1, "primary baseline must exit 1")
            c = red["counts"]
            require(c.get("tests") == 1 and c.get("fail") == 1 and c.get("pass") == 0, "primary did not fail exactly one test")
            require(all(c.get(key) == 0 for key in ("cancelled", "skipped", "todo")), "baseline cannot skip or cancel")
            require(b"SP1707_A1_MIXED_CASE_ANCHOR" in stdout and b"ERR_ASSERTION" in stdout, "primary did not fail its named semantic assertion")
            require(b"failureType: 'testCodeFailure'" in stdout and f"not ok 1 - {PRIMARY}".encode() in stdout, "wrong primary failure")
            green(control, 1)
            receipt["result"] = "EXPECTED_RED_AND_GREEN_CONTROL_REVIEW_REQUIRED"
        elif args.phase == "focused":
            child, _, _ = run("focused", [*node_args, TEST])
            green(child, 23)
            receipt["result"] = "PASS_REVIEW_REQUIRED"
        elif args.phase == "regression":
            child, _, _ = run("original-advisor-pages", [*node_args, "tests/test_advisor_pages.mjs"])
            green(child)
            receipt["result"] = "PASS_REVIEW_REQUIRED"
        elif args.phase == "repository":
            interpreter = manifest["runtime"]["credential_scan_python3"]
            runtime, _, _ = run("scanner-runtime", [interpreter, "--version"])
            require(runtime["exit"] == 0, "full-suite scanner interpreter missing; no substitution allowed")
            child, _, _ = run("repository", [interpreter, "scripts/check_repository.py"])
            require(child["exit"] == 0 and child["counts"].get("repository_text_files", 0) > 0, "repository scan failed or no count")
            receipt["result"] = "PASS_REVIEW_REQUIRED"
        elif args.phase == "typecheck":
            require(pnpm is not None, "installed pnpm missing")
            for index, config in enumerate(("tsconfig.json", "web/tsconfig.json", "packages/coast/tsconfig.json")):
                child, _, _ = run(f"typecheck-{index}", [pnpm, "exec", "tsc", "--noEmit", "--project", config])
                require(child["exit"] == 0, f"typecheck failed: {config}")
            receipt["result"] = "PASS_REVIEW_REQUIRED"
        elif args.phase == "build":
            require(pnpm is not None, "installed pnpm missing")
            child, _, _ = run("build", [pnpm, "build"])
            require(child["exit"] == 0, "local build failed")
            receipt["result"] = "PASS_REVIEW_REQUIRED"
        require(git("rev-parse", "HEAD").decode().strip() == receipt["identity"]["head"], "HEAD changed during acceptance")
        for name, expected in receipt["identity"]["files"].items():
            require(digest((ROOT / name).read_bytes()) == expected, f"source changed during acceptance: {name}")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        receipt["error"] = str(error)
        receipt["result"] = "FAIL"
    finally:
        path = output / "receipt.json"
        path.write_text(json.dumps(receipt, indent=2) + "\n")
        print(f"{receipt['result']}: {path}", flush=True)
        print(f"receipt_sha256={digest(path.read_bytes())}", flush=True)
        if "error" in receipt:
            print(receipt["error"], file=sys.stderr)
    return 1 if receipt["result"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
