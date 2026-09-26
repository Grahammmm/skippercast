"""Contract failures that could silently mix regions or overstate data coverage."""
from copy import deepcopy
from pathlib import Path
import tempfile
from unittest import TestCase
from skippercast.platform.contracts import REPO, read_json, load_region, requirement_report, public_url, within
from skippercast.platform.candidate import validate_candidate
from skippercast.pipeline.settings import settings, previous_for_region
from skippercast.pipeline.collect import model_loader


def candidate():
    return {"schema_version":1,"id":"example-survey","name":"Survey candidate","region_ids":["cambria-san-simeon"],"need_ids":["bathymetry"],
        "documentation_url":"https://example.org/docs","access_url":None,"access_status":"not-tested",
        "producer":{"name":"Example publisher","url":"https://example.org"},"variables":["elevation"],"units":{"elevation":"m"},
        "provenance":{"access_service":None,"raw_sha256":None,"transformations":[]},
        "rights":{"license":None,"terms_url":None,"redistribution_reviewed":False},
        "spatial":{"bounds":None,"resolution_m":None,"horizontal_crs":None,"vertical_datum":None},
        "temporal":{"source_time":None,"checked_at":None,"update_cadence":None},
        "evidence":[{"url":"https://example.org/docs","supports":"Discovery lead only"}],"limitations":["Coverage unknown"]}


class RegionalContracts(TestCase):
    def test_mendocino_preview_withholds_unqualified_fishing_spots(self):
        region = load_region("fort-bragg-point-arena")
        atlas = read_json(REPO / "dist" / region["assets"]["atlas"])
        search = read_json(REPO / "dist" / region["assets"]["search_plans"])
        self.assertEqual(region["status"], "preview")
        self.assertEqual(atlas["targets"], [])
        self.assertEqual(search["features"], [])
        self.assertNotEqual(region["coverage"]["surface-currents"]["status"], "ready")
        self.assertEqual(region["intelligence"]["verification_stations"][0]["id"], "46014")

    def test_published_region_requires_live_intelligence_configuration(self):
        from skippercast.platform.contracts import validate_region, load_catalogs
        region = deepcopy(load_region("fort-bragg-point-arena"))
        del region["intelligence"]
        with self.assertRaisesRegex(ValueError, "intelligence configuration"):
            validate_region(region, *load_catalogs(REPO), root=REPO)

    def test_bodega_preview_keeps_survey_context_out_of_fishing_exports(self):
        region = load_region("bodega-point-reyes")
        atlas = read_json(REPO / "dist" / region["assets"]["atlas"])
        search = read_json(REPO / "dist" / region["assets"]["search_plans"])
        self.assertEqual(region["status"], "preview")
        self.assertEqual(atlas["targets"], [])
        self.assertEqual(len(search["features"]), 17)
        self.assertTrue(all(not f["properties"]["exportable"] and not f["properties"]["depth_qualified"]
                            for f in search["features"]))
        self.assertIn("salmon", [item["id"] for item in region["map"]["local_areas"][0]["hidden_targets"]])
        self.assertNotEqual(region["coverage"]["surface-currents"]["status"], "ready")

    def test_crescent_preview_keeps_mpa_held_survey_out_of_fishing_exports(self):
        region = load_region("crescent-city")
        atlas = read_json(REPO / "dist" / region["assets"]["atlas"])
        search = read_json(REPO / "dist" / region["assets"]["search_plans"])
        self.assertEqual(region["status"], "preview")
        self.assertEqual(atlas["targets"], [])
        self.assertEqual(search["features"], [])
        self.assertNotEqual(region["coverage"]["surface-currents"]["status"], "ready")

    def test_preview_cannot_claim_qualified_targets_exports_or_images(self):
        report=requirement_report(load_region("cambria-san-simeon"))
        for key in ("surveyed-bottom-targets","surveyed-bottom-images","fishing-exports","verified-charter-hotspots","calibrated-catch-model"):
            self.assertFalse(report["capabilities"][key]["ready"],key)

    def test_region_changes_model_coordinates_and_jurisdiction_label(self):
        north=settings("cambria-san-simeon")
        self.assertIn("San Simeon",north["regulations"]["area"])
        points=[(p["name"],p["latitude"],p["longitude"]) for p in north["region"]["forecast_points"]]
        url,_=model_loader("gfs_global",points)
        self.assertIn("35.64",url)
        self.assertNotIn("35.1%2C",url)
        wave_url,_=model_loader("ncep_gfswave016",points)
        self.assertIn("models=ncep_gfswave016",wave_url)
        self.assertIn("wind_wave_height",wave_url)
        self.assertEqual(north["region"]["landing_names"],[])

    def test_cross_region_retention_and_legacy_migration(self):
        legacy={"schema_version":1,"sources":{}}
        self.assertIs(previous_for_region(legacy,"morro-bay"),legacy)
        with self.assertRaises(ValueError): previous_for_region(legacy,"cambria-san-simeon")
        with self.assertRaises(ValueError): previous_for_region({**legacy,"region_id":"cambria-san-simeon"},"morro-bay")

    def test_private_urls_and_escaping_paths_are_rejected(self):
        for url in ("http://example.org","https://127.0.0.1/x","https://169.254.169.254/","https://[::1]/","https://localhost/x","https://u:p@example.org"):
            with self.assertRaises(ValueError):public_url(url)
        with self.assertRaises(ValueError):within(REPO/"dist","../catalog/sources.json")

    def test_strict_json_rejects_duplicates_and_nonfinite_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"input.json"
            for text in ('{"id":1,"id":2}','{"depth":NaN}'):
                path.write_text(text)
                with self.assertRaises(ValueError):read_json(path)

    def test_candidate_preserves_unknowns_without_approving_them(self):
        result=validate_candidate(candidate())
        self.assertTrue(result["valid"])
        self.assertFalse(result["publication_approved"])
        for mutate in (lambda c:c["units"].clear(),lambda c:c.update(access_status="accessible"),lambda c:c["rights"].update(redistribution_reviewed=True),lambda c:c["spatial"].update(resolution_m=0),lambda c:c.update(need_ids=["imagined-need"])):
            data=candidate();mutate(data)
            with self.assertRaises(ValueError):validate_candidate(data)

    def test_sector_source_candidate_can_precede_a_region_package(self):
        data = candidate()
        del data["region_ids"]
        data["sector_ids"] = ["big-sur"]
        data["spatial"]["footprint_kind"] = "valid-cell-envelope"
        self.assertFalse(validate_candidate(data)["publication_approved"])
        data["sector_ids"] = ["imaginary-coast"]
        with self.assertRaisesRegex(ValueError, "Unknown California discovery sector"):
            validate_candidate(data)
        del data["sector_ids"]
        with self.assertRaisesRegex(ValueError, "Candidate fields"):
            validate_candidate(data)

    def test_original_raster_envelope_preserves_nodata_caveat(self):
        data = read_json(REPO / "catalog/candidates/usgs-offshore-aptos-original-grids.json")
        self.assertEqual(data["spatial"]["footprint_kind"], "native-raster-envelope-with-nodata")
        self.assertFalse(validate_candidate(data)["publication_approved"])

    def test_every_saved_source_candidate_stays_valid_and_unpublished(self):
        for path in sorted((REPO / "catalog/candidates").glob("*.json")):
            with self.subTest(candidate=path.name):
                result = validate_candidate(read_json(path))
                self.assertTrue(result["valid"])
                self.assertFalse(result["publication_approved"])

    def test_all_tiles_have_original_source_identity_and_measured_center(self):
        import base64, hashlib, struct
        index=read_json(REPO/"dist/regions/morro-bay/bottom/index.json")
        atlas=read_json(REPO/"dist/data/atlas.json")
        self.assertEqual(len(index["views"]),len(atlas["targets"]))
        for target in atlas["targets"]:
            receipt=index["views"][target["id"]]
            path=within(REPO/"dist",receipt["path"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),receipt["sha256"])
            tile=read_json(path)
            self.assertEqual(tile["region_id"],"morro-bay")
            self.assertEqual(tile["target_id"],target["id"])
            self.assertEqual(tile["vertical_datum"],"MLLW")
            cells=struct.unpack("<16641h",base64.b64decode(tile["elevations"]))
            self.assertNotEqual(cells[64*129+64],-32768)
            self.assertAlmostEqual(-cells[64*129+64]/10*3.28084,target["recorded_validation"]["native_center_depth_ft"],delta=1)
