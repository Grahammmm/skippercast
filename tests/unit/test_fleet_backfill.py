"""skippercast.fleet.ais.backfill and sources.marinecadastre: the MarineCadastre backfill (CF-47, design.md § 11, D9).

Offline and synthetic: every CSV is generated here in the 2026 MarineCadastre
column layout, compressed with zstandard and served by ``http.FakeSession``;
nothing is downloaded. Vessels are made-up MMSIs (999xxxxxx) with made-up names
and call signs, sailing the CF-45 test track out of a square harbor in open
ocean; the region is the committed CA config with that port and a bbox around it.
"""
from contextlib import closing
from dataclasses import replace
from datetime import date, datetime, timezone
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import tracemalloc
import unittest
import unittest.mock

import zstandard

from skippercast.fleet.ais import backfill as bf
from skippercast.fleet.ais import process
from skippercast.fleet.ais.__main__ import COMMANDS
from skippercast.fleet.ais.sources import get_source
from skippercast.fleet.ais.sources.base import AisPosition, AisStatic, Unsupported
from skippercast.fleet.ais import aggregate
from skippercast.fleet.ais.events import Event
from skippercast.fleet.ais.sources.marinecadastre import (CorruptDay, DayNotPublished, MalformedFile,
                                                          MarineCadastreSource, day_url, parse_rows)
from skippercast.fleet.ais.store import RetentionLimits
from skippercast.fleet.ais.store import AisStore
from skippercast.fleet.config import load_region
from skippercast.http import FakeSession
from tests._support import ROOT
from tests.unit.test_fleet_process import MMSI, PORT, FakeWorker, track

UTC = timezone.utc
DAY = date(2026, 6, 20)
NEXT = date(2026, 6, 21)
T0 = round(datetime(2026, 6, 20, 16, 0, tzinfo=UTC).timestamp() * 1000)   # 09:00 PDT
OTHER = 999000777          # in the box, not watched: nothing kept
FAR = 999000888            # outside the box
_CA = load_region("CA")
REGION = replace(_CA, ports=(PORT,), ais=replace(_CA.ais, south=9.0, west=-151.0, north=11.0, east=-149.0))
BBOX = ((9.0, -151.0), (11.0, -149.0))
HEADER = ("mmsi,base_date_time,longitude,latitude,sog,cog,heading,vessel_name,imo,call_sign,vessel_type,status,"
          "length,width,draft,cargo,transceiver")


def stamp(ms):
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d %H:%M:%S")


def row(mmsi, ms, lat, lon, sog="0.0", cog="", heading="", name="TEST BOAT ONE", imo="", call="TEST1", vtype="37",
        status="0", length="18", width="6", cls="A"):
    return f"{mmsi},{stamp(ms)},{lon},{lat},{sog},{cog},{heading},{name},{imo},{call},{vtype},{status},{length},{width},,,{cls}"


def track_rows(fixes):
    return [row(p.mmsi, p.ts, p.lat, p.lon, sog=p.sog, cog="" if p.cog is None else round(p.cog, 1)) for p in fixes]


def zst(lines):
    return zstandard.ZstdCompressor(level=3).compress(("\n".join([HEADER, *lines]) + "\n").encode())


def day_file():
    """The test boat's trip, an unwatched boat in the box, one far away, a malformed row and a row of the next day."""
    lines = track_rows(track(t0=T0))
    lines += [row(OTHER, T0 + k * 60_000, 10.05, -150.05, name="TEST BOAT TWO", call="TEST2") for k in range(5)]
    lines += [row(FAR, T0 + k * 60_000, 33.0, -118.0, name="TEST BOAT FAR", call="TEST3") for k in range(5)]
    lines += ["999000123,not-a-time,-150.0,10.0", f"{MMSI},{stamp(T0 + 86_400_000)},-150.0,10.0,0,,,,,,,,,,,,A"]
    return zst(lines)


def session(routes=None):
    return FakeSession({day_url(DAY): day_file(), day_url(NEXT): zst([]), **(routes or {})})


def dump(store, day):
    with closing(sqlite3.connect(store.day_path(day))) as conn:
        return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in ("positions", "discovery", "statics")}


class ParseTests(unittest.TestCase):
    def parse(self, lines, header=HEADER, mmsis=None):
        counts = {}
        records = list(parse_rows(io.StringIO("\n".join([header, *lines]) + "\n"), DAY, BBOX, mmsis, counts))
        return records, counts

    def test_rows_become_positions_and_changed_statics(self):
        records, counts = self.parse([
            row(MMSI, T0, 10.0, -150.0, sog="102.3", cog="360", heading="511", status="15", imo="IMO1234567"),
            row(MMSI, T0 + 60_000, 10.001, -150.0, sog="4.5", cog="90.0", heading="91", status="7", imo="IMO1234567"),
            row(MMSI, T0 + 120_000, 10.002, -150.0, sog="4.5", cog="90.0", imo="IMO1234567", name="TEST BOAT RENAMED"),
        ])
        positions = [r for r in records if isinstance(r, AisPosition)]
        statics = [r for r in records if isinstance(r, AisStatic)]
        self.assertEqual(len(positions), 3)
        first = positions[0]
        self.assertEqual((first.sog, first.cog, first.heading, first.nav_status), (None, None, None, None))
        self.assertEqual((first.source, first.msg_type, first.received_at), ("marinecadastre", "csv", first.ts))
        self.assertEqual(first.ts, T0)
        self.assertEqual((positions[1].sog, positions[1].cog, positions[1].heading, positions[1].nav_status),
                         (4.5, 90.0, 91, 7))
        self.assertEqual([s.name for s in statics], ["TEST BOAT ONE", "TEST BOAT RENAMED"], "a static only on change")
        s = statics[0]
        self.assertEqual((s.imo, s.call_sign, s.ship_type, s.ais_class, s.source), (1234567, "TEST1", 37, "A",
                                                                                     "marinecadastre"))
        self.assertEqual((s.dim_bow, s.dim_stern, s.dim_port, s.dim_starboard), (18, 0, 6, 0),
                         "overall length and width; the antenna offsets are unknown")
        self.assertEqual(counts["positions"], 3)
        self.assertEqual(counts["statics"], 2)

    def test_bbox_mmsi_day_and_malformed_filters(self):
        lines = [row(MMSI, T0, 10.0, -150.0), row(FAR, T0, 33.0, -118.0), row(OTHER, T0, 10.1, -150.1, call="TEST2"),
                 row(MMSI, T0 + 86_400_000, 10.0, -150.0), row(MMSI, T0 - 86_400_000, 10.0, -150.0),
                 "999000123,2026-06-20 16:00:00,-150.0", "abc,2026-06-20 16:00:00,-150.0,10.0,,,,,,,,,,,,,A",
                 f"{MMSI},2026-06-20 16:00:00,-150.0,not-a-latitude,,,,,,,,,,,,,A"]
        records, counts = self.parse(lines, mmsis={MMSI})
        self.assertEqual({(type(r).__name__, r.mmsi) for r in records}, {("AisPosition", MMSI), ("AisStatic", MMSI)})
        self.assertEqual((counts["rows"], counts["outside"], counts["other_mmsi"], counts["other_day"]), (8, 1, 2, 2))
        self.assertEqual(counts["malformed"], 2)

    def test_legacy_header_names_read_the_same(self):
        legacy = ("MMSI,BaseDateTime,LAT,LON,SOG,COG,Heading,VesselName,IMO,CallSign,VesselType,Status,Length,"
                  "Width,Draft,Cargo,TransceiverClass")
        line = f"{MMSI},2026-06-20T16:00:00,10.0,-150.0,3.0,45.0,44,TEST BOAT ONE,,TEST1,37,0,18,6,,,B"
        records, _ = self.parse([line], header=legacy)
        position, static = records
        self.assertEqual((position.lat, position.lon, position.sog, position.heading), (10.0, -150.0, 3.0, 44))
        self.assertEqual(static.ais_class, "B")

    def test_a_file_without_the_required_columns_is_refused(self):
        with self.assertRaises(MalformedFile):
            self.parse([], header="mmsi,when,lat,lon")
        with self.assertRaises(MalformedFile):
            list(parse_rows(io.StringIO(""), DAY, BBOX))


class SourceTests(unittest.TestCase):
    def test_history_reads_the_day_file_through_the_policy_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = session()
            source = MarineCadastreSource(session=fake, workdir=Path(tmp))
            counts = {}
            records = list(source.history(DAY, BBOX, {MMSI}, counts=counts))
            self.assertEqual(fake.calls[0][1], "https://noaaocm.blob.core.windows.net/ais/csv2/csv2026/ais-2026-06-20.csv.zst")
            self.assertEqual(fake.calls[0][2]["allowed_prefixes"], ("https://noaaocm.blob.core.windows.net/ais/csv2/",))
            self.assertEqual(counts["positions"], len(track(t0=T0)))
            self.assertTrue(all(r.source == "marinecadastre" for r in records))
            self.assertEqual(list(Path(tmp).iterdir()), [], "the download is a temporary file")

    def test_an_unpublished_day_and_no_live_feed(self):
        source = MarineCadastreSource(session=FakeSession({day_url(DAY): (404, b"")}))
        with self.assertRaises(DayNotPublished):
            list(source.history(DAY, BBOX, None))

        async def first():
            async for record in source.stream(BBOX, None):
                return record
        import asyncio
        with self.assertRaises(Unsupported):
            asyncio.run(first())
        self.assertIsInstance(get_source("marinecadastre"), MarineCadastreSource)
        self.assertFalse(get_source("marinecadastre").realtime)


class BackfillTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "CA" / "ais"
        self.store = bf.backfill_store(self.root)

    def run_backfill(self, worker=None, fake=None, **options):
        worker = worker or FakeWorker()
        source = MarineCadastreSource(session=fake or session(), workdir=self.store.root / "staging")
        counts = bf.backfill(REGION, worker, first=DAY, last=DAY, root=self.root, source=source,
                             now_ms=T0 + 200 * 86_400_000, **options)
        return worker, counts


class BackfillTests(BackfillTestCase):
    def test_every_derived_row_carries_the_source_and_its_rights_tag(self):
        worker, counts = self.run_backfill()
        self.assertEqual([d["day"] for d in counts["days"]], ["2026-06-20", "2026-06-21"],
                         "the UTC days of a Pacific day")
        activity = worker.posts("activity", "replace")
        self.assertTrue(activity)
        trips = [t for body in activity for t in body["trips"]]
        events = [e for body in activity for e in body["events"]]
        self.assertEqual(len(trips), 1)
        self.assertTrue(events)
        for body in activity:
            self.assertEqual(body["source"], "marinecadastre")
        for derived in trips + events:
            self.assertEqual((derived["source"], derived["rights"]), ("marinecadastre", "noaa-planning-only"))
        self.assertEqual(trips[0]["local_date"], "2026-06-20")
        cells = [c for body in worker.posts("activity", "aggregates") for c in body["aggregates"]["cells"]]
        self.assertTrue(cells)
        self.assertEqual({c["rights"] for c in cells}, {"noaa-planning-only"})
        # Raw rows: the backfill's own store, never the listener's.
        self.assertFalse((self.root / "raw").exists())
        rows = dump(self.store, DAY)
        self.assertEqual({r[9] for r in rows["positions"]}, {"marinecadastre"})
        self.assertEqual({r[0] for r in rows["positions"]}, {MMSI})
        self.assertEqual({r[0] for r in rows["statics"]}, {MMSI}, "statics of the target vessels only")
        self.assertEqual(rows["discovery"], [])
        self.assertEqual(self.store.root, self.root / "backfill")
        manifest = json.loads((self.store.root / "days" / "2026-06-20.json").read_text())
        self.assertEqual((manifest["source"], manifest["rights"], manifest["mmsis"]),
                         ("marinecadastre", "noaa-planning-only", [MMSI]))

    def test_re_running_a_day_is_idempotent(self):
        first, counts = self.run_backfill()
        rows = dump(self.store, DAY)
        second, again = self.run_backfill(force=True)
        self.assertEqual(dump(self.store, DAY), rows, "a forced re-ingest replaces the day with the same rows")
        self.assertEqual([d["positions"] for d in again["days"]], [d["positions"] for d in counts["days"]])
        self.assertEqual(second.posts("activity", "replace"), first.posts("activity", "replace"))
        third, skipped = self.run_backfill(fake=FakeSession())   # no routes: a download would fail
        self.assertEqual([d.get("skipped") for d in skipped["days"]], [True, True])
        self.assertEqual(third.posts("activity", "replace"), first.posts("activity", "replace"))
        self.assertEqual(dump(self.store, DAY), rows)
        self.assertEqual(sorted(p.name for p in self.store.raw_dir.iterdir()),
                         ["2026-06-20.sqlite", "2026-06-21.sqlite"], "no WAL or staging files left behind")
        self.assertFalse((self.store.root / "staging" / "2026-06-20").exists())

    def test_a_changed_mmsi_list_ingests_the_day_again(self):
        self.run_backfill()
        _, counts = self.run_backfill(mmsis=[MMSI, OTHER])
        self.assertNotIn("skipped", counts["days"][0])
        self.assertEqual({r[0] for r in dump(self.store, DAY)["positions"]}, {MMSI, OTHER})

    def test_an_interrupted_day_leaves_the_previous_copy(self):
        self.run_backfill()
        rows = dump(self.store, DAY)

        class Broken(MarineCadastreSource):
            def history(self, day, bbox, mmsis=None, counts=None):
                yield from list(super().history(day, bbox, mmsis, counts))[:3]
                raise OSError("connection reset")

        with self.assertRaises(OSError):
            bf.ingest_day(Broken(session=session()), self.store, DAY, BBOX, {MMSI}, force=True)
        self.assertEqual(dump(self.store, DAY), rows)
        self.assertFalse((self.store.root / "staging" / "2026-06-20").exists())

    def test_a_fresh_state_never_prunes_unless_allowed(self):
        worker, _ = self.run_backfill()
        bodies = [b["aggregates"] for b in worker.posts("activity", "aggregates")]
        self.assertTrue(bodies)
        self.assertFalse(any("prune" in b for b in bodies), "CF-45: a season new to the state never prunes")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "CA" / "ais"
        self.store = bf.backfill_store(self.root)
        worker, _ = self.run_backfill(allow_prune=True)
        self.assertIn("prune", worker.posts("activity", "aggregates")[-1]["aggregates"])

    def test_unpublished_days_are_reported_and_an_empty_window_is_not_processed(self):
        worker, counts = self.run_backfill(fake=session({day_url(NEXT): (404, b"")}))
        self.assertEqual(counts["missing"], ["2026-06-21"])
        self.assertTrue(worker.posts("activity", "replace"), "the published day is still processed")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "CA" / "ais"
        self.store = bf.backfill_store(self.root)
        worker, counts = self.run_backfill(fake=FakeSession({day_url(DAY): (404, b""), day_url(NEXT): (404, b"")}))
        self.assertIsNone(counts["processed"])
        self.assertEqual(worker.posts("activity"), [])

    def test_no_targets_is_an_error(self):
        with self.assertRaises(ValueError):
            self.run_backfill(worker=FakeWorker(vessels=[]))


WATCHED = [999100000 + k for k in range(4)]


def big_day(rows):
    """``rows`` CSV rows (about 89 bytes each): a quarter watched positions in the box, the rest far outside it."""
    out, size = io.BytesIO(), 0
    start = round(datetime(2026, 6, 20, tzinfo=UTC).timestamp() * 1000)
    with zstandard.ZstdCompressor(level=1).stream_writer(out, closefd=False) as writer:
        for k in range(-1, rows):
            if k < 0:
                line = HEADER
            elif k % 4 == 0:
                line = row(WATCHED[(k // 4) % 4], start + (k // 4) * 2_000, 10.0 + (k % 997) / 1e4, -150.0,
                           sog="1.0", cog="10.0")
            else:
                line = row(990000000 + k % 5000, start + (k // 4) * 2_000, 33.0 + (k % 991) / 1e4,
                           -118.0 - (k % 983) / 1e4, name=f"TEST FAR {k % 5000}", call=f"T{k % 5000}")
            data = (line + "\n").encode()
            size += len(data)
            writer.write(data)
    return out.getvalue(), size


class DamagedDayTests(BackfillTestCase):
    def test_a_truncated_download_stores_nothing_of_the_day(self):
        whole = day_file()
        for name, route in (("cut inside the frame", whole[:len(whole) // 2]),
                            ("short of its Content-Length", (200, whole[:len(whole) // 2],
                                                             {"Content-Length": str(len(whole))})),
                            ("not Zstandard", b"this is not a zstd file at all")):
            with self.subTest(name):
                source = MarineCadastreSource(session=FakeSession({day_url(DAY): route}))
                with self.assertRaises(CorruptDay):
                    list(source.history(DAY, BBOX, {MMSI}))
                with self.assertRaises(CorruptDay):
                    bf.ingest_day(source, self.store, DAY, BBOX, {MMSI})
                self.assertFalse(self.store.day_path(DAY).exists())
                self.assertFalse((self.store.root / "days" / "2026-06-20.json").exists())

    def test_one_corrupt_day_is_reported_and_the_rest_go_on(self):
        whole = day_file()
        worker, counts = self.run_backfill(fake=session({day_url(DAY): whole[:len(whole) // 2]}))
        self.assertEqual([f["day"] for f in counts["failed"]], ["2026-06-20"])
        self.assertEqual([d["day"] for d in counts["days"]], ["2026-06-21"])
        self.assertFalse(self.store.day_path(DAY).exists())
        _, again = self.run_backfill()
        self.assertEqual([d.get("skipped") for d in again["days"]], [None, True],
                         "the failed day is downloaded again; the good one is not")
        self.assertEqual(again["failed"], [])

    def test_the_command_fails_when_a_day_failed(self):
        whole = day_file()
        fake = session({day_url(DAY): whole[:100]})
        original = bf.backfill

        def patched(region, worker, **options):
            return original(REGION, FakeWorker(), root=self.root, source=MarineCadastreSource(session=fake),
                            now_ms=T0 + 200 * 86_400_000, **{k: v for k, v in options.items() if k != "mmsis"})
        with unittest.mock.patch.object(bf, "backfill", patched), \
                unittest.mock.patch.object(bf, "worker_base", lambda: "https://example.invalid"), \
                unittest.mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(bf.main(["--region", "CA", "--from", "2026-06-20", "--to", "2026-06-20"]), 1)


class RetentionTests(BackfillTestCase):
    LIMITS = RetentionLimits(raw_days=30, discovery_days=7, static_days=90)

    def test_days_expire_by_age_since_ingest(self):
        now = T0 + 200 * 86_400_000          # ingested now, about 200 days after the data day
        self.run_backfill()
        self.assertEqual(bf.apply_retention(self.store, self.LIMITS, now + 30 * 86_400_000),
                         {"deleted": [], "emptied": {}}, "day 30 after ingest: kept")
        result = bf.apply_retention(self.store, self.LIMITS, now + 31 * 86_400_000)
        self.assertEqual(result["emptied"], {"2026-06-20": ["positions"]})
        rows = dump(self.store, DAY)
        self.assertEqual(rows["positions"], [])
        self.assertTrue(rows["statics"], "statics last static_days")
        self.assertFalse((self.store.root / "days" / "2026-06-20.json").exists(),
                         "positions gone: the next backfill downloads the day again")
        result = bf.apply_retention(self.store, self.LIMITS, now + 91 * 86_400_000)
        self.assertEqual(sorted(result["deleted"]), ["2026-06-20", "2026-06-21"])
        self.assertEqual(list(self.store.raw_dir.iterdir()), [])
        self.assertEqual(list((self.store.root / "days").iterdir()), [])

    def test_the_scheduled_processor_run_applies_it(self):
        now = T0 + 200 * 86_400_000
        self.run_backfill()
        counts = process.run(REGION, FakeWorker(), root=self.root, now_ms=now + 91 * 86_400_000, hook_table={})
        self.assertEqual(counts["backfill_retention"], {"deleted": 2, "emptied": 0})
        self.assertEqual(self.store.days(), [])


def event(trip, source, start_min, end_min, vessel="v1"):
    return Event(id=f"{trip}-e", trip_id=trip, segment_id=f"{trip}-s", vessel_id=vessel, region="CA",
                 kind="fishing-drift", lat=10.0, lon=-150.0, radius_m=10.0, started_at=T0 + start_min * 60_000,
                 ended_at=T0 + end_min * 60_000, dwell_min=end_min - start_min, port_id=None, vessel_class=None,
                 trip_type=None, season="2026", season_part=None, source=source,
                 rights=process.SOURCE_RIGHTS[source], classifier_version="test")


class SourcePrecedenceTests(BackfillTestCase):
    def test_prefer_sources_keeps_one_source_per_vessel_and_time(self):
        events = [event("live-1", "aisstream", 0, 60), event("noaa-1", "marinecadastre", 30, 90),
                  event("noaa-2", "marinecadastre", 120, 150), event("noaa-3", "marinecadastre", 30, 90, vessel="v2")]
        kept = aggregate.prefer_sources(events, process.SOURCE_PRECEDENCE)
        self.assertEqual([e.trip_id for e in kept], ["live-1", "noaa-2", "noaa-3"])
        self.assertEqual(aggregate.prefer_sources(reversed(events), process.SOURCE_PRECEDENCE)[::-1], kept)

    def test_a_trip_the_listener_already_heard_is_not_counted_twice(self):
        """The processor state already holds aisstream events for the same vessel and time."""
        AisStore(self.root).write(positions=track(t0=T0))
        now = T0 + 200 * 86_400_000
        live = FakeWorker()
        process.run(REGION, live, root=self.root, now_ms=now, window=bf.window_ms(DAY, DAY, REGION.timezone),
                    hook_table={})
        live_cells = {c["id"]: c for b in live.posts("activity", "aggregates") for c in b["aggregates"]["cells"]}
        self.assertTrue(live_cells)
        self.assertEqual({c["rights"] for c in live_cells.values()}, {"internal-only"})
        worker, _ = self.run_backfill()
        self.assertTrue(worker.posts("activity", "replace"), "the backfill still pushes its own trips")
        self.assertEqual(worker.posts("activity", "aggregates"), [],
                         "the same trip from the backfill changes no aggregate cell")
        state = process.State(self.root / "state.sqlite")
        self.addCleanup(state.close)
        stored = state.season_events("2026")
        self.assertEqual({e.source for e in stored}, {"aisstream", "marinecadastre"})
        params = aggregate.AggregateParams.from_region(REGION)
        cells = aggregate.compute(aggregate.prefer_sources(stored, process.SOURCE_PRECEDENCE), params,
                                  now_ms=now, tz=REGION.timezone, computed_at="x")
        for cell in cells:
            self.assertEqual((cell.events_n, cell.dwell_min, cell.rights),
                             (live_cells[cell.id]["events_n"], live_cells[cell.id]["dwell_min"], "internal-only"))
        doubled = aggregate.compute(stored, params, now_ms=now, tz=REGION.timezone, computed_at="x")
        self.assertGreater(sum(c.events_n for c in doubled), sum(c.events_n for c in cells), "without it: twice")


class StreamingTests(BackfillTestCase):
    def peak(self, rows):
        compressed, size = big_day(rows)
        store = AisStore(Path(self.tmp.name) / f"memory-{rows}")
        source = MarineCadastreSource(session=FakeSession({day_url(DAY): compressed}), workdir=store.root / "staging")
        tracemalloc.start()
        try:
            result = bf.ingest_day(source, store, DAY, BBOX, set(WATCHED), batch=2_000)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual((result["positions"], result["outside"]), (rows // 4, rows - rows // 4))
        self.assertEqual(len(dump(store, DAY)["positions"]), rows // 4)
        return peak, size

    def test_memory_stays_bounded_on_a_multi_megabyte_day(self):
        """Five times the rows (over 12 MB of CSV) barely move peak Python memory: the file is streamed, never held."""
        small, small_size = self.peak(28_000)
        large, large_size = self.peak(140_000)
        self.assertGreater(large_size, 12_000_000)
        self.assertGreater(large_size, 4.9 * small_size)
        self.assertLess(large, small * 1.5, f"peak {large} bytes for {large_size} bytes of CSV, {small} for {small_size}")
        self.assertLess(large, 6_000_000)


class CommandTests(unittest.TestCase):
    def test_the_command_and_its_arguments(self):
        self.assertIn("backfill", COMMANDS)
        for argv in (["--region", "CA"], ["--region", "CA", "--month", "2026-13"],
                     ["--region", "CA", "--month", "2026-06", "--from", "2026-06-01", "--to", "2026-06-02"],
                     ["--region", "CA", "--from", "2026-06-02"], ["--region", "CA", "--from", "2026-06-02",
                                                                  "--to", "2026-06-01"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as raised:
                bf.main(argv)
            self.assertEqual(raised.exception.code, 2)

    def test_window_and_utc_days(self):
        start, end = bf.window_ms(date(2026, 6, 1), date(2026, 6, 30), "America/Los_Angeles")
        self.assertEqual(datetime.fromtimestamp(start / 1000, UTC).isoformat(), "2026-06-01T07:00:00+00:00")
        days = bf.utc_days(start, end)
        self.assertEqual((days[0], days[-1], len(days)), (date(2026, 6, 1), date(2026, 7, 1), 31))

    def test_the_store_is_the_processors_marinecadastre_store(self):
        root = Path("/nonexistent/CA/ais")
        self.assertEqual(process.STORES["marinecadastre"](root).raw_dir, root / "backfill" / "raw")
        self.assertEqual(process.SOURCE_RIGHTS["marinecadastre"], "noaa-planning-only")
        self.assertIsInstance(bf.backfill_store(root), AisStore)


class WorkflowTests(unittest.TestCase):
    def test_fleet_ais_takes_a_backfill_month(self):
        text = (ROOT / ".github" / "workflows" / "fleet-ais.yml").read_text()
        self.assertIn("      backfill_month:\n", text)
        self.assertIn("BACKFILL_MONTH: ${{ inputs.backfill_month }}", text)
        self.assertIn('python -m skippercast.fleet.ais backfill --region "$REGION" --month "$BACKFILL_MONTH"', text)
        self.assertIn("timeout-minutes: ${{ inputs.backfill_month && 150 || 25 }}", text)
        self.assertEqual(text.count("inputs.backfill_month"), 2, "the input reaches the script through the environment")
        self.assertNotRegex(text, r"(contents|actions|issues|pull-requests): write")


if __name__ == "__main__":
    unittest.main()
