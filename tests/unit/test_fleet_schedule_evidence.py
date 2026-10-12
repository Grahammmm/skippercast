from __future__ import annotations

from datetime import datetime, timedelta, timezone
import fcntl
import importlib.util
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fleet" / "schedule_evidence.py"
spec = importlib.util.spec_from_file_location("schedule_evidence", SCRIPT)
se = importlib.util.module_from_spec(spec)
spec.loader.exec_module(se)


class ScheduleEvidenceTests(unittest.TestCase):
    def test_dst_gap_is_unresolved_and_fold_preserves_both_utc_choices(self):
        zone = ZoneInfo("America/Los_Angeles")
        gap = datetime(2026, 3, 8, 2, 30)
        self.assertEqual(se.resolve_local(gap, zone), (None, None, "nonexistent-local-time"))
        fold = datetime(2026, 11, 1, 1, 30)
        utc, choices, uncertainty = se.resolve_local(fold, zone)
        self.assertIsNone(utc)
        self.assertEqual(uncertainty, "ambiguous-local-time")
        self.assertEqual(len(__import__("json").loads(choices)), 2)

    def test_local_day_window_respects_dst_day_length(self):
        start, end = se.local_midnight_window("2026-03-08", ZoneInfo("America/Los_Angeles"))
        self.assertEqual((end - start).total_seconds(), 23 * 3600)

    def test_schedule_revisions_are_append_only_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = se.open_database(Path(tmp) / "db.sqlite3")
            row = observation()
            self.assertEqual(se.record_observation(conn, row), (True, 1))
            self.assertEqual(se.record_observation(conn, row), (False, 1))
            changed = dict(row, duration_hours=12.5)
            changed["content_sha256"] = se.digest(se.canonical({k: v for k, v in changed.items() if k != "content_sha256"}))
            self.assertEqual(se.record_observation(conn, changed), (True, 2))
            self.assertEqual(conn.execute("select count(*) from schedule_observations").fetchone()[0], 2)
            conn.close()

    def test_missing_listing_does_not_create_cancellation(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = se.open_database(Path(tmp) / "db.sqlite3")
            row = observation()
            se.record_observation(conn, row)
            conn.execute("update source_pages set listed_currently=0")
            # Listing disappearance is inventory metadata only; prior schedule claims remain untouched.
            stored = conn.execute("select schedule_status,cancellation_evidence from schedule_observations").fetchone()
            self.assertEqual(tuple(stored), ("listed", None))
            conn.close()

    def test_only_machine_readable_status_marker_is_explicit(self):
        cancel = b'<div data-trip-id="1" data-status="cancelled"><div class="trip-info">Dolphin 1/2 Day</div></div>'
        self.assertEqual(se.explicit_annotations(cancel, "1/2 Day"), ("explicitly-cancelled", None))
        substitution = b'<div data-trip-id="1" class="trip-substituted" data-substitute-vessel="Replacement"><div class="trip-info">Dolphin 1/2 Day</div></div>'
        self.assertEqual(se.explicit_annotations(substitution, "1/2 Day"), ("explicitly-substituted", "Replacement"))
        prose = b'<div data-trip-id="1"><div class="trip-info">Dolphin 1/2 Day</div><div class="trip-comments">Cancelled due to weather</div></div>'
        self.assertEqual(se.explicit_annotations(prose, "1/2 Day"), (None, None))

    def test_discovered_boat_parses_with_prior_index_provenance_and_counts_assessments(self):
        # Reproduces the live failure: source_pages already contains discovered
        # links, but each run creates a fresh _Page with an empty times map.
        index_url = "https://schedule.example.test/fleet.php"
        boat_url = "https://schedule.example.test/boats/blueplaceholder.php"
        listed_at = "2026-10-12T02:26:01Z"
        binding = SimpleNamespace(id="synthetic", adapter="landing-pages", rights="facts-only",
                                  params={"url": index_url, "template": "fr-fleet-php",
                                          "landing": "test-landing"})
        region = SimpleNamespace(id="CA", timezone="America/Los_Angeles",
            landings=[SimpleNamespace(id="test-landing", name="Test Landing", port="test-port")],
            ports=[SimpleNamespace(id="test-port", name="Test Port")],
            enabled_sources=lambda: [binding])
        body = (SCRIPT.parents[2] / "tests/fixtures/fleet/landings/fr-boat-blue.html").read_bytes()

        class OfflineClient:
            def __init__(self):
                self.requests = []
                self.skips = []
                self.block_boat = False
            def get(self, url, as_binary=False):
                if url not in {boat_url, se.FISHCOUNTS_URL}:
                    raise AssertionError("unexpected fetch: " + url)
                if url == boat_url and self.block_boat:
                    self.skips.append({"url": url, "reason": "robots", "detail": "blocked"})
                    raise se.Skipped(url, "robots", "blocked")
                self.requests.append({"final_url": url, "http_status": 200})
                return body if url == boat_url else b"<html>synthetic fishcounts</html>"

        with tempfile.TemporaryDirectory() as tmp:
            fleet = Path(tmp)
            db_path = fleet / "CA/schedule-evidence/evidence.sqlite3"
            conn = se.open_database(db_path)
            se.init_sources(conn, region)
            conn.execute("update sources set last_index_ok_at=?,last_index_attempt_at=?",
                         (listed_at, listed_at))
            conn.execute("""insert into source_pages(source_id,page_url,boat_name,landing_id,port_id,
                         listing_order,last_listed_at) values(?,?,?,?,?,?,?)""",
                         ("synthetic", boat_url, "Blue Placeholder II", "test-landing",
                          "test-port", 0, listed_at))
            conn.commit()
            conn.close()
            client = OfflineClient()
            net = SimpleNamespace(skips=client.skips)
            now = datetime(2026, 10, 12, 3, tzinfo=timezone.utc)
            with patch.object(se.FleetSession, "for_region", return_value=net), \
                 patch.object(se, "teck_client", return_value=client):
                first = se.collect_run(region, db_path, fleet, now=now)
                second = se.collect_run(region, db_path, fleet, now=now+timedelta(hours=13))
                client.block_boat = True
                third = se.collect_run(region, db_path, fleet, now=now+timedelta(hours=26))
            self.assertEqual(first["status"], "ok")
            self.assertEqual(first["pages_reviewed"], 2)
            self.assertEqual(first["indexes_reviewed"], 0)
            self.assertEqual(first["schedule_rows_seen"], 1)
            self.assertEqual(first["new_ais_assessments"], 1)
            self.assertEqual(first["ais_trips_checked"], 1)
            self.assertEqual(second["status"], "ok")
            self.assertEqual(second["new_or_changed_schedule_revisions"], 0)
            self.assertEqual(second["new_ais_assessments"], 0)
            self.assertEqual(second["ais_trips_checked"], 1)
            self.assertEqual(third["status"], "ok")
            self.assertEqual([r["final_url"] for r in client.requests],
                             [se.FISHCOUNTS_URL, boat_url]*2 + [se.FISHCOUNTS_URL])
            conn = se.open_database(db_path)
            trip = conn.execute("select source_url,scheduled_date_local from schedule_observations").fetchone()
            self.assertEqual(tuple(trip), (boat_url, "2026-11-02"))
            self.assertEqual(conn.execute("select count(*) from ais_assessments").fetchone()[0], 1)
            self.assertEqual(conn.execute("select last_parse_status from source_pages where page_url=?",
                                          (boat_url,)).fetchone()[0], "fetch-failed")
            conn.close()

    def test_due_boat_pages_fairness_precedes_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = se.open_database(Path(tmp) / "db.sqlite3")
            bindings = [
                SimpleNamespace(id="large", adapter="landing-pages", rights="facts-only",
                                params={"url": "https://large.example.test/fleet", "template": "fr-fleet-php"}),
                SimpleNamespace(id="small", adapter="landing-pages", rights="facts-only",
                                params={"url": "https://small.example.test/fleet", "template": "fr-fleet-php"}),
            ]
            region = SimpleNamespace(enabled_sources=lambda: bindings)
            se.init_sources(conn, region)
            for index in range(10):
                conn.execute("insert into source_pages(source_id,page_url,boat_name,listing_order,last_listed_at) values(?,?,?,?,?)",
                             ("large", f"https://large.example.test/boat/{index}", f"Boat {index}", index, "2026-10-01T00:00:00Z"))
            conn.execute("insert into source_pages(source_id,page_url,boat_name,listing_order,last_listed_at) values(?,?,?,?,?)",
                         ("small", "https://small.example.test/boat/0", "Small Boat", 0, "2026-10-01T00:00:00Z"))
            rows = se.due_boat_pages(conn, 2)
            self.assertEqual({row["source_id"] for row in rows}, {"large", "small"})
            conn.close()

    def test_identity_evidence_schema_is_field_allowlisted_and_source_separated(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = se.open_database(Path(tmp) / "db.sqlite3")
            row = observation()
            se.record_observation(conn, row)
            candidate = {"mmsi": 999000001, "ais_names": ["Test Boat"], "call_signs": ["TEST"],
                         "ship_types": [60], "sources": ["aisstream"],
                         "first_static_utc": "2026-10-01T00:00:00Z"}
            self.assertEqual(se.store_ais_identity_evidence(conn, "trip-a", 1, candidate,
                                                            "2026-10-01T01:00:00Z"), 4)
            columns = {row[1] for row in conn.execute("pragma table_info(identity_evidence)")}
            self.assertTrue({"source_class", "source_id", "source_record_id", "field_name", "rights_basis"} <= columns)
            self.assertFalse({"owner_name", "address", "phone", "email", "contact_name"} & columns)
            classes = {row[0] for row in conn.execute("select distinct source_class from identity_evidence")}
            self.assertEqual(classes, {"ais-self-reported"})
            fields = {row[0] for row in conn.execute("select distinct field_name from identity_evidence")}
            self.assertTrue(fields <= se.IDENTITY_FIELD_ALLOWLIST)
            conn.close()

    def test_page_budget_is_global_and_records_skip(self):
        class Client:
            requests = []
            def get(self, url, as_binary=False):
                self.requests.append({"final_url": url})
                return b"page"
        net = SimpleNamespace(skips=[])
        session = se.CachedPageSession(net, Client(), 1, se.monotonic_time.monotonic() + 60)
        self.assertEqual(session.get("https://example.test/a").body, b"page")
        with self.assertRaises(se.Skipped):
            session.get("https://example.test/b")
        self.assertEqual(session.pages_reviewed, 1)
        self.assertEqual(net.skips[0]["reason"], "page-limit")

    def test_raw_window_summary_keeps_receipt_gaps_not_coordinates(self):
        with tempfile.TemporaryDirectory() as tmp:
            fleet = Path(tmp)
            raw = fleet / "CA" / "ais" / "raw"
            raw.mkdir(parents=True)
            day = datetime(2026, 10, 1, tzinfo=timezone.utc)
            db = sqlite3.connect(raw / "2026-10-01.sqlite")
            for table in ("positions", "discovery"):
                db.execute(f"create table {table}(mmsi integer,ts integer,lat real,lon real,sog real,cog real,heading integer,nav_status integer,msg_type text,source text,received_at integer)")
            for minute in (0, 15):
                ms = int((day + timedelta(minutes=minute)).timestamp() * 1000)
                db.execute("insert into positions values(?,?,?,?,?,?,?,?,?,?,?)", (999000001, ms, 36.0, -122.0, 1.0, 2.0, 3, 0, "position", "aisstream", ms))
            db.commit()
            db.close()
            start = day
            result = se.raw_window_summary(fleet, "CA", 999000001, start, day + timedelta(hours=1), start, day + timedelta(days=1))
            self.assertEqual(result["messages"], 2)
            self.assertEqual(result["gaps"][0]["minutes"], 15)
            self.assertNotIn("lat", result)
            self.assertNotIn("lon", result)

    def test_concurrent_run_skips_without_opening_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite3"
            lock_path = db.with_suffix(db.suffix + ".lock")
            with lock_path.open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = se.collect_run(None, db, Path(tmp), now=datetime(2026, 10, 1, tzinfo=timezone.utc))
                self.assertEqual(result["status"], "skipped-locked")
                self.assertFalse(db.exists())


def observation():
    row = {
        "trip_id": "trip-a", "source_trip_id": "src-trip-a", "source_id": "synthetic",
        "source_url": "https://example.test/boat", "boat_page_url": "https://example.test/boat",
        "boat_name": "Test Boat", "operator_name": "Test Landing", "operator_id": "test-landing",
        "port_name": "Test Port", "port_id": "test-port", "scheduled_date_local": "2026-11-01",
        "timezone": "America/Los_Angeles", "departure_local": "2026-11-01T01:30",
        "departure_utc": None, "departure_possible_utc_json": '["2026-11-01T08:30Z","2026-11-01T09:30Z"]',
        "departure_uncertainty": "ambiguous-local-time", "return_local": None, "return_utc": None,
        "return_possible_utc_json": None, "return_uncertainty": "no-return-time-published",
        "duration_hours": 12.0, "trip_type": "overnight", "target_species_json": None,
        "schedule_status": "listed", "cancellation_evidence": None, "substitute_vessel": None,
        "retrieved_at": "2026-10-01T00:00:00Z", "parser_version": "test", "rights": "facts-only",
        "rights_basis": "synthetic fixture", "content_sha256": "one",
    }
    row["content_sha256"] = se.digest(se.canonical({k: v for k, v in row.items() if k != "content_sha256"}))
    return row


if __name__ == "__main__":
    unittest.main()
