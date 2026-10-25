#!/usr/bin/env python3
"""Offline, bounded SC83 cached-asset-cap acceptance runner."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", required=True, choices=("regression", "compatibility", "negative-control"))
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    script = Path(__file__).resolve()
    repo = script.parents[1]
    manifest_path = Path(args.source_manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "agentorange.source-manifest/v1":
        raise SystemExit("invalid source manifest schema")
    if Path(manifest.get("write_root", "")).resolve() != repo.parent:
        raise SystemExit("manifest write_root does not match candidate root")
    if Path(manifest.get("repo", "")).resolve() != repo:
        raise SystemExit("manifest repo does not match runner repo")
    if manifest.get("head") != "a1f648632e64561d82dcbeb20d9bda19f812560a":
        raise SystemExit("unexpected admitted base")
    runtime = manifest.get("runtime", {})
    if Path(runtime.get("repo_venv", "")).resolve() != (repo / ".venv").resolve():
        raise SystemExit("manifest runtime does not match staged venv")
    scanner = Path(runtime.get("credential_scan_python3", ""))
    if not scanner.is_absolute() or scanner.parts[-4:] != ("tools", "venv-fullsuite", "bin", "python3"):
        raise SystemExit("manifest credential scanner runtime mismatch")

    run_id = f"{time.time_ns()}-{os.getpid()}"
    out = Path(args.out).resolve() / run_id
    out.mkdir(parents=True, exist_ok=False)
    import tempfile
    tempfile.tempdir = str(out)
    sys.dont_write_bytecode = True

    # Defense-in-depth boundary is installed before product imports.
    def denied(*_args, **_kwargs):
        raise RuntimeError("SC83 guard denied network or child process")
    socket.create_connection = denied
    socket.socket.connect = denied
    subprocess.Popen = denied
    subprocess.run = denied
    subprocess.call = denied

    fixture_root = repo / "tests" / "fixtures" / "sc83-cached-asset-cap"
    fixture_before = {str(path.relative_to(fixture_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in sorted(fixture_root.rglob("*")) if path.is_file()}
    allowed_probe = out / "guard-allowed-synthetic.txt"
    allowed_probe.write_text("inert synthetic write allowed", encoding="utf-8")
    allowed_synthetic_passed = allowed_probe.read_text(encoding="utf-8") == "inert synthetic write allowed"
    try:
        denied()
    except RuntimeError:
        denied_sentinel_event = True
    else:
        denied_sentinel_event = False

    sys.path.insert(0, str(repo / "src"))
    sys.path.insert(0, str(repo / "tests" / "unit"))
    from test_sc83_cached_asset_cap import CacheHitCapTests

    mutant_detected = None
    positive_control_passed = None
    if args.suite == "negative-control":
        from unittest.mock import patch
        control = CacheHitCapTests("test_oversized_cache_rejected_before_hash_or_session")
        control.setUp()
        original_stat = Path.stat
        try:
            def cap_bypass_stat(path, *stat_args, **stat_kwargs):
                result = original_stat(path, *stat_args, **stat_kwargs)
                if path == control.destination:
                    values = list(result)
                    values[6] = len(control.payload) - 1
                    return os.stat_result(values)
                return result
            with patch.object(Path, "stat", cap_bypass_stat):
                digest = __import__("hashlib").sha256(control.payload).hexdigest()
                try:
                    io = __import__("skippercast.seafloor.io", fromlist=["verified_file"])
                    io.verified_file(control.url, digest, control.destination, False,
                                     max_bytes=len(control.payload) - 1)
                except ValueError as error:
                    mutant_detected = "Source exceeds byte limit" not in str(error)
                else:
                    mutant_detected = True
        finally:
            control.tearDown()
        positive = CacheHitCapTests("test_matching_cache_exact_cap")
        positive.setUp()
        try:
            positive.test_matching_cache_exact_cap()
            positive_control_passed = True
        finally:
            positive.tearDown()

    selected = {
        "regression": ["test_matching_cache_below_cap", "test_matching_cache_exact_cap",
                       "test_oversized_cache_rejected_before_hash_or_session", "test_invalid_caps",
                       "test_cache_checksum_mismatch_unchanged", "test_missing_offline_refusal_unchanged",
                       "test_small_download_remains_accepted",
                       "test_download_oversize_failure_preserves_absent_destination",
                       "test_download_hash_failure_preserves_existing_destination"],
        "compatibility": ["test_cache_checksum_mismatch_unchanged", "test_missing_offline_refusal_unchanged",
                           "test_small_download_remains_accepted", "test_matching_cache_exact_cap",
                           "test_download_oversize_failure_preserves_absent_destination",
                           "test_download_hash_failure_preserves_existing_destination"],
        "negative-control": ["test_matching_cache_exact_cap", "test_oversized_cache_rejected_before_hash_or_session"],
    }[args.suite]
    suite = unittest.TestSuite(CacheHitCapTests(name) for name in selected)
    stdout_path, stderr_path = out / "stdout.txt", out / "stderr.txt"
    import contextlib
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = unittest.TextTestRunner(stream=stdout, verbosity=2).run(suite)
    test_output = stdout_path.read_bytes()
    fixture_after = {str(path.relative_to(fixture_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in sorted(fixture_root.rglob("*")) if path.is_file()}
    fixture_unchanged = fixture_before == fixture_after
    isolation_passed = (allowed_synthetic_passed and denied_sentinel_event and fixture_unchanged
                        and out.is_relative_to(Path(manifest["write_root"]).resolve()))
    receipt = {
        "suite": args.suite, "run_id": run_id, "argv": sys.argv,
        "cwd": str(Path.cwd()), "interpreter": sys.executable,
        "head": (repo / ".git" / "HEAD").read_text(encoding="utf-8").strip(),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "source_sha256": hashlib.sha256((repo / "src/skippercast/seafloor/io.py").read_bytes()).hexdigest(),
        "test_sha256": hashlib.sha256((repo / "tests/unit/test_sc83_cached_asset_cap.py").read_bytes()).hexdigest(),
        "fixture_hashes_before": fixture_before, "fixture_hashes_after": fixture_after,
        "fixture_unchanged": fixture_unchanged, "allowed_synthetic_passed": allowed_synthetic_passed,
        "denied_sentinel_event": denied_sentinel_event, "isolation_passed": isolation_passed,
        "fixture_root": str(fixture_root), "test_ids": selected, "tests_run": result.testsRun,
        "failures": len(result.failures), "errors": len(result.errors), "skips": len(result.skipped),
        "mutant_detected": mutant_detected, "positive_control_passed": positive_control_passed,
        "exit": 0 if result.wasSuccessful() and isolation_passed and (args.suite != "negative-control" or
                    (mutant_detected is True and positive_control_passed is True)) else 1,
        "stdout_sha256": hashlib.sha256(test_output).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr_path.read_bytes()).hexdigest(),
        "stdout": str(stdout_path), "stderr": str(stderr_path),
    }
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return receipt["exit"]


if __name__ == "__main__":
    raise SystemExit(main())
