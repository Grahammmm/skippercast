#!/usr/bin/env python3
"""Portable, per-run acceptance recorder for SP-10-v1 / SP107."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

SPEC = "SP-10-v1"
ITEM = "SP107-WATCH-DECODE"
BASE = "2979d59bfbb7d724eb83b34a48102b914ee8eaa3"
PRIMARY = "src/skippercast/fleet/ais/watch.py"
TEST = "tests/unit/test_sp107_watch_decode.py"
FIXTURE_DIR = "tests/fixtures/sp107_watch_decode"
BASELINE_TESTS = [
    "tests/unit/test_sp107_watch_decode.py::RegressionTests::test_primary_regression",
    "tests/unit/test_sp107_watch_decode.py::RegressionTests::test_healthy_control",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reject_symlink_ancestry(path: Path, stop: Path) -> None:
    path = path.absolute()
    stop = stop.absolute()
    current = path
    while current == stop or stop in current.parents:
        if current.is_symlink():
            raise RuntimeError(f"symlink refused in output ancestry: {current}")
        if current == stop:
            return
        current = current.parent
    raise RuntimeError(f"path is outside candidate root: {path}")


def run_child(argv, cwd: Path, env, raw_dir: Path):
    result = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True)
    stdout_path = raw_dir / "stdout.txt"
    stderr_path = raw_dir / "stderr.txt"
    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    return {
        "argv": argv,
        "cwd": str(cwd),
        "exit": result.returncode,
        "stdout_path": str(stdout_path),
        "stdout_sha256": sha256(stdout_path),
        "stderr_path": str(stderr_path),
        "stderr_sha256": sha256(stderr_path),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def test_counts(output: str):
    import re
    return {name: int(match.group(1)) if (match := re.search(rf"(\d+) {name}", output)) else 0
            for name in ("passed", "failed", "skipped", "error")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=("baseline", "focused", "regression", "repository"), required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--child-suite", choices=("baseline", "focused", "regression"), help=argparse.SUPPRESS)
    args = parser.parse_args()

    script = Path(__file__).resolve()
    repo = script.parents[1]
    candidate = repo.parent
    if args.child_suite:
        import tempfile
        sys.path.insert(0, str(repo / "src"))
        sys.path.insert(0, str(repo))
        tempfile.tempdir = os.environ.get("TMPDIR")
        import socket
        import urllib.request
        def denied(*_args, **_kwargs):
            raise RuntimeError("offline acceptance network tripwire")
        socket.create_connection = denied
        socket.socket.connect = denied
        urllib.request.urlopen = denied
        from skippercast.fleet.ais import watch as imported_watch
        if not Path(imported_watch.__file__).resolve().is_relative_to(repo.resolve()):
            raise RuntimeError(f"watch module escaped staged repo: {imported_watch.__file__}")
        import pytest
        selectors = {
            "baseline": BASELINE_TESTS,
            "focused": [TEST],
            "regression": ["tests/unit/test_fleet_listener.py::WatchTest"],
        }[args.child_suite]
        raise SystemExit(pytest.main(["-v", *selectors]))

    manifest_path = candidate / "SOURCE-MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "agentorange.source-manifest/v1":
        raise RuntimeError("unexpected source-manifest schema")
    if manifest.get("write_root") != str(candidate) or manifest.get("repo") != str(repo):
        raise RuntimeError("source-manifest root/repo mismatch")
    if manifest.get("head") != BASE:
        raise RuntimeError("source-manifest head differs from pinned base")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()
    subprocess.run(["git", "merge-base", "--is-ancestor", BASE, "HEAD"], cwd=repo, check=True)

    output_root = Path(args.output).absolute()
    reject_symlink_ancestry(output_root.parent, candidate)
    if not (output_root == candidate or candidate in output_root.parents):
        raise RuntimeError("output must be below candidate root")
    output_root.mkdir(parents=True, exist_ok=True)
    reject_symlink_ancestry(output_root, candidate)
    run_dir = output_root / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex}"
    run_dir.mkdir()
    raw_dir = run_dir / "raw"
    raw_dir.mkdir()
    temp_root = run_dir / "tmp"
    temp_root.mkdir()

    python = repo / ".venv" / "bin" / "python3"
    if not python.is_file():
        raise RuntimeError(f"staged repo interpreter missing: {python}")
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["TMPDIR"] = str(temp_root)
    env["TMP"] = str(temp_root)
    env["TEMP"] = str(temp_root)
    env["SKIPPERCAST_ROOT"] = str(repo)
    env["SKIPPERCAST_VAR"] = str(run_dir / "var")
    env["SKIPPERCAST_CACHE"] = str(run_dir / "cache")

    if args.suite == "baseline":
        argv = [str(python), str(script), "--suite", args.suite, "--output", str(output_root), "--child-suite", "baseline"]
    elif args.suite == "focused":
        argv = [str(python), str(script), "--suite", args.suite, "--output", str(output_root), "--child-suite", "focused"]
    elif args.suite == "regression":
        argv = [str(python), str(script), "--suite", args.suite, "--output", str(output_root), "--child-suite", "regression"]
    else:
        scanner = Path(manifest["runtime"]["credential_scan_python3"])
        if not scanner.is_file():
            raise RuntimeError(f"manifest credential scanner interpreter missing: {scanner}")
        version = subprocess.run([str(scanner), "--version"], cwd=repo, text=True, capture_output=True)
        (raw_dir / "scanner-version.txt").write_text(version.stdout + version.stderr, encoding="utf-8")
        argv = [str(scanner), "scripts/check_repository.py"]

    record = run_child(argv, repo, env, raw_dir)
    if args.suite == "baseline":
        counts = test_counts(record["stdout"])
        accepted = (record["exit"] == 1 and counts == {"passed": 1, "failed": 1, "skipped": 0, "error": 0}
                    and "test_primary_regression" in record["stdout"]
                    and "test_healthy_control" in record["stdout"])
        phase = "BASELINE_DEFECT_REPRODUCED" if accepted else "BASELINE_CONTRACT_FAILURE"
    else:
        counts = test_counts(record["stdout"])
        if args.suite in ("focused", "regression"):
            accepted = (record["exit"] == 0 and counts["passed"] > 0 and counts["failed"] == 0
                        and counts["skipped"] == 0 and counts["error"] == 0)
        else:
            accepted = record["exit"] == 0
        phase = "PASS" if accepted else "FAIL"

    paths = [repo / PRIMARY, repo / TEST, repo / "scripts/accept_sp107_watch_decode.py",
             repo / "docs/engineering/sp107_watch_decode.md", *sorted((repo / FIXTURE_DIR).rglob("*"))]
    hashes = {str(path.relative_to(repo)): sha256(path) for path in paths if path.is_file()}
    receipt = {
        "specification": SPEC,
        "item": ITEM,
        "suite": args.suite,
        "phase": phase,
        "base": BASE,
        "head": head,
        "source_manifest": str(manifest_path),
        "source_manifest_sha256": sha256(manifest_path),
        "source_test_fixture_sha256": hashes,
        "author": {"model": "gpt-6-luna", "provider": "openai-codex", "profile": "luna-worker", "effort": "medium"},
        "runtime": {"python": str(python if args.suite != "repository" else scanner)},
        "child": {key: value for key, value in record.items() if key not in ("stdout", "stderr")},
        "counts": counts,
        "accepted_by_runner": accepted,
        "raw": {"stdout_path": record["stdout_path"], "stderr_path": record["stderr_path"]},
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    receipt_path = run_dir / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"phase": phase, "accepted_by_runner": accepted, "receipt": str(receipt_path),
                      "child_exit": record["exit"], "counts": counts}, sort_keys=True))
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
