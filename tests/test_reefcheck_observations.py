"""Historical diver records cannot become map points through the audit path."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from scripts.audit_reefcheck_observations import build, sector_for


SECTORS = {"sectors": [{"id": "north", "latitude": [40.0, 42.0]}]}


class ReefCheckObservationTests(unittest.TestCase):
    def test_broad_aggregate_keeps_uncertainty_and_excludes_positions(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "sample.zip"
            tables = {
                "event.txt": "eventID\teventDate\tlocality\tminimumDepthInMeters\tdecimalLatitude\tdecimalLongitude\tcoordinateUncertaintyInMeters\nA\t2015-08-01\tTest reef\t12.0\t41.0\t-124.2\t250\n",
                "occurrence.txt": "eventID\toccurrenceStatus\tscientificName\nA\tpresent\tOphiodon elongatus\nA\tabsent\tSebastes melanops\n",
                "extendedmeasurementorfact.txt": "id\tmeasurementType\nA\tsubstrate\nA\trelief\n",
                "eml.xml": "<eml/>", "meta.xml": "<archive/>",
            }
            with zipfile.ZipFile(archive, "w") as output:
                for name, contents in tables.items():
                    output.writestr(name, contents)
            manifest = {"archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "expected_rows": {"event.txt": 1, "occurrence.txt": 2,
                                          "extendedmeasurementorfact.txt": 2},
                        "source_id": "fixture", "publisher_url": "https://example.test/",
                        "publisher_date": "2025-01-01"}
            receipt = build(archive, manifest, SECTORS)
            row = receipt["sectors"][0]
            self.assertEqual(row["events_with_lingcod_present"], 1)
            self.assertEqual(row["events_with_any_rockfish_present"], 0)
            self.assertEqual(row["declared_position_uncertainty_m"], [250.0])
            self.assertNotIn("-124.2", json.dumps(receipt))
            manifest["archive_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "archive changed"):
                build(archive, manifest, SECTORS)

    def test_sector_band_has_one_owner(self):
        self.assertEqual(sector_for(42.0, SECTORS["sectors"]), "north")
        self.assertIsNone(sector_for(42.01, SECTORS["sectors"]))
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            sector_for(41.0, SECTORS["sectors"] * 2)


if __name__ == "__main__":
    unittest.main()
