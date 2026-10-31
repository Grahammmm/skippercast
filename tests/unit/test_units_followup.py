"""RF1105-22: atlas export and fleet AIS events read skippercast.util.units; output stays byte-identical."""
import subprocess
import sys
import unittest

from skippercast.atlas import export
from skippercast.fleet.ais import events
from skippercast.fleet.ais.segment import distance_nm
from skippercast.util import units
from tests._support import ROOT

SRC = ROOT / "src" / "skippercast"


def relief_line(relief_m):
    row = {"neighborhood_depth_ft": [90, 110], "habitat_grade": "A", "habitat_score": 80, "rank": 1, "center_depth_ft": 100,
           "terrain_interpretation": "t", "area_ids": [], "drift_id": None, "ais_status": "a", "evidence_status": "e",
           "confidence": "c", "survey_flags": [], "special_note": "No additional note.", "survey_year": 2010,
           "source_url": "u", "legacy_id": "L", "metrics": {"relief_210m_m": relief_m, "rugose_or_bedrock_fraction_210m": 0.5,
                                                             "rough_habitat_within_250m_ha": 1.0}}
    lines = export.target_note(row, {"areas": [], "drifts": [], "targets": [row], "edition": "x"}).split("\n")
    return [line for line in lines if line.startswith("Local relief ")]


class UnitsFollowupTests(unittest.TestCase):
    def test_events_metres_per_nm_is_the_shared_constant(self):
        self.assertIs(events.METRES_PER_NM, units.M_PER_NMI)
        self.assertIs(type(events.METRES_PER_NM), float)
        self.assertEqual(events.METRES_PER_NM, 1852.0)

    def test_no_inline_literal_left(self):
        self.assertNotIn("0.3048", (SRC / "atlas/export.py").read_text(encoding="utf-8"))
        self.assertNotIn("1852", (SRC / "fleet/ais/events.py").read_text(encoding="utf-8"))

    def test_atlas_relief_line_is_byte_identical(self):
        for v in (0, 0.1524, 1, 64.008, 1000):  # 0.1524 m is half a foot: the rounding edge
            old = f"Local relief {v / 0.3048:.0f} ft; mapped rough habitat 50%; usable nearby rough habitat 2.5 acres."
            self.assertEqual(relief_line(v), [old], v)

    def test_ais_distance_is_byte_identical(self):
        pairs = [((37.0, -122.0), (37.0, -122.0)), ((37.0, -122.0), (37.0 + 1 / 60, -122.0)),
                 ((10.0, 179.99), (10.0, -179.99))]
        for centre, point in pairs:
            expected = distance_nm(centre[0], centre[1], point[0], point[1]) * 1852.0
            self.assertEqual(events.p90_radius_m([point], centre).hex(), expected.hex(), (centre, point))
        self.assertEqual(events.p90_radius_m([(37.0, -122.0)], (37.0, -122.0)), 0.0)

    def test_events_import_in_fresh_interpreter(self):  # cwd is this checkout's src, first on sys.path; -E ignores env
        code = ("import sys; import skippercast.fleet.ais.events as e; from skippercast.util import units; "
                "assert e.METRES_PER_NM is units.M_PER_NMI; print(e.__file__); "
                "print(sorted(m for m in ('numpy', 'pandas', 'rasterio', 'shapely') if m in sys.modules))")
        done = subprocess.run([sys.executable, "-E", "-s", "-c", code], cwd=ROOT / "src", capture_output=True,
                              text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.split("\n")[:2], [str(SRC / "fleet/ais/events.py"), "[]"])


if __name__ == "__main__":
    unittest.main()
