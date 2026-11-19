"""F05-05: the runner must check tiles the bridge plan did not submit."""
import hashlib

import pytest

from skippercast.coastal.coordinator import bridge_run, catalog_bridge
from skippercast.coastal.coordinator.stages import digest
from skippercast.coastal.handoff.common import write
from tests import _coastal_catalog_fixture as fx
from tests._support import FakeClock


@pytest.mark.gis
@pytest.mark.parametrize("omit_second", [False, True], ids=["complete", "omission"])
def test_projected_window_set_requires_both_native_tiles(tmp_path, omit_second):
    from pyproj import Transformer
    from shapely.geometry import Polygon, box

    root = tmp_path / "synthetic"
    namespace = "queue:synthetic"
    p = root / "plans/plan01"
    p.mkdir(parents=True)
    record = bridge_run.segment(0, 0, region=root.name)
    inverse = Transformer.from_crs("EPSG:3310", "OGC:CRS84", always_xy=True)
    bbox = list(inverse.transform_bounds(*record["bbox"], densify_pts=41))
    record.update(synthetic=True, bbox_crs84=bbox)
    write(p / "segment.json", record)
    write(root / "campaign.json", dict(campaign_segment_id=root.name, bbox_crs84=bbox))

    # Native projected metres, with a non-zero origin and a clipped edge tile.
    # Both footprints are well inside the synthetic segment (not touch-only).
    tiles = [[8, 4, 512, 512], [520, 4, 380, 512]]
    for x, y, width, height in tiles:
        polygon = Polygon([inverse.transform(500 + 2*col, 4000 - 2*row)
                           for col, row in ((x, y), (x+width, y), (x+width, y+height), (x, y+height))])
        assert box(*bbox).contains(polygon)
    # Changing only the degree hint makes an omitted tile look complete to the bridge.
    cell = 1.0 if omit_second else 0.00002
    anchor = inverse.transform(516, 3992)
    tiling = fx.tiling(900, 516, origin=(8, 4), anchor=anchor, cell=(cell, cell))
    chosen = tiles[:1] if omit_second else tiles
    source = fx.cache_file(root, "cache/synthetic.tif")  # metadata-only, never opened as a raster
    row = fx.candidate("synthetic.tif", bbox=bbox, size=source["bytes"], source_hash=source["sha256"])
    catalog = fx.frozen_catalog([row])
    sha = fx.write_catalog(root / "catalog.json", catalog)
    source_id = row["source_id"]
    plan = fx.plan(catalog, sha, [fx.window_set(source_id, source, chosen, tiling)],
                   segment_id=record["segment_id"], bbox=bbox)
    write(p / "plan.json", plan)
    now = FakeClock().timestamp()
    catalog_bridge.dry_run(root, root / "catalog.json", plan, p / "dry", now=now)
    bridge: dict = catalog_bridge.run(root, root / "catalog.json", plan, p / "bridge", now=now)
    assert [job["window"] for job in bridge["jobs"]] == chosen

    definition = dict(source_sha256=source["sha256"], raster_crs="EPSG:3310", affine_transform=[2, 0, 500, 0, -2, 4000],
                      width=900, height=516, tile_width=512, tile_height=512, tiling_version="window-set-v1", tiling=tiling)
    grid_sha = digest(definition)
    windows = []
    for index, tile in enumerate(chosen):
        key = f"{source_id}#{grid_sha}#{index}"
        windows.append(dict(source_id=source_id, grid_sha256=grid_sha, idx=index, window_key=key,
                            window_dir=hashlib.sha256(key.encode()).hexdigest(), pixel_window=tile,
                            owner_segment_id=record["segment_id"]))
    paths = dict(campaign=root/"campaign.json", segment_record=p/"segment.json", plan_file=p/"plan.json",
                 catalog=root/"catalog.json", dry_run=p/"dry/bridge-dry-run-receipt.json")
    admission = dict(schema="coast-admission-v1", campaign_segment_id=root.name, coordinator_segment_id=record["segment_id"],
                     plan_id=p.name, plan_sha256=digest(plan), holds=[],
                     preconditions=dict(exclusive_writer=True, attested_by="synthetic-test-operator"),
                     windows=windows, grids=[dict(source_id=source_id, grid_sha256=grid_sha, definition=definition,
                                                  cols=len(chosen), rows=1, total=len(chosen))],
                     **{name: bridge_run._ref(root, path, namespace) for name, path in paths.items()})
    write(p / "admission.json", admission)
    args = root, p/"admission.json", p/"bridge/bridge-receipt.json", p/"segment.json"
    if omit_second:
        with pytest.raises(ValueError, match="native window-set completeness:.*row-major"):
            bridge_run._context(*args)
    else:
        admitted, *_ = bridge_run._context(*args)
        assert [win["pixel_window"] for win in admitted["windows"]] == tiles
