import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.queue_nbs_original_class_tiles import intersecting_scheme_rows
from scripts.screen_original_class_nbs_tiles import screen


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


if __name__ == "__main__":
    unittest.main()
