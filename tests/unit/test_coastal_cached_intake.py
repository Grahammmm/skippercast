"""Offline held intake contract; synthetic JSON only, no survey fixtures."""
from copy import deepcopy
import hashlib
from importlib.resources import files
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from jsonschema import Draft202012Validator, ValidationError

from skippercast.coastal import cached_inventory as ci


def reference(path):
    data = path.read_bytes()
    return dict(path=path.name, sha256=hashlib.sha256(data).hexdigest(),
                bytes=len(data), contract=ci.LEAD_SCHEMA)


def lead(kind="regular_bag", lifecycle="pending"):
    evidence = dict(path="retained.json", sha256="e" * 64, bytes=10, contract="retained-metadata-v1")
    source = dict(kind="native", format=kind, url="https://example.org/source.bag",
                  sha256="a" * 64, bytes=128, cache_path="never-open-source.bag")
    if kind == "geotiff":
        source = dict(kind="archive", format="geotiff", url="https://example.org/source.zip",
                      sha256="b" * 64, bytes=1024, member=None)
    return dict(schema=ci.LEAD_SCHEMA, lead_id="synthetic-" + kind, lifecycle=lifecycle,
                purpose="private_terrain", source=source,
                metadata=dict(horizontal_crs="EPSG:26910", vertical_datum="NAVD88" if kind == "geotiff" else "MLLW",
                              datum_realization="unknown", resolution_m=[2, 2],
                              uncertainty="unknown", interpolation_mask="unknown"),
                scope=dict(kind="unresolved"), evidence=[evidence],
                closed_receipt=evidence if lifecycle == "closed_control" else None)


def plan(tmp_path, records, limit=3):
    candidates = []
    for index, record in enumerate(records):
        path = tmp_path / f"lead-{index}.json"
        path.write_bytes(ci.encoded(record))
        candidates.append(dict(lead=reference(path)))
    return dict(schema=ci.LEAD_PLAN, region="synthetic", candidates=candidates,
                metadata_bytes=ci.MAX_METADATA, output_bytes=ci.MAX_OUTPUT,
                network_bytes=0, source_read_bytes=0, output_root=str(tmp_path / "output"),
                proposed_limits=dict(pending_candidates=limit, native_active=1))


def evaluate(tmp_path, value):
    return ci.inventory(tmp_path, value, now=100, horizon=200)


def test_packaged_schema_matches_canonical():
    packaged = files("skippercast.coastal.resources").joinpath("coastal-discovery-lead-v1.schema.json").read_bytes()
    canonical = Path(__file__).resolve().parents[2] / "schemas/coastal-discovery-lead-v1.schema.json"
    assert canonical.read_bytes() == packaged
    Draft202012Validator.check_schema(json.loads(packaged))


def test_heterogeneous_leads_stay_held_without_native_or_queue_operations(tmp_path):
    control = lead(lifecycle="closed_control")
    control["scope"] = dict(kind="native_window", window=[0, 0, 4, 4])
    value = plan(tmp_path, [lead(), lead("variable_resolution_bag"), lead("geotiff"), control])
    # VR is a different raw source; equal raw identity with contradictory reader
    # metadata is tested separately below.
    vr_path = tmp_path / "lead-1.json"
    vr = json.loads(vr_path.read_text()); vr["source"]["sha256"] = "c" * 64
    vr_path.write_bytes(ci.encoded(vr)); value["candidates"][1]["lead"] = reference(vr_path)
    original_owned = ci.owned
    def metadata_only(root, name):
        assert name.startswith("lead-") and name.endswith(".json")
        return original_owned(root, name)
    with patch.object(ci, "owned", side_effect=metadata_only), patch("sqlite3.connect", side_effect=AssertionError("no queue")):
        result = evaluate(tmp_path, value)
    assert result["backpressure"]["pending_candidates"] == 3
    assert result["backpressure"]["closed_controls"] == 1
    assert result["backpressure"]["observed_native_active"] is None
    assert not result["backpressure"]["enforced_by_dispatch"]
    assert not result["execution_authorized"]
    assert result["queue_binding"] == dict(status="unbound", artifact=None, writer=None, consumer=None)
    assert result["usage"]["source_stat_checks"] == result["usage"]["source_hashes"] == 0
    assert all(not e["native_quality_accepted"] and e["actual_data_support"] is None for e in result["candidates"])
    archive = next(e for e in result["candidates"] if e["records"][0]["record"]["source"]["kind"] == "archive")
    assert "archive_member_identity_unresolved" in archive["holds"]
    assert archive["records"][0]["record"]["metadata"]["vertical_datum"] == "NAVD88"
    assert not (tmp_path / "var").exists()


def test_semantic_dedup_keeps_aliases_conflicts_and_all_evidence(tmp_path):
    first = lead(); alias = deepcopy(first)
    alias["lead_id"] = "publisher-alias"; alias["source"]["url"] = "https://mirror.example.org/file.bag"
    alias["source"]["cache_path"] = "other-location.bag"
    value = plan(tmp_path, [first, alias])
    value["candidates"].append(deepcopy(value["candidates"][0]))
    result = evaluate(tmp_path, value)
    assert len(result["candidates"]) == 1
    entry = result["candidates"][0]
    assert len(entry["records"]) == 2 and entry["duplicate_records"] == 1
    assert "conflicting_retained_metadata" not in entry["holds"]
    alias["metadata"]["vertical_datum"] = "NAVD88"
    conflict = evaluate(tmp_path, plan(tmp_path, [first, alias]))
    assert conflict["candidates"][0]["candidate_key"] == entry["candidate_key"]
    assert "conflicting_retained_metadata" in conflict["candidates"][0]["holds"]
    assert len(conflict["candidates"][0]["records"]) == 2


def test_scope_identity_and_order_are_deterministic(tmp_path):
    other = lead(); other["scope"] = dict(kind="fixed_center", longitude=-120.5, latitude=34.48, size_cells=64)
    value = plan(tmp_path, [lead(), other])
    one = evaluate(tmp_path, value)
    value["candidates"].reverse()
    two = evaluate(tmp_path, value)
    assert one["candidates"] == two["candidates"]
    assert len(one["candidates"]) == 2
    assert "native_window_unresolved" in one["candidates"][0]["holds"]


def test_closed_control_is_not_pending_and_conflicting_lifecycle_is_conservative(tmp_path):
    control = lead(lifecycle="closed_control")
    closed = evaluate(tmp_path, plan(tmp_path, [control]))
    assert closed["backpressure"]["pending_candidates"] == 0
    mixed = evaluate(tmp_path, plan(tmp_path, [control, lead()]))
    assert mixed["backpressure"]["pending_candidates"] == 1
    assert "conflicting_retained_metadata" in mixed["candidates"][0]["holds"]


def test_over_limit_preserves_every_candidate_and_does_not_admit_work(tmp_path):
    records = []
    for i in range(4):
        record = lead(); record["scope"] = dict(kind="native_window", window=[i * 4, 0, 4, 4]); records.append(record)
    result = evaluate(tmp_path, plan(tmp_path, records))
    assert len(result["candidates"]) == 4
    assert result["backpressure"]["over_proposed_limit"]
    assert "proposed_pending_limit_exceeded" in result["holds"]
    assert all(not e["execution_authorized"] for e in result["candidates"])


def test_unknown_raw_identity_retains_distinct_leads(tmp_path):
    first = lead(); first["source"].update(sha256=None, bytes=None)
    second = deepcopy(first); second["lead_id"] = "different-unresolved-lead"
    result = evaluate(tmp_path, plan(tmp_path, [first, second]))
    assert len(result["candidates"]) == 2
    assert all("native_source_identity_unresolved" in e["holds"] for e in result["candidates"])


def test_unknown_hash_same_lead_id_different_publishers_do_not_collapse(tmp_path):
    first = lead(); first["source"].update(sha256=None, bytes=None)
    second = deepcopy(first); second["source"]["url"] = "https://different.example.org/source.bag"
    result = evaluate(tmp_path, plan(tmp_path, [first, second], limit=1))
    assert len(result["candidates"]) == 2
    assert result["backpressure"]["over_proposed_limit"]


@pytest.mark.parametrize("change", [
    lambda r: r.update(execution_authorized=True),
    lambda r: r["source"].update(member={"sha256": "b" * 64}),
    lambda r: r.update(lifecycle="closed_control"),
    lambda r: r.update(scope=dict(kind="native_window", window=[0, 0, 129, 129])),
    lambda r: r["source"].update(url="https://user:password@example.org/source.bag"),
    lambda r: r.update(scope=dict(kind="native_window", window=[0, 0, 2.0, 2.0])),
])
def test_unsafe_or_overclaiming_descriptor_is_refused(tmp_path, change):
    record = lead(); change(record)
    with pytest.raises((ValueError, ValidationError)):
        evaluate(tmp_path, plan(tmp_path, [record]))


def test_plan_limit_failure_precedes_any_metadata_read(tmp_path):
    value = plan(tmp_path, [lead()]); value["proposed_limits"]["pending_candidates"] = 0
    with patch.object(ci, "read_metadata", side_effect=AssertionError("must not read")):
        with pytest.raises(ValueError):
            ci.produce(tmp_path, value, tmp_path / "output", now=100, horizon=200)
    assert not (tmp_path / "output").exists()


def test_tamper_is_charged_once_and_cannot_reset_or_retry(tmp_path):
    value = plan(tmp_path, [lead()]); output = tmp_path / "output"
    original = (tmp_path / "lead-0.json").read_bytes()
    (tmp_path / "lead-0.json").write_bytes(original.replace(b"MLLW", b"BAD!"))
    with pytest.raises(ValueError, match="metadata hash changed"):
        ci.produce(tmp_path, value, output, now=100, horizon=200)
    admission = (output / "metadata-admission.json").read_bytes()
    (tmp_path / "lead-0.json").write_bytes(original)
    with pytest.raises(ValueError, match="remains charged; no retry"):
        ci.produce(tmp_path, value, output, now=100, horizon=200)
    assert (output / "metadata-admission.json").read_bytes() == admission
    with pytest.raises(ValueError, match="no fresh-root reset"):
        ci.produce(tmp_path, value, tmp_path / "other", now=100, horizon=200)


def test_completed_metadata_result_is_reused_without_another_catalog_read(tmp_path):
    value = plan(tmp_path, [lead()]); output = tmp_path / "output"
    first = ci.produce(tmp_path, value, output, now=100, horizon=200)
    with patch.object(ci, "inventory", side_effect=AssertionError("no second pass")):
        second = ci.produce(tmp_path, value, output, now=100, horizon=200)
    assert first["manifest_sha256"] == second["manifest_sha256"]
    assert second["status"] == "completed_reused"
    assert second["catalog_metadata_bytes_this_call"] == 0


def test_legacy_v2_regular_bag_branch_remains_strict(tmp_path):
    source = dict(sha256="a" * 64, bytes=4, url="https://example.org/source.bag")
    (tmp_path / "source.bag").write_bytes(b"data")
    source_path = tmp_path / "source.json"; source_path.write_bytes(ci.encoded(source))
    descriptor = reference(source_path); descriptor["contract"] = "cached-source-json-v1"
    value = dict(schema=ci.PLAN, region="synthetic", candidates=[dict(source_manifest=descriptor,
                 cache_path="source.bag", window_set=[[0, 0, 4, 4]])],
                 metadata_bytes=ci.MAX_METADATA, output_bytes=ci.MAX_OUTPUT,
                 network_bytes=0, source_read_bytes=0, output_root=str(tmp_path / "output"))
    result = evaluate(tmp_path, value)
    assert result["schema"] == ci.MANIFEST
    assert result["sources"][0]["holds"] == ["header_metadata_missing", "prepared_acquisition_metadata_missing",
                                             "rights_metadata_missing", "scope_metadata_missing"]
    assert result["usable_source_ids"] == []
    value["candidates"][0]["window_set"] = [[0, 0, 129, 129]]
    with pytest.raises(ValueError, match="native square window required"):
        evaluate(tmp_path, value)
