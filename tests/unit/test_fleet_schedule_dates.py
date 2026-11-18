"""fleet ais schedule.report_days admits only real ASCII YYYY-MM-DD days (RF0422-4). Synthetic, in memory."""
from types import SimpleNamespace
import unittest
from unittest import mock

from skippercast.fleet.ais import schedule

VESSEL = {"id": "v1", "name": "Synthetic Star", "port_id": "p1", "status": "active"}
LANDING = {"synthetic harbor": "p1"}


def row(day, boat="Synthetic Star", port="Synthetic Harbor"):
    return {"date": day, "boat": boat, "port": port}


def days(*dates, vessels=(VESSEL,), landing=LANDING):
    return schedule.report_days([row(d) for d in dates], list(vessels), landing)


class ReportDaysDateTest(unittest.TestCase):
    def test_impossible_calendar_dates_are_not_report_evidence(self):
        for d in ("2026-02-29", "2026-02-30", "2026-04-31", "2026-00-01", "2026-13-01", "2026-01-00", "0000-01-01"):
            with self.subTest(d=d):
                self.assertEqual(days(d), {})

    def test_only_ascii_exact_date_tokens_are_admitted(self):
        bad = ("2026-02-28\n", "2026-02-28\r\n", " 2026-02-28", "2026-02-28 ", "2026-2-8", "20260228",
               "2026-W09-6", "2026-02-28T00:00:00", "２０２６-０２-２８", None, True, 20260228, 2026.0)
        for d in bad:
            with self.subTest(d=d):
                self.assertEqual(days(d), {})

    def test_real_calendar_boundaries_remain_evidence(self):
        for d in ("0001-01-01", "9999-12-31", "2024-02-29", "2000-02-29", "2026-02-28"):
            with self.subTest(d=d):
                self.assertEqual(days(d), {"v1": {d}})
        self.assertEqual(days("1900-02-29"), {})

    def test_mixed_valid_and_invalid_rows_keep_only_good_days(self):
        self.assertEqual(days("2026-02-27", "2026-02-30", "2026-02-27", "2026-02-27\n", "2026-02-28"),
                         {"v1": {"2026-02-27", "2026-02-28"}})

    def test_existing_identity_and_home_port_filters_remain(self):
        d = "2026-02-28"
        self.assertEqual(schedule.report_days([row(d, port="Elsewhere")], [VESSEL], LANDING), {})
        self.assertEqual(days(d, vessels=[dict(VESSEL, status="excluded")]), {})
        twin = dict(VESSEL, id="v2")
        self.assertEqual(days(d, vessels=[VESSEL, twin]), {})
        alias = dict(VESSEL, aliases=[{"alias_norm": schedule.name_norm("Other Name")}])
        self.assertEqual(schedule.report_days([row(d, boat="Other Name")], [alias], LANDING), {"v1": {d}})

    def test_feed_loader_filters_dates_without_conflating_read_failure(self):
        region = SimpleNamespace()
        mixed = {"reports": [row("2026-02-28"), row("2026-02-30"), row("2026-02-28\n")]}
        bad = {"reports": [row("2026-02-30")]}
        with mock.patch.object(schedule, "_feed_ports", return_value={"u": {"p1"}}), \
                mock.patch.object(schedule, "landing_ports", return_value=LANDING):
            covered = frozenset({"p1"})
            self.assertEqual(schedule.load_report_days(region, [VESSEL], fetch=lambda u: mixed),
                             schedule.ReportDays({"v1": {"2026-02-28"}}, covered))
            self.assertEqual(schedule.load_report_days(region, [VESSEL], fetch=lambda u: bad),
                             schedule.ReportDays({}, covered))

            def boom(u):
                raise OSError("down")
            self.assertIsNone(schedule.load_report_days(region, [VESSEL], fetch=boom))


if __name__ == "__main__":
    unittest.main()
