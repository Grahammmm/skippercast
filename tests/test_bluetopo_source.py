import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.audit_bluetopo_tile import scheme_row
from scripts.refresh_bluetopo_samples import listed_schemes, refresh


class BlueTopoSourceReviewTests(unittest.TestCase):
    def test_scheme_requires_official_table_and_complete_tile_links(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "scheme.gpkg"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT)")
                db.execute("CREATE TABLE BlueTopo_Tile_Scheme_20260924 (tile TEXT, GeoTIFF_Link TEXT, RAT_Link TEXT)")
                db.execute("INSERT INTO gpkg_contents VALUES ('BlueTopo_Tile_Scheme_20260924','features')")
                db.execute("INSERT INTO BlueTopo_Tile_Scheme_20260924 VALUES ('A',NULL,'rat')")
            with self.assertRaisesRegex(ValueError, "no published raster"):
                scheme_row(path, "A")
            with self.assertRaisesRegex(ValueError, "no published raster"):
                scheme_row(path, "B")

    def test_scheme_listing_ignores_unrelated_objects(self):
        xml = b'''<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
        <Contents><Key>BlueTopo/_BlueTopo_Tile_Scheme/BlueTopo_Tile_Scheme_20260924.gpkg</Key></Contents>
        <Contents><Key>BlueTopo/_BlueTopo_Tile_Scheme/readme.txt</Key></Contents>
        <Contents><Key>Test-and-Evaluation/Modeling/foo.gpkg</Key></Contents>
        </ListBucketResult>'''
        self.assertEqual(listed_schemes(xml),
                         ["BlueTopo/_BlueTopo_Tile_Scheme/BlueTopo_Tile_Scheme_20260924.gpkg"])

    def test_rejects_scheme_outside_noaa_bucket_before_network(self):
        with self.assertRaisesRegex(ValueError, "outside the reviewed NOAA source"):
            refresh({"tile_ids": ["A"], "scheme_url": "https://example.com/fake.gpkg"}, Path("unused"))

    def test_rejects_duplicate_or_unmapped_sector_tiles_before_network(self):
        with self.assertRaisesRegex(ValueError, "empty or repeated"):
            refresh({"tile_ids": ["A", "A"]}, Path("unused"))
        with self.assertRaisesRegex(ValueError, "one distinct tile"):
            refresh({"tile_ids": ["A", "B"], "sector_tile_ids": {"north": "A"}}, Path("unused"))


if __name__ == "__main__":
    unittest.main()
