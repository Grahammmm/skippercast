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


def _tiles(width, height, tile=512):
    return [[x, y, min(tile, width - x), min(tile, height - y)]
            for y in range(0, height, tile) for x in range(0, width, tile)]


def _window_bbox(anchor, cell, x, y, w, h):
    west, north = anchor
    dx, dy = cell
    return [west + x * dx, north - (y + h) * dy, west + (x + w) * dx, north - y * dy]


def _overlaps(a, b):
    w1, s1, e1, n1 = a
    w2, s2, e2, n2 = b
    return min(e1, e2) > max(w1, w2) and min(n1, n2) > max(s1, s2)


def test_window_set_plan_tiles_a_real_geotiff_and_restricts_to_the_segment(tmp_path, monkeypatch):
    """Acceptance (b) against a real raster: the bridge derives the canonical tiling from the
    plan-bound transform and restricts it to tiles intersecting the segment bbox."""
    monkeypatch.setattr(socket, "create_connection",
                        lambda *a, **k: pytest.fail("bridge/enqueue must not open a connection"))
    west, north, dx, dy = -120.6, 34.6, 0.0001, 0.0001   # dy is the southward cell size
    width, height = 1500, 1000                            # partial edges (not a multiple of 512)
    raster = tmp_path / "sources/synthetic.tif"
    raster.parent.mkdir(parents=True)
    with rasterio.open(raster, "w", driver="GTiff", width=width, height=height, count=1,
                       dtype="float32", crs="OGC:CRS84",
                       transform=from_origin(west, north, dx, -dy)) as ds:
        ds.write(np.arange(width * height, dtype="float32").reshape(1, height, width))
    source = dict(path="sources/synthetic.tif", sha256=hashlib.sha256(raster.read_bytes()).hexdigest(),
                  bytes=raster.stat().st_size, contract="native-raster-v1")

    anchor, cell = [west, north], [dx, dy]
    # The segment bbox is the south-east clipped tile only.
    se = [1024, 512, min(512, width - 1024), min(512, height - 512)]
    segment = _window_bbox(anchor, cell, *se)
    expected = [w for w in _tiles(width, height) if _overlaps(_window_bbox(anchor, cell, *w), segment)]
    assert expected == [se] == [[1024, 512, 476, 488]]

    footprint = [anchor[0], anchor[1] - height * cell[1], anchor[0] + width * cell[0], anchor[1]]
    rows = [fx.candidate("synthetic.tif", bbox=footprint, size=source["bytes"],
                         source_hash=source["sha256"])]
    catalog = fx.frozen_catalog(rows)
    catalog_path = tmp_path / "catalog.json"
    sha = fx.write_catalog(catalog_path, catalog)
    selection = fx.window_set(rows[0]["source_id"], source, expected,
                              tiling=fx.tiling(width, height, anchor=anchor, cell=cell))
    plan = fx.plan(catalog, sha, [selection], bbox=segment,
                   budget=dict(fx.BUDGET, bytes=20_000_000), max_total_bytes=20_000_000)

    allow = Allowlist([fx.HOST])
    root = tmp_path
    dry = bridge.dry_run(root, catalog_path, plan, tmp_path / "dry", allowlist=allow)
    assert [w["window"] for w in dry["would_enqueue"]] == expected
    assert [w["window_index"] for w in dry["would_enqueue"]] == [0]
