"""F33-10 fixture: one validated tile read must preserve both report signatures.

Run ``python -m tests.unit.test_f33_10_audit`` to replay the read-only baseline
without test-local sharing. Pytest compares signatures with the baseline but
only requires the decode budget of the positive reference, until SCA-521.
"""

from collections import Counter
from contextlib import contextmanager
from hashlib import sha256
from inspect import signature
from pathlib import Path
from tempfile import TemporaryDirectory
import xml.etree.ElementTree as ET

import pytest

pytestmark = pytest.mark.gis


def tile_fixture(root, patch):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    from research.scripts import audit_nbs_modeling_tile as audit
    from research.scripts import screen_usgs_map_nbs_overlap as overlap

    tile, rat, original, scheme = (root / name for name in (
        "synthetic.tiff", "synthetic.tiff.aux.xml", "classes.tif", "scheme.gpkg",
    ))
    grid = dict(driver="GTiff", crs="EPSG:3857+5866", transform=from_origin(0, 4, 4, 4),
                width=4, height=1)
    # Qualified hard, qualified non-hard, unqualified hard, qualified hard.
    with rasterio.open(tile, "w", count=3, dtype="float32", **grid) as raster:
        raster.descriptions = ("Elevation", "Uncertainty", "Contributor")
        raster.write(np.array([[[-40] * 4], [[0.5, 0.5, 2, 0.5]], [[1, 1, 2, 2]]], dtype="float32"))
    with rasterio.open(original, "w", count=1, dtype="uint8", nodata=0, **grid) as raster:
        raster.write(np.array([[7, 8, 7, 7]], dtype="uint8"), 1)

    table = ET.Element("GDALRasterAttributeTable")
    for name in ("value", "coverage", "bathy_coverage", "source_survey_id", "survey_date_end"):
        ET.SubElement(ET.SubElement(table, "FieldDefn"), "Name").text = name
    for value in (1, 2):
        row = ET.SubElement(table, "Row")
        for field in (str(value), "1", "1", f"synthetic-{value}", "2020-01-01"):
            ET.SubElement(row, "F").text = field
    ET.ElementTree(table).write(rat)
    scheme.write_bytes(b"synthetic scheme identity")

    def digest(path):
        return sha256(path.read_bytes()).hexdigest()

    lead = {"tile": "synthetic", "GeoTIFF_Link": "https://example.invalid/tile",
            "RAT_Link": "https://example.invalid/rat", "Delivered_Date": "2020-01-01",
            "GeoTIFF_SHA256_Checksum": digest(tile), "RAT_SHA256_Checksum": digest(rat)}
    source = {"block_id": "synthetic", "kind": "seafloor_character", "status": "ok",
              "archive_sha256": "a" * 64, "metadata_sha256": "b" * 64,
              "original_class_table_sha256": "c" * 64, "class_table_status": "verified",
              "original_class_table": [{"value": 7, "count": 3, "substrate_class": 3},
                                       {"value": 8, "count": 1, "substrate_class": 1}],
              "class_counts": {"7": 3, "8": 1}}
    native = {"scope": "usgs-state-waters-native-grid-audit", "fishing_target": False, "products": [source]}
    # Replace jurisdiction/archive lookup only. Keep NOAA byte verification, RAT parsing,
    # actual raster decoding and warping, qualification, and receipt construction real.
    patch.setattr(overlap, "original_character", lambda *_: original)
    patch.setattr(overlap, "intersecting_scheme_rows", lambda *_args, **_kw: [lead])
    patch.setattr(audit, "scheme_row", lambda *_: lead)

    def run(*, shared):
        calls, memo, audit_reports = Counter(), {}, []
        open_raster, parse, mask, verify = rasterio.open, audit.contributors, audit.qualified_mask, audit.verified_file

        def observe(name, key, work):
            if shared and key in memo:
                return memo[key]
            calls[name] += 1
            result = work()
            if shared:
                memo[key] = result
            return result

        class ObservedTile:
            def __init__(self, dataset):
                self.dataset = dataset

            def __getattr__(self, name):
                return getattr(self.dataset, name)

            def read(self):
                # The entire 1×4, three-band fixture is one bounded window.
                return observe("decode", ("tile", tile), lambda: tuple(self.dataset.read()))

        @contextmanager
        def open_tile(path, *args, **kw):
            with open_raster(path, *args, **kw) as dataset:
                yield ObservedTile(dataset) if path == tile else dataset

        def parse_once(path):
            return observe("parse", ("rat", path), lambda: parse(path))

        def qualify_once(elevation, uncertainty, contributor, rows, **kw):
            bound = signature(mask).bind(elevation, uncertainty, contributor, rows, **kw)
            bound.apply_defaults()
            key = ("mask", tuple(map(id, bound.args)), tuple(sorted(bound.kwargs.items())))
            return observe("mask", key, lambda: mask(*bound.args, **bound.kwargs))

        def verify_source(url, expected, path, fetch):
            calls[path.name] += 1
            assert not fetch
            return verify(url, expected, path, fetch)

        def record_audit(*args, **kw):
            audit_reports.append(audit.audit(*args, **kw))
            return audit_reports[-1]

        with patch.context() as local:
            local.setattr(rasterio, "open", open_tile)
            for module in (audit, overlap):
                local.setattr(module, "contributors", parse_once)
                local.setattr(module, "qualified_mask", qualify_once)
            local.setattr(audit, "verified_file", verify_source)
            local.setattr(overlap, "audit_tile", record_audit)
            report = overlap.signature(overlap.screen(native, {}, "synthetic", "a" * 64, scheme, root, root))
        tile_report, = audit_reports
        tile_report.pop("reviewed_at")
        assert tile_report["counts"] == {"depth_25_to_200_ft_pixels": 4, "measured_depth_pixels": 4,
                                          "recent_measured_depth_pixels": 4, "qualified_screen_pixels": 3}
        assert [row["pixels"] for row in tile_report["qualified_contributors"]] == [2, 1]
        assert report["noaa_scheme_sha256"] == tile_report["scheme_sha256"] == digest(scheme)
        result, = report["tiles"]
        for field, path in (("raster_sha256", tile), ("rat_sha256", rat)):
            assert result[field] == tile_report[field] == digest(path)
            assert calls[path.name] == 1  # Shared decoding must not remove source verification.
        assert (result["qualified_measured_mllw_pixels"], result["original_rock_class_pixels_at_tile_centers"],
                result["strict_measured_rock_overlap_pixels"]) == (3, 3, 2)
        assert result["source_survey_contributors"] == [
            {"survey_id": f"synthetic-{i}", "survey_date_end": "2020-01-01", "overlap_pixels": 1} for i in (1, 2)
        ]
        return (tile_report, report), {name: calls[name] for name in ("decode", "parse", "mask")}

    return run


def assert_single_pass(work):
    assert work == {"decode": 1, "parse": 1, "mask": 1}, f"one tile pass required; observed {work}"


def test_reusing_one_tile_pass_preserves_signatures(tmp_path, monkeypatch):
    run = tile_fixture(tmp_path, monkeypatch)
    baseline, _ = run(shared=False)
    shared, work = run(shared=True)
    assert_single_pass(work)
    assert shared == baseline  # Full verification signatures, not just overlap totals.


if __name__ == "__main__":
    with TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as patch:
        _, work = tile_fixture(Path(directory), patch)(shared=False)
        print(f"Read-only baseline: {work}; source hashes, counts and tallies passed", flush=True)
        assert_single_pass(work)
