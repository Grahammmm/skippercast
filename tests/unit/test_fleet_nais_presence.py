"""The NAIS transmit check (scripts/fleet/nais_presence.py): offline, against a fake day source.

Synthetic MMSIs 999000001..3; nothing here reaches the network, the Worker or a real store.
"""
from contextlib import redirect_stderr
from datetime import date, datetime, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from skippercast.fleet.ais.sources.base import AisPosition
from skippercast.fleet.ais.sources.marinecadastre import CorruptDay, DayNotPublished
from tests._support import ROOT

_spec = importlib.util.spec_from_file_location("nais_presence", ROOT / "scripts/fleet/nais_presence.py")
nais = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nais)

HOME = (35.37, -120.86)      # inside the morro-bay geofence
AWAY = (36.9, -122.0)        # inside the CA box, outside both ports
FREE = mock.Mock(free=500 * 10**9)


def ms(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp() * 1000)


def pos(mmsi, when, place):
    return AisPosition(mmsi, ms(when), place[0], place[1], 1.0, 0.0, None, None, "csv", "marinecadastre", ms(when))


class FakeSource:
    def __init__(self, days):
        self.days, self.calls = days, []

    def history(self, day, bbox, mmsis=None, counts=None):
        self.calls.append(day)
        got = self.days.get(day.isoformat(), [])
        if isinstance(got, Exception):
            raise got
        return iter(got)


class Worker:
    def __getattr__(self, name):
        raise AssertionError(f"Worker.{name} must not be used")


class NaisPresenceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.targets = self.dir / "targets.json"
        self.targets.write_text(json.dumps({"A": 999000001, "B": 999000002, "C": 999000003}))

    def run_check(self, days, extra=(), first="2026-01-12", last="2026-01-14", free=FREE):
        source = FakeSource(days)
        out = io.StringIO()
        argv = ["--region", "CA", "--from", first, "--to", last, "--targets", str(self.targets),
                "--workdir", str(self.dir / "work"), *extra]
        with mock.patch.object(nais.shutil, "disk_usage", return_value=free):
            code = nais.main(argv, source=source, out=out)
        return code, out.getvalue(), source

    def row(self, text, label):
        line = next(l for l in text.splitlines() if l.startswith(f"| {label} |"))
        return [c.strip() for c in line.strip("|").split("|")][1:]

    def test_home_and_anywhere_days(self):
        days = {"2026-01-12": [pos(999000001, "2026-01-12T20:00", HOME)],
                "2026-01-13": [pos(999000001, "2026-01-13T20:00", HOME)],
                "2026-01-14": [pos(999000001, "2026-01-14T20:00", AWAY)]}
        code, text, _ = self.run_check(days)
        self.assertEqual(code, 0)
        self.assertEqual(self.row(text, "A"), ["2", "3", "3"])

    def test_never_heard_label_still_listed(self):
        code, text, _ = self.run_check({"2026-01-12": [pos(999000001, "2026-01-12T20:00", HOME)]})
        self.assertEqual(code, 0)
        self.assertEqual(self.row(text, "B"), ["0", "0", "3"])
        self.assertEqual(self.row(text, "C"), ["0", "0", "3"])

    def test_late_utc_position_lands_on_previous_pacific_day(self):
        # 2026-01-13 07:30Z is 23:30 on 12 Jan in Pacific time.
        out = self.dir / "private.json"
        code, _, _ = self.run_check({"2026-01-13": [pos(999000002, "2026-01-13T07:30", HOME)]},
                                    extra=["--private-out", str(out)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.read_text())["B"], {"home_days": ["2026-01-12"], "anywhere_days": ["2026-01-12"]})

    def test_positions_outside_the_local_window_do_not_count(self):
        # 2026-01-12 07:30Z is still 11 Jan locally.
        code, text, _ = self.run_check({"2026-01-12": [pos(999000001, "2026-01-12T07:30", HOME)]})
        self.assertEqual(self.row(text, "A"), ["0", "0", "3"])

    def test_missing_day_reported_others_count(self):
        days = {"2026-01-13": DayNotPublished("x"), "2026-01-12": [pos(999000001, "2026-01-12T20:00", HOME)]}
        code, text, _ = self.run_check(days)
        self.assertEqual(code, 0)
        self.assertIn("Missing (not published): 2026-01-13", text)
        self.assertEqual(self.row(text, "A"), ["1", "1", "3"])

    def test_every_day_missing_exits_1(self):
        days = {d: DayNotPublished("x") for d in ("2026-01-12", "2026-01-13", "2026-01-14", "2026-01-15")}
        code, text, _ = self.run_check(days)
        self.assertEqual(code, 1)
        self.assertIn("Missing (not published): 2026-01-12", text)

    def test_corrupt_day_listed_and_run_continues(self):
        days = {"2026-01-12": CorruptDay("short"), "2026-01-13": [pos(999000001, "2026-01-13T20:00", HOME)]}
        code, text, _ = self.run_check(days)
        self.assertEqual(code, 0)
        self.assertIn("Failed: 2026-01-12 (CorruptDay)", text)
        self.assertEqual(self.row(text, "A"), ["1", "1", "3"])

    def test_disk_below_floor_exits_3_before_any_download(self):
        code, text, source = self.run_check({}, free=mock.Mock(free=10 * 10**9))
        self.assertEqual(code, 3)
        self.assertIn("stopped: 10 GB free, below 50 GB", text)
        self.assertEqual(source.calls, [])

    def test_disk_recheck_before_each_day(self):
        source = FakeSource({})
        usage = [mock.Mock(free=500 * 10**9), mock.Mock(free=500 * 10**9), mock.Mock(free=1 * 10**9)]
        out = io.StringIO()
        argv = ["--region", "CA", "--from", "2026-01-12", "--to", "2026-01-14", "--targets", str(self.targets),
                "--workdir", str(self.dir / "work")]
        with mock.patch.object(nais.shutil, "disk_usage", side_effect=usage):
            code = nais.main(argv, source=source, out=out)
        self.assertEqual(code, 3)
        self.assertEqual(len(source.calls), 1)

    def test_bad_arguments_exit_2(self):
        def code_of(first, last, targets=None):
            if targets is not None:
                self.targets.write_text(json.dumps(targets))
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                self.run_check({}, first=first, last=last)
            return caught.exception.code
        self.assertEqual(code_of("2026-01-12", "2026-01-19"), 2)                       # 8 days
        six = {c: 999000000 + i for i, c in enumerate("ABCDEF", 1)}
        self.assertEqual(code_of("2026-01-12", "2026-01-13", six), 2)                  # 6 labels
        self.assertEqual(code_of("2026-01-12", "2026-01-13", {"ab": 999000001}), 2)    # bad label
        self.assertEqual(code_of("2026-01-12", "2026-01-13", {"A": 0}), 2)             # invalid MMSI
        self.assertEqual(code_of("2026-01-12", "2026-01-13", {"A": True}), 2)
        self.assertEqual(code_of("2026-01-14", "2026-01-12", {"A": 999000001}), 2)     # reversed
        self.targets.write_text(json.dumps({"A": 999000001}))
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            self.run_check({}, extra=["--ports", "nowhere"])
        self.assertEqual(caught.exception.code, 2)

    def test_seven_day_window_is_allowed(self):
        code, text, _ = self.run_check({}, first="2026-01-12", last="2026-01-18")
        self.assertEqual(code, 0)
        self.assertEqual(self.row(text, "A"), ["0", "0", "7"])

    def test_stdout_has_no_mmsi_position_or_name_and_states_the_caveat(self):
        days = {"2026-01-12": [pos(999000001, "2026-01-12T20:00", HOME), pos(999000002, "2026-01-12T21:00", AWAY)]}
        code, text, _ = self.run_check(days)
        for secret in ("999000001", "999000002", "999000003", "35.37", "120.86", "36.9", "122.0"):
            self.assertNotIn(secret, text)
        self.assertIn("Window: 2026-01-12 to 2026-01-14", text)
        self.assertIn(nais.NOTE, text)
        self.assertIn("neither that a boat has no transponder nor that it made no trip", text)

    def test_private_out_mode_is_0600(self):
        out = self.dir / "private.json"
        self.run_check({"2026-01-12": [pos(999000001, "2026-01-12T20:00", HOME)]}, extra=["--private-out", str(out)])
        self.assertEqual(stat.S_IMODE(os.stat(out).st_mode), 0o600)
        self.assertEqual(json.loads(out.read_text())["A"]["home_days"], ["2026-01-12"])

    def test_no_worker_is_constructed(self):
        with mock.patch("skippercast.fleet.ais.process.Worker", Worker, create=True), \
                mock.patch("skippercast.fleet.ais.backfill.backfill", side_effect=AssertionError("backfill called")):
            code, _, _ = self.run_check({"2026-01-12": [pos(999000001, "2026-01-12T20:00", HOME)]})
        self.assertEqual(code, 0)
        self.assertFalse(hasattr(nais, "Worker"))


if __name__ == "__main__":
    unittest.main()
