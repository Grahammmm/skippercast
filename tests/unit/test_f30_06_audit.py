"""A failed build must not rewrite any tile referenced by the retained index."""
import base64
from datetime import datetime, timezone
from functools import partial
from hashlib import sha256
from pathlib import Path
import sys

import pytest

from research.scripts import publish_bottom_subset
from skippercast.platform.contracts import atomic_json, read_json
from tests.integration import test_qualified_scope as fixtures


def assert_receipt(path, receipt):
    data = path.read_bytes()
    assert len(data) == receipt["bytes"]
    assert sha256(data).hexdigest() == receipt["sha256"]


@pytest.mark.gis
@pytest.mark.parametrize("fault", ["later source", "manifest install"])
def test_failed_rebuild_retains_indexed_tiles_and_retry_is_coherent(monkeypatch, request, fault):
    from research.scripts import build_socal_targets as compiler

    # Reuse reviewed synthetic geometry and the real qualification validator.
    seed = fixtures.QualifiedScopeTests()
    request.addfinalizer(seed.doCleanups)
    seed.setUp()
    root, folder = seed.root, seed.folder
    dist = root / "dist"
    index_path = dist / seed.region["assets"]["bottom_index"]
    seed.region["assets"]["atlas"] = seed.base + "atlas.json"
    atlas_path = dist / seed.region["assets"]["atlas"]
    atomic_json(atlas_path, seed.atlas)
    # Not every indexed tile belongs to the qualified compiler.
    context_path = seed.base + "bottom/context.json"
    original = seed.views["views"][seed.tid]
    original.update(atomic_json(dist / original["path"], seed.tile))
    seed.publish()
    index = read_json(index_path)
    index["views"]["context"] = {"path": context_path, "status": "surveyed",
                                  **atomic_json(dist / context_path, {"target_id": "context"})}
    atomic_json(index_path, index)
    previous = {path: path.read_bytes() for path in [atlas_path, index_path, *folder.iterdir()]}
    previous_tile = index["views"][seed.tid]

    later = {**seed.spec, "id": "NOAA-LATER", "survey_id": "H00002",
             "url": seed.spec["url"].replace("test.bag", "later.bag"), "sha256": "b" * 64}
    seed.spec["survey_id"] = "H00001"
    seed.config["sources"].append(later)
    seed.region["source_bindings"]["bathymetry"].append("noaa-later")
    seed.catalog["noaa-later"] = {**seed.catalog["noaa-test"], "pinned_sha256": later["sha256"],
                                  "access_url": later["url"]}
    instant = datetime(2020, 1, 1, tzinfo=timezone.utc)
    checked = instant.isoformat()
    for path, closure in seed.closures.items():
        atomic_json(root / path, {**closure, "checked_at": checked})
    config = root / "regions/test-coast/bottom-sources.reviewed.json"
    atomic_json(config, seed.config)
    monkeypatch.setattr(compiler, "ROOT", root)
    monkeypatch.setattr(compiler, "fresh_closures", partial(compiler.fresh_closures, now=instant))
    monkeypatch.setattr(sys, "argv", ["compiler", "--config", str(config), "--output", str(folder)])
    monkeypatch.setattr(publish_bottom_subset, "load_region", lambda *_: seed.region)

    # Isolate the compiler's filesystem orchestration from native BAG input.
    changed = {**seed.tile, "elevations": base64.b64encode(b"\x80\xfe" * 4).decode()}
    writes = []
    injecting = True

    def acquire(spec, cache, fetch):
        assert not fetch
        if injecting and fault == "later source" and spec["id"] == later["id"]:
            raise ValueError("injected later source failure")
        return root / "synthetic.bag", {"url": spec["url"], "sha256": spec["sha256"],
                                        "bytes": spec["bytes"], "http_status": 206, "retrieved_at": checked}


    def compile_source(spec, path, config, features, closed, output, tiles):
        if spec["id"] == later["id"]:
            return [], [], {}, {"source_id": spec["id"], "targets": 0}
        receipt = atomic_json(tiles / f"{seed.tid}.json", changed)
        writes.append(receipt["sha256"])
        target = {**seed.atlas["targets"][0], "habitat_score": 55}
        return [target], seed.atlas["areas"], {seed.tid: {**previous_tile, **receipt}}, {"targets": 1}

    replace = Path.replace

    def fail_manifest(path, destination):
        if injecting and fault == "manifest install" and destination == folder / "manifest.json":
            raise OSError("injected manifest install failure")
        return replace(path, destination)

    monkeypatch.setattr(compiler, "acquire", acquire)
    monkeypatch.setattr(compiler, "compile_source", compile_source)
    monkeypatch.setattr(Path, "replace", fail_manifest)
    with pytest.raises(ValueError if fault == "later source" else OSError, match=f"injected {fault}"):
        compiler.main()
    assert len(writes) == 1 and writes[0] != previous_tile["sha256"]
    for tile in index["views"].values():
        assert_receipt(dist / tile["path"], tile)
    assert all(path.read_bytes() == data for path, data in previous.items())
    health = read_json(folder / "health.json")
    assert health["status"] == "held" and health["previous_release_retained"] is True

    injecting = False
    compiler.main()
    result = publish_bottom_subset.publish(seed.rid, root)
    assert result is not None and result["ready"] is True and result["target_count"] == 1
    manifest = read_json(folder / "manifest.json")
    for name, receipt in manifest["artifacts"].items():
        assert_receipt(folder / name, receipt)
    fragment = read_json(folder / "bottom-index-fragment.json")
    published = read_json(index_path)
    assert published["views"] == {"context": index["views"]["context"], **fragment["views"]}
    assert published["views"][seed.tid]["sha256"] == writes[0]
    for tile in published["views"].values():
        assert_receipt(dist / tile["path"], tile)
    assert read_json(dist / previous_tile["path"]) == changed
    assert read_json(atlas_path) == read_json(folder / "atlas.json")
    assert not list(folder.parent.glob(".target-build-*"))
    print(f"{fault}: retained prior hashes; retry tile sha256={writes[0]}")
