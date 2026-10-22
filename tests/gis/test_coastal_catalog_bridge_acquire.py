"""SC-3: the coordinator's real acquire stage reads a job bridged from a frozen catalog.

A synthetic frozen discovery catalog (#734 shape) names one allowlisted NCEI
lead. Its cached copy is a tiny synthetic EPSG:3310 GeoTIFF inside the queue
root. The source-free bridge writes the `coastal-native-job-v1` input, the
ordinary `Store.enqueue` queues it at the acquire stage, and the coordinator
dispatches the repository's fixed stage CLI. No network: this process refuses
outbound connections and the stage records zero requests.
"""
import hashlib
import json
import socket
import sys

import numpy as np
from pyproj import Transformer
import pytest
import rasterio
from rasterio.transform import from_origin

from skippercast.coastal.coordinator import catalog_bridge as bridge
from skippercast.coastal.coordinator.segments import segment
from skippercast.http import Allowlist
from tests import _coastal_catalog_fixture as fx
from tests._coastal_operations import REGION, Harness, export_package, policy

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="coastal supervisor requires Linux /proc")


@pytest.fixture
def ops(tmp_path, tmp_path_factory):
    harness = Harness(tmp_path, export_package(tmp_path_factory.mktemp("package-export")),
                      real_stages=True, policy_value=policy(budgets={"bytes": 10_000_000}))
    yield harness
    harness.close()


def test_frozen_catalog_lead_is_read_by_the_real_acquire_stage(ops, tmp_path, monkeypatch):
    monkeypatch.setattr(socket, "create_connection",
                        lambda *a, **k: pytest.fail("bridge/enqueue must not open a connection"))
    record = segment(-200000, -50000, region=REGION)
    inverse = Transformer.from_crs("EPSG:3310", "OGC:CRS84", always_xy=True)
    record["bbox_crs84"] = list(inverse.transform_bounds(*record["bbox"], densify_pts=21))
    record["synthetic"] = True
    ops.store.add_segment(record)

    raster = ops.root / "sources/H11952_synthetic.tif"
    raster.parent.mkdir(parents=True)
    west, south, east, north = record["bbox"]
    with rasterio.open(raster, "w", driver="GTiff", width=4, height=4, count=1, dtype="float32",
                       crs="EPSG:3310", transform=from_origin(west + 1000, north - 1000, 250, 250)) as ds:
        ds.write(np.full((1, 4, 4), -20.0, dtype="float32"))
    source = dict(path="sources/H11952_synthetic.tif", sha256=hashlib.sha256(raster.read_bytes()).hexdigest(),
                  bytes=raster.stat().st_size, contract="native-raster-v1")

    rows = [fx.candidate("H11952_synthetic.tif", bbox=record["bbox_crs84"], size=source["bytes"],
                         source_hash=source["sha256"])]
    catalog = fx.frozen_catalog(rows)
    catalog_path = tmp_path / "catalog.json"
    sha = fx.write_catalog(catalog_path, catalog)
    plan = fx.plan(catalog, sha, [fx.selection(rows[0]["source_id"], source)], bbox=record["bbox_crs84"],
                   segment_id=record["segment_id"])

    allow = Allowlist([fx.HOST])
    dry = bridge.dry_run(ops.root, catalog_path, plan, tmp_path / "dry", allowlist=allow)
    assert dry["selected_source_ids"] == [rows[0]["source_id"]]
    receipt = bridge.run(ops.root, catalog_path, plan, ops.root / "bridge", allowlist=allow)
    ref = dict(path=receipt["output"]["path"], sha256=receipt["output"]["sha256"],
               bytes=receipt["output"]["bytes"], kind="input", contract=bridge.RECEIPT)
    [acquire] = bridge.enqueue(ops.store, ref, code_sha=ops.code, deps_sha=ops.deps)

    states = [r["state"] for r in ops.run(seconds=150, max_jobs=1)]
    assert states == ["held"]

    job = dict(ops.store.db.execute("SELECT * FROM jobs WHERE job_id=?", (acquire,)).fetchone())
    assert job["stage"] == "acquire" and job["attempts"] == 1 and job["state"] == "held"
    produced = {row["kind"]: row["path"] for row in ops.store.db.execute(
        "SELECT kind,path FROM artifacts WHERE produced_by_job=?", (acquire,))}
    assert "coastal-cached-observation-v1" in produced, (job, produced)
    observation = json.loads((ops.root / produced["coastal-cached-observation-v1"]).read_text())
    assert observation["acquisition"] == "verified_existing_cache"
    assert observation["requests"] == 0 and observation["transferred_bytes"] == 0
    assert observation["source"] == source
    native = json.loads((ops.root / produced["coastal-native-job-v1"]).read_text())
    assert native["catalog_lineage"]["catalog_id"] == catalog["catalog_id"]
    assert native["catalog_lineage"]["source_id"] == rows[0]["source_id"]
    # No vertical contract was declared, so the real stage holds rather than inventing one:
    # the bridge feeds acquire; it does not qualify anything.
    holds = json.loads(job["holds_json"])
    assert holds and all(h.startswith("vertical_") for h in holds)
    assert ops.store.db.execute("SELECT COUNT(*) FROM jobs WHERE stage!='acquire'").fetchone()[0] == 0


@pytest.mark.parametrize("width,height,origin,subset,count", [
    (4096, 4096, (0, 0), None, 64),
    (1150, 1300, (128, 256), None, 6),
    (1500, 1000, (128, 256), [1152, 768, 348, 232], 1),
    (8192, 8192, (0, 0), [4096, 4096, 4096, 4096], 64),
])
def test_window_set_real_native_raster_run_and_enqueue(tmp_path, monkeypatch,
                                                       width, height, origin, subset, count):
    """Independent rasterio footprints, native coverage, hashes and ordinary queue order."""
    from rasterio.windows import Window, bounds
    from skippercast.coastal.coordinator.store import Store

    monkeypatch.setattr(socket, "create_connection",
                        lambda *a, **k: pytest.fail("bridge/enqueue must not open a connection"))
    transform = from_origin(-120.6, 34.6, 0.0001, 0.0001)
    raster = tmp_path / "sources/synthetic.tif"
    raster.parent.mkdir(parents=True)
    # uint8 keeps the largest synthetic raster bounded; 0 is nodata, 1 is valid.
    pixels = np.zeros((height, width), dtype="uint8")
    pixels[origin[1]:, origin[0]:] = 1
    with rasterio.open(raster, "w", driver="GTiff", width=width, height=height, count=1,
                       dtype="uint8", nodata=0, crs="EPSG:4326", transform=transform) as ds:
        ds.write(pixels, 1)
    source = dict(path="sources/synthetic.tif", sha256=hashlib.sha256(raster.read_bytes()).hexdigest(),
                  bytes=raster.stat().st_size, contract="native-raster-v1")
    with rasterio.open(raster) as ds:
        assert ds.transform.e < 0
        mask = ds.read_masks(1)
        assert [int(np.flatnonzero(mask.any(axis=0))[0]),
                int(np.flatnonzero(mask.any(axis=1))[0])] == list(origin)
        del mask
        coverage = subset or [origin[0], origin[1], width - origin[0], height - origin[1]]
        segment_bbox = list(bounds(Window(*coverage), ds.transform))
        footprint = list(ds.bounds)
        anchor = list(ds.transform * origin)
        # Expected offsets are native coordinates, independent of bridge helpers.
        expected = []
        for row in range(origin[1], height, 512):
            for col in range(origin[0], width, 512):
                window = [col, row, min(512, width - col), min(512, height - row)]
                west, south, east, north = bounds(Window(*window), ds.transform)
                if (min(east, segment_bbox[2]) > max(west, segment_bbox[0])
                        and min(north, segment_bbox[3]) > max(south, segment_bbox[1])):
                    expected.append(window)
    assert len(expected) == count
    if origin != (0, 0) and subset is None:
        assert expected[0] == [128, 256, 512, 512]
        assert expected[-1] == [640, 1280, 510, 20]
    if subset is not None and count == 1:
        assert expected == [subset]
    rows = [fx.candidate("synthetic.tif", bbox=footprint, size=source["bytes"],
                         source_hash=source["sha256"])]
    catalog = fx.frozen_catalog(rows)
    catalog_path = tmp_path / "catalog.json"
    sha = fx.write_catalog(catalog_path, catalog)
    selection = fx.window_set(rows[0]["source_id"], source, expected,
                              tiling=fx.tiling(width, height, origin=origin, anchor=anchor))
    plan = fx.plan(catalog, sha, [selection], bbox=segment_bbox,
                   budget=dict(fx.BUDGET, bytes=100_000_000), max_total_bytes=100_000_000)
    allow = Allowlist([fx.HOST])
    # Source-free even on genuine rasters: neither bridge nor enqueue may open one.
    with monkeypatch.context() as guarded:
        guarded.setattr(rasterio, "open", lambda *a, **k: pytest.fail("source-free bridge opened raster"))
        receipt = bridge.run(tmp_path, catalog_path, plan, tmp_path / "bridge", allowlist=allow)
    assert receipt["held_source_ids"] == []
    assert receipt["caps"]["selected_bytes"] == source["bytes"]
    assert [j["window_index"] for j in receipt["jobs"]] == list(range(count))
    assert [j["window"] for j in receipt["jobs"]] == expected
    store = Store(tmp_path / "var/coastal/coordinator.sqlite", root=tmp_path, policy=policy())
    try:
        store.add_segment(dict(schema="coastal-segment-v1", segment_id=plan["segment"]["segment_id"],
                               region=REGION, crs="EPSG:3310", bbox=[0, 0, 5000, 5000],
                               bbox_crs84=segment_bbox))
        ref = dict(receipt["output"], kind="input", contract=bridge.RECEIPT)
        ids = bridge.enqueue(store, ref, code_sha="a" * 64, deps_sha="b" * 64)
        assert len(ids) == len(set(ids)) == count
        assert store.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == count
        seen = np.zeros((height, width), dtype="uint8")
        with rasterio.open(raster) as ds:
            for index, job_id in enumerate(ids):
                queued = json.loads(store.db.execute("SELECT record_json FROM jobs WHERE job_id=?",
                                                     (job_id,)).fetchone()[0])
                manifest_ref = receipt["jobs"][index]["input_manifest"]
                assert queued["input_manifest"] == manifest_ref
                raw = (tmp_path / manifest_ref["path"]).read_bytes()
                assert hashlib.sha256(raw).hexdigest() == manifest_ref["sha256"]
                assert len(raw) == manifest_ref["bytes"]
                manifest = json.loads(raw)
                assert manifest["window"] == expected[index]
                assert manifest["source"] == source
                x, y, w, h = manifest["window"]
                assert ds.read(1, window=Window(x, y, w, h)).shape == (h, w)
                assert np.all(ds.read_masks(1, window=Window(x, y, w, h)) == 255)
                west, south, east, north = bounds(Window(x, y, w, h), ds.transform)
                assert min(east, segment_bbox[2]) > max(west, segment_bbox[0])
                assert min(north, segment_bbox[3]) > max(south, segment_bbox[1])
                seen[y:y + h, x:x + w] += 1
        wanted = np.zeros_like(seen)
        x, y, w, h = coverage
        wanted[y:y + h, x:x + w] = 1
        np.testing.assert_array_equal(seen, wanted)  # no native gaps, overlap or out-of-bbox tiles
    finally:
        store.close()
    # The formerly accepted local/cropped offsets must now fail before any output.
    if origin != (0, 0):
        selection["windows"] = [[x - origin[0], y - origin[1], w, h] for x, y, w, h in expected]
        with pytest.raises(ValueError, match="deterministic"):
            bridge.run(tmp_path, catalog_path, plan, tmp_path / "wrong-origin", allowlist=allow)
        assert not (tmp_path / "wrong-origin").exists()
