"""Publication integrity and fail-closed fixtures for a limited surveyed subset."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skippercast.platform.bottom_targets import VERSION
from skippercast.platform.qualified_scope import (
    validate_qualified_scope, qualified_subset_satisfies, _intersects, _polygons)


def polygon(west, south, east, north):
    return {"type": "Polygon", "coordinates": [[[west, south], [east, south],
             [east, north], [west, north], [west, south]]]}


class QualifiedScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.rid = "test-coast"
        self.base = "regions/test-coast/"
        self.folder = self.root / "dist" / self.base / "qualified-bottom"
        self.tid, self.aid = "TEST-Q-a123456789", "TEST-Q-AREA-a123456789"
        self.spec = {"id": "NOAA-TEST", "url": "https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/test.bag",
                     "sha256": "a" * 64, "bytes": 100, "vertical_datum": "MLLW",
                     "documentation_url": "https://data.ngdc.noaa.gov/test.pdf", "survey_start": "2017-01-01",
                     "horizontal_crs": "EPSG:26911", "qualification_resolution_limit_m": 4}
        self.catalog = {"noaa-test": {"review_status": "approved", "adapter": "noaa-native-vr-bag",
                        "pinned_sha256": self.spec["sha256"], "access_url": self.spec["url"],
                        "vertical_datum": "MLLW", "qualified_resolution_limit_m": 4,
                        "bounds": [-121, 33, -117, 35]}, "mpa": {"review_status": "approved"}}
        self.region = {"id": self.rid, "assets": {"target_qualification": self.base + "qualified-bottom/manifest.json",
                       "bottom_index": self.base + "bottom-index.json", "protected_areas": self.base + "protected.geojson",
                       "closures": self.base + "closures.geojson"}, "source_bindings": {"bathymetry": ["noaa-test"],
                       "protected-areas": ["mpa"]}, "coverage": {"protected-areas": {"status": "ready"}},
                       "boat": {"bottom_depth_limit_ft": 200}, "fishing_bounds": [-121, 33, -117, 35]}
        self.habitat = {"schema_version": 1, "region_id": self.rid, "type": "FeatureCollection", "features": []}
        hp = "dist/" + self.base + "habitat.geojson"
        hd = self.write(hp, self.habitat)
        self.closures = {}
        closure_receipts = []
        for key, x in (("protected_areas", -120.8), ("closures", -120.5)):
            path = "dist/" + self.region["assets"][key]
            value = {"region_id": self.rid, "type": "FeatureCollection", "checked_at": "2020-01-01T00:00:00Z",
                     "source_url": "https://official.example/" + key,
                     "features": [{"type": "Feature", "geometry": polygon(x, 34.4, x + .1, 34.6)}]}
            receipt = self.write(path, value)
            self.closures[path] = value
            closure_receipts.append({"path": path, "checked_at": value["checked_at"], "sha256": receipt["sha256"],
                                     "features": 1, "source_url": value["source_url"]})
        self.config = {"schema_version": 1, "region_id": self.rid, "status": "reviewed", "target_prefix": "TEST-Q",
                       "depth_limit_ft": 200, "minimum_depth_ft": 25, "planning_margin_m": 2,
                       "maximum_product_uncertainty_m": 1, "maximum_native_cell_m": 4, "closure_clearance_m": 75,
                       "habitat_path": hp, "habitat_sha256": hd["sha256"], "sources": [self.spec],
                       "closure_inputs": [{"path": p, "minimum_features": 1} for p in self.closures]}
        config_receipt = self.write("regions/test-coast/bottom-sources.reviewed.json", self.config)
        source = {**self.spec, "url": self.spec["documentation_url"], "native_data_url": self.spec["url"],
                  "survey_year": 2017, "datum": "MLLW"}
        q = {"policy": VERSION, "native_datum": "MLLW", "full_geometry_screened": True, "verified_catches": False,
             "planning_margin_m": 2, "maximum_product_uncertainty_m": 1, "closure_clearance_m": 75,
             "native_resolution_limit_m": 4, "max_depth_including_uncertainty_and_margin_ft": 120,
             "source_cell_count_in_outline": 100}
        validation = {"datum": "MLLW", "missing_depth": False, "minimum_ft": 80, "maximum_ft": 110,
                      "closure_clearance_m": 1000}
        target = {"id": self.tid, "source_id": self.spec["id"], "qualification": deepcopy(q),
                  "recorded_validation": deepcopy(validation), "depth_qualified": True, "fishing_target": True,
                  "fishing_export": True, "vertical_datum": "MLLW", "drift_id": None,
                  "rating": {"score_type": "uncalibrated-habitat-rank", "catch_probability": None},
                  "native_resolution_range_m": [1, 4], "analysis_cell_m": 4,
                  "longitude": -119, "latitude": 34, "area_ids": [self.aid]}
        area = {"id": self.aid, "source_id": self.spec["id"], "target_ids": [self.tid],
                "qualification": deepcopy(q), "recorded_validation": deepcopy(validation),
                "geometry": polygon(-119.1, 33.9, -118.9, 34.1)}
        self.atlas = {"schema_version": 1, "region_id": self.rid, "edition": VERSION, "fishing_depth_limit_ft": 200,
                      "targets": [target], "areas": [area], "drifts": [], "sources": [source]}
        self.quality = {"schema_version": 1, "region_id": self.rid, "status": "qualified-partial",
                        "transformation_version": VERSION, "config_sha256": config_receipt["sha256"],
                        "habitat_sha256": hd["sha256"], "sources": [source], "closure_receipts": closure_receipts,
                        "source_receipts": [{"url": self.spec["url"], "sha256": self.spec["sha256"], "bytes": 100,
                                             "http_status": 206, "retrieved_at": "2020-01-01T00:00:00Z"}],
                        "target_count": 1, "area_count": 1, "bottom_views": 1,
                        "claims": {"measured_datum": "MLLW", "depth_qualified": True, "catch_calibrated": False,
                                   "boulder_size_measured": False, "complete_island_coverage": False}}
        self.tile = {"schema_version": 1, "region_id": self.rid, "target_id": self.tid, "source_id": self.spec["id"],
                     "source_sha256": self.spec["sha256"], "source_url": self.spec["documentation_url"],
                     "vertical_datum": "MLLW", "horizontal_crs": "EPSG:26911", "depth_qualified": True,
                     "fishing_target": True, "width": 2, "height": 2, "cell_m": 4, "native_cell_m": 1,
                     "encoding": "base64-int16-le", "nodata": -32768, "elevation_unit_m": .1,
                     "coverage_fraction": 1, "elevations": base64.b64encode(b"\x00\x01" * 4).decode()}
        self.views = {"schema_version": 1, "region_id": self.rid, "views": {},
                      "sources": {self.spec["id"]: {"source_id": self.spec["id"], "sha256": self.spec["sha256"],
                                  "url": self.spec["url"], "survey_year": 2017, "vertical_datum": "MLLW"}}}
        self.write_tile()
        self.manifest = {"schema_version": 1, "region_id": self.rid, "status": "ready", "generated_at": "2020-01-01T00:00:00Z",
                         "transformation_version": VERSION, "artifacts": {}}
        self.publish()
        mock = patch("skippercast.platform.qualified_scope.load_catalogs", side_effect=lambda root: ({}, self.catalog))
        mock.start()
        self.addCleanup(mock.stop)

    def write(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(data, allow_nan=False) + "\n").encode()
        target.write_bytes(raw)
        return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

    def write_tile(self):
        path = self.base + "bottom/" + self.tid + ".json"
        receipt = self.write("dist/" + path, self.tile)
        self.views["views"][self.tid] = {"status": "surveyed", "path": path, "source_id": self.spec["id"],
                                         "coverage_fraction": 1, **receipt}

    def publish(self):
        for name, data in (("atlas.json", self.atlas), ("quality.json", self.quality), ("bottom-index-fragment.json", self.views)):
            self.manifest["artifacts"][name] = self.write(self.folder.relative_to(self.root) / name, data)
        self.write(self.folder.relative_to(self.root) / "manifest.json", self.manifest)
        self.write("dist/" + self.region["assets"]["bottom_index"], self.views)

    def validate(self):
        return validate_qualified_scope(self.region, self.atlas, self.root)

    def assert_held(self):
        self.publish()  # Rehash artifacts so semantic defects cannot hide behind a checksum failure.
        with self.assertRaises(ValueError):
            self.validate()

    def test_reviewed_partial_subset_does_not_claim_current_legal_clearance(self):
        result = self.validate()
        self.assertTrue(result["ready"])
        self.assertFalse(result["complete_region_coverage"])
        self.assertFalse(result["current_legal_clearance"])
        self.assertTrue(result["runtime_closure_screen_required"])
        self.assertEqual(result["target_count"], 1)

    def test_absent_asset_remains_unqualified(self):
        self.region["assets"].pop("target_qualification")
        self.assertIsNone(self.validate())

    def test_artifact_hash_and_size_are_required(self):
        path = self.folder / "quality.json"
        path.write_text(path.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.validate()

    def test_wrong_region_each_artifact_is_held_even_when_rehashed(self):
        for document in (self.atlas, self.quality, self.views):
            with self.subTest(document=list(document)):
                document["region_id"] = "foreign-region"
                self.assert_held()
                document["region_id"] = self.rid

    def test_configuration_and_habitat_hashes_are_bound(self):
        for path in ("regions/test-coast/bottom-sources.reviewed.json", self.config["habitat_path"]):
            with self.subTest(path=path):
                content = (self.root / path).read_bytes()
                (self.root / path).write_bytes(content + b" ")
                with self.assertRaises(ValueError):
                    self.validate()
                (self.root / path).write_bytes(content)

    def test_substrate_identity_cannot_be_rehashed_into_another_region(self):
        self.habitat["region_id"] = "foreign-region"
        digest = self.write(self.config["habitat_path"], self.habitat)["sha256"]
        self.config["habitat_sha256"] = self.quality["habitat_sha256"] = digest
        self.quality["config_sha256"] = self.write("regions/test-coast/bottom-sources.reviewed.json", self.config)["sha256"]
        self.assert_held()

    def test_source_requires_approval_binding_url_and_pin(self):
        source = self.catalog["noaa-test"]
        for key, value in (("review_status", "candidate"), ("pinned_sha256", "b" * 64),
                           ("access_url", "https://example.org/other.bag"), ("vertical_datum", "ellipsoid")):
            with self.subTest(key=key):
                previous = source[key]
                source[key] = value
                self.assert_held()
                source[key] = previous
        self.region["source_bindings"]["bathymetry"] = []
        self.assert_held()

    def test_source_receipts_require_exact_set_size_digest_and_status(self):
        original = deepcopy(self.quality["source_receipts"])
        invalid = [[], original + original, [{**original[0], "url": "https://example.org/other"}],
                   [{**original[0], "sha256": "b" * 64}], [{**original[0], "bytes": 99}],
                   [{**original[0], "http_status": 404}], [{**original[0], "retrieved_at": "2020-01-01"}]]
        for receipts in invalid:
            with self.subTest(receipts=receipts):
                self.quality["source_receipts"] = receipts
                self.assert_held()
        self.quality["source_receipts"] = original

    def test_source_provenance_cannot_silently_change(self):
        self.views["sources"][self.spec["id"]]["sha256"] = "b" * 64
        self.assert_held()

    def test_protected_areas_cannot_be_partial_unapproved_or_unbound(self):
        for status in ("partial", "missing", "not-applicable"):
            with self.subTest(status=status):
                self.region["coverage"]["protected-areas"]["status"] = status
                self.assert_held()
        self.region["coverage"]["protected-areas"]["status"] = "ready"
        self.catalog["mpa"]["review_status"] = "candidate"
        self.assert_held()
        self.catalog["mpa"]["review_status"] = "approved"
        self.region["source_bindings"]["protected-areas"] = []
        self.assert_held()

    def test_closure_asset_receipt_set_cannot_be_reduced_or_duplicated(self):
        original = self.quality["closure_receipts"]
        for receipts in (original[:1], original + original[:1]):
            self.quality["closure_receipts"] = receipts
            self.assert_held()
        self.quality["closure_receipts"] = original
        self.region["assets"]["closures"] = self.base + "different.geojson"
        self.assert_held()

    def test_closure_sha_region_counts_source_and_time_must_match(self):
        path = next(iter(self.closures))
        receipt = self.quality["closure_receipts"][0]
        original = deepcopy(self.closures[path])
        for change in ({"region_id": "elsewhere"}, {"features": []}, {"source_url": "https://wrong.example/"},
                       {"checked_at": "2021-01-01T00:00:00Z"}):
            with self.subTest(change=change):
                digest = self.write(path, {**original, **change})["sha256"]
                receipt["sha256"] = digest
                self.assert_held()
        self.write(path, original)
        receipt["sha256"] = "0" * 64
        self.assert_held()

    def test_added_drift_is_not_authorized_by_matching_target_centers(self):
        changed = deepcopy(self.atlas)
        changed["drifts"] = [{"id": "invented-drift"}]
        with self.assertRaises(ValueError):
            validate_qualified_scope(self.region, changed, self.root)
        self.atlas["drifts"] = changed["drifts"]
        self.assert_held()

    def test_target_depth_resolution_datum_and_boolean_claims_fail_closed(self):
        q = self.atlas["targets"][0]["qualification"]
        for key, value in (("full_geometry_screened", 1), ("verified_catches", True), ("native_datum", "unknown"),
                           ("max_depth_including_uncertainty_and_margin_ft", -1),
                           ("max_depth_including_uncertainty_and_margin_ft", 201),
                           ("native_resolution_limit_m", 8), ("planning_margin_m", 0),
                           ("source_cell_count_in_outline", 0)):
            with self.subTest(key=key, value=value):
                previous = q[key]
                q[key] = value
                self.atlas["areas"][0]["qualification"] = deepcopy(q)
                self.assert_held()
                q[key] = previous
        self.atlas["areas"][0]["qualification"] = deepcopy(q)
        self.atlas["targets"][0]["native_resolution_range_m"] = [1, 8]
        self.assert_held()

    def test_target_footprint_links_and_counts_are_exact(self):
        self.atlas["targets"][0]["area_ids"] = []
        self.assert_held()
        self.atlas["targets"][0]["area_ids"] = [self.aid]
        self.atlas["areas"][0]["target_ids"] = ["another-target"]
        self.assert_held()
        self.atlas["areas"][0]["target_ids"] = [self.tid]
        self.quality["target_count"] = 2
        self.assert_held()

    def test_full_footprint_screen_catches_edges_and_containment_not_just_marker(self):
        path = next(iter(self.closures))
        closure = self.closures[path]
        # Marker (-119, 34) is outside, but eastern footprint edge enters this closure.
        closure["features"][0]["geometry"] = polygon(-118.95, 33.95, -118.8, 34.05)
        receipt = self.write(path, closure)
        self.quality["closure_receipts"][0]["sha256"] = receipt["sha256"]
        self.assert_held()
        closure["features"][0]["geometry"] = polygon(-119.05, 33.97, -119.03, 33.99)
        self.quality["closure_receipts"][0]["sha256"] = self.write(path, closure)["sha256"]
        self.assert_held()

    def test_region_extent_and_center_are_checked_for_whole_footprint(self):
        for geometry in (polygon(-121.1, 33.9, -118.9, 34.1), polygon(-119.2, 33.8, -119.1, 33.9)):
            with self.subTest(geometry=geometry):
                self.atlas["areas"][0]["geometry"] = geometry
                self.assert_held()

    def test_bottom_tile_identity_and_raster_contract_even_with_new_hash(self):
        original = deepcopy(self.tile)
        for change in ({"region_id": "foreign-region"}, {"target_id": "different-target"}, {"source_id": "another-source"},
                       {"source_sha256": "b" * 64}, {"vertical_datum": "ellipsoid"}, {"horizontal_crs": "EPSG:4326"},
                       {"depth_qualified": 1}, {"width": 3}, {"elevations": "AAAA"}, {"cell_m": 1}):
            with self.subTest(change=change):
                self.tile = {**original, **change}
                self.write_tile()
                self.assert_held()

    def test_bottom_tile_size_path_and_published_index_are_bound(self):
        record = self.views["views"][self.tid]
        record["bytes"] += 1
        self.assert_held()
        self.write_tile()
        self.views["views"][self.tid]["path"] = "regions/foreign/bottom/target.json"
        self.assert_held()
        self.write_tile()
        self.publish()
        index = deepcopy(self.views)
        index["views"][self.tid]["status"] = "context-only"
        self.write("dist/" + self.region["assets"]["bottom_index"], index)
        with self.assertRaises(ValueError):
            self.validate()


class QualifiedGateTests(unittest.TestCase):
    def test_only_physical_coverage_gaps_can_be_replaced(self):
        qualified = {"ready": True, "complete_region_coverage": False}
        report = {"capabilities": {"surveyed-bottom-targets": {"ready": False, "gaps": ["bathymetry", "substrate"]}},
                  "needs": [{"id": "protected-areas", "status": "ready", "approved_sources": ["mpa"]}]}
        self.assertTrue(qualified_subset_satisfies(report, qualified))
        self.assertFalse(report["capabilities"]["surveyed-bottom-targets"]["ready"])
        for gap in ("protected-areas", "regulations", "unreviewed-new-requirement"):
            with self.subTest(gap=gap):
                report["capabilities"]["surveyed-bottom-targets"]["gaps"] = ["bathymetry", gap]
                self.assertFalse(qualified_subset_satisfies(report, qualified))
        report["capabilities"]["surveyed-bottom-targets"]["gaps"] = ["bathymetry", "substrate"]
        for status in ("partial", "not-applicable", "missing"):
            report["needs"][0]["status"] = status
            self.assertFalse(qualified_subset_satisfies(report, qualified))
        report["needs"][0]["status"] = "ready"
        report["needs"][0]["approved_sources"] = []
        self.assertFalse(qualified_subset_satisfies(report, qualified))
        self.assertFalse(qualified_subset_satisfies(report, None))

    def test_polygon_screen_handles_boundary_crossing_and_holes(self):
        outer = polygon(0, 0, 10, 10)
        outer["coordinates"].append(polygon(2, 2, 8, 8)["coordinates"][0])
        self.assertFalse(_intersects(_polygons(outer), _polygons(polygon(3, 3, 4, 4))))
        self.assertTrue(_intersects(_polygons(outer), _polygons(polygon(1, 3, 3, 4))))
        self.assertTrue(_intersects(_polygons(outer), _polygons(polygon(10, 1, 11, 2))))
        # Crossing strips intersect without containing any vertex from the other strip.
        self.assertTrue(_intersects(_polygons(polygon(0, 4, 10, 6)), _polygons(polygon(4, 0, 6, 10))))
