"""SC44: two-way JSON detachment, with a frozen pre-fix serialization oracle.

The small synthetic fixture follows discover.candidate/finalize field shapes.
The golden catalog was recorded from the pinned, unmodified full module.
"""
import copy
import hashlib
import json

import pytest

from skippercast.coastal import live_discovery as ld
from tests._support import FIXTURES

GOLDEN = FIXTURES / "sc44" / "golden.json"
CANDIDATE_FIELDS = (
    "metadata", "provenance", "extent", "unknowns", "field_evidence",
    "rejection_reasons", "terrain", "habitat", "render",
)
MANIFEST_FIELDS = ("bbox", "lead_source_ids", "usable_source_ids", "unattempted_queries")
ALIAS_CASES = CANDIDATE_FIELDS + MANIFEST_FIELDS


def fixture():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def manifest_bytes(manifest):
    return encode(manifest)


def snapshot():
    manifest = fixture()["manifest"]
    return manifest, ld.frozen_catalog(manifest, manifest_bytes(manifest))


def target(document, key):
    return document["candidates"][0][key] if key in CANDIDATE_FIELDS else document[key]


def mutate(value):
    if isinstance(value, dict):
        value["sc44_mutation"] = {"nested": ["changed"]}
    else:
        value.append({"sc44_mutation": ["changed"]})


def test_byte_compatibility():
    data = fixture()
    manifest = data["manifest"]
    before = encode(manifest)
    catalog = ld.frozen_catalog(manifest, before)
    assert encode(catalog) == encode(data["catalog"]), "baseline_catalog_bytes_changed"
    assert encode(manifest) == before, "construction_changed_input"
    assert [c["source_id"] for c in catalog["candidates"]] == ["synthetic:a", "synthetic:z"]
    assert catalog["mapping_accepted"] is False
    assert catalog["execution_authorized"] is False
    assert catalog["review_required"] is True
    assert "cache" not in catalog["candidates"][0]
    assert "not_retained" not in catalog
    manifest["candidates"].reverse()
    # Bind the same original raw manifest bytes: permutation is about projection order.
    assert encode(ld.frozen_catalog(manifest, before)) == encode(catalog)


@pytest.mark.parametrize("key", ALIAS_CASES)
def test_input_detachment(key):
    manifest, catalog = snapshot()
    before = encode(catalog)
    identity = catalog["catalog_id"]
    mutate(target(manifest, key))
    assert encode(catalog) == before, f"input_alias:{key}"
    assert catalog["catalog_id"] == identity


@pytest.mark.parametrize("key", ALIAS_CASES)
def test_returned_detachment(key):
    manifest, catalog = snapshot()
    before = encode(manifest)
    mutate(target(catalog, key))
    assert encode(manifest) == before, f"returned_alias:{key}"


def containers(value, path=()):
    if isinstance(value, (dict, list)):
        yield path
        iterator = value.items() if isinstance(value, dict) else enumerate(value)
        for key, child in iterator:
            yield from containers(child, path + (key,))


def at_path(value, path):
    for key in path:
        value = value[key]
    return value


def test_every_nested_container_is_detached():
    manifest, catalog = snapshot()
    paths = []
    for key in CANDIDATE_FIELDS:
        paths.extend(("candidates", 0, key) + p for p in containers(target(manifest, key)))
    for key in MANIFEST_FIELDS:
        paths.extend((key,) + p for p in containers(manifest[key]))
    assert len(paths) > len(ALIAS_CASES), "nested_fixture_coverage_missing"
    for path in paths:
        source = fixture()["manifest"]
        result = ld.frozen_catalog(source, manifest_bytes(source))
        before = encode(result)
        mutate(at_path(source, path))
        assert encode(result) == before, f"nested_input_alias:{path}"
        source = fixture()["manifest"]
        result = ld.frozen_catalog(source, manifest_bytes(source))
        before = encode(source)
        mutate(at_path(result, path))
        assert encode(source) == before, f"nested_returned_alias:{path}"


def test_reload_preserves_identity():
    manifest, catalog = snapshot()
    raw = encode(catalog)
    for key in ALIAS_CASES:
        mutate(target(manifest, key))
    assert encode(catalog) == raw
    loaded = json.loads(raw)
    identity = loaded.pop("catalog_id")
    independent = hashlib.sha256(json.dumps(
        loaded, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()
    assert identity == independent == ld._digest(loaded)
    assert loaded["manifest_sha256"] == hashlib.sha256(manifest_bytes(fixture()["manifest"])).hexdigest()


def test_empty_and_missing_optional_fields():
    manifest = fixture()["manifest"]
    manifest["candidates"] = []
    for key in MANIFEST_FIELDS[1:]:
        manifest[key] = []
    result = ld.frozen_catalog(manifest, manifest_bytes(manifest))
    assert result["candidates"] == []
    for key in MANIFEST_FIELDS[1:]:
        mutate(manifest[key])
        assert result[key] == []
    manifest["candidates"] = [{"source_id": "synthetic:optional"}]
    result = ld.frozen_catalog(manifest, manifest_bytes(manifest))
    assert result["candidates"][0]["metadata"] is None
    assert result["candidates"][0]["field_evidence"] is None
    assert result["mapping_accepted"] is False


def test_construction_does_not_alias_between_calls():
    manifest = fixture()["manifest"]
    raw = manifest_bytes(manifest)
    first = ld.frozen_catalog(manifest, raw)
    second = ld.frozen_catalog(manifest, raw)
    before = copy.deepcopy(second)
    mutate(first["candidates"][0]["metadata"])
    assert second == before, "cross_call_alias"
