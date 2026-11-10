"""skippercast.fleet.ais.store: complementary statics of one (mmsi, ts, source) key (RF0804-6).

The two parts of a Class B type-24 report are normalised in the same receipt millisecond, so they share a
statics key. The store fills NULL fields of the first row from a compatible later row and never mixes in a
row that contradicts it. Synthetic MMSIs only (the encoder lives in test_fleet_local_nmea).
"""
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
from zoneinfo import ZoneInfo

from skippercast.fleet.ais import process
from skippercast.fleet.ais.match import MatchState
from skippercast.fleet.ais.sources.base import AisPosition, AisStatic
from skippercast.fleet.ais.store import AisStore
from tests.unit.test_fleet_local_nmea import NOW_MS, feed, make, single, type24a, type24b

MMSI = 999000011
TS = 1793908830500
DAY_MS = 86_400_000
_STATIC_FILL_COLUMNS = ("name", "call_sign", "imo", "ship_type", "dim_bow", "dim_stern", "dim_port", "dim_starboard")
FULL = AisStatic(MMSI, TS, "SEA EXAMPLE", "WDX0011", 9999999, 30, 6, 4, 2, 2, "B", "local-nmea")
VALUES = {"name": "OTHER NAME", "call_sign": "WDX0099", "imo": 1234567, "ship_type": 37, "dim_bow": 9,
          "dim_stern": 9, "dim_port": 3, "dim_starboard": 3}


def only(**fields):
    """A record carrying just the named payload fields."""
    base = AisStatic(MMSI, TS, None, None, None, None, None, None, None, None, "B", "local-nmea")
    return replace(base, **fields)


class StoreCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "CA" / "ais"
        self.store = AisStore(self.root)

    def rows(self, start=0, end=10 * DAY_MS * 365 * 60):
        return list(self.store.read_statics(start, end))


class HandoffTest(StoreCase):
    def parts(self):
        source = make()
        a = feed(source, [single(type24a(MMSI, "SEA EXAMPLE"))])
        b = feed(source, [single(type24b(MMSI, 30, "WDX0011", (7, 3, 2, 2)))])
        self.assertEqual((len(a), len(b)), (1, 1))
        self.assertEqual(a[0].ts, b[0].ts, "both parts get the same receipt millisecond")
        self.assertEqual(a[0].ts, NOW_MS)
        return a[0], b[0]

    def test_type24_same_millisecond_parts_survive_both_orders(self):
        part_a, part_b = self.parts()
        for order, batch in (("A-then-B", [part_a, part_b]), ("B-then-A", [part_b, part_a])):
            with self.subTest(order=order):
                store = AisStore(self.root / order)
                counts = store.write(statics=batch)
                self.assertEqual(counts.statics, 2, "one insert and one enrichment")
                rows = list(store.read_statics(0, 2 * NOW_MS))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].ts, NOW_MS, "no timestamp is invented")
                self.assertEqual((rows[0].name, rows[0].call_sign, rows[0].ship_type, rows[0].dim_bow,
                                  rows[0].dim_stern), ("SEA EXAMPLE", "WDX0011", 30, 7, 3))
                state = process.State(self.root / order / "state.sqlite")
                self.addCleanup(state.close)
                mstate = MatchState(state)
                mstate.add(rows, (), (), ZoneInfo("America/Los_Angeles"))
                seen = mstate.statics()[MMSI]
                self.assertEqual((seen.name, seen.call_sign, seen.ship_type, seen.length_m),
                                 ("SEA EXAMPLE", "WDX0011", 30, 10.0))


class EnrichmentTest(StoreCase):
    def test_static_enrichment_across_batches_and_replay(self):
        name_part, rest = only(name="SEA EXAMPLE"), only(call_sign="WDX0011", ship_type=30, dim_bow=7, dim_stern=3)
        self.assertEqual(self.store.write(statics=[name_part]).statics, 1)
        self.assertEqual(self.store.write(statics=[name_part]).statics, 0, "exact duplicate")
        self.assertEqual(self.store.write(statics=[rest]).statics, 1, "enrichment")
        self.assertEqual(self.store.write(statics=[rest]).statics, 0, "replay of the second part")
        self.assertEqual(self.store.write(statics=[name_part, rest]).statics, 0, "replay of the batch")
        expected = [replace(name_part, call_sign="WDX0011", ship_type=30, dim_bow=7, dim_stern=3)]
        self.assertEqual(self.rows(), expected)
        reopened = AisStore(self.root)       # a new store object on the same files: nothing changes on replay
        self.assertEqual(reopened.write(statics=[rest, name_part]).statics, 0)
        self.assertEqual(list(reopened.read_statics(0, 2 * NOW_MS)), expected)
        self.assertEqual(self.rows(), expected)

    def test_static_compatible_subsets_are_noops(self):
        self.store.write(statics=[FULL])
        for record in (only(), only(name=FULL.name), only(call_sign=FULL.call_sign, dim_bow=6), FULL):
            with self.subTest(record=record):
                self.assertEqual(self.store.write(statics=[record]).statics, 0)
                self.assertEqual(self.rows(), [FULL])

    def test_static_independent_fills_keep_existing_values_and_zero_is_a_value(self):
        self.store.write(statics=[only(name="SEA EXAMPLE", dim_bow=0, imo=0)])
        self.assertEqual(self.store.write(statics=[only(name="SEA EXAMPLE", dim_bow=0, ship_type=30)]).statics, 1)
        self.assertEqual(self.store.write(statics=[only(dim_bow=5)]).statics, 0, "0 is known, not NULL")
        self.assertEqual(self.store.write(statics=[only(name="", call_sign="WDX0011")]).statics, 0,
                         "an empty name conflicts with the known one")
        self.assertEqual(self.rows(), [only(name="SEA EXAMPLE", dim_bow=0, imo=0, ship_type=30)])
        self.assertEqual(self.store.write(statics=[only(dim_stern=3, call_sign="WDX0011")]).statics, 1)
        row = self.rows()[0]
        self.assertEqual((row.name, row.dim_bow, row.imo, row.ship_type, row.dim_stern, row.call_sign),
                         ("SEA EXAMPLE", 0, 0, 30, 3, "WDX0011"))


class ConflictTest(StoreCase):
    def test_static_collision_refuses_any_conflicting_known_field(self):
        for column in _STATIC_FILL_COLUMNS + ("ais_class",):
            with self.subTest(column=column):
                store = AisStore(self.root / column)
                if column == "ais_class":
                    first, clash = only(name="SEA EXAMPLE", ais_class="A"), only(name="SEA EXAMPLE", ais_class="B")
                else:
                    known = VALUES[column]
                    other = known + "X" if isinstance(known, str) else known + 1
                    first, clash = only(**{column: known}), only(**{column: other})
                # the clash also offers a field the first row lacks; none of it may apply
                missing = "call_sign" if column != "call_sign" else "name"
                clash = replace(clash, **{missing: VALUES[missing]})
                self.assertEqual(store.write(statics=[first]).statics, 1)
                self.assertEqual(store.write(statics=[clash]).statics, 0)
                self.assertEqual(list(store.read_statics(0, 2 * NOW_MS)), [first])
                self.assertEqual(store.write(statics=[first, clash]).statics, 0)
                self.assertEqual(list(store.read_statics(0, 2 * NOW_MS)), [first])

    def test_conflict_within_one_batch_keeps_the_first_row_whole(self):
        counts = self.store.write(statics=[only(name="SEA EXAMPLE"), only(name="OTHER", call_sign="WDX0099"),
                                           only(call_sign="WDX0011")])
        self.assertEqual(counts.statics, 2, "insert, refused clash, then a compatible fill")
        self.assertEqual(self.rows(), [only(name="SEA EXAMPLE", call_sign="WDX0011")])


class KeyTest(StoreCase):
    def test_static_identity_source_time_and_day_boundaries(self):
        midnight = (TS // DAY_MS + 1) * DAY_MS
        other = [only(name="A"), replace(only(name="B"), mmsi=MMSI + 1), replace(only(name="C"), source="aisstream"),
                 replace(only(name="D"), ts=TS + 1), replace(only(name="E"), ts=midnight - 1),
                 replace(only(name="F"), ts=midnight)]
        self.assertEqual(self.store.write(statics=other).statics, 6)
        self.assertEqual(self.store.write(statics=[replace(r, call_sign="WDX0011") for r in other]).statics, 6)
        rows = self.rows()
        self.assertEqual(sorted((r.name, r.call_sign) for r in rows), [(n, "WDX0011") for n in "ABCDEF"])
        self.assertEqual(len(self.store.days()), 2, "the UTC-boundary rows stay in their own day files")
        with sqlite3.connect(self.store.day_path(self.store.days()[1])) as conn:
            self.assertEqual(conn.execute("SELECT name FROM statics").fetchall(), [("F",)])

    def test_positions_and_discovery_keep_earliest_receipt(self):
        def fix(received):
            return AisPosition(MMSI, TS, 32.7, -117.2, 5.0, None, None, None, "PositionReport", "local-nmea",
                               received)
        for table in ("positions", "discovery"):
            with self.subTest(table=table):
                store = AisStore(self.root / table)
                written = [getattr(store.write(**{table: [fix(TS + late)]}), table) for late in (500, 900, 100)]
                self.assertEqual(written, [1, 0, 1])
                rows = list(store.read_positions(0, 2 * TS, table=table))
                self.assertEqual([r.received_at for r in rows], [TS + 100])


if __name__ == "__main__":
    unittest.main()
