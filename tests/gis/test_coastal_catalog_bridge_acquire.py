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
