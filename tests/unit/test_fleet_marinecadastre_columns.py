"""skippercast.fleet.ais.sources.marinecadastre header admission (RF0640-9).

Offline and synthetic: every CSV is a generated string with a made-up 999xxxxxx MMSI; nothing is downloaded and no
source, session or history call is made. Two recognized columns that resolve to the same canonical field make the
header ambiguous, so the file is refused before any row is read, whatever order the columns come in and whether or
not their values agree.
"""
from datetime import date
import io
import unittest

from skippercast.fleet.ais.sources.base import AisPosition, AisStatic
from skippercast.fleet.ais.sources.marinecadastre import COUNTERS, MalformedFile, parse_rows

DAY = date(2026, 6, 20)
BBOX = ((9.0, -151.0), (11.0, -149.0))
STAMP = "2026-06-20 16:00:00"
MMSI = 999000123


def parse(header, *rows, counts=None):
    text = io.StringIO("\n".join([header, *rows]) + "\n")
    return list(parse_rows(text, DAY, BBOX, None, counts))


class AmbiguousHeaderTests(unittest.TestCase):
    def refuses(self, header, *rows, field, first, second):
        counts = {}
        with self.assertRaises(MalformedFile) as caught:
            parse(header, *rows, counts=counts)
        message = str(caught.exception)
        self.assertIn(f"'{field}'", message)
        self.assertIn(f"columns {first} and {second}", message)
        self.assertNotIn("999000123", message)
        self.assertEqual(counts, dict.fromkeys(COUNTERS, 0))

    def test_required_alias_collision_refuses_in_both_orders(self):
        self.refuses("mmsi,base_date_time,latitude,lat,longitude",
                     f"{MMSI},{STAMP},10.0,10.5,-150.0", field="lat", first=2, second=3)
        self.refuses("mmsi,base_date_time,lat,latitude,longitude",
                     f"{MMSI},{STAMP},10.5,10.0,-150.0", field="lat", first=2, second=3)
        self.refuses("mmsi,base_date_time,latitude,longitude,lon",
                     f"{MMSI},{STAMP},10.0,-150.0,-150.5", field="lon", first=3, second=4)
        self.refuses("mmsi,base_date_time,latitude,lon,longitude",
                     f"{MMSI},{STAMP},10.0,-150.5,-150.0", field="lon", first=3, second=4)
        self.refuses("mmsi,base_date_time,latitude,latitude,longitude",
                     f"{MMSI},{STAMP},10.0,10.5,-150.0", field="lat", first=2, second=3)
        self.refuses("mmsi,mmsi,base_date_time,latitude,longitude",
                     f"{MMSI},{MMSI},{STAMP},10.0,-150.0", field="mmsi", first=0, second=1)

    def test_normalized_and_optional_collisions_refuse(self):
        base = "mmsi,base_date_time,latitude,longitude"
        row = f"{MMSI},{STAMP},10.0,-150.0"
        cases = (
            ("mmsi,BaseDateTime,base_date_time,latitude,longitude", "time", 1, 2),
            ("mmsi,base_date_time, LATITUDE ,Lat_itude,longitude", "lat", 2, 3),
            ("\ufeffmmsi,base_date_time,latitude,longitude,MMSI", "mmsi", 0, 4),
            (base + ",sog,SOG", "sog", 4, 5),
            (base + ",vessel_name,VesselName", "name", 4, 5),
            (base + ",transceiver,TransceiverClass", "transceiver", 4, 5),
            (base + ",transceiver_class,transceiver", "transceiver", 4, 5),
        )
        for header, field, first, second in cases:
            with self.subTest(header=header):
                self.refuses(header, row, field=field, first=first, second=second)

    def test_third_duplicate_does_not_pick_a_last_wins_column(self):
        self.refuses("mmsi,base_date_time,lat,latitude,LAT,longitude", f"{MMSI},{STAMP},1,2,3,-150.0",
                     field="lat", first=2, second=3)

    def test_header_only_file_is_refused_without_any_row(self):
        self.refuses("mmsi,base_date_time,lat,latitude,longitude", field="lat", first=2, second=3)

    def test_matching_values_do_not_resolve_ambiguity(self):
        self.refuses("mmsi,base_date_time,latitude,lat,longitude",
                     f"{MMSI},{STAMP},10.0,10.0,-150.0", field="lat", first=2, second=3)
        self.refuses("mmsi,base_date_time,latitude,longitude,sog,sog",
                     f"{MMSI},{STAMP},10.0,-150.0,3.0,3.0", field="sog", first=4, second=5)

    def test_header_error_precedes_row_consumption(self):
        def lines():
            yield "mmsi,base_date_time,latitude,lat,longitude\n"
            raise AssertionError("a data row was requested after an ambiguous header")

        counts = {}
        records = parse_rows(lines(), DAY, BBOX, None, counts)
        self.assertEqual(counts, {})  # lazy: nothing runs until the first next()
        with self.assertRaises(MalformedFile):
            next(records)
        self.assertEqual(counts, dict.fromkeys(COUNTERS, 0))


class AdmittedHeaderTests(unittest.TestCase):
    def test_unique_current_legacy_and_reordered_headers_keep_records(self):
        current = ("mmsi,base_date_time,longitude,latitude,sog,cog,heading,vessel_name,imo,call_sign,vessel_type,"
                   "status,length,width,draft,cargo,transceiver")
        legacy = ("MMSI,BaseDateTime,LAT,LON,SOG,COG,Heading,VesselName,IMO,CallSign,VesselType,Status,Length,"
                  "Width,Draft,Cargo,TransceiverClass")
        reordered = ("TransceiverClass,lon,Lat,status,base_date_time,mmsi,sog")
        rows = {
            current: f"{MMSI},{STAMP},-150.0,10.0,3.0,45.0,44,TEST BOAT ONE,,TEST1,37,0,18,6,,,A",
            legacy: f"{MMSI},{STAMP},10.0,-150.0,3.0,45.0,44,TEST BOAT ONE,,TEST1,37,0,18,6,,,A",
            reordered: f"A,-150.0,10.0,0,{STAMP},{MMSI},3.0",
        }
        for header, line in rows.items():
            with self.subTest(header=header):
                counts = {}
                position, *static = parse(header, line, counts=counts)
                self.assertIsInstance(position, AisPosition)
                self.assertEqual((position.mmsi, position.lat, position.lon, position.sog),
                                 (MMSI, 10.0, -150.0, 3.0))
                self.assertEqual(position.source, "marinecadastre")
                self.assertEqual((counts["rows"], counts["positions"], counts["malformed"]), (1, 1, 0))
                if header is reordered:
                    self.assertEqual(static, [])  # no name/size, so no static record
                else:
                    self.assertEqual(len(static), 1)
                    self.assertIsInstance(static[0], AisStatic)
                    self.assertEqual((static[0].name, static[0].ais_class), ("TEST BOAT ONE", "A"))

    def test_missing_required_column_and_empty_file_still_fail(self):
        with self.assertRaisesRegex(MalformedFile, "no lon column"):
            parse("mmsi,base_date_time,latitude", f"{MMSI},{STAMP},10.0")
        with self.assertRaisesRegex(MalformedFile, "empty file"):
            list(parse_rows(io.StringIO(""), DAY, BBOX))

    def test_unknown_columns_remain_ignored_even_when_repeated(self):
        header = "draft,mmsi,cargo,base_date_time,draft,latitude,cargo,longitude,sog,notes,notes"
        counts = {}
        (position,) = parse(header, f"1,{MMSI},9,{STAMP},2,10.0,8,-150.0,3.0,x,y", counts=counts)
        self.assertEqual((position.mmsi, position.lat, position.lon, position.sog), (MMSI, 10.0, -150.0, 3.0))
        self.assertEqual((counts["positions"], counts["malformed"]), (1, 0))


if __name__ == "__main__":
    unittest.main()
