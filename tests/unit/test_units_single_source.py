import re
import unittest

from skippercast.pipeline import cdip_nearshore, coast_report, ndbc_history, verification
from skippercast.util import units
from tests._support import ROOT

NAMES = ("cdip_nearshore", "coast_report", "coast_snapshots", "ndbc_history", "verification")
PIPELINE = ROOT / "src" / "skippercast" / "pipeline"
LITERAL = re.compile(r"3\.2808|1\.9438|0\.5144|(?<![\d.])0\.3048")


class UnitsSingleSourceTest(unittest.TestCase):
    def test_no_literal_factor_in_the_five_readers(self):
        for name in NAMES:
            text = (PIPELINE / f"{name}.py").read_text(encoding="utf-8")
            self.assertIsNone(LITERAL.search(text), name)

    def test_aliases_are_the_shared_constants(self):
        self.assertIs(cdip_nearshore.FT_PER_M, units.FT_PER_M)
        self.assertEqual(coast_report.FT, round(units.FT_PER_M, 9))  # the feed's published precision stays 9 places
        self.assertEqual(coast_report.KT, round(units.KT_PER_MS, 9))
        self.assertIs(verification.FT_PER_M, units.FT_PER_M)
        self.assertIs(ndbc_history.KT_PER_MS, units.KT_PER_MS)

    def test_wave_height_rounds_the_same_at_a_tenth_foot_boundary(self):
        station = {"id": "46000", "variables": ["wave_height"]}
        row = {"time": "2026-01-01T00:00:00Z", "WVHT": 1.524, "WSPD": None}
        (rec,) = verification.observation_records(station, [row], "t", "u")
        self.assertEqual(round(rec["value"], 1), round(1.524 * 3.28084, 1))
        self.assertEqual(round(rec["value"], 1), 5.0)


if __name__ == "__main__":
    unittest.main()
