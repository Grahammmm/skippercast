import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_ccfrp_area_evidence as ccfrp


class CcfrpAreaEvidenceTest(unittest.TestCase):
    def test_reviewed_snapshot_contains_only_bounded_reference_context(self):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root / "dist/data/central-ccfrp-area-evidence.json").read_text())
        self.assertFalse(data["fishing_target"])
        self.assertFalse(data["exportable"])
        self.assertEqual(data["source_rows_checked"], 366630)
        self.assertEqual({a["area"] for a in data["areas"]}, set(ccfrp.AREAS))
        self.assertTrue(all(a["site_type"] == "fished_reference_only" for a in data["areas"]))
        self.assertFalse(any("lat" in json.dumps(a).lower() or "lon" in json.dumps(a).lower()
                             for a in data["areas"]))
        self.assertLess(max(a["maximum_recorded_sample_depth_m"] for a in data["areas"]), 46)

    def test_effort_is_deduplicated_and_protected_rows_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def write_csv(name, fields, rows):
                with (root / f"{name}.csv").open("w", newline="", encoding="latin1") as out:
                    writer = csv.DictWriter(out, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(rows)
            write_csv("species", ["Common_Name"], [{"Common_Name": "Lingcod"},
                                                   {"Common_Name": "Blue Rockfish"}])
            write_csv("location", ["Area", "Grid_Cell_ID", "MPA_Status"], [
                {"Area": "Point Lobos", "Grid_Cell_ID": "REF1", "MPA_Status": "REF"},
                {"Area": "Point Lobos", "Grid_Cell_ID": "MPA1", "MPA_Status": "MPA"}])
            fields = ["Area", "MPA_Status", "Date", "Year", "ID_Cell_per_Trip",
                      "Grid_Cell_ID", "Total_Angler_Hours", "Common_Name", "Count",
                      "Start_Depth_m", "End_Depth_m"]
            def row(cell, status, name, count, date):
                return dict(zip(fields, ["Point Lobos", status, date, "2024", cell,
                                         "REF1" if status == "REF" else "MPA1", "5",
                                         name, str(count), "20", "21"]))
            write_csv("effort", fields, [
                row("cell1", "REF", "Lingcod", 1, "2024-08-01"),
                row("cell1", "REF", "Blue Rockfish", 0, "2024-08-01"),
                row("cell2", "REF", "Lingcod", 0, "2024-08-02"),
                row("cell2", "REF", "Blue Rockfish", 2, "2024-08-02"),
                row("cell3", "MPA", "Lingcod", 100, "2024-08-02")])
            pin = {"coverage_years": [2007, 2024], "package_id": "example",
                   "citation_url": "example", "license": "CC BY 4.0", "files": {}}
            for name in ("species", "location", "effort"):
                body = (root / f"{name}.csv").read_bytes()
                pin["files"][name] = {"bytes": len(body),
                                      "sha256": hashlib.sha256(body).hexdigest()}
            with patch.object(ccfrp, "AREAS", ("Point Lobos",)), patch.object(
                    ccfrp, "SPECIES", ("Lingcod", "Blue Rockfish")):
                area = ccfrp.build(pin, root, minimum_rows=0)["areas"][0]
            self.assertEqual(area["sampled_cell_trips"], 2)
            self.assertEqual(area["angler_hours"], 10)
            self.assertEqual(area["species"][0]["observed_catch"], 1)
            self.assertEqual(area["species"][0]["catch_per_angler_hour"], 0.1)
            self.assertEqual(area["species"][1]["observed_catch"], 2)


if __name__ == "__main__":
    unittest.main()
