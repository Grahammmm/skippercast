"""Offline, receipt-producing acceptance for the bounded SP79 change.

The expected-red baseline is historical sensitivity evidence, never GREEN.
No installs, network acquisition, shell commands or runtime fallback are used.
"""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[1]
WRITE_ROOT = REPO.parent
BASE = "a1f648632e64561d82dcbeb20d9bda19f812560a"
PRODUCT = "web/station-label.ts"
ORIGINAL_PRODUCT_HASH = "bf99e06bd3408cab15046214e930b16155465fb94add3e125f9a6a8954e8c12a"
NEW_TEST = "tests/test_sp79_backup_identity.mjs"
FIXTURE = "tests/fixtures/sp79_backup_identity/cases.json"
REGRESSION = ["tests/test_station_label.mjs"]
MANIFEST = WRITE_ROOT / "SOURCE-MANIFEST.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(argv, env):
    result = subprocess.run(argv, cwd=REPO, env=env, text=True, capture_output=True, check=False)
    return {"argv": argv, "cwd": str(REPO), "exit": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr}


def checked(argv, env):
    result = command(argv, env)
    if result["exit"] != 0:
        raise RuntimeError(f"Prerequisite command failed: {argv}: {result}")
    return result["stdout"].strip()


def resolve_export(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for condition in ("node", "import", "default"):
            if condition in value:
                return resolve_export(value[condition])
    raise RuntimeError("Unsupported installed dependency export")


def inspect_closure(entries):
    """Audit this literal, pinned local selector closure, not arbitrary JS.

    Type-only edges are conservatively retained. Installed ESM dependencies
    are resolved from their package exports and hashed as well. This audit and
    runtime sentinels are not a hostile-code sandbox.
    """
    pending = [REPO / entry for entry in entries]
    seen, hashes = set(), {}
    while pending:
        path = pending.pop().absolute()
        real = path.resolve(strict=True)
        if real in seen:
            continue
        seen.add(real)
        label = str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path)
        hashes[label] = sha(real)
        if path.suffix == ".json":
            continue
        text = real.read_text()
        if path != REPO / NEW_TEST and re.search(r"node:(child_process|worker_threads|cluster)|\brequire\s*\(|\b(?:execFile|execSync|spawnSync)\s*\(", text):
            raise RuntimeError(f"Unadmitted process/import closure in {label}")
        for match in re.finditer(r"\bimport\s*\(([^)]+)\)", text):
            if not re.fullmatch(r"\s*['\"][^'\"]+['\"]\s*", match.group(1)):
                raise RuntimeError(f"Nonliteral import in {label}")
        names = re.findall(r'''(?:from\s*|import\s*\(\s*|import\s*)['"]([^'"]+)['"]''', text)
        for name in names:
            if name.startswith("node:"):
                continue
            if name.startswith("."):
                pending.append(path.parent / name)
                continue
            parts = name.split("/")
            package = "/".join(parts[:2]) if name.startswith("@") else parts[0]
            sub = parts[2:] if name.startswith("@") else parts[1:]
            # Only the already-qualified packages in this original selector.
            if package not in {"suncalc", "preact", "@preact/signals", "@preact/signals-core"}:
                raise RuntimeError(f"Unadmitted dependency {name}")
            # Follow Node's ancestor lookup from the real importing file;
            # pnpm transitive dependencies need not be hoisted at repo root.
            package_root = next((ancestor / "node_modules" / package
                                 for ancestor in [real.parent, *real.parents]
                                 if (ancestor / "node_modules" / package / "package.json").is_file()), None)
            if package_root is None:
                raise RuntimeError(f"Installed dependency unavailable: {name}")
            package_json = package_root / "package.json"
            meta = json.loads(package_json.read_text())
            package_label = str(package_json.relative_to(REPO)) if package_json.is_relative_to(REPO) else str(package_json)
            hashes[package_label] = sha(package_json)
            exports = meta["exports"]
            if isinstance(exports, dict) and any(k.startswith(".") for k in exports):
                exports = exports["./" + "/".join(sub) if sub else "."]
            elif sub:
                raise RuntimeError(f"Unsupported subpath {name}")
            pending.append(package_root / resolve_export(exports))
    return dict(sorted(hashes.items()))


def parse_tap(text):
    counts = {}
    for key in ("tests", "pass", "fail", "cancelled", "skipped", "todo"):
        matches = re.findall(rf"^# {key} (\d+)\s*$", text, re.M)
        if len(matches) != 1:
            raise RuntimeError(f"Missing or ambiguous TAP {key}")
        counts[key] = int(matches[0])
    counts["errors"] = counts["cancelled"]
    names = re.findall(r"^(?:not )?ok \d+ - (.+)$", text, re.M)
    return counts, names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=["baseline", "focused", "regression", "repository"])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    parent = args.output.resolve()
    if not parent.is_relative_to(WRITE_ROOT) or parent.is_relative_to(REPO):
        parser.error("Output must be inside Write root, outside the repository")
    parent.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix=args.suite + "-", dir=parent))
    tmp = out / "tmp"
    tmp.mkdir()
    env = os.environ.copy()
    env.update({"TMPDIR": str(tmp), "TMP": str(tmp), "TEMP": str(tmp),
                "SP79_SUITE": args.suite, "PYTHONDONTWRITEBYTECODE": "1"})
    receipt = {"schema_version": 1, "phase": args.suite,
               "created_at": datetime.now(timezone.utc).isoformat(),
               "wrapper_argv": [sys.executable, *sys.argv], "wrapper_cwd": str(Path.cwd()),
               "staging_base": BASE, "wrapper_runtime": {"executable": sys.executable, "version": sys.version},
               "wrapper_exit": 1, "status": "FAIL", "output": str(out)}
    try:
        manifest = json.loads(MANIFEST.read_text())
        receipt["source_manifest_sha256"] = sha(MANIFEST)
        if manifest["head"] != BASE:
            raise RuntimeError("Staging manifest base mismatch")
        head = checked(["git", "rev-parse", "HEAD"], env)
        checked(["git", "merge-base", "--is-ancestor", BASE, head], env)
        receipt["actual_head"] = head
        receipt["git_status"] = checked(["git", "status", "--porcelain"], env)
        receipt["source_hashes"] = {PRODUCT: sha(REPO / PRODUCT)}
        receipt["test_fixture_hashes"] = {name: sha(REPO / name) for name in [NEW_TEST, FIXTURE]}
        receipt["helper_sha256"] = sha(Path(__file__))
        for name in [*REGRESSION, "scripts/check_repository.py", "package.json", "pnpm-lock.yaml"]:
            baseline = subprocess.run(["git", "show", f"{BASE}:{name}"], cwd=REPO, env=env, capture_output=True, check=False)
            if baseline.returncode != 0 or baseline.stdout != (REPO / name).read_bytes():
                raise RuntimeError(f"Required original file changed or unavailable: {name}")
        if args.suite == "baseline":
            if head != BASE or receipt["source_hashes"][PRODUCT] != ORIGINAL_PRODUCT_HASH:
                raise RuntimeError("Baseline requires exact unchanged pinned product and base HEAD")
        else:
            baselines = []
            for path in (WRITE_ROOT / "out" / "author-baseline").glob("*/receipt.json"):
                old = json.loads(path.read_text())
                if old.get("status") == "BASELINE_DEFECT_REPRODUCED" and old.get("wrapper_exit") == 0:
                    baselines.append((path, old))
            if not baselines:
                raise RuntimeError("Missing honest historical baseline receipt")
            for path, old in baselines:
                if (old["test_fixture_hashes"] != receipt["test_fixture_hashes"] or
                        old["source_hashes"][PRODUCT] != ORIGINAL_PRODUCT_HASH or
                        old["actual_head"] != BASE):
                    raise RuntimeError("Test/fixture freeze or baseline source identity mismatch")
            receipt["historical_baselines"] = [{"path": str(p), "sha256": sha(p)} for p, _ in baselines]
        if args.suite == "repository":
            scanner = REPO / "scripts/check_repository.py"
            tree = ast.parse(scanner.read_text())
            imports = sorted({n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)} |
                             {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module is not None})
            if not set(imports) <= {"pathlib", "hashlib", "json", "re", "sys", "urllib.parse"}:
                raise RuntimeError("Repository scanner import closure changed")
            receipt["closure"] = {"scripts/check_repository.py": sha(scanner), "imports": imports,
                                  "side_effect_audit": "Local file/link scan only; no network or child process API"}
            interpreter = manifest["runtime"]["credential_scan_python3"]
            if not Path(interpreter).is_file() or not os.access(interpreter, os.X_OK):
                raise RuntimeError("Manifest-approved credential scanner unavailable")
            receipt["runtime"] = {"argv": [interpreter, "--version"], "resolved": str(Path(interpreter).resolve()),
                                  "version": checked([interpreter, "--version"], env)}
            argv = [interpreter, "scripts/check_repository.py"]
        else:
            entries = [NEW_TEST, *REGRESSION] if args.suite == "regression" else [NEW_TEST]
            receipt["closure_hashes"] = inspect_closure(entries)
            node = shutil.which("node")
            if not node:
                raise RuntimeError("Qualified installed node unavailable; no fallback")
            receipt["runtime"] = {"argv": [node, "--version"], "resolved": str(Path(node).resolve()),
                                  "version": checked([node, "--version"], env)}
            argv = [node, "--experimental-strip-types", "--test", "--experimental-test-isolation=none", "--test-reporter=tap"]
            if args.suite == "regression":
                argv.extend(["--import", "./" + NEW_TEST, *REGRESSION])
            else:
                argv.append(NEW_TEST)
        result = command(argv, env)
        receipt["child"] = {k: v for k, v in result.items() if k not in {"stdout", "stderr"}}
        for stream in ("stdout", "stderr"):
            path = out / ("child." + stream)
            path.write_text(result[stream])
            receipt[stream] = {"path": str(path), "sha256": sha(path)}
        text = result["stdout"]
        if args.suite == "repository":
            match = re.fullmatch(r"Checked (\d+) text files: .+ passed\.\n", text)
            if result["exit"] != 0 or not match or result["stderr"]:
                raise RuntimeError("Repository scan failed or required completion marker absent")
            receipt["cases"] = {"passed": 1, "failed": 0, "errors": 0, "skips": 0,
                                "text_files_checked": int(match.group(1))}
        else:
            counts, names = parse_tap(text)
            receipt["cases"] = {"passed": counts["pass"], "failed": counts["fail"],
                                "errors": counts["errors"], "skips": counts["skipped"], "total": counts["tests"]}
            receipt["case_names"] = names
            if any(counts[k] for k in ["cancelled", "skipped", "todo"]):
                raise RuntimeError("Unexpected cancellation, skip or TODO")
            if "SP79_OFFLINE_ATTEMPTS 0" not in text:
                raise RuntimeError("Offline sentinel completion absent")
            fixture = json.loads((REPO / FIXTURE).read_text())
            controls = [fixture["primary"]["name"], fixture["control"]["name"]]
            if args.suite == "baseline":
                failures = re.findall(r"^not ok \d+ - (.+)$", text, re.M)
                expected_data = 'SP79_PRIMARY_OBSERVED {"returned":{"id":"46053","backupFor":null}}'
                if not (result["exit"] == 1 and counts["tests"] == 2 and counts["pass"] == 1 and counts["fail"] == 1 and
                        names == controls and failures == [controls[0]] and expected_data in text and
                        "ERR_ASSERTION" in text and "failureType: 'testCodeFailure'" in text):
                    raise RuntimeError("Not the exact declared baseline semantic failure plus healthy pass")
                receipt["status"] = "BASELINE_DEFECT_REPRODUCED"
            else:
                expected_names = controls + [
                    "A1 no identity matrix never fabricates either caller fallback",
                    *[item["name"] for item in fixture["identified"]],
                    "A2 empty and every invalid explicit identity use valid data identity",
                    "A3 null missing and invalid backup declarations retain legacy fallback",
                    "A3 identifier grammar and trimming remain unchanged in every identity position",
                    "A3 station labels official URL strings and sharing of identified readings unchanged",
                ] if args.suite == "focused" else re.findall(r"^test\('([^']+)'", (REPO / REGRESSION[0]).read_text(), re.M)
                if not (result["exit"] == 0 and counts["fail"] == 0 and counts["tests"] == len(expected_names) and
                        counts["pass"] == len(expected_names) and names == expected_names):
                    raise RuntimeError("Required assertions missing or not all green")
                receipt["status"] = "GREEN_SCOPED_REVIEW_REQUIRED"
        if args.suite == "repository":
            receipt["status"] = "GREEN_SCOPED_REVIEW_REQUIRED"
        receipt["wrapper_exit"] = 0
    except Exception as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "wrapper_exit": receipt["wrapper_exit"],
                      "receipt": str(out / "receipt.json"), "cases": receipt.get("cases"), "error": receipt.get("error")}))
    return receipt["wrapper_exit"]


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
