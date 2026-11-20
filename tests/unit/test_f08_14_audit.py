"""F08-14: run and step reports preserve failures across partial reruns."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from skippercast.fleet import cli
from skippercast.fleet.adapters import RunContext
from skippercast.fleet.config import Binding
from skippercast.fleet.runs import Run


def read_report(run, name="report.json"):
    return json.loads((run.dir / name).read_text(encoding="utf-8"))


def test_different_step_cannot_clear_a_saved_failure(tmp_path, monkeypatch):
    # A refresh with any outcome must not hide the failure saved by discovery.
    var = tmp_path.resolve()
    run = Run("CA", var=var)
    ctx = RunContext(region=None, net=None, run_dir=run.dir, clock=cli.now)
    sink = SimpleNamespace(name="staging", apply=Mock())
    discover = Mock(side_effect=ValueError("synthetic discovery failure"))
    monkeypatch.setitem(cli.STEPS, "discover", discover)
    with pytest.raises(ValueError, match="synthetic discovery failure"):
        cli.execute(run, ctx, sink, ("discover",))
    failed = read_report(run)["steps"]["discover"]
    assert failed["status"] == "failed"

    resumed = Run("CA", run.id, var=var)
    for counts, status in (({}, "ok"), ({"gaps": 1}, cli.KNOWN_GAPS), ({"failed": 1}, "partial"), ({}, "ok")):
        monkeypatch.setitem(cli.STEPS, "refresh", lambda *_: counts)
        cli.execute(resumed, ctx, sink, ("refresh",))
        report = read_report(resumed)
        assert report["steps"]["refresh"]["status"] == status
        assert report["steps"]["discover"] == failed
        assert report["status"] == "failed"
    discover.assert_called_once()

    discover.side_effect = None
    discover.return_value = {"failed": 1}
    cli.execute(resumed, ctx, sink, ("discover",))
    assert read_report(resumed)["status"] == "failed"

    discover.return_value = {"candidates": 1}
    cli.execute(resumed, ctx, sink, ("discover",))
    report = read_report(resumed)
    assert report["status"] == report["steps"]["discover"]["status"] == "ok"
    assert "error" not in report["steps"]["discover"]


def test_enrich_code_counts_a_refused_import_and_clears_it_on_retry(tmp_path):
    # The actual importer refuses malformed CSV; its failure must reach the CLI's
    # persisted summary and run.record, not just the per-binding report.
    var = tmp_path.resolve()
    run = Run("CA", var=var)
    binding = Binding("synthetic-import", "file-import", True,
                      {"path": "inputs/fleet.csv", "columns": "cdfw-cpfv-v1",
                       "source_url": "https://fleet.example/records"}, "public-record")
    region = SimpleNamespace(sources=(binding,), enabled_sources=lambda: (binding,), binding=lambda _: binding)
    ctx = RunContext(region=region, net=None, run_dir=run.dir, clock=cli.now)
    sink = SimpleNamespace(name="staging", apply=Mock())
    path = var / "CA" / "inputs" / "fleet.csv"
    path.write_bytes(b'Vessel Name,FG Number\n"Broken Boat"junk,FG1\n')
    cli.execute(run, ctx, sink, ("enrich-code",))
    assert read_report(run, "enrich-code.json")["bindings"][binding.id]["status"] == "failed"
    report = read_report(run)
    assert report["status"] == report["steps"]["enrich-code"]["status"] == "partial"
    assert report["steps"]["enrich-code"]["counts"]["failed"] == 1
    assert read_report(run, "state.json")["steps"]["enrich-code"]["counts"]["failed"] == 1
    record, = sink.apply.call_args.args[0]
    assert (record["op"], record["status"], record["counts_json"]["failed"]) == ("run.record", "partial", 1)
    assert not run.read_jsonl("imported.jsonl")

    path.write_bytes(b"Vessel Name,FG Number\nSynthetic Boat,FG1\n")
    cli.execute(Run("CA", run.id, var=var), ctx, sink, ("enrich-code",))
    report = read_report(run)
    assert report["status"] == report["steps"]["enrich-code"]["status"] == "ok"
    assert "failed" not in report["steps"]["enrich-code"]["counts"]
    assert len(run.read_jsonl("imported.jsonl")) == 1
