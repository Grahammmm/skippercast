"""FE-42: NDBC history collector, offline against synthetic standard-met excerpts."""

from datetime import datetime, timezone
import gzip
import json
import math
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


def split_top(expr, sep):
    """Split a TypeScript type expression on `sep` outside brackets."""
    depth, part, parts = 0, "", []
    for ch in expr:
        depth += ch in "{[(<" and 1 or (ch in "}])>" and -1 or 0)
        if ch == sep and depth == 0:
            parts.append(part.strip())
            part = ""
        else:
            part += ch
    return [p for p in parts + [part.strip()] if p]


class TsTypes:
    """Values and nullability checked against the packages/coast history-types.ts declarations."""

    def __init__(self):
        source = (ROOT / "packages/coast/src/history-types.ts").read_text()
        self.types = dict(re.findall(r"export type (\w+)=(.*?);\n", source + "\n"))

    def literals(self, expr):
        expr = self.types.get(expr, expr)
        return [p.strip("'") for p in split_top(expr, "|")]

    def fields(self, expr):
        """Object-like type -> {field: (optional, type)}, or None for non-object types."""
        expr = expr.strip()
        if expr in self.types:
            return self.fields(self.types[expr])
        parts = split_top(expr, "&")
        if len(parts) > 1:
            merged = {}
            for part in parts:
                merged.update(self.fields(part))
            return merged
        if expr.startswith("Record<"):
            key, value = split_top(expr[7:-1], ",")
            return {k: (False, value) for k in self.literals(key)}
        if expr.startswith("{") and expr.endswith("}"):
            out = {}
            for item in split_top(expr[1:-1], ";"):
                key, value = item.split(":", 1)
                out[key.rstrip("?")] = (key.endswith("?"), value)
            return out
        return None

    def errors(self, value, expr, where="$"):
        expr = expr.strip()
        options = split_top(expr, "|")
        if len(options) > 1:
            found = [self.errors(value, o, where) for o in options]
            return [] if any(not f for f in found) else [f"{where}: {value!r} is not {expr}"]
        if expr.endswith("[]"):
            if not isinstance(value, list):
                return [f"{where}: expected array, got {value!r}"]
            return [e for i, item in enumerate(value) for e in self.errors(item, expr[:-2], f"{where}[{i}]")]
        primitives = {"number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v),
                      "string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool), "null": lambda v: v is None}
        if expr in primitives:
            return [] if primitives[expr](value) else [f"{where}: {value!r} is not {expr}"]
        if expr.startswith("'"):
            return [] if value == expr.strip("'") else [f"{where}: {value!r} is not {expr}"]
        if re.fullmatch(r"-?\d+", expr):
            return [] if value == int(expr) and not isinstance(value, bool) else [f"{where}: {value!r} is not {expr}"]
        if expr in self.types and self.fields(expr) is None:
            return self.errors(value, self.types[expr], where)
        fields = self.fields(expr)
        if fields is None:
            raise AssertionError(f"Unhandled TypeScript type {expr}")
        if not isinstance(value, dict):
            return [f"{where}: expected object, got {value!r}"]
        out = [f"{where}.{k}: unexpected field" for k in value.keys() - fields.keys()]
        for key, (optional, kind) in fields.items():
            if key in value:
                out += self.errors(value[key], kind, f"{where}.{key}")
            elif not optional:
                out.append(f"{where}.{key}: missing")
        return out


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
        types = TsTypes()
        self.assertEqual(types.errors(bundle, "HistoryBundle"), [])
        self.assertEqual((bundle["schemaVersion"], bundle["countyId"], bundle["recentWindowDays"]), (1, "slo", 45))
        for station in bundle["stations"]:
            self.assertEqual(len(station["baseline"]["months"]), 12 * len(nh.FIELDS))
            for hour in station["recent"]["hours"]:
                self.assertEqual(set(hour["counts"]), set(nh.FIELDS))
        self.assertTrue(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", bundle["generatedAt"]))
        json.dumps(bundle, allow_nan=False)
        # The checker catches wrong value types and nulls, not only field names.
        broken = json.loads(json.dumps(bundle))
        broken["stations"][0]["baseline"]["months"][0]["count"] = None
        broken["stations"][0]["recent"]["stale"] = "no"
        broken["stations"][0]["recent"]["hours"][0]["waveFt"] = "1.5"
        broken["stations"][0]["sources"][0]["role"] = "archive"
        broken["stations"][1]["baseline"]["periodStart"] = 2024
        self.assertEqual(len(types.errors(broken, "HistoryBundle")), 5)

    def test_corrupt_gzip_fails_only_its_year(self):
        truncated = b"\x1f\x8b\x08\x00garbage"  # ends mid-header: decodes to nothing, never reaches EOF
        garbage = truncated + b"\xff" * 20  # invalid deflate data: zlib.error inside the decoder
        for body, message in ((truncated, "truncated"), (garbage, "Corrupt NOAA gzip")):
            with self.assertRaisesRegex(ValueError, message):
                nh.decode(body)
        bundle, _ = self.run_full(FakeSession({**routes(), nh.annual_url("46215", 2023): garbage}))
        station = bundle["stations"][0]
        failed = next(s for s in station["sources"] if s.get("year") == 2023)
        self.assertEqual(failed["outcome"], "error")
        self.assertIn("Corrupt NOAA gzip", failed["error"])
        self.assertEqual(station["baseline"]["years"], [2024])
        self.assertEqual(bundle["stations"][1]["baseline"]["years"], [1999, 2024])

    def test_short_units_line_is_a_recorded_mismatch(self):
        lines = text("h2024.txt").decode().splitlines()
        lines[1] = "#yr  mo dy hr mn degT m/s  m/s     m   sec"  # stops before the ATMP/WTMP units
        short = "\n".join(lines)
        with self.assertRaisesRegex(ValueError, "unit"):
            nh.parse(short, NOW, 2024)
        bundle, _ = self.run_full(FakeSession({**routes(), nh.annual_url("46215", 2024): gzip.compress(short.encode(), mtime=0)}))
        station = bundle["stations"][0]
        failed = next(s for s in station["sources"] if s.get("year") == 2024)
        self.assertEqual((failed["outcome"], station["baseline"]["years"]), ("error", [2023]))

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
