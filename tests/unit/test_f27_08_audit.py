"""F27-08: a tile is listed as occupied only after an exact polygon hit, not a bbox hit."""
import importlib.util
import json
from types import SimpleNamespace

import pytest

from tests._support import ROOT

np = pytest.importorskip("numpy")
pytest.importorskip("laspy")
pytest.importorskip("shapefile")
pyproj = pytest.importorskip("pyproj")
shapely_geometry = pytest.importorskip("shapely.geometry")
Transformer = pyproj.Transformer

SCRIPT = ROOT / "research/scripts/audit_monterey_noaa2612_acoustic_points.py"
spec = importlib.util.spec_from_file_location("audit_monterey_noaa2612_acoustic_points", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

TILE = "synthetic-tile.copc.laz"
OUTER = [(-121.90, 36.600), (-121.88, 36.600), (-121.88, 36.620), (-121.90, 36.620)]
HOLE = [(-121.895, 36.605), (-121.885, 36.605), (-121.885, 36.615), (-121.895, 36.615)]
HOLE_POINT = (-121.890, 36.610)
RIM_POINT = (-121.8975, 36.6025)  # inside the outer ring, outside the hole
IDS = [f"o{i}" for i in range(17)]


def utm(point):
    return Transformer.from_crs("EPSG:4326", "EPSG:3717", always_xy=True).transform(*point)


class FakeReader:
    def iterShapeRecords(self):
        bbox = [utm(OUTER[0])[0] - 1000, utm(OUTER[0])[1] - 1000, utm(OUTER[2])[0] + 1000, utm(OUTER[2])[1] + 1000]
        yield SimpleNamespace(record=[TILE, "EPSG:3717", module.BASE + TILE], shape=SimpleNamespace(bbox=bbox))


def fake_handle(points):
    xs, ys = zip(*(utm(point) for point in points))
    cloud = SimpleNamespace(x=np.array(xs), y=np.array(ys), z=np.full(len(points), -70.0),
                            classification=np.full(len(points), 13), point_source_id=np.full(len(points), 7))
    crs = SimpleNamespace(sub_crs_list=[SimpleNamespace(to_epsg=lambda: 3717), SimpleNamespace(to_epsg=lambda: 5703)])
    return SimpleNamespace(header=SimpleNamespace(parse_crs=lambda: crs), read=lambda: cloud)


class FakeOpen:
    def __init__(self, points):
        self.handle = fake_handle(points)

    def __call__(self, path):
        return self

    def __enter__(self):
        return self.handle

    def __exit__(self, *exc):
        return None


def run(tmp_path, monkeypatch, points):
    receipts = tmp_path / "research/receipts"
    receipts.mkdir(parents=True)
    (receipts / "monterey-300-source-evidence-matrix.json").write_text(json.dumps({
        "outline_count": 17,
        "review_order": [{"context_id": i, "historical_rockfish_positive_windows": 0,
                          "mapped_protected_area_or_gea_buffer": False, "mapped_enc_danger_buffer": False}
                         for i in IDS]}))
    geometry = {"type": "Polygon", "coordinates": [OUTER + [OUTER[0]], HOLE + [HOLE[0]]]}
    (receipts / "usgs-offshore-monterey-hard-context.geojson").write_text(json.dumps({
        "features": [{"properties": {"id": i}, "geometry": geometry} for i in IDS]}))
    monkeypatch.setattr(module, "TILE_SHA", {TILE: "0" * 64})
    monkeypatch.setattr(module, "read_pinned", lambda *a, **k: None)
    monkeypatch.setattr(module, "index_reader", lambda path: FakeReader())
    monkeypatch.setattr(module.laspy, "open", FakeOpen(points))
    return module.build(tmp_path)


def test_point_in_hole_has_bbox_membership_but_no_occupied_tile(tmp_path, monkeypatch):
    report = run(tmp_path, monkeypatch, [HOLE_POINT])
    for row in report["outlines"]:
        assert row["intersecting_tiles"] == [TILE]
        assert row["tiles_with_any_points_in_outline"] == []
        assert row["class13_acoustic_points"] == 0


def test_interior_point_lists_the_tile(tmp_path, monkeypatch):
    report = run(tmp_path, monkeypatch, [HOLE_POINT, RIM_POINT])
    for row in report["outlines"]:
        assert row["intersecting_tiles"] == [TILE]
        assert row["tiles_with_any_points_in_outline"] == [TILE]
        assert row["class13_acoustic_points"] == 1
