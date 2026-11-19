"""SCA-281 / F09-11: a missing hourly-counter store is unknown uptime, not a measured 0.0% outage.

Contract protected: the fleet report separates three cases that used to print the same ``uptime 7 d 0.0%``:
(1) no ``<region>/ais/state.sqlite`` on the runner -> coverage ``unknown`` with a reason, every figure None, and the
Markdown and status line say "unknown", not a percentage; (2) the store exists and its monitored hours carry zero
messages (or no rows) -> a measured 0.0% that stays 0.0%, so a real outage is never hidden or relabelled healthy;
(3) a fully populated store -> measured 100.0%.  Believable bug: ``read_hours`` returns ``{}`` for an absent file and
``uptime`` turns that into 0.0%; or the fix over-reaches and reports unknown for a store of confirmed zero-message hours.

Each case is its own test.  All data is synthetic (a temporary FLEET_VAR; counters are invented); producer
telemetry only, not an AIS service measurement.
"""
from pathlib import Path
import tempfile
import unittest

from skippercast.fleet import report
from skippercast.fleet.ais.process import State
from skippercast.fleet.config import load_region
from tests.unit.test_fleet_report import HOUR, NOW


def seed_store(var: Path, messages: int | None, days: int = 30) -> None:
    """A runner's ``state.sqlite`` with one row per whole UTC hour before NOW; ``None`` leaves the table empty."""
    path = var / "CA" / "ais" / "state.sqlite"
    path.parent.mkdir(parents=True)
    state = State(path)
    end = NOW // HOUR * HOUR
    if messages is not None:
        for i in range(days * 24):
            state.set_hour(end - (i + 1) * HOUR,
                           {"messages": messages, "watched_messages": 0, "vessels": 1, "max_gap_s": 60})
    state.close()


def report_from(var: Path) -> dict:
    """The report exactly as ``main`` builds it from a runner's local inputs."""
    inputs = report.collect(load_region("CA"), "staging", var)
    return report.build("CA", **inputs, now_ms=NOW)


class MissingListenerEvidenceTests(unittest.TestCase):
    def test_absent_store_is_unknown_with_a_coverage_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = report_from(Path(tmp))
        u = result["uptime"]
        self.assertEqual(u["coverage"], {"status": "unknown", "reason": report.NO_HOURLY_STORE})
        self.assertEqual((u["d7"]["pct"], u["d30"]["pct"]), (None, None))
        self.assertEqual((u["d7"]["up_hours"], u["d30"]["up_hours"], u["hours_recorded"]), (None, None, None))
        self.assertEqual(u["full_days"], {"longest": None, "current": None, "days": None})
        line, text = report.status_line(result), report.markdown(result)
        self.assertIn("AIS ingestion uptime unknown (no hourly counters on this runner)", line)
        self.assertNotIn("0.0%", line.split("AIS ingestion")[1].split(";")[0])
        self.assertIn("Uptime unknown", text)
        self.assertIn("not a measured outage", text)
        self.assertNotIn("consecutive full days", line)

    def test_known_empty_monitored_interval_stays_a_measured_outage(self):
        for messages in (0, None):           # zero-message rows, and a store that exists but holds no rows
            with self.subTest(messages=messages), tempfile.TemporaryDirectory() as tmp:
                seed_store(Path(tmp), messages)
                result = report_from(Path(tmp))
            u = result["uptime"]
            self.assertEqual(u["coverage"], {"status": "measured", "reason": None})
            self.assertEqual((u["d7"], u["d30"]), ({"pct": 0.0, "up_hours": 0, "hours": 168},
                                                   {"pct": 0.0, "up_hours": 0, "hours": 720}))
            self.assertEqual(u["full_days"]["current"], 0)
            self.assertIn("uptime 7 d 0.0%, 30 d 0.0%", report.status_line(result))
            self.assertNotIn("unknown", report.markdown(result).split("### AIS ingestion")[1].split("###")[0])

    def test_fully_populated_store_is_the_measured_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_store(Path(tmp), 100)
            result = report_from(Path(tmp))
        u = result["uptime"]
        self.assertEqual(u["coverage"], {"status": "measured", "reason": None})
        self.assertEqual((u["d7"]["pct"], u["d30"]["pct"]), (100.0, 100.0))
        self.assertEqual((u["d7"]["up_hours"], u["d30"]["up_hours"]), (168, 720))
        self.assertIn("uptime 7 d 100.0%, 30 d 100.0%", report.status_line(result))

    def test_unknown_and_measured_zero_are_distinguishable_in_one_comparison(self):
        """The cited failure: the two outputs must differ even though both have no up hours."""
        missing = report.uptime({}, NOW, store_present=False)
        empty = report.uptime({}, NOW)
        self.assertNotEqual(missing, empty)
        self.assertIsNone(missing["d7"]["pct"])
        self.assertEqual(empty["d7"]["pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
