"""The coarse NOAA coverage map must remain a discovery-only source."""
import json
import unittest

from research.scripts.audit_noaa_bathymetry_gap import classify
from research.lib.receipts import RECEIPTS
from research.lib.paths import ROOT


def layer(layer_id, alpha):
    return {"layerId": layer_id, "attributes": {"RGB.Alpha": str(alpha)}}


class NOAABathymetryGapTest(unittest.TestCase):
    def test_discovery_only(self):
        receipt = json.loads((RECEIPTS / "noaa-central-bathymetry-gap-discovery.json").read_text())
        candidate = json.loads((ROOT / "catalog/candidates/noaa-bathymetry-coverage-gap-map.json").read_text())
        self.assertFalse(receipt["fishing_target"])
        self.assertFalse(receipt["exportable"])
        self.assertIsNone(candidate["spatial"]["vertical_datum"])
        self.assertEqual(candidate["variables"], ["archived_bathymetry_coverage_class"])
        self.assertFalse(candidate["rights"]["redistribution_reviewed"])

    def test_classes_and_incomplete_response(self):
        self.assertEqual(classify([layer(0, 255), layer(1, 0)]),
                         "three-or-more-or-coverage-footprint")
        self.assertEqual(classify([layer(0, 0), layer(1, 255)]), "one-or-two")
        self.assertEqual(classify([layer(0, 0), layer(1, 0)]), "no-class-at-probe")
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            classify([layer(0, 0)])
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            classify([layer(0, 255), layer(1, 255)])


if __name__ == "__main__":
    unittest.main()
