from __future__ import annotations

import importlib.util
import unittest
from types import SimpleNamespace

from tests._support import ROOT

SCRIPT = ROOT / "scripts" / "fleet" / "schedule_evidence.py"
spec = importlib.util.spec_from_file_location("schedule_evidence_elapsed", SCRIPT)
se = importlib.util.module_from_spec(spec)
spec.loader.exec_module(se)

REGION = SimpleNamespace(timezone="America/Los_Angeles", landings=[], ports=[])
BINDING = SimpleNamespace(id="src-example", rights="internal")
CANDIDATE = SimpleNamespace(landing_hint=None, port_hint=None, name="Example Boat",
                            record_id="https://example.test/boat")


def project(day, start, hours, retrieved="2026-01-01T00:00Z"):
    offering = SimpleNamespace(duration_h=hours, name="Half day", trip_type="half")
    departure = SimpleNamespace(date=day, departs_local=start, offering=offering,
                                source_url="https://example.test/s")
    return se.trip_projection(departure, CANDIDATE, REGION, BINDING, retrieved)


class ElapsedDurationTests(unittest.TestCase):
    def test_spring_forward_preserves_four_elapsed_hours(self):
        row = project("2026-03-08", "00:30", 4)
        self.assertEqual(row["return_utc"], "2026-03-08T12:30Z")
        self.assertEqual(row["return_local"], "2026-03-08T05:30")

    def test_fall_back_preserves_four_elapsed_hours(self):
        row = project("2026-11-01", "00:30", 4)
        self.assertEqual(row["return_utc"], "2026-11-01T11:30Z")
        self.assertEqual(row["return_local"], "2026-11-01T03:30")

    def test_fold_departure_retains_both_elapsed_returns(self):
        row = project("2026-11-01", "01:30", 4)
        self.assertIsNone(row["return_utc"])
        self.assertEqual(row["return_possible_utc_json"], '["2026-11-01T12:30Z","2026-11-01T13:30Z"]')
        self.assertIsNone(row["return_local"])
        self.assertTrue(row["return_uncertainty"].endswith("ambiguous-local-time"))

    def test_gap_departure_does_not_invent_return(self):
        row = project("2026-03-08", "02:30", 4)
        for key in ("return_utc", "return_local", "return_possible_utc_json"):
            self.assertIsNone(row[key])
        self.assertTrue(row["return_uncertainty"].endswith("unresolved-departure"))

    def test_normal_and_missing_duration_controls(self):
        row = project("2026-03-07", "08:30", 4)
        self.assertEqual((row["return_utc"], row["return_local"]), ("2026-03-07T20:30Z", "2026-03-07T12:30"))
        self.assertEqual(row, project("2026-03-07", "08:30", 4))
        later = project("2026-03-07", "08:30", 4, retrieved="2026-02-02T00:00Z")
        self.assertEqual(row["content_sha256"], later["content_sha256"])
        self.assertEqual(row["trip_id"], later["trip_id"])
        for day, start, hours in (("2026-03-07", None, 4), ("2026-03-07", "08:30", None), ("2026-03-07", "08:30", 0)):
            blank = project(day, start, hours)
            self.assertIsNone(blank["return_local"])
            self.assertIsNone(blank["return_utc"])
            self.assertEqual(blank["return_uncertainty"], "no-return-time-published")


if __name__ == "__main__":
    unittest.main()
