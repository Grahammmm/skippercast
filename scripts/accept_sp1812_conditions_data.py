"""SP-18-v1 / SP1812 scoped offline acceptance; a pass still requires review."""
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
BASE = "67ff9bcf34257698a41585bc2ad163171dc68259"
PRODUCT = "server/advisor/answers/conditions.ts"
PRODUCT_PIN = "9a1ffbe43c3faf2a59494ce08cb01345e17a5fedc2b1fb87246b51ad55b8d557"
TEST = "tests/test_sp1812_conditions_data.mjs"
FIXTURE = "tests/fixtures/sp1812_conditions_data"
PAIR = "^A[13] "
COMPAT = {
    "tests/test_advisor_tools.mjs": "8f926981e36d3c456764e3486fab5550ad86f0ce86a00961cb7dabc5d881f285",
    "tests/test_advisor_daily.mjs": "356dcaa6b8403bcbd594aff15ee9799da910c2b1b43fab533ae9c90e09f3b9d2",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def identity():
    paths = [PRODUCT, TEST, "scripts/accept_sp1812_conditions_data.py", *COMPAT]
    paths += [str(p.relative_to(ROOT)) for p in sorted((ROOT / FIXTURE).rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
    doc = "docs/engineering/sp1812_conditions_data.md"
    if (ROOT / doc).exists():
        paths.append(doc)
    return {"head": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
            "status": git("status", "--porcelain"),
            "sha256": {p: digest((ROOT / p).read_bytes()) for p in paths}}


def tap_counts(text):
    result = {}
    for key in ("tests", "pass", "fail", "cancelled", "skipped", "todo"):
        matches = re.findall(rf"^# {key} (\d+)\s*$", text, re.M)
        if len(matches) != 1:
            raise ValueError(f"missing or ambiguous TAP {key}")
        result[key] = int(matches[0])
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", required=True, choices=["baseline", "focused", "regression", "repository", "typecheck", "build"])
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT.parent / "out"):
        raise SystemExit("output must be under the staged candidate out directory")
    out.mkdir(parents=True, exist_ok=True)
    run = out / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex)
    run.mkdir()
    receipt = {"spec": "SP-18-v1", "card": "SP1812-CONDITIONS-DATA", "phase": args.phase,
               "argv": [sys.executable, *sys.argv], "cwd": str(Path.cwd()), "repo": str(ROOT),
               "python": sys.version, "commands": [], "status": "ERROR", "started_at": datetime.now(timezone.utc).isoformat()}
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR"}}
    env["CI"] = "true"
    env["NO_COLOR"] = "1"
    env["NODE_OPTIONS"] = "--import " + str(ROOT / FIXTURE / "offline.mjs")

    def child(argv, mode="check"):
        index = len(receipt["commands"])
        start = time.monotonic()
        cp = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, timeout=600, check=False)
        stdout = run / f"{index:02d}.stdout.txt"
        stderr = run / f"{index:02d}.stderr.txt"
        stdout.write_bytes(cp.stdout)
        stderr.write_bytes(cp.stderr)
        row = {"argv": argv, "cwd": str(ROOT), "exit": cp.returncode, "elapsed_s": time.monotonic() - start,
               "stdout": str(stdout), "stderr": str(stderr), "stdout_sha256": digest(cp.stdout), "stderr_sha256": digest(cp.stderr)}
        receipt["commands"].append(row)
        text = cp.stdout.decode("utf-8", errors="replace")
        if mode == "tap":
            row["counts"] = tap_counts(text)
            counts = row["counts"]
            if counts["tests"] <= 0 or any(counts[k] for k in ("skipped", "cancelled", "todo")):
                raise ValueError("positive executed test counts and zero skips/cancellations/todos required")
        elif mode == "repository":
            match = re.search(r"Checked (\d+) text files:", text)
            if not match or int(match[1]) <= 0:
                raise ValueError("repository scanner positive file count missing")
            row["counts"] = {"text_files": int(match[1])}
        else:
            row["counts"] = {"checks": 1}
        if mode != "tap" and cp.returncode != 0:
            raise ValueError(f"child exited {cp.returncode}")
        return cp, row, text

    def green(argv, expected=None):
        cp, row, _ = child(argv, "tap")
        counts = row["counts"]
        if cp.returncode or counts["fail"] or counts["pass"] != counts["tests"] or (expected is not None and counts["tests"] != expected):
            raise ValueError("green TAP contract failed")

    try:
        if Path.cwd().resolve() != ROOT:
            raise ValueError("acceptance cwd must be staged repo")
        manifest_path = ROOT.parent / "SOURCE-MANIFEST.json"
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("schema") != "agentorange.source-manifest/v1" or manifest.get("head") != BASE or Path(manifest.get("repo", "")).resolve() != ROOT:
            raise ValueError("source manifest schema/repo/head mismatch")
        receipt["source_manifest_sha256"] = digest(manifest_path.read_bytes())
        receipt["source"] = identity()
        subprocess.run(["git", "merge-base", "--is-ancestor", BASE, receipt["source"]["head"]], cwd=ROOT, check=True)
        for path, pin in COMPAT.items():
            if digest((ROOT / path).read_bytes()) != pin:
                raise ValueError("compatibility source drift: " + path)
        node = shutil.which("node")
        pnpm = manifest["runtime"]["pnpm"]
        if not node or not Path(pnpm).is_file():
            raise ValueError("standard installed Node/pnpm missing; no installation allowed")
        cp, _, _ = child([node, "--version"])
        receipt["node"] = cp.stdout.decode().strip()
        pair = [node, "--test", "--test-reporter=tap", "--test-name-pattern", PAIR, TEST]
        if args.phase == "baseline":
            if digest((ROOT / PRODUCT).read_bytes()) != PRODUCT_PIN or receipt["source"]["head"] != BASE and git("diff", BASE, "--", PRODUCT):
                raise ValueError("baseline requires unchanged pinned product source")
            cp, row, text = child(pair, "tap")
            required = {"tests": 2, "pass": 1, "fail": 1, "cancelled": 0, "skipped": 0, "todo": 0}
            if cp.returncode != 1 or row["counts"] != required or not re.search(r"^not ok \d+ - A1 primary regression:", text, re.M) or not re.search(r"^ok \d+ - A3 healthy control:", text, re.M) or "SP1812_A1_NO_USABLE_FORECAST" not in text or "ERR_ASSERTION" not in text:
                raise ValueError("exact A1 semantic red plus A3 healthy contract not reproduced")
            receipt["status"] = "BASELINE_GAP_REPRODUCED"
        elif args.phase == "focused":
            green(pair, 2)
            green([node, "--test", "--test-reporter=tap", TEST], 33)
            receipt["status"] = "PASS_REVIEW_REQUIRED"
        elif args.phase == "regression":
            for path in COMPAT:
                green([node, "--test", "--test-reporter=tap", path])
            receipt["status"] = "PASS_REVIEW_REQUIRED"
        elif args.phase == "repository":
            scanner = manifest["runtime"]["credential_scan_python3"]
            if not Path(scanner).is_file():
                raise ValueError("manifest credential scanner runtime unavailable; no fallback")
            child([scanner, FIXTURE + "/offline_python.py", "scripts/check_repository.py"], "repository")
            receipt["status"] = "PASS_REVIEW_REQUIRED"
        elif args.phase == "typecheck":
            for project in ("tsconfig.json", "web/tsconfig.json", "packages/coast/tsconfig.json"):
                child([pnpm, "exec", "tsc", "--noEmit", "--project", project])
            receipt["status"] = "PASS_REVIEW_REQUIRED"
        elif args.phase == "build":
            child([pnpm, "build"])
            receipt["status"] = "PASS_REVIEW_REQUIRED"
        if receipt["source"] != identity():
            raise ValueError("source changed during acceptance")
        receipt["exit"] = 0
    except Exception as exc:
        receipt["status"] = "ERROR"
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        receipt["exit"] = 1
    receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
    target = run / "receipt.json"
    target.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "exit": receipt["exit"], "receipt": str(target), "receipt_sha256": digest(target.read_bytes()), "commands": [{k: row[k] for k in ("argv", "exit", "counts") if k in row} for row in receipt["commands"]], "error": receipt.get("error")}))
    return receipt["exit"]


if __name__ == "__main__":
    raise SystemExit(main())
