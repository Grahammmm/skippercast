import csv
from pathlib import Path
import tempfile
import unittest

from scripts.audit_dataone_rov_spot_precision import FIELDS, build


class DataOneRovPrecisionTest(unittest.TestCase):
    def fixture(self, lat="35.28", count="1.5"):
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name) / "source.csv"
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            row = dict.fromkeys(FIELDS, "")
            row.update(Year="2016", Month="10", Day="9", Region="Central",
                       MPA_Group="Point Buchon", Type="SMR", Designation="Reference",
                       Habitat_Type="Hard", Lat=lat, Long="-120.92", Depth="75",
                       Common_Name="Lingcod", Scientific_Name="Ophiodon elongatus", Count=count)
            for species in range(128):
                row["Common_Name"] = ("Lingcod" if species == 0 else
                                      "Vermilion Rockfish" if species == 1 else f"species {species}")
                row["Count"] = count if species < 2 else "0"
                writer.writerow(row)
        return temp, path

    def test_public_rounded_positions_are_not_spot_evidence(self):
        temp, path = self.fixture()
        try:
            report = build(path, min_rows=128)
            self.assertEqual(report["central_location_date_depth_habitat_units_200_300ft"], 1)
            self.assertEqual(report["fractional_positive_count_rows_in_band"], 2)
            self.assertEqual(report["open_reference_detection_units_200_300ft"][0]["lingcod_positive_units"], 1)
            self.assertEqual(report["open_reference_detection_units_200_300ft"][0]["rockfish_group_positive_units"], 1)
            self.assertFalse(report["fishing_target"])
        finally:
            temp.cleanup()

    def test_finer_positions_force_new_spatial_review(self):
        temp, path = self.fixture(lat="35.2812")
        try:
            with self.assertRaisesRegex(ValueError, "finer precision"):
                build(path, min_rows=128)
        finally:
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
