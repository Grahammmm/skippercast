"""AISLIVE-01: the counts-only per-port AIS coverage block, offline, on a synthetic state.sqlite."""
import contextlib
import io
import os
import sqlite3
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path
from unittest import mock

from skippercast.fleet.ais import __main__ as ais_main
from skippercast.fleet.ais import port_coverage as pc
from skippercast.fleet.config import load_region

Port = namedtuple("Port", "id name")
PORTS = [Port("aa", "Alpha Harbor"), Port("bb", "Bravo Bay"), Port("cc", "Cove Landing")]
M1, M2, M3 = 999000001, 999000002, 999000003
SINCE = "2026-10-06"
DDL = "CREATE TABLE match_presence (mmsi INTEGER NOT NULL, port_id TEXT NOT NULL, day TEXT NOT NULL, " \
      "PRIMARY KEY (mmsi, port_id, day))"


def make_db(path, rows):
    db = sqlite3.connect(path)
    db.execute(DDL)
    db.executemany("INSERT INTO match_presence VALUES (?,?,?)", rows)
    db.commit()
    db.close()


class PortCoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "state.sqlite"

    def run_render(self, ports=PORTS):
        return pc.render(pc.port_coverage(self.db, ports, SINCE), ports)

    def test_counts_and_never_heard(self):
        make_db(self.db, [(M1, "aa", "2026-10-10"), (M1, "aa", "2026-10-11"), (M2, "aa", "2026-10-11"),
                          (M3, "bb", "2026-10-12")])
        result = pc.port_coverage(self.db, PORTS, SINCE)
        self.assertEqual(result["ports"], {"aa": {"mmsis": 2, "mmsi_days": 3}, "bb": {"mmsis": 1, "mmsi_days": 1},
                                           "cc": {"mmsis": 0, "mmsi_days": 0}})
        self.assertEqual(result["never_heard"], ["cc"])
        text = pc.render(result, PORTS)
        self.assertIn("### AIS coverage by port (last 30 days, counts only)", text)
        self.assertLess(text.index("| Alpha Harbor | 2 | 3 |"), text.index("| Bravo Bay | 1 | 1 |"))
        self.assertIn("| Cove Landing | 0 | 0 |", text)
        self.assertIn("Never heard (0 MMSI-days): Cove Landing", text)

    def test_window_boundary(self):
        make_db(self.db, [(M1, "aa", "2026-10-05"), (M2, "bb", SINCE)])
        result = pc.port_coverage(self.db, PORTS, SINCE)
        self.assertEqual(result["ports"]["aa"], {"mmsis": 0, "mmsi_days": 0})
        self.assertEqual(result["ports"]["bb"], {"mmsis": 1, "mmsi_days": 1})

    def test_same_mmsi_in_two_ports_counts_in_each(self):
        make_db(self.db, [(M1, "aa", "2026-10-10"), (M1, "bb", "2026-10-10")])
        ports = pc.port_coverage(self.db, PORTS, SINCE)["ports"]
        self.assertEqual((ports["aa"]["mmsis"], ports["bb"]["mmsis"]), (1, 1))

    def test_missing_state_is_unknown_and_not_created(self):
        self.assertFalse(self.db.exists())
        text = self.run_render()
        self.assertIn("No processor state yet: coverage unknown.", text)
        self.assertFalse(self.db.exists())

    def test_no_presence_table_is_unknown_and_bytes_unchanged(self):
        db = sqlite3.connect(self.db)
        db.execute("CREATE TABLE other (x INTEGER)")
        db.commit()
        db.close()
        before = self.db.read_bytes()
        self.assertIn("No processor state yet: coverage unknown.", self.run_render())
        self.assertEqual(self.db.read_bytes(), before)

    def test_every_port_heard(self):
        make_db(self.db, [(M1, "aa", SINCE), (M1, "bb", SINCE), (M1, "cc", SINCE)])
        text = self.run_render()
        self.assertIn("Every port heard.", text)
        self.assertNotIn("Never heard", text)

    def test_no_mmsi_in_output(self):
        make_db(self.db, [(M1, "aa", SINCE), (M2, "aa", SINCE), (M3, "bb", SINCE)])
        text = self.run_render()
        for mmsi in (M1, M2, M3):
            self.assertNotIn(str(mmsi), text)

    def test_command_registered_and_help(self):
        self.assertIn("port-coverage", ais_main.COMMANDS)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as raised:
            ais_main.main(["port-coverage", "--help"])
        self.assertEqual(raised.exception.code, 0)

    def test_main_missing_state_exits_zero(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"SKIPPERCAST_FLEET_VAR": self.tmp.name}), contextlib.redirect_stdout(out):
            code = ais_main.main(["port-coverage", "--region", "CA", "--now", "2026-11-05T12:00:00+00:00"])
        self.assertEqual(code, 0)
        self.assertIn("No processor state yet", out.getvalue())

    def test_main_reads_region_state(self):
        region = load_region("CA")
        root = Path(self.tmp.name) / "CA" / "ais"
        root.mkdir(parents=True)
        make_db(root / "state.sqlite", [(M1, region.ports[0].id, "2026-11-01")])
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"SKIPPERCAST_FLEET_VAR": self.tmp.name}), contextlib.redirect_stdout(out):
            code = ais_main.main(["port-coverage", "--region", "CA", "--now", "2026-11-05T12:00:00+00:00"])
        self.assertEqual(code, 0)
        self.assertIn(f"| {region.ports[0].name} | 1 | 1 |", out.getvalue())
        self.assertNotIn(str(M1), out.getvalue())

    def test_unknown_region_exits_two(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ais_main.main(["port-coverage", "--region", "ZZ"]), 2)


if __name__ == "__main__":
    unittest.main()
