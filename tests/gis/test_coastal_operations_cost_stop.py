"""T12 cost-bound stop through the real stage CLI (rasterio discovery lane).

The coordinator dispatches the repository's fixed ``stage_cli`` discover stage
against a tiny synthetic EPSG:3310 GeoTIFF inside the queue root. Discovery
completes and emits its acquire successor, which inherits the 100 B chain
reservation; the 150 B mission cap leaves 50 B, so the successor is held at the
cap before any lease, reservation or process exists for it. No network, no
native survey source: the raster is synthetic and marked so.
"""
import json

import numpy as np
from pyproj import Transformer
import pytest
import rasterio
from rasterio.transform import from_origin

from skippercast.coastal.coordinator.loop import byte_ref
from skippercast.coastal.coordinator.segments import segment
from skippercast.coastal.handoff.common import ref
from tests._coastal_operations import REGION, Harness, export_package, policy


@pytest.fixture
def ops(tmp_path, tmp_path_factory):
    harness = Harness(tmp_path, export_package(tmp_path_factory.mktemp("package-export")),
                      real_stages=True, policy_value=policy(budgets={"bytes": 150}))
    yield harness
    harness.close()


def _synthetic_discovery_plan(ops):
    record = segment(-200000, -50000, region=REGION)
    inverse = Transformer.from_crs("EPSG:3310", "OGC:CRS84", always_xy=True)
    record["bbox_crs84"] = list(inverse.transform_bounds(*record["bbox"], densify_pts=21))
    record["synthetic"] = True
    raster = ops.root / "sources/synthetic-depth.tif"
    raster.parent.mkdir(parents=True)
    west, south, east, north = record["bbox"]
    with rasterio.open(raster, "w", driver="GTiff", width=4, height=4, count=1, dtype="float32",
                       crs="EPSG:3310", transform=from_origin(west + 1000, north - 1000, 250, 250)) as ds:
        ds.write(np.full((1, 4, 4), -20.0, dtype="float32"))
    candidate = {"source": ref(ops.root, raster, "native-raster-v1"), "window": [0, 0, 4, 4]}
    plan = ops.root / "plans/discovery.json"
    plan.parent.mkdir(parents=True)
    plan.write_text(json.dumps({"schema": "coastal-local-discovery-plan-v1", "synthetic": True,
                                "segment_id": record["segment_id"], "candidates": [candidate]}))
    return record, byte_ref(ops.root, plan, kind="plan", contract="coastal-local-discovery-plan-v1")


def test_real_discovery_successor_is_held_at_byte_cap(ops):
    record, plan = _synthetic_discovery_plan(ops)
    ops.store.add_segment(record)
    discover = ops.store.enqueue(record["segment_id"], "discover", code_sha=ops.code, deps_sha=ops.deps,
                                 input_manifest=plan,
                                 budget={"wall_s": 120, "memory_bytes": 4 * 1024**3, "bytes": 100, "requests": 0})

    assert [r["state"] for r in ops.run(seconds=150)] == ["done", "idle"]

    jobs = {row["stage"]: dict(row) for row in ops.store.db.execute("SELECT * FROM jobs")}
    assert set(jobs) == {"discover", "acquire"}
    assert jobs["discover"]["job_id"] == discover and jobs["discover"]["state"] == "done"
    produced = {row["kind"] for row in ops.store.db.execute(
        "SELECT kind FROM artifacts WHERE produced_by_job=?", (discover,))}
    assert produced == {"coastal-local-discovery-v1", "coastal-native-job-v1"}
    receipt_path = ops.store.db.execute("SELECT path FROM artifacts WHERE produced_by_job=? AND kind=?",
                                        (discover, "coastal-local-discovery-v1")).fetchone()[0]
    receipt = json.loads((ops.root / receipt_path).read_text())
    assert len(receipt["leads"]) == 1 and receipt["synthetic"] is True
    # The real stage ran source-only from the export; it cached no bytecode there.
    assert not list(ops.export.rglob("__pycache__"))

    acquire = jobs["acquire"]
    assert acquire["state"] == "held" and json.loads(acquire["holds_json"]) == ["budget_exhausted"]
    assert acquire["attempts"] == 0 and ops.lease(acquire["job_id"]) is None
    assert not ops.job_dir(acquire["job_id"]).exists()
    ledger = ops.ledger()
    assert [e["candidate"] for e in ledger["reservations"].values()] == [discover]
    assert ledger["charged"]["bytes"] == 100 == ops.effective_bytes() <= ops.policy["budgets"]["bytes"]
