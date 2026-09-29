import json
from pathlib import Path
import unittest

from research.scripts import audit_point_buchon_caris_prefix as caris
from research.lib.receipts import RECEIPTS


ROOT = Path(__file__).resolve().parents[1]


class PointBuchonCarisPrefixTest(unittest.TestCase):
    def test_public_receipt_is_only_an_acquisition_lead(self):
        receipt = json.loads((RECEIPTS / "point-buchon-2007-caris-prefix-lead.json").read_text())
        self.assertEqual(receipt["scope"], "point-buchon-2007-original-caris-prefix-acquisition-lead")
        self.assertEqual(receipt["qualified_waypoints"], 0)
        self.assertFalse(receipt["fishing_target"])
        self.assertFalse(receipt["exportable"])
        self.assertEqual({row["survey_id"] for row in receipt["surveys"]}, set(caris.ARCHIVES))
        for row in receipt["surveys"]:
            self.assertEqual(row["project_definition_projection"], "AUTO_UTM,WG84_10N")
            self.assertTrue(row["prefix_not_complete_archive"])
            self.assertEqual(row["inspected_compressed_prefix_bytes"], caris.PREFIX_SIZE)
        control = next(row for row in receipt["surveys"] if row["survey_id"] == "PointBuchon_Control")
        self.assertEqual(len(control["tpe_member_names_visible_in_prefix"]), 1)

    def test_changed_prefix_hash_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "prefix bytes changed"):
            caris.inspect_prefix(b"wrong", "0" * 64)


if __name__ == "__main__":
    unittest.main()
