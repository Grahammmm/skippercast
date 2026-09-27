import copy
import csv
import io
import unittest

from scripts import audit_w00614_noaa_sh1809_observations as audit


class SH1809ObservationTests(unittest.TestCase):
    def setUp(self):
        self.depth = {
            "survey_id": "W00614", "vertical_datum": "MLLW", "source_sha256": "bag",
            "counts": {"depth_uncertainty_qualified_200_300ft_cells": 141331},
        }
        self.gap = {
            "bag_sha256": "bag", "qualified_cells": 141331,
            "qualified_cell_center_envelope_wgs84": [-122.485, 37.11, -122.443, 37.163],
        }

    def source(self, lon=-122.495):
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(audit.FIELDS.split(","))
        writer.writerow(["", "", "degrees_north", "degrees_east", "m", "", "", "", "", "", "", "m", "", ""])
        writer.writerow([audit.DATASET, "1", "37.13", str(lon), "86", "Pigeon Point",
                         "", "", "2018-08-03", "1", "1", "20m", "USBL", "video observation"])
        return stream.getvalue().encode()

    def test_named_reef_outside_measured_cells_stays_research_only(self):
        result = audit.build(self.source(), self.depth, self.gap)
        self.assertEqual(result["source_rows"], 1)
        self.assertEqual(result["points_within_100m_of_envelope"], 0)
        self.assertGreater(result["approx_nearest_point_to_envelope_m"], 100)
        self.assertFalse(result["biological_fish_gate_satisfied"])
        self.assertFalse(result["exportable"])

    def test_nearby_observation_demands_exact_cell_review(self):
        with self.assertRaisesRegex(ValueError, "exact W00614 cell/position join"):
            audit.build(self.source(-122.484), self.depth, self.gap)

    def test_depth_lineage_change_fails(self):
        changed = copy.deepcopy(self.depth)
        changed["source_sha256"] = "new survey"
        with self.assertRaisesRegex(ValueError, "depth lineage changed"):
            audit.build(self.source(), changed, self.gap)


if __name__ == "__main__":
    unittest.main()
