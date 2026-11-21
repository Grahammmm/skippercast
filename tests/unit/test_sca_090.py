"""Replay the bottom-view compiler with tiny private GeoTIFFs, not survey data."""
import base64
import hashlib
import json
import sys

import pytest

pytestmark = pytest.mark.gis

HELD = {"PointBuchon": "usgs-point-buchon", "MorroBay": "usgs-morro-bay",
        "PointEstero": "usgs-point-estero"}
UNKNOWN = "unverified source datum"
BOTTOM = "regions/test/bottom"


@pytest.fixture
def build(tmp_path, monkeypatch):
    import numpy as np
    import rasterio
    from pyproj import Transformer
    from rasterio.transform import from_origin

    from research.scripts import build_bottom_views as compiler

    def seed(held=True):
        repo = tmp_path / "repo"
        atlas = repo / "dist/atlas.json"
        atlas.parent.mkdir(parents=True)
        profiles = HELD if held else {"Qualified": "qualified-synthetic"}
        region = {"id": "morro-bay" if held else "qualified-control",
                  "assets": {"atlas": "atlas.json", "bottom_index": f"{BOTTOM}/index.json"},
                  "source_bindings": {"bathymetry": list(profiles.values())}}
        datum = UNKNOWN if held else "MLLW"
        lon, lat = Transformer.from_crs(32610, 4326, always_xy=True).transform(500001, 1000001)
        targets, manifest, sources, pins = [], {}, {}, {}
        for i, (name, ident) in enumerate(profiles.items()):
            path = tmp_path / f"fixture-{i}.tif"
            values = np.array([[-10.1 - i, -9999], [-12.3, -13.2]], dtype="float32")
            with rasterio.open(path, "w", driver="GTiff", width=2, height=2, count=1,
                               dtype=values.dtype, crs="EPSG:32610", nodata=-9999,
                               transform=from_origin(500000, 1000002, 2, 2)) as grid:
                grid.write(values, 1)
            pins[name] = (ident, hashlib.sha256(path.read_bytes()).hexdigest())
            manifest[name] = {"source_id": ident, "path": str(path), "survey_year": 2008,
                              "vertical_datum": datum}
            sources[ident] = {"review_status": "approved", "documentation_url": "https://example.com/grid",
                              "vertical_datum": None if held else datum}
            targets.append({"id": f"test-{i}", "source_id": name, "longitude": lon, "latitude": lat,
                            "research_only": held})
        atlas.write_text(json.dumps({"targets": targets}))
        monkeypatch.setattr(compiler, "REPO", repo)
        monkeypatch.setattr(compiler, "load_catalogs", lambda: ({}, sources))
        monkeypatch.setattr(compiler, "load_region", lambda _: region)
        if held:
            monkeypatch.setattr(compiler, "MORRO_PRODUCTS", pins)
        manifest_path = tmp_path / "manifest.json"
        held_output = tmp_path / "private"

        def run(private=held):
            manifest_path.write_text(json.dumps({"sources": manifest}))
            flags = ["--held-output", str(held_output)] if private else []
            monkeypatch.setattr(sys, "argv", ["build_bottom_views", "--region", region["id"],
                                               "--manifest", str(manifest_path), *flags])
            compiler.main()

        return run, manifest, atlas, held_output if held else repo / "dist"

    return seed


@pytest.mark.parametrize("name", HELD)
def test_mllw_conflict_refuses_before_any_output(build, name):
    run, manifest, atlas, output = build()
    manifest[name]["vertical_datum"] = "MLLW"
    with pytest.raises(ValueError, match="reviewed raster datum"):
        run()
    assert not output.exists()
    assert not (atlas.parent / BOTTOM).exists()


@pytest.mark.parametrize("conflict", ["bytes", "binding", "output"])
def test_other_held_conflicts_refuse_before_output(build, conflict):
    run, manifest, atlas, output = build()
    last = manifest["PointEstero"]
    if conflict == "bytes":
        last["path"] = manifest["PointBuchon"]["path"]  # valid raster, different product
        message = "SHA-256 differs"
    elif conflict == "binding":
        last["source_id"] = "usgs-point-buchon"  # approved, but not this atlas source
        message = "product binding"
    else:
        message = "require private --held-output"
    with pytest.raises(ValueError, match=message):
        run(private=conflict != "output")
    assert not output.exists()
    assert not (atlas.parent / BOTTOM).exists()


@pytest.mark.parametrize("held", [True, False])
def test_rebuild_keeps_values_masks_and_evidence_limits(build, held):
    import numpy as np

    run, manifest, atlas, output = build(held)
    original_atlas = atlas.read_bytes()
    run()
    index = json.loads((output / BOTTOM / "index.json").read_bytes())
    assert len(index["views"]) == len(manifest)
    for i, spec in enumerate(manifest.values()):
        ident = spec["source_id"]
        record = index["views"][f"test-{i}"]
        raw = (output / record["path"]).read_bytes()
        tile = json.loads(raw)
        assert record["sha256"] == hashlib.sha256(raw).hexdigest()
        assert record["source_id"] == tile["source_id"] == ident
        assert tile["source_sha256"] == index["sources"][ident]["sha256"]
        assert tile["vertical_datum"] == (UNKNOWN if held else "MLLW")
        assert record["status"] == ("research_only" if held else "surveyed")
        if held:
            assert record["research_only"] is tile["research_only"] is True
            assert record["vertical_datum"] == tile["vertical_datum"]
        else:
            assert "research_only" not in record and "research_only" not in tile
        assert not any(row.get(key) for row in (record, tile) for key in ("fishing_target", "exportable"))
        levels = np.frombuffer(base64.b64decode(tile["elevations"]), dtype="<i2").reshape(129, 129)
        assert levels[64:66, 64:66].tolist() == [[-101 - i * 10, -32768], [-123, -132]]
        assert np.count_nonzero(levels != -32768) == 3
    assert atlas.read_bytes() == original_atlas
    if held:
        assert not (atlas.parent / BOTTOM).exists()
