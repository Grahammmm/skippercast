"""runs.validate names every manifest shape report.render() would crash on; valid manifests render unchanged."""
from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess
import sys

import pytest

from skippercast import report, runs
from skippercast.platform.contracts import read_json
from tests._support import ROOT


def manifest(**fields):
    doc = {"schema_version": runs.SCHEMA_VERSION, "job": "refresh", "run_id": "1", "started_at": "2026-10-31T00:00:00Z",
           "status": "ok", "inputs": [], "outputs": [], "sources": {}}
    doc.update(fields)
    return doc


@pytest.mark.parametrize("fields, message", [
    ({"inputs": ["var/x.json"]}, "Run manifest inputs must be a list of file rows"),
    ({"inputs": "var/x.json"}, "Run manifest inputs must be a list of file rows"),
    ({"outputs": {}}, "Run manifest outputs must be a list of file rows"),
    ({"outputs": [{"path": "a"}, None]}, "Run manifest outputs must be a list of file rows"),
    ({"error": "boom"}, "Run manifest error must be an object or null"),
    ({"error": ["boom"]}, "Run manifest error must be an object or null"),
    ({"started_at": 1730000000}, "Run manifest started_at must be text"),
    ({"started_at": None}, "Run manifest started_at must be text"),
    ({"git_sha": 123}, "Run manifest git_sha must be text or null"),
    ({"exit_code": True}, "Run manifest exit_code must be a number or null"),
    ({"exit_code": "0"}, "Run manifest exit_code must be a number or null"),
    ({"duration_ms": False}, "Run manifest duration_ms must be a number or null"),
    ({"duration_ms": "1500"}, "Run manifest duration_ms must be a number or null"),
])
def test_bad_shape_is_refused_with_the_field_named_and_not_echoed(fields, message):
    with pytest.raises(ValueError) as caught:
        runs.validate(manifest(**fields))
    assert str(caught.value) == message
    with pytest.raises(ValueError):  # render validates first, so it never reaches the AttributeError
        report.render(manifest(**fields))


@pytest.mark.parametrize("fields", [
    {"error": None},
    {"error": {"class": "X", "message": "m"}, "status": "failed", "exit_code": 1},
    {"git_sha": None},
    {"git_sha": "a" * 40},
    {"duration_ms": 1.5, "exit_code": 0},
    {"duration_ms": None, "exit_code": None},
    {"inputs": [{"path": "a", "sha256": "0" * 64, "bytes": 2}], "outputs": [{}]},
])
def test_good_shapes_validate_and_render(fields):
    doc = manifest(**fields)
    assert runs.validate(doc) is doc
    assert report.render(doc).startswith("### refresh: ")


def test_git_sha_missing_is_valid():
    doc = manifest()
    assert "git_sha" not in doc
    assert runs.validate(doc) is doc


def test_old_manifest_without_regions_error_or_run_attempt_is_valid():
    doc = manifest(status="degraded", sources={"noaa": {"status": "stale"}})
    for key in ("regions", "error", "run_attempt"):
        assert key not in doc
    assert runs.validate(doc) is doc
    assert "| noaa | stale | – | – |" in report.render(doc)


def test_real_manifest_round_trips_through_validate_and_render(tmp_path):
    source = tmp_path / "in.json"
    source.write_bytes(b"{}")
    ticks = iter([0.0, 1.5])
    run = runs.RunManifest("refresh", "42", run_attempt=2, git_sha="a" * 40, clock=lambda: next(ticks),
                           wall_clock=lambda: datetime(2026, 10, 31, tzinfo=timezone.utc))
    run.add_input(source)
    run.source("noaa", "ok", duration_ms=1200, detail="fine")
    run.write(tmp_path / "run.json")
    doc = read_json(tmp_path / "run.json")
    assert doc == run.to_dict()
    assert runs.validate(doc) is doc
    sha = hashlib.sha256(b"{}").hexdigest()[:12]
    assert report.render(doc) == "\n".join([
        "### refresh: ✅ ok", "",
        "| Run | Commit | Started | Duration | Exit |", "| --- | --- | --- | --- | --- |",
        "| 42 (attempt 2) | aaaaaaaaaaaa | 2026-10-31T00:00:00Z | 1.5 s | 0 |", "",
        "| Source | Status | Duration | Detail |", "| --- | --- | --- | --- |",
        "| noaa | ✅ ok | 1.2 s | fine |", "", "Sources: 1 ok", "",
        "<details><summary>Inputs (1)</summary>", "", "| File | Bytes | sha256 |", "| --- | ---: | --- |",
        f"| in.json | 2 | `{sha}` |", "", "</details>",
    ]) + "\n"


def test_report_cli_names_the_bad_field_without_a_traceback(tmp_path):
    bad_inputs, bad_error, good = tmp_path / "inputs.json", tmp_path / "error.json", tmp_path / "good.json"
    bad_inputs.write_text(json.dumps(manifest(inputs=["var/x.json"])))
    bad_error.write_text(json.dumps(manifest(status="failed", error="boom-secret")))
    good.write_text(json.dumps(manifest()))
    env = dict(os.environ)  # import this checkout's src, not another installed skippercast
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(ROOT / "src"), env.get("PYTHONPATH")) if p)
    result = subprocess.run([sys.executable, "-m", "skippercast.report", str(bad_inputs), str(bad_error), str(good)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "ValueError: Run manifest inputs must be a list of file rows" in result.stderr
    assert "ValueError: Run manifest error must be an object or null" in result.stderr
    assert "var/x.json" not in result.stderr and "boom-secret" not in result.stderr
    assert result.stdout.startswith("### refresh: ✅ ok")
