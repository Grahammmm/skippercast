"""SP-15-v1 offline argv launcher. Green results remain REVIEW REQUIRED.

No shell, inline source, installs, fallback interpreter, or network acquisition.
Each invocation creates a unique evidence directory outside the repository.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
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
PRIMARY = "web/land-water.ts"
BASE_PRIMARY_SHA = "d01945fab06a291dc8b2bb35fe365105cbe21e50a49810f2092d2ab81b5ef935"
ORIGINAL = "tests/test_land_water.mjs"
ORIGINAL_SHA = "79a50409efc0231dd7e64c43b99788175eb4c18e7d4f345ccfaf82a1650b1636"
TEST = "tests/test_sp1503_land_water_retry.mjs"
FIXTURES = "tests/fixtures/sp1503_land_water_retry"
HELPER = "scripts/accept_sp1503_land_water_retry.py"
DOC = "docs/engineering/sp1503_land_water_retry.md"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], cwd=ROOT, text=True).strip()


def identity():
    paths = [PRIMARY, ORIGINAL, TEST, HELPER]
    if (ROOT / DOC).exists():
        paths.append(DOC)
    paths.extend(p.relative_to(ROOT).as_posix() for p in sorted((ROOT / FIXTURES).rglob("*")) if p.is_file())
    return {"head": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
            "status": git("status", "--porcelain"), "files_sha256": {p: sha(ROOT / p) for p in paths}}


def execute(argv, directory, name):
    started = datetime.now(timezone.utc).isoformat()
    clock = time.monotonic()
    out = directory / f"{name}.stdout.txt"
    err = directory / f"{name}.stderr.txt"
    timeout = False
    with out.open("wb") as stdout, err.open("wb") as stderr:
        try:
            result = subprocess.run(argv, cwd=ROOT, stdout=stdout, stderr=stderr, timeout=900, check=False)
            code = result.returncode
        except subprocess.TimeoutExpired:
            timeout = True
            code = None
        except OSError as error:
            stderr.write(f"launcher setup error: {error}\n".encode())
            code = None
    return {"argv": argv, "cwd": str(ROOT), "started_utc": started,
            "duration_seconds": time.monotonic() - clock, "exit": code, "timeout": timeout,
            "stdout": str(out), "stdout_sha256": sha(out), "stderr": str(err), "stderr_sha256": sha(err)}


def tap_counts(text):
    values = {}
    for key in ("tests", "pass", "fail", "cancelled", "skipped", "todo"):
        matches = re.findall(rf"^# {key} (\d+)\s*$", text, flags=re.MULTILINE)
        if len(matches) != 1:
            raise ValueError(f"missing or ambiguous TAP count: {key}")
        values[key] = int(matches[0])
    return values


def check_tap(child, baseline=False, regression=False):
    text = Path(child["stdout"]).read_text()
    counts = tap_counts(text)
    child["counts"] = counts
    for key in ("cancelled", "skipped", "todo"):
        if counts[key] != 0:
            raise ValueError(f"nonzero TAP {key}")
    if baseline:
        expected = {"tests": 2, "pass": 1, "fail": 1, "cancelled": 0, "skipped": 0, "todo": 0}
        if child["exit"] != 1 or counts != expected:
            raise ValueError("baseline must exit 1 with exactly one failed regression and one passed control")
        required = [r"^not ok 1 - primary regression\s*$", r"^ok 2 - healthy control\s*$",
                    r"SP1503_A1_EXPLICIT_TRANSIENT_RECOVERY", r"ERR_ASSERTION",
                    r"SP1503_OBSERVED .*\"first\":\"unavailable\",\"recovered\":\"unavailable\",\"calls\":1"]
        if not all(re.search(pattern, text, re.MULTILINE) for pattern in required):
            raise ValueError("baseline did not expose the exact A1 semantic mismatch and healthy control")
        if Path(child["stderr"]).read_text().strip():
            raise ValueError("baseline has unexpected setup/runtime stderr")
    else:
        expected = len(re.findall(r"^test\(", (ROOT / ORIGINAL).read_text(), re.MULTILINE)) if regression else 9
        if child["exit"] != 0 or counts["tests"] != expected or counts["pass"] != expected or counts["fail"] != 0:
            raise ValueError(f"expected {expected} tests executed and green")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=("baseline", "focused", "regression", "repository", "typecheck", "build"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    # Validate the output boundary before creating any evidence; no repository or shared writes.
    allowed = (CANDIDATE / "out").resolve()
    output = args.output.expanduser().absolute()
    for part in [output, *output.parents]:
        if part.is_symlink():
            raise ValueError("symlinked evidence ancestry is not admitted")
    if not output.resolve().is_relative_to(allowed):
        raise ValueError("output must be under the staged candidate out directory")
    output.mkdir(parents=True, exist_ok=True)
    directory = output / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex)
    directory.mkdir()
    receipt = {"schema": "skippercast.sp1503.acceptance/v1", "spec": "SP-15-v1", "card": "SP1503-LAND-WATER-RETRY",
               "suite": args.suite, "acceptance_argv": [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
               "acceptance_cwd": str(Path.cwd()), "python": sys.version, "base": BASE,
               "children": [], "runtimes": [], "status": "UNVERIFIED", "errors": []}
    try:
        source_manifest = json.loads((CANDIDATE / "SOURCE-MANIFEST.json").read_text())
        if source_manifest.get("schema") != "agentorange.source-manifest/v1" or source_manifest.get("head") != BASE or Path(source_manifest["repo"]).resolve() != ROOT:
            raise ValueError("staged source manifest does not match this clone and base")
        credential_python = source_manifest["runtime"]["credential_scan_python3"]
        if not Path(credential_python).is_file():
            raise ValueError("missing admitted credential scan runtime; no fallback allowed")
        receipt["source_manifest_sha256"] = sha(CANDIDATE / "SOURCE-MANIFEST.json")
        before = identity()
        receipt["source_before"] = before
        if before["files_sha256"][ORIGINAL] != ORIGINAL_SHA:
            raise ValueError("original selector changed")
        if args.suite == "baseline" and (before["head"] != BASE or before["files_sha256"][PRIMARY] != BASE_PRIMARY_SHA or git("diff", BASE, "--", PRIMARY)):
            raise ValueError("baseline requires unchanged pinned product at the staged head")
        node = shutil.which("node")
        pnpm = shutil.which("pnpm")
        if not node or not pnpm:
            raise ValueError("missing installed Node/pnpm; installation is not admitted")
        for name, argv in [("node", [node, "--version"]), ("pnpm", [pnpm, "--version"])]:
            runtime = execute(argv, directory, "runtime-" + name)
            receipt["runtimes"].append(runtime)
            if runtime["exit"] != 0:
                raise ValueError("runtime version probe failed")
        if args.suite in ("baseline", "focused", "regression"):
            argv = [node, TEST]
            if args.suite == "baseline":
                argv.append("--baseline-pair")
            elif args.suite == "regression":
                argv.append("--original-regression")
            commands = [argv]
        elif args.suite == "repository":
            commands = [[credential_python, "scripts/check_repository.py"]]
        elif args.suite == "typecheck":
            commands = [[pnpm, "exec", "tsc", "--noEmit", "-p", config]
                        for config in ("tsconfig.json", "web/tsconfig.json", "packages/coast/tsconfig.json")]
        else:
            commands = [[pnpm, "build"]]
        for number, argv in enumerate(commands, 1):
            child = execute(argv, directory, f"child-{number}")
            receipt["children"].append(child)
            if args.suite in ("baseline", "focused", "regression"):
                check_tap(child, baseline=args.suite == "baseline", regression=args.suite == "regression")
            elif child["exit"] != 0:
                raise ValueError(f"acceptance child failed: {argv}")
            elif args.suite == "repository":
                match = re.search(r"Checked (\d+) text files:", Path(child["stdout"]).read_text())
                if not match:
                    raise ValueError("repository checker did not report actual scan count")
                child["checked_text_files"] = int(match[1])
        receipt["source_after"] = identity()
        if receipt["source_after"] != before:
            raise ValueError("source identity changed during acceptance")
        receipt["status"] = "BASELINE_GAP_REPRODUCED" if args.suite == "baseline" else "SCOPED_GREEN_REVIEW_REQUIRED"
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        receipt["errors"].append(str(error))
        receipt["status"] = "FAILED_UNVERIFIED"
    receipt_path = directory / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "receipt": str(receipt_path), "receipt_sha256": sha(receipt_path),
                      "children": [{k: child[k] for k in ("argv", "cwd", "exit", "stdout_sha256", "stderr_sha256", "counts", "checked_text_files") if k in child} for child in receipt["children"]],
                      "errors": receipt["errors"]}, indent=2))
    return 0 if not receipt["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
