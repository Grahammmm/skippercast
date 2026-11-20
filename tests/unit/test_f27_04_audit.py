"""F27-04: bound each beam-hit cell count by its matching reference population."""

from contextlib import nullcontext
import json

import pytest

pytestmark = pytest.mark.gis


@pytest.mark.parametrize(
    ("second_elevation", "reference_class", "rejects"),
    [(-110, 3, False), (-80, 3, True), (-110, 2, True)],
    ids=["two-centers-one-in-band", "in-band-overcount", "class3-overcount"],
)
def test_beam_join_bounds(tmp_path, monkeypatch, second_elevation, reference_class, rejects):
    import numpy as np
    from pyproj import Transformer
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin
    from shapely.geometry import box, mapping
    from shapely.ops import transform

    from research.scripts import audit_monterey_2009_beam_usgs_cells as audit
    from research.scripts.audit_usgs_monterey_300_paired import paired_count

    # The first cell receives two hits. A beam in the last cell is inside the
    # outline, but its in-band cell center is outside and must not be counted.
    x, y = 500000, 1000
    to_geo = Transformer.from_crs("EPSG:26910", "EPSG:4326", always_xy=True).transform
    polygon = transform(to_geo, box(x, y - 2, x + 4.5, y))
    outline_counts = {"valid_beams_inside_outline": 4}
    reviews = {
        "monterey-2009-centralmontereybay-valid-beam-review.json": {
            "scope": "monterey-2009-centralmontereybay-original-valid-beam-research",
            "fishing_target": False,
            "outlines": {"test": {"context_id": "test", **outline_counts}},
            "lines": [{"ncei_file_id": "test", "outlines": {"test": outline_counts}}],
        },
        "monterey-300-source-evidence-matrix.json": {"review_order": [
            {"context_id": "test", **paired_count(np.array([[-70, -110]]),
                                                  np.array([[reference_class, 2]]))},
        ]},
        "usgs-offshore-monterey-hard-context.geojson": {"features": [
            {"properties": {"id": "test"}, "geometry": mapping(polygon)},
        ]},
    }
    receipts = tmp_path / "research/receipts"
    receipts.mkdir(parents=True)
    for name, document in reviews.items():
        (receipts / name).write_text(json.dumps(document))

    def decode_line(*args, collect):
        for offset in (1, 1, 3, 4.25):
            collect("test", *(np.array([v]) for v in to_geo(x + offset, y - 1)), np.array([71.0]))
        return None, {"test": outline_counts}, None, None

    monkeypatch.setattr(audit, "PROCESSED", {"synthetic": ("test", None, None, None)})
    monkeypatch.setattr(audit, "read_pinned", lambda *args: b"")
    monkeypatch.setattr(audit, "decode_line", decode_line)
    monkeypatch.setattr(audit, "ensure_archive", lambda *args: None)
    monkeypatch.setattr(audit, "original_tiff", lambda path: path)
    profile = dict(driver="GTiff", height=1, width=3, count=1, transform=from_origin(x, y, 2, 2))
    with MemoryFile() as depths, MemoryFile() as classes:
        with depths.open(**profile, crs="EPSG:26910", dtype="float32") as bathy:
            bathy.write(np.array([[-70, second_elevation, -75]], dtype="float32"), 1)
        with classes.open(**profile, crs="EPSG:32610", dtype="uint8") as character:
            character.write(np.array([[3, 2, 2]], dtype="uint8"), 1)
        rasters = {"Bathymetry_2m_OffshoreMonterey.zip": depths,
                   "SeafloorCharacter_2m_OffshoreMonterey.zip": classes}
        monkeypatch.setattr(audit.rasterio, "open", lambda path: rasters[path.name].open())
        # The synthetic character cells are already aligned by index.
        monkeypatch.setattr(audit, "WarpedVRT", lambda raster, **kwargs: nullcontext(raster))
        if rejects:
            with pytest.raises(ValueError, match="Beam-to-cell join exceeds original measured outline cells"):
                audit.build(tmp_path)
        else:
            row = audit.build(tmp_path)["outlines"]["test"]
            assert row["unique_usgs_2m_cell_centers_inside_outline_under_source_beams"] == 2
            assert row["unique_paired_class3_band_cells_under_source_beams"] == 1
