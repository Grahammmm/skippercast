#!/usr/bin/env python3
"""Offline, card-scoped SC144 acceptance runner."""
import argparse
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest

sys.dont_write_bytecode = True


def forbidden(*args, **kwargs):
    raise RuntimeError("SC144 offline guard refused network or child process")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=("preflight", "regression", "compatibility", "negative-control"), required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    started = time.time()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    run_dir = out / ("run-" + str(time.time_ns()))
    run_dir.mkdir()
    root = Path(__file__).resolve().parents[1]
    manifest_path = Path(args.source_manifest)
    raw_manifest = manifest_path.read_bytes()
    manifest = json.loads(raw_manifest)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    if manifest.get("head") != "8a805820c30895f5f037e26af9079fd3dc015b0f":
        raise SystemExit("preflight manifest head is not the frozen pinned base")
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", manifest["head"], "HEAD"], cwd=root, check=False, capture_output=True, text=True)
    if ancestor.returncode != 0:
        raise SystemExit("preflight candidate HEAD is not descended from admitted base")
    report = {"suite": args.suite, "argv": sys.argv, "cwd": os.getcwd(), "run_dir": str(run_dir), "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(), "base": manifest["head"], "head": head, "started": started}
    if manifest.get("schema") != "agentorange.source-manifest/v1" or manifest.get("repo") != str(root) or manifest.get("card") != root.parent.name:
        raise SystemExit("preflight manifest identity mismatch")
    venv = root / ".venv"
    if not venv.exists() or not (venv / "bin/python3").exists() or str(venv.resolve()) != manifest.get("runtime", {}).get("repo_venv"):
        raise SystemExit("preflight admitted repo venv identity missing or mismatched")
    credential_python = manifest.get("runtime", {}).get("credential_scan_python3")
    expected_credential_python = "/home/user/agent-work/tools/venv-fullsuite/bin/python3"
    if credential_python != expected_credential_python or not Path(credential_python).is_file():
        raise SystemExit("preflight credential scan interpreter missing or mismatched")
    if args.suite == "preflight":
        status = subprocess.run(["git", "status", "--porcelain=v1"], cwd=root, check=True, capture_output=True, text=True).stdout
        if status:
            raise SystemExit("preflight candidate stage is not clean")
        socket.socket = forbidden
        socket.create_connection = forbidden
        subprocess.Popen = forbidden
        subprocess.run = forbidden
        subprocess.call = forbidden
        os.system = forbidden
        sys.path.insert(0, str(root / "src"))
        from skippercast.coastal.handoff import common
        report.update({"status": "PASS", "checks": ["manifest_schema", "repo_identity", "frozen_base", "repo_venv_present", "credential_scan_interpreter", "clean_stage", "guarded_import_closure"], "source_closure": ["read-only: runner, test module, common.py and Python runtime imports", "synthetic: unique run_dir/synthetic-root; no product data roots read"]})
        (run_dir / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
        print(json.dumps(report, sort_keys=True))
        return 0

    socket.socket = forbidden
    socket.create_connection = forbidden
    subprocess.Popen = forbidden
    subprocess.run = forbidden
    subprocess.call = forbidden
    os.system = forbidden
    os.environ["SC144_RUN_ROOT"] = str(run_dir)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.path.insert(0, str(root / "src"))
    from skippercast.coastal.handoff import common

    suite = unittest.defaultTestLoader.discover(str(root / "tests" / "unit"), pattern="test_sc144_handoff_reviewer_identity.py")
    if args.suite in ("compatibility", "negative-control"):
        sys.path.insert(0, str(root / "tests" / "unit"))
        test_module = __import__("test_sc144_handoff_reviewer_identity")
    if args.suite == "compatibility":
        suite = unittest.TestSuite([
            test_module.ReviewerIdentityTests("test_T01_valid_spelling_preserved_and_accepted"),
            test_module.ReviewerIdentityTests("test_T02_accepted_decisions_windows_and_added_hold"),
        ])
    elif args.suite == "negative-control":
        if not hasattr(common, "_valid_reviewer_identity"):
            raise SystemExit("negative control requires isolated identity predicate")
        original = common._valid_reviewer_identity
        common._valid_reviewer_identity = lambda value: bool(value) and not value.startswith("coastal.")
        test_module = __import__("test_sc144_handoff_reviewer_identity")
        mutant_suite = unittest.defaultTestLoader.loadTestsFromName("ReviewerIdentityTests.test_T03_invalid_identity_shapes_fail_closed_without_crash", test_module)
        mutant_stream = open(run_dir / "mutant.log", "w")
        mutant_result = unittest.TextTestRunner(stream=mutant_stream, verbosity=2).run(mutant_suite)
        mutant_stream.close()
        common._valid_reviewer_identity = original
        positive_suite = unittest.defaultTestLoader.loadTestsFromName("ReviewerIdentityTests.test_T07_valid_control", test_module)
        positive_stream = open(run_dir / "positive.log", "w")
        positive_result = unittest.TextTestRunner(stream=positive_stream, verbosity=2).run(positive_suite)
        positive_stream.close()
        report.update({"mutant_detected": not mutant_result.wasSuccessful(), "mutant_failure_count": len(mutant_result.failures) + len(mutant_result.errors), "positive_passed": positive_result.wasSuccessful()})
        if not report["mutant_detected"] or not report["positive_passed"]:
            return 1
        report.update({"status": "PASS", "tests_executed": 2})
        (run_dir / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
        print(json.dumps(report, sort_keys=True))
        return 0

    stream = open(run_dir / "unittest.log", "w")
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    stream.close()
    report.update({"status": "PASS" if result.wasSuccessful() else "FAIL", "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "skips": len(result.skipped)})
    (run_dir / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
