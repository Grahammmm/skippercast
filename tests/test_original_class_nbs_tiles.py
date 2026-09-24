import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.queue_nbs_original_class_tiles import intersecting_scheme_rows
from scripts.queue_statewide_original_class_tiles import build as build_statewide_queue
from scripts.screen_original_class_nbs_tiles import screen
from scripts.screen_statewide_original_class_leads import build as build_statewide_overlap
from scripts.triage_original_class_tile_queue import triage


class OriginalClassNbsTilesTest(unittest.TestCase):
    def test_rtree_limits_leads_to_actual_intersecting_envelopes(self):
        with tempfile.TemporaryDirectory() as directory:
            scheme = Path(directory) / "scheme.gpkg"
            with sqlite3.connect(scheme) as db:
                db.execute("CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT)")
                db.execute("INSERT INTO gpkg_contents VALUES ('Modeling_Tile_Scheme_fixture','features')")
                db.execute("CREATE TABLE Modeling_Tile_Scheme_fixture (fid INTEGER, tile TEXT, Resolution TEXT, GeoTIFF_Link TEXT, RAT_Link TEXT)")
                db.execute("CREATE TABLE rtree_Modeling_Tile_Scheme_fixture_geom (id INTEGER, minx REAL, maxx REAL, miny REAL, maxy REAL)")
                db.executemany("INSERT INTO Modeling_Tile_Scheme_fixture VALUES (?,?,?,?,?)", [
                    (1, "inside", "4m", "raster", "rat"), (2, "outside", "4m", "raster", "rat")])
                db.executemany("INSERT INTO rtree_Modeling_Tile_Scheme_fixture_geom VALUES (?,?,?,?,?)", [
                    (1, -124.5, -124.4, 40.5, 40.6), (2, -122, -121, 37, 38)])
            rows = intersecting_scheme_rows(scheme, (-124.45, 40.54, -124.43, 40.57))
            self.assertEqual([row["tile"] for row in rows], ["inside"])
            with self.assertRaises(ValueError):
                intersecting_scheme_rows(scheme, (-128, 40, -127, 41))

    def test_screen_rejects_unreviewed_or_changed_sources_before_cell_read(self):
        with tempfile.TemporaryDirectory() as directory:
            scheme = Path(directory) / "scheme"
            scheme.write_bytes(b"scheme")
            queue = {"scope": "original-usgs-hard-class-noaa-tile-acquisition-queue",
                     "fishing_target": False, "noaa_scheme_sha256": "wrong"}
            native_audit = {"scope": "usgs-state-waters-doi-native-grid-audit"}
            with self.assertRaisesRegex(ValueError, "scheme changed"):
                screen(queue, native_audit, {}, scheme, Path(directory), Path(directory), [])
            queue["noaa_scheme_sha256"] = __import__("hashlib").sha256(b"scheme").hexdigest()
            with self.assertRaisesRegex(ValueError, "native audit required"):
                screen(queue, {}, {}, scheme, Path(directory), Path(directory), [])

    def test_statewide_queue_requires_reviewed_originals(self):
        with self.assertRaisesRegex(ValueError, "Original DOI native audit required"):
            build_statewide_queue({}, {}, Path("unused"), Path("unused"))
        with self.assertRaisesRegex(ValueError, "No reviewed original"):
            build_statewide_queue({"scope": "usgs-state-waters-doi-native-grid-audit", "products": []},
                                  {}, Path("unused"), Path("unused"))

    def test_triage_cannot_silently_omit_a_requested_release(self):
        with tempfile.TemporaryDirectory() as directory:
            scheme = Path(directory) / "scheme"
            scheme.write_bytes(b"scheme")
            source_queue = {"scope": "statewide-original-class-noaa-fine-tile-source-queue",
                            "fishing_target": False,
                            "noaa_scheme_sha256": __import__("hashlib").sha256(b"scheme").hexdigest(),
                            "products": []}
            with self.assertRaisesRegex(ValueError, "missing from source queue"):
                triage(source_queue, scheme, Path(directory), ["F7513W80"])

    def test_statewide_overlap_requires_complete_matching_source_triage(self):
        with tempfile.TemporaryDirectory() as directory:
            scheme = Path(directory) / "scheme"
            scheme.write_bytes(b"scheme")
            digest = __import__("hashlib").sha256(b"scheme").hexdigest()
            source_queue = {"scope": "statewide-original-class-noaa-fine-tile-source-queue",
                            "noaa_scheme_sha256": digest,
                            "products": [{"release_id": "sample", "original_archive_sha256": "a" * 64}]}
            depth_triage = {"scope": "statewide-original-class-noaa-measured-depth-triage",
                            "noaa_scheme_sha256": digest, "products": []}
            with self.assertRaisesRegex(ValueError, "does not cover every original class grid"):
                build_statewide_overlap(source_queue, depth_triage,
                                        {"scope": "usgs-state-waters-doi-native-grid-audit"}, {},
                                        scheme, Path(directory), Path(directory))


if __name__ == "__main__":
    unittest.main()
