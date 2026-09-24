import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    "audit_noaa_dismap_groundfish",
    Path(__file__).resolve().parents[1] / "scripts/audit_noaa_dismap_groundfish.py",
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class DisMAPAuditTests(unittest.TestCase):
    def test_grouped_sample_can_have_zero_and_positive_rockfish_species(self):
        base = {"SampleID": "haul-1", "Year": 2025, "Latitude": 35.4,
                "Longitude": -121.0, "Depth": 50.0}
        records = [
            {**base, "OBJECTID": 1, "Species": "Sebastes melanops",
             "SpeciesCommonName": "Black rockfish", "WTCPUE": 0.0},
            {**base, "OBJECTID": 2, "Species": "Sebastes carnatus",
             "SpeciesCommonName": "Gopher rockfish", "WTCPUE": 2.0},
        ]
        groups, outside = audit.summarize(records, [{"id": "one", "latitude": [35, 36]}], [2025])
        self.assertEqual(outside, 0)
        self.assertEqual(groups[0]["samples_with_taxon_record"], 1)
        self.assertEqual(groups[0]["samples_with_positive_cpue"], 1)
        self.assertEqual(groups[0]["samples_at_or_under_200ft"], 1)
        self.assertEqual(groups[0]["positive_samples_at_or_under_200ft"], 1)

    def test_duplicate_page_record_is_rejected(self):
        row = {"OBJECTID": 7, "SampleID": "haul-1", "Year": 2025, "Latitude": 35.4,
               "Longitude": -121.0, "Depth": 80.0, "Species": "Ophiodon elongatus",
               "SpeciesCommonName": "Lingcod", "WTCPUE": 0.0}
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            audit.summarize([row, row], [{"id": "one", "latitude": [35, 36]}], [2025])


if __name__ == "__main__":
    unittest.main()
