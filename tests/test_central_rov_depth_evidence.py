import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts import build_central_rov_depth_evidence as rov


class CentralRovDepthEvidenceTest(unittest.TestCase):
    def test_published_summary_is_nonpositional_and_reference_only(self):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root / "dist/data/central-rov-200-300ft-evidence.json").read_text())
        self.assertFalse(data["fishing_target"])
        self.assertFalse(data["exportable"])
        self.assertEqual(data["depth_band_ft"], [200, 300])
        self.assertEqual(data["source_rows_checked"], 133506)
        self.assertEqual({a["area"] for a in data["areas"]},
                         {"Big Creek", "Point Buchon", "Point Lobos", "Point Sur", "Portuguese Ledge"})
        self.assertTrue(all(a["site_type"] == "unprotected_reference_only" for a in data["areas"]))
        self.assertFalse(any("Avg.X" in json.dumps(a) or "Avg.Y" in json.dumps(a)
                             for a in data["areas"]))

    def test_protected_and_out_of_band_subunits_do_not_enter_summary(self):
        fields = ["SurveyYear", "LongTerm_Region", "MPAGroup", "Protection", "Type",
                  "X10m_ID", "Avg.Depth", "Usable_Area_Fish", "Propn_Hard", "Propn_Mixed"] + list(rov.SPECIES)
        def row(identity, protection, role, depth, count):
            base = dict.fromkeys(fields, "0")
            base.update({"SurveyYear": "2020", "LongTerm_Region": "Central", "MPAGroup": "Big Creek",
                         "Protection": protection, "Type": role, "X10m_ID": identity,
                         "Avg.Depth": str(depth), "Usable_Area_Fish": "20", "Propn_Hard": "0.6",
                         "Propn_Mixed": "0.2", "Lingcod": str(count)})
            return base
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.csv"
            with path.open("w", newline="") as out:
                writer = csv.DictWriter(out, fieldnames=fields)
                writer.writeheader()
                writer.writerows([row("open", "0", "Reference", 70, 2),
                                  row("mpa", "1", "SMR", 70, 100),
                                  row("shallow", "0", "Reference", 40, 50)])
            body = path.read_bytes()
            pin = {"file_bytes": len(body), "file_md5": hashlib.md5(body).hexdigest(),
                   "file_sha256": hashlib.sha256(body).hexdigest(), "depth_band_ft": [200, 300],
                   "observation_years": [2005, 2021], "doi": "example",
                   "source_url": "example", "license": "CC BY 4.0"}
            result = rov.build(pin, path, minimum_rows=0)
            self.assertEqual(result["areas"][0]["surveyed_10m_subunits"], 1)
            self.assertEqual(result["areas"][0]["surveyed_camera_area_m2"], 20)
            self.assertEqual(result["areas"][0]["species"][0]["observed_count"], 2)


if __name__ == "__main__":
    unittest.main()
