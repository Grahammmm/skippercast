"""Empty supplied header/rights/scope objects must not clear legacy v2 holds; synthetic JSON only."""
import hashlib
from unittest.mock import patch

import pytest

from skippercast.coastal import cached_inventory as ci

NOW, HORIZON = 100, 200
SHAPE, AFFINE = [8, 8], [2, 0, 500000, 0, -2, 3800000]
HEADER_HOLDS = ["header_source_changed", "native_grid_metadata_unresolved", "vertical_metadata_unresolved"]
RIGHTS_HOLD = ["private_source_rights_unreviewed"]
SCOPE_HOLD = ["prospective_geographic_scope_unreviewed"]


def reference(path, contract):
    data = path.read_bytes()
    return dict(path=path.name, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), contract=contract)


def build(tmp_path, empty=(), omit=()):
    """Independently complete valid evidence; `empty` roles become {} and `omit` roles are absent."""
    source = dict(sha256="a" * 64, bytes=4, url="https://example.org/source.bag")
    (tmp_path / "source.bag").write_bytes(b"data")  # stat-only stand-in; never opened
    (tmp_path / "source.json").write_bytes(ci.encoded(source))
    ident = dict(sha256=source["sha256"], bytes=source["bytes"])
    clocks = dict(checked_at=50, valid_until=300)
    docs = dict(
        header=dict(source=ident, shape=SHAPE, transform=AFFINE, resolution_m=[2, 2], driver="BAG", count=2,
                    horizontal_crs="EPSG:26910",
                    vertical=dict(conflicts=[], datum="MLLW", sign="positive_up", units="m",
                                  datum_realization="unknown", scale=1, offset=0, scale_offset_applied=False)),
        rights=dict(independent=True, private_use=True, accepted_source_rights_for_declared_private_purpose=True,
                    holds_added=[], source=ident, **clocks),
        scope=dict(status="accepted_scope_only", independent=True, holds=[], source=ident, window_set=[[0, 0, 4, 4]],
                   product_region="synthetic", native_quality_accepted=False, global_affine=AFFINE,
                   grid_shape=SHAPE, **clocks),
        prepared_acquisition=dict(source=ident))
    candidate = dict(source_manifest=reference(tmp_path / "source.json", "cached-source-json-v1"),
                     cache_path="source.bag", window_set=[[0, 0, 4, 4]])
    for role, doc in docs.items():
        if role in omit:
            continue
        doc = {} if role in empty else dict(doc, schema="synthetic-" + role + "-v1")
        (tmp_path / (role + ".json")).write_bytes(ci.encoded(doc))
        candidate[role] = reference(tmp_path / (role + ".json"), "cached-source-json-v1")
    return dict(schema=ci.PLAN, region="synthetic", candidates=[candidate], metadata_bytes=ci.MAX_METADATA,
                output_bytes=ci.MAX_OUTPUT, network_bytes=0, source_read_bytes=0,
                output_root=str(tmp_path / "output"))


def entry(tmp_path, **kwargs):
    result = ci.inventory(tmp_path, build(tmp_path, **kwargs), now=NOW, horizon=HORIZON)
    return result, result["sources"][0]


def test_complete_valid_v2_evidence_remains_usable(tmp_path):
    result, e = entry(tmp_path)
    assert e["holds"] == [] and e["usable_for_acquisition_request"]
    assert result["status"] == "USABLE_METADATA_ONLY" and result["usable_source_ids"] == [e["source_id"]]
    assert result["execution_authorized"] is False and e["publication_prohibited"] is True
    assert e["native_quality_accepted"] is False and e["acquisition_recipe"]["native_read_authorized"] is False


@pytest.mark.parametrize("role,expected", [
    ("header", HEADER_HOLDS + SCOPE_HOLD), ("rights", RIGHTS_HOLD), ("scope", SCOPE_HOLD)])
def test_single_empty_role_is_held(tmp_path, role, expected):
    result, e = entry(tmp_path, empty=(role,))
    assert e["holds"] == sorted(expected)
    assert not e["usable_for_acquisition_request"]
    assert result["status"] == "HELD_METADATA_ONLY" and result["usable_source_ids"] == []


def test_all_empty_objects_cannot_clear_holds(tmp_path):
    result, e = entry(tmp_path, empty=("header", "rights", "scope"))
    assert e["holds"] == sorted(HEADER_HOLDS + RIGHTS_HOLD + SCOPE_HOLD)
    assert result["status"] == "HELD_METADATA_ONLY" and result["usable_source_ids"] == []
    assert result["execution_authorized"] is False


@pytest.mark.parametrize("role", ["header", "rights", "scope"])
def test_omitted_roles_keep_missing_holds(tmp_path, role):
    _, e = entry(tmp_path, omit=(role,))
    # scope binds its affine and shape to the header, so a missing header also fails that binding
    assert e["holds"] == sorted([role + "_metadata_missing"] + (SCOPE_HOLD if role == "header" else []))


def test_empty_prepared_already_stays_held(tmp_path):
    result, e = entry(tmp_path, empty=("prepared_acquisition",))
    assert e["holds"] == ["prepared_source_changed"]
    assert result["status"] == "HELD_METADATA_ONLY"


def test_held_producer_and_reuse(tmp_path):
    value = build(tmp_path, empty=("header", "rights", "scope"))
    output = tmp_path / "output"
    first = ci.produce(tmp_path, value, output, now=NOW, horizon=HORIZON)
    assert first["status"] == "completed" and first["result"]["status"] == "HELD_METADATA_ONLY"
    assert first["result"]["execution_authorized"] is False and first["result"]["usable_source_ids"] == []
    assert first["catalog_metadata_bytes_this_call"] > 0
    refuse = AssertionError("no catalog read on reuse")
    with patch.object(ci, "read_metadata", side_effect=refuse), patch.object(ci, "inventory", side_effect=refuse):
        again = ci.produce(tmp_path, value, output, now=NOW, horizon=HORIZON)
    assert again["status"] == "completed_reused" and again["catalog_metadata_bytes_this_call"] == 0
    assert again["manifest_sha256"] == first["manifest_sha256"]
    assert again["result"]["status"] == "HELD_METADATA_ONLY"
    assert again["result"]["metadata_accounting"]["refunds"] is False
