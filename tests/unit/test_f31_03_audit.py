"""F31-03: the San Simeon geology rebuild is bound to the reviewed ZIP digest and metric CRS."""
import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.gis

ROOT = Path(__file__).resolve().parents[2]
SQ = [(700000, 3940000), (700400, 3940000), (700400, 3940400), (700000, 3940400), (700000, 3940000)]


@pytest.fixture
def mod():
    spec = importlib.util.spec_from_file_location("import_usgs_geology", ROOT / "research/scripts/import_usgs_geology.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def make_zip(path, epsg):
    import shapefile
    from pyproj import CRS

    streams = {k: io.BytesIO() for k in ("shp", "shx", "dbf")}
    w = shapefile.Writer(**streams, shapeType=shapefile.POLYGON)
    w.field("MapUnitAbb", "C", size=16)
    w.field("UnitType", "C", size=32)
    w.poly([SQ])
    w.record("Tus", "Unit")
    w.close()
    with zipfile.ZipFile(path, "w") as z:
        for k, s in streams.items():
            z.writestr("Geology_SanSimeon." + k, s.getvalue())
        z.writestr("Geology_SanSimeon.prj", CRS.from_epsg(epsg).to_wkt())
    return path


def setup(mod, tmp_path, monkeypatch, epsg, digest=None):
    archive = make_zip(tmp_path / "g.zip", epsg)
    good = hashlib.sha256(archive.read_bytes()).hexdigest()
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps({"archive_sha256": digest or good, "shapefile_crs": "EPSG:32610"}))
    dist = tmp_path / "dist"
    (dist / "r").mkdir(parents=True)
    (dist / "r/mpa.json").write_text(json.dumps({"type": "FeatureCollection", "features": []}))
    region = {"id": "r", "source_bindings": {"substrate": ["usgs-san-simeon"]},
              "fishing_bounds": [-121.5, 35.0, -120.5, 36.0],
              "assets": {"protected_areas": "r/mpa.json", "geology": "r/geology.geojson"}}
    monkeypatch.setattr(mod, "REPO", tmp_path)
    monkeypatch.setattr(mod, "CATALOG", cat)
    monkeypatch.setattr(mod, "load_region", lambda _id: region)
    monkeypatch.setattr("sys.argv", ["x", "--region", "r", "--zip", str(archive)])
    return dist / "r/geology.geojson", good


def test_accepted_fixture_keeps_non_target_output(mod, tmp_path, monkeypatch):
    out, good = setup(mod, tmp_path, monkeypatch, 32610)
    mod.main()
    data = json.loads(out.read_text())
    assert data["source"]["sha256"] == good
    assert data["features"]
    assert all(f["properties"]["fishing_target"] is False and f["properties"]["depth_qualified"] is False
               for f in data["features"])


def test_different_digest_stops_before_dist(mod, tmp_path, monkeypatch):
    out, _ = setup(mod, tmp_path, monkeypatch, 32610, digest="0" * 64)
    with pytest.raises(ValueError, match="digest"):
        mod.main()
    assert not out.exists()


@pytest.mark.parametrize("epsg", [26910, 4326, 2227])
def test_incompatible_projection_stops_before_dist(mod, tmp_path, monkeypatch, epsg):
    out, _ = setup(mod, tmp_path, monkeypatch, epsg)
    with pytest.raises(ValueError, match="metric CRS"):
        mod.main()
    assert not out.exists()
