"""SP-17-v1 offline acceptance. Each invocation retains unique, unhashed-over evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
BASE = "8a805820c30895f5f037e26af9079fd3dc015b0f"
PRIMARY_HASH = "ac3cbf29b6ac5a36a43835186df40c463a95eb7e48f10d280dc57696e603a7e1"
TEST = "tests/test_sp1710_sheet_pointer_owner.mjs"
OWNED = ["web/ui/Sheet.tsx", TEST, "scripts/accept_sp1710_sheet_pointer_owner.py",
         "tests/fixtures/sp1710_sheet_pointer_owner/gestures.json",
         "docs/engineering/sp1710_sheet_pointer_owner.md", "tests/test_app_shell.mjs"]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def identity():
    return {"head": git("rev-parse", "HEAD"), "base": BASE,
            "status_porcelain": git("status", "--porcelain=v1"),
            "files_sha256": {p: digest((ROOT / p).read_bytes()) for p in OWNED if (ROOT / p).is_file()}}


def tap_counts(text):
    counts = {}
    for field in ["tests", "pass", "fail", "cancelled", "skipped", "todo"]:
        match = re.search(rf"^# {field} (\d+)\s*$", text, re.M)
        counts[field] = int(match[1]) if match else None
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=["baseline", "focused", "regression", "repository", "typecheck", "build"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = ROOT.parent / "SOURCE-MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get("schema") != "agentorange.source-manifest/v1"
            or manifest.get("head") != BASE or Path(manifest.get("repo", "")).resolve() != ROOT
            or not manifest.get("runtime", {}).get("credential_scan_python3")):
        raise ValueError("Standard stage schema/repo/base/scanner runtime mismatch")
    if git("rev-parse", f"{BASE}^{{commit}}") != BASE:
        raise ValueError("Pinned base unavailable")
    before = identity()
    if args.phase == "baseline" and before["files_sha256"]["web/ui/Sheet.tsx"] != PRIMARY_HASH:
        raise ValueError("Baseline requires unchanged pinned product source")
    out = args.output.resolve() / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex)
    out.mkdir(parents=True, exist_ok=False)
    scratch = out / "tmp"
    scratch.mkdir()
    node = shutil.which("node")
    pnpm = manifest["runtime"].get("pnpm") or shutil.which("pnpm")
    receipt = {"schema": "sp1710.acceptance/v1", "spec": "SP-17-v1", "card": "SP1710-SHEET-POINTER-OWNER",
               "phase": args.phase, "cwd": str(ROOT), "source_before": before,
               "source_manifest_sha256": digest(manifest_path.read_bytes()),
               "runner_python": sys.executable, "children": [], "passed": False}

    def run(label, argv, selector=None, expected_tests=None, expected_fail=0):
        env = os.environ.copy()
        env["TMPDIR"] = str(scratch)
        # An ambient selector must never narrow the focused suite.
        env.pop("SP1710_SELECTOR", None)
        if selector:
            env["SP1710_SELECTOR"] = selector
        result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, timeout=600, check=False)
        stdout, stderr = out / f"{label}.stdout", out / f"{label}.stderr"
        stdout.write_bytes(result.stdout)
        stderr.write_bytes(result.stderr)
        text = result.stdout.decode("utf-8", errors="replace")
        counts = tap_counts(text) if expected_tests is not None else None
        valid = result.returncode == (1 if expected_fail else 0)
        if expected_tests is not None:
            valid = valid and counts == {"tests": expected_tests, "pass": expected_tests - expected_fail,
                                         "fail": expected_fail, "cancelled": 0, "skipped": 0, "todo": 0}
        if expected_fail:
            valid = valid and all(token in text for token in ["SP1710_ORIGIN", "ERR_ASSERTION", "full", "half",
                "not ok 1 - A1: interleaved pointer-2 down cannot replace pointer-1 origin"])
        checked = None
        if label == "repository":
            match = re.search(r"Checked (\d+) text files:", text)
            checked = int(match[1]) if match else None
            valid = valid and checked is not None
        receipt["children"].append({"label": label, "argv": argv, "cwd": str(ROOT),
            "environment_overrides": {"TMPDIR": str(scratch), "SP1710_SELECTOR": selector},
            "runtime": {"node": node, "pnpm": pnpm, "python": sys.executable},
            "exit": result.returncode, "counts": counts, "checked_text_files": checked,
            "stdout": str(stdout), "stdout_sha256": digest(result.stdout),
            "stderr": str(stderr), "stderr_sha256": digest(result.stderr), "contract_passed": bool(valid)})
        print(f"{label}: exit={result.returncode} counts={counts} checked={checked} contract_passed={bool(valid)}", flush=True)
        if not valid:
            raise RuntimeError(f"{label}: acceptance contract failed; see retained raw output")

    try:
        if args.phase in {"baseline", "focused"}:
            if not node:
                raise RuntimeError("Installed node missing; no installation permitted")
            argv = [node, "--test", "--test-reporter=tap", TEST]
            run("primary", argv, "A1", 1, 1 if args.phase == "baseline" else 0)
            run("control", argv, "control", 1)
            if args.phase == "focused":
                run("focused", argv, "all", 5)
        elif args.phase == "regression":
            run("app-shell", [node, "--test", "--test-reporter=tap", "tests/test_app_shell.mjs"], expected_tests=15)
        elif args.phase == "repository":
            run("repository", [manifest["runtime"]["credential_scan_python3"], "scripts/check_repository.py"])
        elif args.phase == "typecheck":
            for index, project in enumerate(["tsconfig.json", "web/tsconfig.json", "packages/coast/tsconfig.json"]):
                run(f"typecheck-{index + 1}", [pnpm, "exec", "tsc", "--noEmit", "--project", project])
        elif args.phase == "build":
            run("build", [pnpm, "build"])
        receipt["source_after"] = identity()
        if receipt["source_after"] != before:
            raise RuntimeError("Source identity changed during acceptance")
        receipt["passed"] = True
    except Exception as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
    finally:
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(f"receipt: {out / 'receipt.json'}", flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
