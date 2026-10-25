#!/usr/bin/env python3
"""Offline SC143 acceptance runner. Each invocation owns a fresh output child."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import traceback
import unittest
import urllib.request

BASE = "8a805820c30895f5f037e26af9079fd3dc015b0f"
PRODUCT = "src/skippercast/coastal/retention.py"
EXPECTED_PRODUCT_SHA = "66c65a4d15d0793f35aff435af6d0894356ca569cce924f6a54995f27a9c646b"
EXPECTED_PRODUCT_BLOB = "8e3fa70af308cef75af83b2e6a903b360f96e584"
TEST_FILE = "tests/unit/test_sc143_retention_completion_bool.py"


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def deny(*args, **kwargs):
    raise RuntimeError("SC143 offline guard: prohibited network or child process")


def install_guards():
    socket.socket = deny
    socket.create_connection = deny
    socket.getaddrinfo = deny
    subprocess.Popen = deny
    subprocess.run = deny
    subprocess.call = deny
    subprocess.check_call = deny
    subprocess.check_output = deny
    os.system = deny
    urllib.request.urlopen = deny


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=("preflight", "regression", "compatibility", "negative-control"), required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    started = time.time()
    repo = Path(__file__).resolve().parents[1]
    manifest_path = Path(args.source_manifest).resolve(strict=True)
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    output_parent = Path(args.out)
    output_parent.mkdir(parents=True, exist_ok=True)
    run_dir = output_parent / ("run-" + args.suite + "-" + str(time.time_ns()) + "-" + str(os.getpid()))
    run_dir.mkdir(exist_ok=False)
    stdout_path, stderr_path = run_dir / "stdout.txt", run_dir / "stderr.txt"
    captured_out, captured_err = [], []
    exit_code = 1
    result_details = {}
    try:
        sys.dont_write_bytecode = True
        if (manifest.get("schema") != "agentorange.source-manifest/v1"
                or manifest.get("card") != "skippercast-sc143-retention-completion-bool"
                or Path(manifest.get("repo", "")).resolve() != repo
                or manifest.get("head") != BASE or manifest.get("clean") is not True):
            raise ValueError("manifest schema/card/repo/base/clean identity mismatch")
        if Path(sys.executable).absolute() != (repo / ".venv/bin/python3").absolute():
            raise ValueError("acceptance interpreter is not the staged repo venv")
        if Path(manifest["runtime"]["repo_venv"]).resolve() != (repo / ".venv").resolve():
            raise ValueError("manifest repo_venv does not resolve to staged .venv")
        expected_scan_python = str(Path.home() / "agent-work/tools/venv-fullsuite/bin/python3")
        if manifest["runtime"]["credential_scan_python3"] != expected_scan_python:
            raise ValueError("credential scan interpreter mismatch")
        product = repo / PRODUCT
        import subprocess as sp
        baseline_blob = sp.run(["git", "rev-parse", BASE + ":" + PRODUCT], cwd=repo, check=True,
                               stdout=sp.PIPE, stderr=sp.PIPE, text=True).stdout.strip()
        baseline_source = sp.run(["git", "show", BASE + ":" + PRODUCT], cwd=repo, check=True,
                                 stdout=sp.PIPE, stderr=sp.PIPE)
        baseline_hash = sha_bytes(baseline_source.stdout)
        head = sp.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                      stdout=sp.PIPE, stderr=sp.PIPE, text=True).stdout.strip()
        ancestry = sp.run(["git", "merge-base", "--is-ancestor", BASE, "HEAD"], cwd=repo,
                          stdout=sp.PIPE, stderr=sp.PIPE)
        if baseline_hash != EXPECTED_PRODUCT_SHA or baseline_blob != EXPECTED_PRODUCT_BLOB:
            raise ValueError("pinned baseline product source SHA/blob mismatch")
        if ancestry.returncode != 0:
            raise ValueError("candidate HEAD is not a descendant of the admitted base")
        candidate_source_sha = sha_bytes(product.read_bytes())
        result_details["candidate_head"] = head
        result_details["candidate_product_sha256"] = candidate_source_sha
        result_details["source_closure"] = {
            "product": PRODUCT, "baseline_sha256": baseline_hash, "baseline_git_blob": EXPECTED_PRODUCT_BLOB,
            "candidate_sha256": candidate_source_sha, "synthetic_root": str(run_dir / "synthetic"),
            "imports": ["skippercast", "skippercast.coastal", "skippercast.coastal.handoff", "skippercast.coastal.handoff.common", "skippercast.coastal.retention"],
            "reads": ["pinned Python source files only"], "external_data": False
        }
        os.environ["SC143_RUN_ROOT"] = str(run_dir / "synthetic")
        (run_dir / "synthetic").mkdir()
        sys.path.insert(0, str(repo / "src"))
        install_guards()
        selected = ["skippercast", "skippercast.coastal", "skippercast.coastal.handoff",
                    "skippercast.coastal.handoff.common", "skippercast.coastal.retention"]
        imported = {}
        for name in selected:
            imported[name] = importlib.import_module(name)
            origin = Path(imported[name].__file__).resolve()
            if not origin.is_relative_to((repo / "src").resolve()):
                raise ValueError("selected import escaped candidate source: " + name)
        spec = importlib.util.spec_from_file_location("sc143_test_module", repo / TEST_FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        selected.append("sc143_test_module")
        result_details["source_closure"] = {
            "imports": {name: {"origin": str(Path(imported[name].__file__).resolve()),
                               "sha256": sha_bytes(Path(imported[name].__file__).read_bytes())}
                        for name in imported},
            "test_file": {"origin": str((repo / TEST_FILE).resolve()),
                          "sha256": sha_bytes((repo / TEST_FILE).read_bytes())},
            "runner_sha256": sha_bytes(Path(__file__).read_bytes()),
            "fixture_tree": {str(path.relative_to(repo)): sha_bytes(path.read_bytes())
                             for path in sorted((repo / "tests/fixtures/sc143-retention-completion-bool").rglob("*"))
                             if path.is_file()} if (repo / "tests/fixtures/sc143-retention-completion-bool").exists() else {},
            "synthetic_root": str(run_dir / "synthetic"), "external_data": False
        }
        if args.suite == "preflight":
            if manifest.get("inputs") != []:
                raise ValueError("preflight expects empty inputs")
            exit_code = 0
        else:
            names = {
                "regression": ["test_boolean_outcomes_persist_and_reservation_is_immutable", "test_nonbooleans_fail_before_side_effects_for_both_states"],
                "compatibility": ["test_boolean_outcomes_persist_and_reservation_is_immutable"],
                "negative-control": ["test_negative_control_detects_truthiness_regression"]
            }[args.suite]
            suite = unittest.TestSuite(module.RetentionCompletionBooleanTests(name) for name in names)
            with (run_dir / "test-log.txt").open("w") as test_stream:
                runner = unittest.TextTestRunner(verbosity=2, stream=test_stream)
                result = runner.run(suite)
            test_log = (run_dir / "test-log.txt").read_bytes()
            result_details.update(tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped), test_ids=names,
                                  test_log={"path": "test-log.txt", "sha256": sha_bytes(test_log)})
            if args.suite == "negative-control":
                result_details["negative_control"] = dict(module.RetentionCompletionBooleanTests.negative_control_result)
                if not (result_details["negative_control"].get("mutant_detected") is True
                        and result_details["negative_control"].get("positive_passed") is True
                        and result_details["negative_control"].get("expected_red_assertion")):
                    exit_code = 1
            negative_ok = args.suite != "negative-control" or (
                result_details.get("negative_control", {}).get("mutant_detected") is True
                and result_details.get("negative_control", {}).get("positive_passed") is True
                and bool(result_details.get("negative_control", {}).get("expected_red_assertion")))
            exit_code = 0 if result.wasSuccessful() and result.testsRun == len(names) and not result.skipped and negative_ok else 1
        captured_out.append("suite=" + args.suite + " tests=" + str(result_details.get("tests_run", 0)) + " exit=" + str(exit_code))
    except BaseException:
        captured_err.append(traceback.format_exc())
        exit_code = 1
    stdout_bytes = ("SC143 suite=" + args.suite + " tests=" + str(result_details.get("tests_run", 0)) + " exit=" + str(exit_code) + "\n").encode()
    stderr_bytes = ("\n".join(captured_err) + ("\n" if captured_err else "")).encode()
    stdout_path.write_bytes(stdout_bytes)
    stderr_path.write_bytes(stderr_bytes)
    receipt = {
        "suite": args.suite, "argv": sys.argv, "cwd": str(Path.cwd()), "exit": exit_code,
        "duration_seconds": round(time.time() - started, 6), "manifest_sha256": sha_bytes(manifest_bytes),
        "stdout": {"path": stdout_path.name, "sha256": sha_bytes(stdout_bytes)},
        "stderr": {"path": stderr_path.name, "sha256": sha_bytes(stderr_bytes)},
        "details": result_details
    }
    (run_dir / "receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(stdout_bytes.decode(), end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
