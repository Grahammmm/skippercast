#!/usr/bin/env python3
"""SP-17-v1 offline acceptance; every invocation retains a unique raw receipt."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
BASE = "8a805820c30895f5f037e26af9079fd3dc015b0f"
PRODUCT = "web/map/commercial-ais.ts"
BASE_HASH = "2aa03ba230a8b4c866b337df3c581047bc22d8ae1611640d668d94a02c545881"
TEST = "tests/test_sp1711_ais_scale_refresh.mjs"
PRIMARY = "A1: primary regression same-engine maximum removal refreshes scale"
CONTROL = "Healthy control: initial 2 and 20 install matching denominator 20"
OWNED = [PRODUCT, TEST, "scripts/accept_sp1711_ais_scale_refresh.py",
         "tests/fixtures/sp1711_ais_scale_refresh/cells.json", "docs/engineering/sp1711_ais_scale_refresh.md",
         "tests/test_fleet_public_layers.mjs", "web/map/engine.ts", "web/map/charter-grounds.ts"]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()


def identity():
    return {"head": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
            "status": git("status", "--porcelain"),
            "diff_sha256": digest(subprocess.check_output(["git", "diff", BASE], cwd=ROOT)),
            "files": {p: digest((ROOT / p).read_bytes()) for p in OWNED if (ROOT / p).is_file()}}


def counts(text):
    return {key: int(value) for key, value in re.findall(r"^# (tests|pass|fail|skipped|cancelled|todo) (\d+)\s*$", text, re.M)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=["baseline", "focused", "regression", "repository", "typecheck", "build"])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    out = args.output.resolve() / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex)
    out.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": "sp1711.acceptance/v1", "spec": "SP-17-v1", "card": "SP1711-AIS-SCALE-REFRESH",
               "phase": args.phase, "cwd": str(ROOT), "runner_python": sys.executable,
               "started_at": datetime.now(timezone.utc).isoformat(), "children": [], "accepted": False}
    try:
        manifest_path = ROOT.parent / "SOURCE-MANIFEST.json"
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("schema") != "agentorange.source-manifest/v1" or manifest.get("head") != BASE or Path(manifest.get("repo", "")).resolve() != ROOT:
            raise ValueError("source manifest schema/base/repo mismatch")
        if manifest.get("card") != "SP1711-AIS-SCALE-REFRESH" or git("rev-parse", BASE) != BASE:
            raise ValueError("source manifest card/base identity mismatch")
        scanner = manifest["runtime"]["credential_scan_python3"]
        if not Path(scanner).is_file():
            raise ValueError("operator full-suite interpreter missing; no fallback")
        receipt["source_manifest_sha256"] = digest(manifest_path.read_bytes())
        receipt["source_before"] = identity()
        node = shutil.which("node")
        pnpm = manifest["runtime"]["pnpm"]
        if not node:
            raise ValueError("installed Node is required")
        receipt["node_version"] = subprocess.check_output([node, "--version"], cwd=ROOT).decode().strip()
        commands = []
        if args.phase == "baseline":
            if digest((ROOT / PRODUCT).read_bytes()) != BASE_HASH:
                raise ValueError("baseline requires unchanged pinned product source")
            commands = [("primary", [node, "--test", "--test-name-pattern", "^" + PRIMARY + "$", TEST], 1, 1),
                        ("control", [node, "--test", "--test-name-pattern", "^" + CONTROL + "$", TEST], 0, 1)]
        elif args.phase == "focused":
            commands = [("focused", [node, "--test", TEST], 0, 8)]
        elif args.phase == "regression":
            commands = [("fleet-public-layers", [node, "--test", "tests/test_fleet_public_layers.mjs"], 0, 6)]
        elif args.phase == "repository":
            commands = [("repository", [scanner, "scripts/check_repository.py"], 0, None)]
        elif args.phase == "typecheck":
            commands = [("tsc-" + str(i), [pnpm, "exec", "tsc", "--noEmit", "--project", project], 0, None)
                        for i, project in enumerate(["tsconfig.json", "web/tsconfig.json", "packages/coast/tsconfig.json"])]
        elif args.phase == "build":
            commands = [("build", [pnpm, "build"], 0, None)]
        valid = True
        for name, argv, expected_exit, expected_tests in commands:
            child = {"name": name, "argv": argv, "cwd": str(ROOT), "expected_exit": expected_exit, "expected_tests": expected_tests}
            start = datetime.now(timezone.utc)
            result = subprocess.run(argv, cwd=ROOT, capture_output=True, check=False, timeout=600)
            child.update({"exit": result.returncode, "started_at": start.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat()})
            for stream in ["stdout", "stderr"]:
                raw = getattr(result, stream)
                filename = name + "." + stream + ".txt"
                (out / filename).write_bytes(raw)
                child[stream] = {"file": filename, "bytes": len(raw), "sha256": digest(raw)}
            text = result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace")
            child["counts"] = counts(text)
            ok = result.returncode == expected_exit
            if expected_tests is not None:
                c = child["counts"]
                ok = ok and c == {"tests": expected_tests, "pass": expected_tests - (expected_exit == 1),
                                  "fail": int(expected_exit == 1), "cancelled": 0, "skipped": 0, "todo": 0}
            if args.phase == "baseline" and name == "primary":
                ok = ok and all(token in text for token in ["SP1711_SCALE_MISMATCH", "ERR_ASSERTION", "expected: 2", "actual: 20"])
            if args.phase == "repository":
                match = re.search(r"Checked (\d+) text files:", text)
                child["checked_text_files"] = int(match.group(1)) if match else None
                ok = ok and bool(match)
            child["contract_pass"] = bool(ok)
            receipt["children"].append(child)
            valid = valid and ok
            print(json.dumps(child, sort_keys=True), flush=True)
        receipt["source_after"] = identity()
        if receipt["source_before"] != receipt["source_after"]:
            valid = False
            receipt["identity_error"] = "source changed while acceptance ran"
        receipt["accepted"] = bool(valid)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        receipt["error"] = str(exc)
    finally:
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        receipt["exit"] = 0 if receipt["accepted"] else 1
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        print(f"receipt={out / 'receipt.json'} accepted={receipt['accepted']}", flush=True)
    return receipt["exit"]


if __name__ == "__main__":
    raise SystemExit(main())
