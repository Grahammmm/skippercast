"""F20-09: retained search leads must not carry forward catch facts or extra fields."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from tests._support import ROOT


spec = importlib.util.spec_from_file_location("recent_intel_retention", ROOT / "scripts/collect_recent_intel.py")
assert spec is not None and spec.loader is not None
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
NOW = datetime(2026, 9, 22, 20, tzinfo=timezone.utc)
URL = "https://example.org/lead"
LEAD = {
    "id": hashlib.sha256(URL.encode()).hexdigest()[:20],
    "region_id": "morro-bay",
    "query_id": "reef",
    "source": "reddit",
    "url": URL,
    "published_at": "2026-09-15T09:30:00-07:00",
    "title": "Morro Bay lingcod discussion",
    "summary": "A synthetic search lead",
    "location_basis": "text mentions region",
    "review_status": "candidate",
    "reported_catch": None,
    "species": [],
    "fishing_date": None,
    "geometry": None,
    "note": "Search lead only; no catch, species, trip date, or fishing position verified.",
}


def gather(tmp_path, *previous, fresh=()):
    config = {
        "schema_version": 1, "lookback_days": 30, "jobs_per_day": 1,
        "source_set": ["reddit"], "upstream": {},
        "regions": [{"id": "morro-bay", "queries": [{"id": "reef", "text": "Synthetic reef query"}]}],
    }
    engine = tmp_path / "fake-engine.py"
    engine.touch()

    def runner(cmd, **kwargs):
        target = Path(next(arg.removeprefix("--output=") for arg in cmd if arg.startswith("--output=")))
        target.write_text(json.dumps({"schema_version": "1.3", "results": list(fresh),
                                      "source_status": {"reddit": "ok" if fresh else "no-results"}}))
        return CompletedProcess(cmd, 0)

    return collector.gather(config, engine, tmp_path / "out", NOW, {"candidates": list(previous)}, runner)["candidates"]


def test_retention_rebuilds_candidate_and_preserves_dated_attribution(tmp_path):
    # The old dict spread trusted facts and unknown fields in a dated lead.
    historical = dict(LEAD, verified=True, extra="historical-only", review_status="verified",
                      reported_catch=7, species=["lingcod"], fishing_date="2026-09-14",
                      geometry={"type": "synthetic"}, note="Verified result")
    assert gather(tmp_path, LEAD) == [{**LEAD, "retained": True}]
    assert gather(tmp_path, historical) == [{**LEAD, "retained": True}]


@pytest.mark.parametrize("field, value", [
    ("region_id", "unknown-region"), ("region_id", "southern-california"), ("region_id", None),
    ("url", "http://example.org/lead"), ("url", "https:///lead"), ("url", "https://example.org:bad/lead"),
    ("published_at", "not-a-date"), ("published_at", "2026-08-01"), ("published_at", "2026-09-23"),
    ("title", {"extra": "not public attribution"}),
])
def test_retention_rejects_invalid_region_link_date_or_attribution(tmp_path, field, value):
    # An ID alone does not make malformed or out-of-window history publishable.
    assert gather(tmp_path, {**LEAD, field: value}) == []


def test_fresh_canonical_url_wins_over_retained_alias(tmp_path):
    # A stale stored ID and tracking suffix cannot create a second copy of the same link.
    previous = dict(LEAD, id="legacy-id", url=f"{URL}/?utm_source=synthetic#fragment")
    fresh = dict(LEAD, published_at="2026-09-21", summary="A newer synthetic search lead")
    assert gather(tmp_path, previous, fresh=[fresh]) == [
        dict(LEAD, published_at="2026-09-21T00:00:00+00:00", summary="A newer synthetic search lead"),
    ]
