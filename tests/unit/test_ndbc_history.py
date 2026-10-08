"""FE-42: NDBC history collector, offline against synthetic standard-met excerpts."""

from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import re
import tempfile
from unittest import TestCase

from skippercast.http import FakeSession, TransportError
from skippercast.pipeline import ndbc_history as nh
from tests._support import FIXTURES as ALL_FIXTURES, ROOT

FIXTURES = ALL_FIXTURES / "ndbc-history"
NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


def text(name):
    return (FIXTURES / name).read_bytes()


def routes():
    gz = lambda name: gzip.compress(text(name), mtime=0)
    return {nh.index_url("46215"): text("index.html"), nh.index_url("46028"): text("index.html"),
            nh.recent_url("46215"): text("recent.txt"), nh.recent_url("46028"): text("recent.txt"),
            nh.annual_url("46215", 2023): gz("h2023.txt"), nh.annual_url("46215", 2024): gz("h2024.txt"),
            nh.annual_url("46028", 1999): gz("h1999-legacy.txt"), nh.annual_url("46028", 2024): gz("h2024.txt")}


def ts_fields():
    """Top-level field names (and optional ones) of each type in packages/coast history-types.ts."""
    source = (ROOT / "packages/coast/src/history-types.ts").read_text()
    types = {}
    for name, body in re.findall(r"export type (\w+)=(.*?);\n", source + "\n"):
        fields = {}
        for block in re.findall(r"\{(.*)\}", body):
            depth, part, parts = 0, "", []
            for ch in block + ";":
                depth += ch in "{[(" and 1 or (ch in "}])" and -1 or 0)
                if ch == ";" and depth == 0:
                    parts.append(part)
                    part = ""
                else:
                    part += ch
            for item in filter(None, parts):
                key = item.split(":", 1)[0]
                fields[key.rstrip("?")] = key.endswith("?")
        types[name] = fields
    return types


class NdbcHistoryTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_full(self, session=None):
        session = session or FakeSession(routes())
        return nh.collect("morro-bay", "full", session, self.cache, now=NOW), session

    def test_monthly_quantiles_match_hand_computed_values(self):
        bundle, _ = self.run_full()
        station = bundle["stations"][0]
        jan = next(m for m in station["baseline"]["months"] if m["month"] == 1 and m["metric"] == "waterTempF")
        # Jan UTC-hour means (°F): 2023 → 51.8 (two samples), 53.6, 57.2, 60.8 (02:00 is a sentinel); 2024 → 48.2
        self.assertEqual((jan["count"], jan["rawSampleCount"], jan["yearsWithData"]), (5, 6, [2023, 2024]))
        self.assertAlmostEqual(jan["p10"], 49.64, 3)  # 48.2 + 0.4 × 3.6
        self.assertAlmostEqual(jan["median"], 53.6, 3)
        self.assertAlmostEqual(jan["p90"], 59.36, 3)  # 57.2 + 0.6 × 3.6
        self.assertEqual((jan["min"], jan["max"], jan["expectedHours"]), (48.2, 60.8, 2 * 744))
        self.assertAlmostEqual(jan["coverageFraction"], 5 / 1488)
        july_period = next(m for m in station["baseline"]["months"] if m["month"] == 7 and m["metric"] == "periodS")
        self.assertEqual((july_period["count"], july_period["median"]), (0, None))  # 0 s period is masked, not data
        self.assertEqual(station["baseline"]["label"], "Recorded seasonal history · 2023–2024")
        legacy = bundle["stations"][1]
        self.assertEqual(legacy["baseline"]["years"], [1999, 2024])
        jan99 = next(m for m in legacy["baseline"]["months"] if m["month"] == 1 and m["metric"] == "waterTempF")
        self.assertEqual(jan99["yearsWithData"], [1999, 2024])
        annual = next(s for s in station["sources"] if s.get("year") == 2023)
        self.assertEqual((annual["parsedRows"], annual["rejectedRows"]), (6, 1))  # 2022 row rejected, TIDE-less row kept

    def test_unchanged_archives_download_nothing(self):
        self.run_full()
        bundle, session = self.run_full()
        annual_calls = [url for _, url, _ in session.calls if "/historical/" in url]
        self.assertEqual(annual_calls, [])
        self.assertEqual(len([s for s in bundle["stations"][0]["sources"] if s["role"] == "annual"]), 2)
        # A corrupted checkpoint fails its SHA-256 check and only that archive is refetched.
        key = json.loads((self.cache / "morro-bay-checkpoint.json").read_text())["records"]["46215:annual:2023"]["objectKey"]
        (self.cache / key).write_bytes(b"tampered")
        _, session = self.run_full()
        self.assertEqual([url for _, url, _ in session.calls if "/historical/" in url], [nh.annual_url("46215", 2023)])

    def test_missing_hours_are_counted_never_filled(self):
        bundle, _ = self.run_full()
        recent = bundle["stations"][0]["recent"]
        self.assertEqual([h["at"] for h in recent["hours"]],
                         ["2026-10-07T08:00:00.000Z", "2026-10-07T10:00:00.000Z", "2026-10-07T11:00:00.000Z"])
        self.assertEqual((recent["expectedHours"], recent["observedHours"], recent["maxGapHours"]), (1080, 3, 1076))
        self.assertAlmostEqual(recent["hourCoverageFraction"], 3 / 1080)
        ten = recent["hours"][1]
        self.assertIsNone(ten["waterTempF"])  # conflicting duplicate rows mask the value
        self.assertEqual((ten["sampleCount"], ten["counts"]["waveFt"], ten["waveFt"]), (1, 0, None))
        self.assertAlmostEqual(recent["hours"][2]["waterTempF"], 59.18, 3)
        self.assertEqual((recent["lastObservedAt"], recent["stale"]), ("2026-10-07T11:30:00.000Z", False))
        self.assertEqual((recent["qc"]["rejectedRows"], recent["qc"]["duplicateRows"], recent["qc"]["conflictingValues"]), (1, 1, 1))

    def test_output_matches_packages_coast_history_bundle(self):
        bundle, _ = self.run_full()
        types = ts_fields()
        hour_fields = {**types["HistoricalHour"], **{m: False for m in nh.FIELDS}, "at": False}

        def check(value, fields, where):
            required = {k for k, optional in fields.items() if not optional}
            self.assertLessEqual(required, value.keys(), where)
            self.assertLessEqual(value.keys(), fields.keys(), where)

        check(bundle, types["HistoryBundle"], "bundle")
        self.assertEqual((bundle["schemaVersion"], bundle["countyId"], bundle["recentWindowDays"]), (1, "slo", 45))
        for station in bundle["stations"]:
            check(station, types["StationHistory"], "station")
            check(station["recent"], types["RecentHistory"], "recent")
            check(station["recent"]["qc"], types["HistoryQC"], "qc")
            check(station["archive"], types["HistoryArchive"], "archive")
            for hour in station["recent"]["hours"]:
                check(hour, hour_fields, "hour")
                self.assertEqual(set(hour["counts"]), set(nh.FIELDS))
            for source in station["sources"]:
                check(source, types["HistorySource"], "source")
                self.assertIn(source["role"], ("index", "recent", "annual"))
            baseline_type = re.search(r"baseline:\{(.*?)\};archive", (ROOT / "packages/coast/src/history-types.ts").read_text()).group(1)
            self.assertEqual(set(station["baseline"]), set(re.findall(r"(?:^|;)(\w+):", baseline_type)))
            self.assertEqual(len(station["baseline"]["months"]), 12 * len(nh.FIELDS))
            for month in station["baseline"]["months"]:
                check(month, types["MonthlyDistribution"], "month")
        self.assertTrue(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", bundle["generatedAt"]))
        json.dumps(bundle, allow_nan=False)

    def test_recent_mode_keeps_published_baseline_and_fetches_only_recent(self):
        published, _ = self.run_full()
        session = FakeSession({url: body for url, body in routes().items() if "realtime2" in url})
        bundle = nh.collect("morro-bay", "recent", session, self.cache, previous=published, now=NOW)
        self.assertTrue(all("realtime2" in url for _, url, _ in session.calls))
        for old, new in zip(published["stations"], bundle["stations"]):
            self.assertEqual(new["baseline"], old["baseline"])
            self.assertEqual([s for s in new["sources"] if s["role"] != "recent"], [s for s in old["sources"] if s["role"] != "recent"])
        with self.assertRaises(SystemExit):
            nh.collect("morro-bay", "recent", session, self.cache, previous=None, now=NOW)

    def test_total_outage_publishes_nothing_and_unapproved_urls_are_refused(self):
        with self.assertRaises(SystemExit):
            nh.collect("morro-bay", "full", FakeSession({}), self.cache, now=NOW)
        with self.assertRaises(ValueError):
            nh.fetch(FakeSession({}), "https://www.ndbc.noaa.gov/../etc/passwd", "recent")
        with self.assertRaises(ValueError):
            nh.parse("YYYY MM DD hh mm WSPD\n2024 01 01 00 00 5.0", NOW)  # missing WVHT/WTMP columns
        self.assertIsInstance(TransportError("x"), OSError)
