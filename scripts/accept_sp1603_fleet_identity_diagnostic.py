"""Offline SP-16-v1 acceptance; green means REVIEW REQUIRED/PARITY_UNRESOLVED.

Each invocation retains a new evidence directory. Child argv never uses a shell
or inline interpreter source. All acceptance decisions use explicit checks.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/sp1603_fleet_identity_diagnostic"
PINS = json.loads((FIXTURE / "pins.json").read_text())
BASE = PINS["base"]
OWNED = ["tests/test_sp1603_fleet_identity_diagnostic.mjs", "scripts/accept_sp1603_fleet_identity_diagnostic.py",
         "docs/engineering/sp1603_fleet_identity_diagnostic.md"]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def git(*args):
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True)
    return result.stdout.decode().strip()


def sources():
    paths = set(PINS["sources"]) | set(OWNED)
    paths.update(str(p.relative_to(ROOT)) for p in FIXTURE.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    return {p: sha((ROOT / p).read_bytes()) for p in sorted(paths) if (ROOT / p).is_file()}


def stage():
    manifest_path = ROOT.parent / "SOURCE-MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    require(manifest.get("schema") == "agentorange.source-manifest/v1", "invalid stage schema")
    require(manifest.get("card") == PINS["id"], "wrong stage card")
    require(Path(manifest.get("repo", "")).resolve() == ROOT, "wrong stage repository")
    require(manifest.get("head") == BASE, "wrong staged base")
    require(Path(manifest.get("remote", "")).name == "skippercast", "wrong stage repository identity")
    require(git("rev-parse", f"{BASE}^{{tree}}") == manifest.get("tree"), "wrong staged tree")
    require(git("merge-base", BASE, "HEAD") == BASE, "candidate does not descend from base")
    changed = git("diff", "--name-only", BASE).splitlines() + git("ls-files", "--others", "--exclude-standard").splitlines()
    for name in changed:
        require(name in OWNED or name.startswith("tests/fixtures/sp1603_fleet_identity_diagnostic/"), f"out-of-scope change:{name}")
    for name, expected in PINS["sources"].items():
        require(sha((ROOT / name).read_bytes()) == expected, f"SOURCE_HASH_MISMATCH:{name}")
    require(sha((FIXTURE / "corpus.json").read_bytes()) == PINS["corpus_sha256"], "committed corpus hash mismatch")
    runtime = manifest.get("runtime", {})
    require(Path(runtime.get("credential_scan_python3", "")).is_file(), "missing credential_scan_python3")
    require((ROOT / ".venv/bin/python3").is_file(), "missing staged Python")
    require((ROOT / "node_modules").is_dir(), "missing staged node_modules")
    return manifest, sha(manifest_path.read_bytes())


def counts(stdout, stderr, kind):
    text = stdout + "\n" + stderr
    if kind == "node-tests":
        fields = {}
        for key in ("tests", "pass", "fail", "cancelled", "skipped", "todo"):
            matches = re.findall(rf"^# {key} (\d+)\s*$", text, re.M)
            require(len(matches) == 1, f"missing/ambiguous TAP {key}")
            fields[key] = int(matches[0])
        require(fields["tests"] > 0 and fields["tests"] == fields["pass"] and not any(fields[k] for k in ("fail", "cancelled", "skipped", "todo")), "not every Node test passed")
        return fields
    if kind == "python-tests":
        match = re.search(r"Ran (\d+) tests? in", text)
        if match is None:
            raise RuntimeError("missing unittest summary")
        require(int(match[1]) > 0 and re.search(r"^OK\s*$", text, re.M), "failed unittest summary or skips")
        return {"tests": int(match[1]), "passed": int(match[1]), "skipped": 0}
    if kind == "repository":
        match = re.search(r"Checked (\d+) text files:", text)
        require(match is not None and int(match[1]) > 0, "missing repository scan count")
        return {"files_checked": int(match[1]), "checks": 1}
    return {"checks": 1, "tests": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=["baseline", "focused", "regression", "repository", "typecheck", "build"])
    parser.add_argument("--output", required=True, type=Path)
    # Synthetic negative controls use the SAME wrapper and failure disposition.
    parser.add_argument("--fixture", type=Path, default=FIXTURE / "corpus.json")
    parser.add_argument("--python", type=Path, default=ROOT / ".venv/bin/python3")
    args = parser.parse_args()
    output = args.output.absolute()
    for ancestor in [output, *output.parents]:
        require(not ancestor.is_symlink(), "evidence ancestry must not contain symlinks")
    require(not output.resolve().is_relative_to(ROOT), "evidence must stay outside the repository")
    output = output / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex)
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": "skippercast.sp1603-acceptance/v1", "spec_version": PINS["spec_version"], "id": PINS["id"],
               "suite": args.suite, "output": str(output), "wrapper_argv": [sys.executable, *sys.argv], "cwd": str(Path.cwd()),
               "wrapper_runtime": {"executable": sys.executable, "version": platform.python_version()}, "children": [],
               "status": "UNEXPECTED_ERROR", "exit": 1}
    env = dict(os.environ)
    env.update({"TMPDIR": str(output), "SP1603_OUTPUT": str(output), "SKIPPERCAST_ROOT": str(ROOT),
                "SKIPPERCAST_FLEET_VAR": str(output / "synthetic-fleet"), "PYTHONDONTWRITEBYTECODE": "1"})
    env.pop("SKIPPERCAST_NETWORK", None)

    def run(label, argv, kind="check", expected=0):
        start = datetime.now(timezone.utc).isoformat()
        clock = time.monotonic()
        result = subprocess.run([str(x) for x in argv], cwd=ROOT, env=env, capture_output=True, timeout=600, check=False)
        stdout, stderr = result.stdout, result.stderr
        (output / f"{label}.stdout").write_bytes(stdout)
        (output / f"{label}.stderr").write_bytes(stderr)
        child = {"argv": [str(x) for x in argv], "cwd": str(ROOT), "started_at": start, "duration_seconds": time.monotonic() - clock,
                 "exit": result.returncode, "expected_exit": expected, "stdout": f"{label}.stdout", "stderr": f"{label}.stderr",
                 "stdout_sha256": sha(stdout), "stderr_sha256": sha(stderr)}
        save(output / f"{label}.receipt.json", child)
        receipt["children"].append(child)
        require(result.returncode == expected, f"{label} exited {result.returncode}, expected {expected}")
        if kind != "strict":
            child["counts"] = counts(stdout.decode(), stderr.decode(), kind)
            save(output / f"{label}.receipt.json", child)
        return child

    try:
        require(Path.cwd().resolve() == ROOT, "acceptance cwd must be staged repository")
        # Input negatives do not depend on a box-specific stage receipt and can
        # run in ordinary test discovery. Healthy acceptance still needs stage().
        require(sha(args.fixture.read_bytes()) == PINS["corpus_sha256"], "FIXTURE_HASH_MISMATCH")
        require(args.python.is_file(), "PYTHON_RUNTIME_MISSING")
        manifest, manifest_sha = stage()
        receipt.update({"head": git("rev-parse", "HEAD"), "base": BASE, "git_status": git("status", "--porcelain"),
                        "stage_manifest_sha256": manifest_sha, "sources_before": sources()})
        node = shutil.which("node")
        require(node is not None, "missing installed Node")
        python = ROOT / ".venv/bin/python3"
        pnpm = manifest["runtime"].get("pnpm")
        run("node-runtime", [node, "--version"])
        run("python-runtime", [python, "--version"])
        if args.suite in ("baseline", "focused"):
            strict = run("strict", [node, FIXTURE / "diagnostic.mjs", "--output", output / "strict-producers",
                                     "--fixture", args.fixture.absolute(), "--python", args.python.absolute()], "strict", 1)
            report = json.loads((output / "strict-producers/diagnostic.json").read_text())
            require(report.get("status") == "PARITY_UNRESOLVED" and report.get("strict_exit") == 1, "strict diagnostic wrong disposition")
            require(report.get("mismatch_ids") == ["exponent_parity", "astral_key_parity"], "strict diagnostic mismatch IDs changed")
            require(report.get("counts") == {"root_tests": 2, "passed": 0, "failed": 2, "controls": 13, "cases": 17, "skipped": 0}, "strict diagnostic count mismatch")
            strict["counts"] = report["counts"]
            save(output / "strict.receipt.json", strict)
            run("characterization", [node, "--test", ROOT / "tests/test_sp1603_fleet_identity_diagnostic.mjs"], "node-tests")
            receipt["diagnostic_status"] = "PARITY_UNRESOLVED"
        elif args.suite == "regression":
            run("fleet-jobs", [node, "--import", FIXTURE / "offline.mjs", "--test", ROOT / "tests/test_fleet_jobs.mjs"], "node-tests")
            run("sqlite-sink", [python, FIXTURE / "python_entry.py", "unittest", "--output", output / "synthetic-unittest"], "python-tests")
        elif args.suite == "repository":
            run("repository", [manifest["runtime"]["credential_scan_python3"], ROOT / "scripts/check_repository.py"], "repository")
        elif args.suite == "typecheck":
            require(pnpm and Path(pnpm).is_file(), "missing staged pnpm")
            for i, config in enumerate(("tsconfig.json", "web/tsconfig.json", "packages/coast/tsconfig.json")):
                run(f"typecheck-{i + 1}", [pnpm, "exec", "tsc", "--noEmit", "-p", config])
        elif args.suite == "build":
            require(pnpm and Path(pnpm).is_file(), "missing staged pnpm")
            run("build", [pnpm, "build"])
        receipt["sources_after"] = sources()
        require(receipt["sources_before"] == receipt["sources_after"], "source/test/fixture bytes changed during acceptance")
        receipt["final_head"] = git("rev-parse", "HEAD")
        require(receipt["head"] == receipt["final_head"], "head changed during acceptance")
        receipt.update(status="REVIEW_REQUIRED", exit=0)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        receipt["error"] = str(error)
    # All synchronous evidence writers have completed before hashing the inventory.
    receipt["evidence_hashes"] = {str(p.relative_to(output)): sha(p.read_bytes()) for p in sorted(output.rglob("*")) if p.is_file()}
    save(output / "acceptance.json", receipt)
    print(json.dumps({k: receipt[k] for k in ("status", "exit", "output", "suite") } | {"error": receipt.get("error"), "head": receipt.get("head")}))
    return receipt["exit"]


if __name__ == "__main__":
    raise SystemExit(main())
