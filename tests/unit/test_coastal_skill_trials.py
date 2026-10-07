"""Calibration receipts cannot conflate simulations with actual model trials."""

import json
import subprocess
import sys

from tests._support import ROOT

SCRIPT = ROOT / "skills/skippercast-build-coastal-map/scripts/model_trials.py"


def run_script(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)


def record(ledger, kind="actual", outcome="pass", *extra):
    return run_script("record", "--ledger", str(ledger), "--task", "receipt-check",
                      "--fingerprint", "fixture-a", "--model", "gpt-6-luna",
                      "--effort", "low", "--evidence", "review.json",
                      "--kind", kind, "--outcome", outcome, *extra)


def test_trial_receipts_separate_simulation_and_actual_failures(tmp_path):
    ledger = tmp_path / "trials.jsonl"
    assert record(ledger, "simulation").returncode == 0
    assert record(ledger, outcome="fail").returncode == 0
    assert record(ledger).returncode == 0
    report = json.loads(run_script("report", "--ledger", str(ledger)).stdout)
    assert report["minimumEstablished"] is False
    groups = {item["kind"]: item for item in report["groups"]}
    assert groups["simulation"]["pass"] == 1
    assert groups["actual"]["pass"] == 1
    assert groups["actual"]["fail"] == 1
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert all("tokens" not in row and "elapsed_seconds" not in row for row in rows)
    assert all(row["modelSetting"] == "requested; not independently observed" for row in rows)


def test_invalid_usage_does_not_append_a_trial(tmp_path):
    ledger = tmp_path / "trials.jsonl"
    assert record(ledger).returncode == 0
    original = ledger.read_bytes()
    assert record(ledger, "actual", "pass", "--tokens", "-1").returncode != 0
    assert ledger.read_bytes() == original


def test_malformed_or_unknown_trial_kind_fails_report(tmp_path):
    ledger = tmp_path / "trials.jsonl"
    assert record(ledger).returncode == 0
    row = json.loads(ledger.read_text())
    row["kind"] = "made-up"
    ledger.write_text(json.dumps(row) + "\n")
    assert run_script("report", "--ledger", str(ledger)).returncode != 0
    ledger.write_text("{invalid-json}\n")
    assert run_script("report", "--ledger", str(ledger)).returncode != 0
