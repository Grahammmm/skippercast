"""F20-08: only completed configured providers count toward search coverage."""
from datetime import datetime, timezone
from functools import partial
import importlib.util
import json
from pathlib import Path
from subprocess import CompletedProcess
import sys

import pytest
from tests._support import ROOT


spec = importlib.util.spec_from_file_location("recent_intel_coverage", ROOT / "scripts/collect_recent_intel.py")
assert spec is not None and spec.loader is not None
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
NOW = datetime(2026, 9, 22, 20, tzinfo=timezone.utc)
PREVIOUS = {
    "id": "old", "url": "https://example.org/old", "published_at": "2026-09-15T00:00:00+00:00",
    "review_status": "candidate",
}
LEAD = {
    "url": "https://example.org/new", "published_at": "2026-09-21T00:00:00+00:00",
    "title": "Morro Bay lingcod discussion", "summary": "A synthetic research lead", "source": "reddit",
}


class FrozenClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


@pytest.mark.parametrize(
    "source_status, rows, job_status, usable",
    [
        pytest.param({"reddit": "timeout", "grounding": "error"}, [LEAD], "failed", 0, id="all-failed"),
        pytest.param({"reddit": "ok", "other": "ok"}, [LEAD], "partial", 1, id="missing-configured"),
        pytest.param({"other": "ok"}, [], "failed", 0, id="only-unconfigured"),
        pytest.param({"reddit": "ok", "grounding": "timeout"}, [LEAD], "partial", 1, id="mixed"),
        pytest.param({"reddit": "no-results", "grounding": "no-results"}, [], "ok", 1, id="all-no-results"),
    ],
)
def test_snapshot_reports_configured_provider_coverage(tmp_path, monkeypatch, source_status, rows, job_status, usable):
    # A successful process exit is not search success, and unrelated provider
    # keys must not make up for a configured provider that never reported.
    config = tmp_path / "watchlist.json"
    config.write_text(json.dumps({
        "schema_version": 1, "lookback_days": 30, "jobs_per_day": 1,
        "source_set": ["reddit", "grounding"], "upstream": {},
        "regions": [{"id": "morro-bay", "queries": [{"id": "reef", "text": "Synthetic reef query"}]}],
    }))
    engine = tmp_path / "fake-engine.py"
    engine.touch()
    previous = tmp_path / "previous.json"
    previous.write_text(json.dumps({"candidates": [PREVIOUS]}))
    output = tmp_path / "out"

    def runner(cmd, **kwargs):
        target = Path(next(arg.removeprefix("--output=") for arg in cmd if arg.startswith("--output=")))
        target.write_text(json.dumps({"schema_version": "1.3", "results": rows, "source_status": source_status}))
        return CompletedProcess(cmd, 0)

    monkeypatch.setattr(collector, "datetime", FrozenClock)
    monkeypatch.setattr(collector, "gather", partial(collector.gather, runner=runner))
    monkeypatch.setattr(sys, "argv", ["collect", "--engine", str(engine), "--config", str(config),
                                     "--previous", str(previous), "--output", str(output)])
    if usable:
        collector.main()
    else:
        with pytest.raises(SystemExit, match="No recent-intel research job completed"):
            collector.main()

    snapshot = json.loads((output / "recent-intel.json").read_text())
    check = snapshot["checks"]["morro-bay/reef"]
    assert check["source_status"] == source_status
    assert check["status"] == job_status
    health = snapshot["health"]
    assert health["jobs_usable"] == usable
    assert health["jobs_total"] == 1
    assert health["status"] == ("ok" if job_status == "ok" else "degraded")
    candidates = {row["url"]: row for row in snapshot["candidates"]}
    assert candidates.pop(PREVIOUS["url"]) == {**PREVIOUS, "retained": True}
    assert set(candidates) == ({LEAD["url"]} if usable and rows else set())
    for candidate in candidates.values():
        assert candidate["review_status"] == "candidate"
        assert candidate["reported_catch"] is None
        assert candidate["fishing_date"] is None
        assert candidate["geometry"] is None
        assert candidate["species"] == []
