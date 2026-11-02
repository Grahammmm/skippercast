"""RF0450-3: a damaged seafloor ledger is one named ValueError / one stderr line, never a traceback."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "seafloor_status.py"
_spec = importlib.util.spec_from_file_location("seafloor_status_rf0450_3", SCRIPT)
status = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(status)

EXPECTED = "\n".join([
    "# Committed seafloor status", "",
    "Ledger input hash: `hash-1`", "",
    "| Region | Reaches | Valid survey reaches | Screen-ready with habitat | Other states | Tier 1 km² | Tier 2 km² | Live publication |",
    "| --- | ---: | ---: | ---: | --- | ---: | ---: | --- |",
    "| alpha | 2 | 1 | 1 | habitat-screened: 1, unknown: 1 | 2.500000 | 1.000000 | Not verified by this report |",
    "| beta | 1 | 1 | 0 | surveyed: 1 | 1.250000 | 0.750000 | Not verified by this report |",
    "", "Total reaches: 3.", "",
    "Tier areas are ledger measurements, not catch probability. A screened status",
    "with zero selected survey area is not useful measured coverage. Screen-ready",
    "counts describe saved screens, not current season/gear clearance. Publication",
    "requires current manifest/hash and live HTTP/range receipts; this offline report",
    "does not contact storage or infer publication from processing state.", ""])


def ledger():
    return {"input_hash": "hash-1", "reaches": [
        {"id": "b1", "region": "beta", "status": "surveyed", "tier1_km2": 1.25, "tier2_km2": 0.75,
         "selected_valid_km2": 1, "screen": {"status": "draft"}},
        {"id": "a1", "region": "alpha", "status": "habitat-screened", "tier1_km2": 2, "tier2_km2": 1,
         "selected_valid_km2": 2, "screen": {"status": "ready"}},
        {"id": "a2", "region": "alpha", "tier1_km2": 0.5, "tier2_km2": 0, "selected_valid_km2": 0}]}


def damaged(change):
    data = ledger()
    change(data)
    return data


def test_good_two_region_ledger_renders_pinned_markdown():
    assert status.render(ledger()) == EXPECTED


@pytest.mark.parametrize("data, message", [
    ([], "Ledger is not an object"),
    ("ledger", "Ledger is not an object"),
    (damaged(lambda d: d.pop("input_hash")), "Ledger input_hash missing or not text"),
    (damaged(lambda d: d.update(input_hash=5)), "Ledger input_hash missing or not text"),
    (damaged(lambda d: d.update(input_hash="")), "Ledger input_hash missing or not text"),
    (damaged(lambda d: d.pop("reaches")), "Missing reach coverage"),
    (damaged(lambda d: d["reaches"].__setitem__(1, "x")), "Reach 1 is not an object"),
    (damaged(lambda d: d["reaches"].__setitem__(2, ["a2"])), "Reach 2 is not an object"),
    (damaged(lambda d: d["reaches"][0].pop("region")), "Reach 0 missing region"),
    (damaged(lambda d: d["reaches"][0].pop("id")), "Reach 0 missing id"),
    (damaged(lambda d: d["reaches"][1].update(id=7)), "Reach 1 missing id"),
    (damaged(lambda d: d["reaches"][2].update(region="")), "Reach 2 missing region"),
    (damaged(lambda d: d["reaches"][0].update(screen=None)), "Reach 0 screen not an object"),
    (damaged(lambda d: d["reaches"][0].update(screen="ready")), "Reach 0 screen not an object"),
    (damaged(lambda d: d["reaches"][0].update(status=3)), "Reach 0 status not text"),
    (damaged(lambda d: d["reaches"][1].update(status=None)), "Reach 1 status not text"),
])
def test_damaged_ledger_is_named_value_error(data, message):
    with pytest.raises(ValueError) as caught:
        status.render(data)
    assert str(caught.value) == message


def test_existing_checks_keep_their_messages():
    dup = damaged(lambda d: d["reaches"][2].update(id="a1"))
    with pytest.raises(ValueError, match="^Duplicate reach$"):
        status.render(dup)
    bad = damaged(lambda d: d["reaches"][0].update(tier2_km2=-1))
    with pytest.raises(ValueError, match="^Missing or invalid measured coverage: tier2_km2$"):
        status.render(bad)


def run_cli(path):
    return subprocess.run([sys.executable, str(SCRIPT), "--ledger", str(path)],
                          capture_output=True, text=True, timeout=60)


def test_cli_missing_ledger_is_one_line_without_path(tmp_path):
    missing = tmp_path / "secret-dir" / "nope.json"
    done = run_cli(missing)
    assert done.returncode == 1
    assert done.stdout == ""
    assert done.stderr.startswith("seafloor_status: FileNotFoundError")
    assert done.stderr.count("\n") == 1
    assert "secret-dir" not in done.stderr and "nope.json" not in done.stderr
    assert "Traceback" not in done.stderr


@pytest.mark.parametrize("text, line", [
    ("{not json", None),
    ("[]", "seafloor_status: Ledger is not an object\n"),
    (json.dumps({"input_hash": "h", "reaches": [{"id": "x"}]}), "seafloor_status: Reach 0 missing region\n"),
])
def test_cli_bad_ledger_is_one_stderr_line(tmp_path, text, line):
    path = tmp_path / "ledger.json"
    path.write_text(text)
    done = run_cli(path)
    assert done.returncode == 1
    assert done.stdout == ""
    assert done.stderr.startswith("seafloor_status: ") and done.stderr.count("\n") == 1
    assert "Traceback" not in done.stderr
    if line is not None:
        assert done.stderr == line


def test_cli_good_ledger_prints_report(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(ledger()))
    done = run_cli(path)
    assert (done.returncode, done.stdout, done.stderr) == (0, EXPECTED, "")
