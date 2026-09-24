"""A survey lead cannot inherit a hazard review for different report bytes."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from scripts.audit_statewide_regular_camera import reviewed_hazards


class ReportReviewTests(unittest.TestCase):
    def test_exact_original_required_for_historical_hazard_status(self):
        raw = b"%PDF-1.7 reviewed original"
        url = "https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H10001-H12000/H11735/DR/H11735.pdf"
        catalog = {"surveys": [{"survey_id": "H11735", "report_url": url,
                                 "report_sha256": hashlib.sha256(raw).hexdigest(),
                                 "report_section": "Final HCell review", "hazards": [{"id": "dton-53ft"}]}]}
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            self.assertIsNone(reviewed_hazards(catalog, cache, "H11735", url))
            (cache / "H11735.pdf").write_bytes(raw)
            result = reviewed_hazards(catalog, cache, "H11735", url)
            self.assertEqual(result["historical_hazard_ids"], ["dton-53ft"])
            with self.assertRaisesRegex(ValueError, "another report"):
                reviewed_hazards(catalog, cache, "H11735", url + "?changed=1")
            (cache / "H11735.pdf").write_bytes(raw + b" changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                reviewed_hazards(catalog, cache, "H11735", url)


if __name__ == "__main__":
    unittest.main()
