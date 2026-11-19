"""F06-02: compare frozen discovery metadata without treating a gap as removal."""
import hashlib
import json

import pytest

from skippercast.coastal import live_discovery as ld
from skippercast.http import Allowlist
from tests.unit.test_coastal_live_discovery import Opener, runner_for


def catalog(*rows, **overrides):
    result = dict(schema=ld.CATALOG, region="synthetic", bbox=[0, 0, 1, 1],
                  source_revision="source-1", policy_revision="policy-1",
                  method_revision="bounded-catalog-v1", plan_sha256="a" * 64,
                  discovery_complete=True, bounded_plan_finished=True,
                  unattempted_queries=[], checked_until="2000-01-01T00:01:00Z",
                  candidates=list(rows))
    return {**result, **overrides}


@pytest.mark.parametrize("terminate_early", [True, False], ids=["cutoff", "complete"])
def test_frozen_diff_distinguishes_skipped_query_from_empty_result(tmp_path, terminate_early):
    # No response and a successfully ingested empty response must not mean the same thing.
    host = "catalog.example.invalid"
    url = f"https://{host}/listing/"
    plan = dict(schema=ld.PLAN, region="synthetic", bbox=[0, 0, 1, 1],
                source_revision="source-1", policy_revision="policy-1", byte_limit=10_000,
                catalogs=[dict(id="test", publisher="Synthetic", authority_url=url, allowed_hosts=[host],
                               queries=[dict(url=url, purpose="metadata", max_bytes=10_000, adapter="listing")])])
    allowlist = Allowlist([host])
    ld.run(plan, tmp_path / "baseline", allowlist=allowlist, clock=lambda: 946684800,
           runner=runner_for(Opener({url: b'<a href="fictional.bag">test</a>'})))
    previous = tmp_path / "baseline" / "catalog.json"
    previous_bytes = previous.read_bytes()
    out = tmp_path / "comparison"
    ticks = iter([0, ld.WALL_SECONDS if terminate_early else 0, ld.WALL_SECONDS])
    opener = Opener({url: b"No files"})
    receipt = ld.run(plan, out, previous=previous, allowlist=allowlist, clock=lambda: 946771200,
                     monotonic=lambda: next(ticks), runner=runner_for(opener))
    change = json.loads((out / "catalog-diff.json").read_bytes())
    assert previous.read_bytes() == previous_bytes
    assert change["previous"]["sha256"] == hashlib.sha256(previous_bytes).hexdigest()
    assert opener.urls == ([] if terminate_early else [url])
    assert change["removed"] == ([] if terminate_early else ["test:fictional.bag"])
    assert change["not_rechecked"] == (["test:fictional.bag"] if terminate_early else [])
    assert change["comparison_scope"] == ("incomplete" if terminate_early else "complete")
    assert receipt["diff_summary"]["not_rechecked"] == int(terminate_early)
    assert receipt["diff_summary"]["removed"] == int(not terminate_early)


@pytest.mark.parametrize("scope_change, expected", [
    (dict(region="other"), "different_scope"),
    (dict(bbox=[0, 0, 2, 2]), "different_scope"),
    (dict(plan_sha256="b" * 64), "different_scope"),
    (dict(policy_revision="policy-2"), "different_scope"),
    (dict(plan_sha256=None), "unknown_scope"),
])
def test_diff_does_not_infer_removal_or_same_row_readiness_across_scopes(scope_change, expected):
    # A reused ID does not make different or unbound geographic/query scopes comparable.
    shared = {"source_id": "synthetic:existing"}
    previous = catalog(shared, {"source_id": "synthetic:absent"})
    change = ld.diff(previous, catalog(shared, **scope_change))
    assert change["comparison_scope"] == expected
    assert change["removed"] == []
    assert change["not_rechecked"] == ["synthetic:absent", "synthetic:existing"]
    assert change["changed"] == [] and change["unchanged"] == 0


def test_partial_comparison_keeps_observed_changes_but_not_removals():
    # Success flags cannot override an explicitly unattempted query. Common rows
    # still carry observable readiness changes when their scope matches.
    row = {"source_id": "synthetic:existing", "render": {"status": "blocked"}}
    previous = catalog(row, {"source_id": "synthetic:absent"})
    current = catalog({**row, "render": {"status": "needs_review"}}, unattempted_queries=["skipped"])
    change = ld.diff(previous, current)
    assert change["comparison_scope"] == "incomplete"
    assert change["removed"] == [] and change["not_rechecked"] == ["synthetic:absent"]
    assert change["changed"] == [{"source_id": row["source_id"], "fields": ["render"]}]


@pytest.mark.parametrize("field, value", [
    ("habitat", {"status": "needs_review"}),
    ("render", {"status": "needs_review"}),
    ("expires_at", "2000-01-03T00:00:00Z"),
])
def test_readiness_and_expiry_changes_are_visible(field, value):
    # Changing only one of these fields used to leave the row counted as unchanged.
    row = dict(source_id="synthetic:existing", habitat={"status": "unassessed"},
               render={"status": "blocked"}, expires_at="2000-01-08T00:00:00Z",
               provenance={"checked_at": "2000-01-01T00:00:00Z"})
    previous = catalog(row)
    assert ld.diff(previous, catalog(row))["unchanged"] == 1
    change = ld.diff(previous, catalog({**row, field: value}))
    assert change["changed"] == [{"source_id": row["source_id"], "fields": [field]}]
    assert change["unchanged"] == 0


def test_expiry_state_uses_snapshot_time_without_counting_routine_refresh():
    old = dict(source_id="synthetic:existing", provenance={"checked_at": "2000-01-01T00:00:00Z"},
               expires_at="2000-01-08T00:00:00Z")
    refreshed = dict(old, provenance={"checked_at": "2000-01-02T00:00:00Z"},
                     expires_at="2000-01-09T00:00:00Z")
    previous = catalog(old)
    change = ld.diff(previous, catalog(refreshed, checked_until="2000-01-02T00:01:00Z"))
    assert change["changed"] == [] and change["unchanged"] == 1
    expired = ld.diff(previous, catalog(old, checked_until=old["expires_at"]))
    assert expired["changed"] == [{"source_id": old["source_id"], "fields": ["expires_at"]}]
