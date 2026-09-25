"""Producer policy must not be mistaken for a grid publication license."""
import json
from pathlib import Path
import unittest

from scripts.audit_csumb_source_policy import ARCHIVES, audit


ROOT = Path(__file__).resolve().parents[1]


class CSUMBSourcePolicyTest(unittest.TestCase):
    def test_six_source_records_remain_held(self):
        receipt = json.loads((ROOT / "dist/data/csumb-original-source-policy-review.json").read_text())
        self.assertEqual(set(receipt["affected_candidate_ids"]), set(ARCHIVES))
        self.assertFalse(receipt["website_redistribution_cleared"])
        self.assertFalse(receipt["fishing_target"])
        self.assertFalse(receipt["exportable"])
        for path in sorted((ROOT / "catalog/candidates").glob("csumb-*.json")):
            candidate = json.loads(path.read_text())
            if candidate["id"] not in ARCHIVES:
                continue
            self.assertFalse(candidate["rights"]["redistribution_reviewed"])

    def test_missing_for_profit_condition_fails_closed(self):
        policy = (b"These data are not copyrighted. Data used in this study were acquired, processed, "
                  b"archived, and distributed by the Seafloor Mapping Lab. NOT to be used for navigational purposes")
        bss = (b"<accconst>To be determined by Seafloor Mapping Lab- California State University Monterey Bay and contractor(s)</accconst>"
               b"<useconst>To be determined by Seafloor Mapping Lab- California State University Monterey Bay and contractor(s)</useconst>")
        scc = b"Seafloor Mapping Lab at California State University Monterey Bay"
        with self.assertRaisesRegex(ValueError, "policy changed"):
            audit(policy, bss, scc)


if __name__ == "__main__":
    unittest.main()
