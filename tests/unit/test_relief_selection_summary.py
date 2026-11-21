"""CLI contracts for the fixture-only relief selection diagnostic."""

import json
import subprocess
import sys

from tests._support import ROOT


SCRIPT = ROOT / "scripts/coast_diagnostics/relief_selection_summary.py"


def run_summary(path, *flags):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path), *flags],
        capture_output=True, text=True, timeout=10,
    )


def test_counts_and_redaction_in_both_formats(tmp_path):
    # Multiple reasons, duplicate rows, and both decisions for a source catch
    # grouping on the wrong dimension or dropping rows. Raw passthrough leaks
    # the path, exception, and area sentinels, even for an unknown decision.
    path = tmp_path / "path-sentinel-selection.json"
    known = {"source_id": "source-z", "decision": "skipped", "reason": "no_admissible_normalized_twin"}
    files = [
        known,
        {"source_id": "source-z", "decision": "included", "reason": "registry_public_display_allowed"},
        {"source_id": None, "decision": "skipped", "reason": "no_unambiguous_registry_binding"},
        {"source_id": "source-a", "decision": "skipped", "reason": "registry_public_display_not_allowed"},
        {"source_id": "source-z", "decision": "skipped", "reason": "exception-sentinel: /cache/raster.tif"},
        {"source_id": "source-z", "decision": "skipped", "reason": "external mask or auxiliary metadata requires normalization"},
        known,
        {"source_id": "/cache/source-sentinel", "decision": "decision-sentinel", "reason": ["exception-sentinel"]},
    ]
    doc = {
        "schema_version": 1, "scope": "public", "region": "fixture",
        "area_basis": "area-sentinel: overlaps not deduplicated",
        "files": [dict(row, path="/cache/path-sentinel.tif",
                       certified_area_m2_by_depth_band={"0-20m": 123456}) for row in files],
    }
    path.write_text(json.dumps(doc), encoding="utf-8")
    json_result = run_summary(path, "--json")
    text_result = run_summary(path)
    for result in (json_result, text_result):
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        assert "not surveys, coverage, or rights clearance" in result.stdout
        for forbidden in ("/cache/", "sentinel", "123456", "certified_area", "area_basis"):
            assert forbidden not in result.stdout

    summary = json.loads(json_result.stdout)
    assert summary["total_rows"] == sum(row["count"] for row in summary["counts"]) == len(files)
    expected = [
        ("source-a", "skipped", "registry_display_held", 1),
        ("source-z", "included", "registry_display_allowed", 1),
        ("source-z", "skipped", "normalization_needed", 3),
        ("source-z", "skipped", "other", 1),
        (None, "other", "other", 1),
        (None, "skipped", "registry_unbound", 1),
    ]
    assert summary["counts"] == [
        dict(source_id=source, decision=decision, reason_category=category, count=count)
        for source, decision, category, count in expected
    ]
    assert "Total file rows: 8" in text_result.stdout
    assert text_result.stdout.splitlines()[2:] == [
        "source_id\tdecision\treason_category\trows",
        *(f"{source or '(unbound)'}\t{decision}\t{category}\t{count}"
          for source, decision, category, count in expected),
    ]

    # A first-seen ordering would make pasteable reports differ after a reshuffle.
    doc["files"].reverse()
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert run_summary(path, "--json").stdout == json_result.stdout
    assert run_summary(path).stdout == text_result.stdout


def test_empty_files_is_a_zero_row_report(tmp_path):
    path = tmp_path / "selection.json"
    path.write_text('{"files": []}', encoding="utf-8")
    result = run_summary(path, "--json")
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["total_rows"] == 0
    assert summary["counts"] == []


def test_invalid_input_fails_without_echoing_details(tmp_path):
    # A missing file would expose its path if the CLI printed the OSError.
    # A wrong shape must not masquerade as a successfully counted empty file.
    path = tmp_path / "path-sentinel.json"
    for raw in (None, 'exception-sentinel', '{"files": ["exception-sentinel"]}'):
        if raw is not None:
            path.write_text(raw, encoding="utf-8")
        result = run_summary(path, "--json")
        assert result.returncode != 0
        assert result.stdout == ""
        assert "error:" in result.stderr
        assert "sentinel" not in result.stderr
        assert "Traceback" not in result.stderr
