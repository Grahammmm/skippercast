"""MarineCadastre CSV quoting syntax (RF0520-6): broken quoting is a file-level MalformedFile, never a recovered row.

Offline and synthetic: generated CSV with made-up 999xxxxxx MMSIs, zstandard bytes served by ``FakeSession``,
every store under a temporary directory.
"""
from datetime import date
import io
from pathlib import Path
import tempfile
import unittest

import zstandard

from skippercast.fleet.ais import backfill as bf
from skippercast.fleet.ais.sources.base import AisPosition, AisStatic
from skippercast.fleet.ais.sources.marinecadastre import (CorruptDay, MalformedFile, MarineCadastreSource, day_url,
                                                          parse_rows)
from skippercast.fleet.ais.store import AisStore
from skippercast.http import FakeSession

DAY = date(2026, 6, 20)
BBOX = ((9.0, -151.0), (11.0, -149.0))
HEADER = "mmsi,base_date_time,longitude,latitude,notes"
GOOD = "999000111,2026-06-20 15:00:00,-150,10,fine"
BAD = '999000123,2026-06-20 16:00:00,-150,10,"unterminated'
JUNK = '999000123,2026-06-20 16:00:00,-150,10,"note"junk'


def parse(*lines, header=HEADER, counts=None, crlf=False):
    text = ("\r\n" if crlf else "\n").join([header, *lines]) + ("\r\n" if crlf else "\n")
    return parse_rows(io.StringIO(text, newline=""), DAY, BBOX, None, counts)


def zst(*lines):
    return zstandard.ZstdCompressor(level=3).compress(("\n".join([HEADER, *lines]) + "\n").encode())


class SyntaxTests(unittest.TestCase):
    def refuses(self, *lines, header=HEADER):
        with self.assertRaises(MalformedFile) as caught:
            list(parse(*lines, header=header))
        self.assertNotIn("999000123", str(caught.exception))
        self.assertNotIn("unterminated", str(caught.exception))
        self.assertRegex(str(caught.exception), r"near line \d+$")
        return caught.exception

    def test_unterminated_ignored_field_refuses(self):
        self.refuses(BAD)
        self.refuses(GOOD, BAD)
        self.refuses('999000123,"2026-06-20 16:00:00,-150,10,x')   # a recognized column

    def test_header_syntax_refuses(self):
        self.refuses(GOOD, header='mmsi,base_date_time,"longitude,latitude')
        self.refuses(header='mmsi,"base_date_time"x,longitude,latitude')

    def test_junk_after_closing_quote_refuses_before_yielding_the_record(self):
        self.assertEqual(self.refuses(JUNK).args, ("malformed MarineCadastre CSV near line 2",))
        seen = []
        with self.assertRaises(MalformedFile):
            for record in parse(GOOD, JUNK, GOOD.replace("111", "222")):
                seen.append(record)
        self.assertEqual([r.mmsi for r in seen], [999000111], "the damaged record and what follows are never read")

    def test_valid_quoting_remains_compatible(self):
        counts = {}
        header = "mmsi,base_date_time,longitude,latitude,vessel_name,call_sign,length,width,transceiver"
        rows = ['999000111,2026-06-20 15:00:00,-150,10,"BOAT, THE ""ONE""",TEST1,18,6,A',
                "", '999000222,2026-06-20 15:01:00,-150,10,"TWO\nLINE",TEST2,18,6,A']
        for crlf in (False, True):
            records = list(parse(*rows, header=header, counts=counts, crlf=crlf))
            self.assertEqual([type(r) for r in records], [AisPosition, AisStatic] * 2)
            self.assertEqual(records[1].name, 'BOAT, THE "ONE"')
            self.assertEqual(records[3].name, "TWO\nLINE")
        self.assertEqual(counts["positions"], 4)
        self.assertEqual(counts["malformed"], 2, "the blank line counts as a short row, as before")
        self.assertEqual(list(parse(header=HEADER)), [])

    def test_header_failures_keep_their_types_and_failure_is_lazy(self):
        generator = parse(GOOD, header="a,b")        # nothing is read until it is advanced
        with self.assertRaisesRegex(MalformedFile, "no mmsi"):
            next(generator)
        with self.assertRaisesRegex(MalformedFile, "empty file"):
            list(parse_rows(io.StringIO(""), DAY, BBOX))

    def test_a_later_record_fails_on_later_advancement_and_stops_reading(self):
        def lines():
            yield from (HEADER + "\n", GOOD + "\n", JUNK + "\n")
            raise AssertionError("read past the damaged record")
        generator = parse_rows(lines(), DAY, BBOX)
        self.assertEqual(next(generator).mmsi, 999000111)
        with self.assertRaises(MalformedFile):
            next(generator)

    def test_field_limit_is_the_same_bounded_failure(self):
        huge = "9" * 200_000
        with self.assertRaises(MalformedFile) as caught:
            list(parse(f"999000111,2026-06-20 15:00:00,-150,10,{huge}"))
        self.assertNotIn("99999", str(caught.exception))


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = AisStore(Path(self.tmp.name) / "ais")

    def source(self, route):
        return MarineCadastreSource(session=FakeSession({day_url(DAY): route}), workdir=self.store.root / "staging")

    def files(self):
        manifest = self.store.root / "days" / "2026-06-20.json"
        day = self.store.day_path(DAY)
        return (day.read_bytes() if day.exists() else None, manifest.read_bytes() if manifest.exists() else None)

    def test_damaged_history_is_malformed_and_corrupt_zstd_stays_corrupt(self):
        with self.assertRaises(MalformedFile):
            list(self.source(zst(GOOD, BAD)).history(DAY, BBOX))
        with self.assertRaises(CorruptDay):
            list(self.source(b"not zstandard").history(DAY, BBOX))

    def test_staged_prefix_never_becomes_a_successful_day(self):
        with self.assertRaises(MalformedFile):
            bf.ingest_day(self.source(zst(GOOD, GOOD.replace("111", "222"), BAD)), self.store, DAY, BBOX, set(), batch=1)
        self.assertEqual(self.files(), (None, None))
        self.assertFalse((self.store.root / "staging" / "2026-06-20").exists())

    def test_force_reingest_failure_leaves_the_earlier_day_untouched(self):
        bf.ingest_day(self.source(zst(GOOD)), self.store, DAY, BBOX, set())
        before = self.files()
        self.assertIsNotNone(before[0])
        self.assertIsNotNone(before[1])
        with self.assertRaises(MalformedFile):
            bf.ingest_day(self.source(zst(GOOD, JUNK)), self.store, DAY, BBOX, set(), force=True, batch=1)
        self.assertEqual(self.files(), before)

    def test_a_malformed_day_is_reported_and_the_next_day_goes_on(self):
        from tests.unit.test_fleet_backfill import NEXT, REGION, T0, zst as good_zst
        from tests.unit.test_fleet_process import FakeWorker
        fake = FakeSession({day_url(DAY): zst(GOOD, BAD), day_url(NEXT): good_zst([])})
        source = MarineCadastreSource(session=fake, workdir=self.store.root / "staging")
        root = Path(self.tmp.name) / "CA" / "ais"
        counts = bf.backfill(REGION, FakeWorker(), first=DAY, last=DAY, root=root, source=source,
                             now_ms=T0 + 200 * 86_400_000)
        self.assertEqual([f["day"] for f in counts["failed"]], ["2026-06-20"])
        self.assertEqual([d["day"] for d in counts["days"]], ["2026-06-21"])
        self.assertFalse(bf.backfill_store(root).day_path(DAY).exists())


if __name__ == "__main__":
    unittest.main()
