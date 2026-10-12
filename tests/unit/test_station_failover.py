from copy import deepcopy
from datetime import timedelta
import json
import os
from unittest import TestCase
from unittest.mock import patch

from tests._support import NOW, FIXTURES
from skippercast.pipeline import live, collect as daily
from skippercast.pipeline.collect import source
from skippercast.pipeline.failover import ordered_source, station_chain
from skippercast.pipeline.settings import settings
from skippercast.platform.contracts import validate_station_roles
from scripts.check_feed_freshness import main, source_verdict, FAILING


class MemoryClient:
    responses = {}

    def __init__(self, now):
        self.requests = []

    def get(self, url, *args):
        from urllib.parse import parse_qs, urlsplit
        station = parse_qs(urlsplit(url).query).get("station", [url.split("/")[-1].split(".")[0]])[0]
        key = station + ".spec" if url.endswith(".spec") and station + ".spec" in self.responses else station
        response = self.responses[key]
        self.requests.append({"url": url})
        if isinstance(response, Exception):
            raise response
        if url.endswith(".spec"):
            time = " ".join(response.splitlines()[2].split()[:5])
            return "#YY MM DD hh mm WVHT SwH SwP WWH WWP\n#yr mo dy hr mn m m sec m sec\n" + time + " 1.5 1.2 10 0.3 5\n"
        return response


def fixed_source(*args, **kwargs):
    return source(*args, **kwargs, client_factory=MemoryClient)


def buoy(hours=0):
    t = NOW - timedelta(hours=hours)
    return "#YY MM DD hh mm WVHT DPD WTMP WSPD\n#yr mo dy hr mn m sec degC m/s\n" + t.strftime("%Y %m %d %H %M") + " 1.5 10 18 4\n"


def predictions(hours=0):
    return {"predictions": [{"t": (NOW + timedelta(hours=h-hours)).strftime("%Y-%m-%d %H:%M"),
                             "v": "2.0", "type": "H"} for h in (-3, 9, 21)]}


class StationFailoverTests(TestCase):
    def region(self):
        region = deepcopy(settings()["region"])
        region["stations"]["roles"] = {"nearshore_buoy": {"stations": ["46215", "46299"]}}
        return region

    def collect_live(self, responses, previous=None):
        MemoryClient.responses = {"46028": buoy(), **responses}
        with patch.object(live, "settings", return_value={"region": self.region()}), \
             patch.object(live, "source", side_effect=fixed_source), \
             patch("skippercast.pipeline.collect.stamp", return_value=NOW.isoformat()):
            return live.collect(NOW, previous)

    def test_fresh_primary_has_station_and_no_fallback(self):
        row = self.collect_live({"46215": buoy()})["sources"]["diablo"]
        self.assertEqual(row["station"], "46215")
        self.assertNotIn("fallback_for", row)
        self.assertEqual(row["status"], "ok")

    def test_stale_or_error_primary_uses_next_fresh_backup(self):
        for bad in (buoy(3), ValueError("synthetic outage")):
            with self.subTest(primary=type(bad).__name__):
                feed = self.collect_live({"46215": bad, "46299": buoy()})
                row = feed["sources"]["diablo"]
                self.assertEqual((row["station"], row["fallback_for"], row["data"]["station"]),
                                 ("46299", "46215", "46299"))
                self.assertIn("46299", row["url"])
                self.assertIn("46299", row["station_url"])
                spectrum = feed["sources"]["diablo-spectrum"]
                self.assertEqual((spectrum["station"], spectrum["fallback_for"]), ("46299", "46215"))
                self.assertEqual(spectrum["data"]["observations"][0]["SwP"], 10)
                self.assertEqual(feed["health"]["status"], "degraded")

    def test_all_stale_preserves_previous_backup_and_times(self):
        old = {"station": "46299", "data": {"station": "46299", "sample_at": (NOW - timedelta(hours=7)).isoformat()},
               "last_success_at": "2026-09-28T05:01:00Z", "data_retrieved_at": "2026-09-28T05:01:00Z"}
        feed = self.collect_live({"46215": buoy(8), "46299": buoy(9)},
                                 {"schema_version": 1, "sources": {"diablo": old}})
        row = feed["sources"]["diablo"]
        self.assertEqual(row["status"], "retained")
        self.assertEqual(row["data"], old["data"])
        self.assertEqual(row["station"], "46299")
        self.assertEqual(row["fallback_for"], "46215")
        self.assertEqual(row["data_retrieved_at"], old["data_retrieved_at"])
        self.assertEqual(row["last_success_at"], old["last_success_at"])
        self.assertIn("46299", row["name"])
        self.assertIn("46299", row["url"])

    def test_newer_stale_reading_beats_older_retained_data(self):
        # #565: the backup served 10 h ago now reads 3 h old; the primary is staler.
        old = {"station": "46299", "data": {"station": "46299", "sample_at": (NOW - timedelta(hours=10)).isoformat()},
               "last_success_at": "2026-09-28T02:01:00Z", "data_retrieved_at": "2026-09-28T02:01:00Z"}
        row = self.collect_live({"46215": buoy(5), "46299": buoy(3)},
                                {"schema_version": 1, "sources": {"diablo": old}})["sources"]["diablo"]
        self.assertEqual((row["status"], row["station"], row["fallback_for"]), ("stale", "46299", "46215"))
        self.assertEqual(row["data"]["station"], "46299")
        self.assertEqual(row["data"]["sample_at"], (NOW - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.assertIn("46299", row["name"])

    def test_stale_primary_beats_older_retained_backup(self):
        # The primary reads 3 h stale; the backup it fell back to earlier fails and holds 9 h old data.
        old = {"station": "46299", "data": {"station": "46299", "sample_at": (NOW - timedelta(hours=9)).isoformat()},
               "last_success_at": "2026-09-28T03:01:00Z", "data_retrieved_at": "2026-09-28T03:01:00Z"}
        row = self.collect_live({"46215": buoy(3), "46299": ValueError("synthetic outage")},
                                {"schema_version": 1, "sources": {"diablo": old}})["sources"]["diablo"]
        self.assertEqual((row["status"], row["station"]), ("stale", "46215"))
        self.assertNotIn("fallback_for", row)
        self.assertEqual(row["data"]["station"], "46215")
        self.assertEqual(row["data"]["sample_at"], (NOW - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.assertNotIn("46299", row["name"])

    def test_all_failed_without_previous_reports_the_primary_failure(self):
        row = self.collect_live({"46215": ValueError("synthetic outage"), "46299": ValueError("synthetic outage")})["sources"]["diablo"]
        self.assertEqual((row["status"], row["station"], row["data"]), ("failed", "46215", None))
        self.assertNotIn("fallback_for", row)
        self.assertIn("synthetic outage", row["issue"])

    def test_previous_station_dropped_from_chain_is_not_retained(self):
        # A config change removed 46288; its data cannot be served under another station's name and URL.
        old = {"station": "46288", "data": {"station": "46288", "sample_at": (NOW - timedelta(hours=1)).isoformat()}}
        row = self.collect_live({"46215": ValueError("synthetic outage"), "46299": ValueError("synthetic outage")},
                                {"schema_version": 1, "sources": {"diablo": old}})["sources"]["diablo"]
        self.assertEqual((row["status"], row["station"], row["data"]), ("failed", "46215", None))
        self.assertNotIn("fallback_for", row)

    def test_missing_rows_fail_over_and_never_outrank_retained_data(self):
        def reader(statuses):
            def read(station, old):
                status = statuses[station]
                data = {"sample_at": NOW.isoformat(), "valid_cells": 0, "total_cells": 4} if status == "missing" else (
                       {"sample_at": (NOW - timedelta(hours=1)).isoformat()} if status == "ok" else None)
                return {"kind": "observation", "status": status, "max_age_hours": 2, "data": data}
            return read
        row = ordered_source(["1", "2"], reader({"1": "missing", "2": "ok"}), NOW)
        self.assertEqual((row["status"], row["station"], row["fallback_for"]), ("ok", "2", "1"))
        old = {"station": "1", "data": {"sample_at": (NOW - timedelta(hours=6)).isoformat()}}
        row = ordered_source(["1", "2"], reader({"1": "missing", "2": "failed"}), NOW, old)
        self.assertEqual((row["status"], row["station"], row["data"]), ("retained", "1", old["data"]))
        row = ordered_source(["1", "2"], reader({"1": "missing", "2": "missing"}), NOW)
        self.assertEqual((row["status"], row["station"]), ("missing", "1"))

    def test_partial_fields_keep_the_fresh_primary_and_stay_missing(self):
        # Wind without waves is still a fresh primary reading: the gaps stay null, never zero, never filled from a backup.
        t = NOW.strftime("%Y %m %d %H %M")
        partial = "#YY MM DD hh mm WVHT DPD WTMP WSPD\n#yr mo dy hr mn m sec degC m/s\n" + t + " MM MM 18 4\n"
        row = self.collect_live({"46215": partial, "46299": buoy()})["sources"]["diablo"]
        self.assertEqual((row["status"], row["station"]), ("ok", "46215"))
        self.assertNotIn("fallback_for", row)
        latest = row["data"]["observations"][0]
        self.assertIsNone(latest["WVHT"])
        self.assertIsNone(latest["DPD"])
        self.assertEqual(latest["WSPD"], 4)

    def test_unknown_clock_never_outranks_a_dated_reading(self):
        def read(station, old):
            data = {"sample_at": (NOW - timedelta(hours=4)).isoformat()} if station == "1" else {"note": "no clock"}
            return {"kind": "observation", "status": "stale", "max_age_hours": 2, "data": data}
        row = ordered_source(["1", "2"], read, NOW, {"station": "2", "data": {"note": "older, no clock"}})
        self.assertEqual((row["status"], row["station"]), ("stale", "1"))
        row = ordered_source(["1", "2"], read, NOW, {"station": "2", "data": {"sample_at": (NOW - timedelta(hours=3)).isoformat()}})
        self.assertEqual((row["status"], row["station"], row["fallback_for"]), ("retained", "2", "1"))

    def test_error_primary_retains_inside_max_age_then_falls_back(self):
        old = {"station": "46215", "data": {"station": "46215", "sample_at": NOW.isoformat()}}
        row = self.collect_live({"46215": ValueError("outage")},
                                {"schema_version": 1, "sources": {"diablo": old}})["sources"]["diablo"]
        self.assertEqual(row["status"], "retained")
        self.assertEqual(row["station"], "46215")
        self.assertNotIn("fallback_for", row)

    def tide(self, primary, backup=None, previous=None):
        config = legacy_config()
        config["region"]["stations"]["roles"] = {"tide": {"stations": ["9412110", "9412999"]}}
        MemoryClient.responses = {"9412110": primary, "9412999": backup}
        def read(*args, **kwargs):
            if args[0] == "tides":
                return fixed_source(*args, **kwargs)
            return {"id": args[0], "kind": args[2], "status": "failed", "data": None}
        with patch.object(daily, "settings", return_value=config), patch.object(daily, "source", side_effect=read), \
             patch.object(daily, "regulatory_snapshot", return_value={}), \
             patch.object(daily, "stamp", return_value=NOW.isoformat()):
            return daily.collect(NOW, previous, days=0)["sources"]["tides"]

    def test_daily_shared_primary_uses_the_configured_role_chain(self):
        config = legacy_config()
        stations = config["region"]["stations"]
        stations["offshore_buoy"] = stations["nearshore_buoy"]
        stations["roles"] = {"offshore_buoy": {"stations": ["46215", "46299"]}}
        MemoryClient.responses = {"46215": ValueError("outage"), "46299": buoy()}
        def read(*args, **kwargs):
            return fixed_source(*args, **kwargs) if args[0].startswith("buoy-") else legacy_source(*args, **kwargs)
        with patch.object(daily, "settings", return_value=config), patch.object(daily, "source", side_effect=read), \
             patch.object(daily, "regulatory_snapshot", return_value={}), \
             patch.object(daily, "stamp", return_value=NOW.isoformat()):
            feed = daily.collect(NOW, days=0)
        for ident in ("buoy-46215", "buoy-46215-swell"):
            row = feed["sources"][ident]
            self.assertEqual((row["station"], row["fallback_for"]), ("46299", "46215"))
            self.assertIn("swell components" if ident.endswith("-swell") else "observations", row["name"])

    def test_tide_fresh_primary(self):
        row = self.tide(predictions())
        self.assertEqual(row["station"], "9412110")
        self.assertNotIn("fallback_for", row)
        self.assertEqual(row["data"]["datum"], "MLLW")

    def test_tide_expired_or_error_primary_uses_backup(self):
        for primary in (predictions(72), ValueError("outage")):
            row = self.tide(primary, predictions())
            self.assertEqual((row["station"], row["fallback_for"]), ("9412999", "9412110"))
            self.assertEqual(row["data"]["station"], "9412999")
            self.assertIn("9412999", row["data"]["note"])
            self.assertNotIn("Reference only", row["data"]["note"])

    def test_tide_all_stale_retains(self):
        old = {"data": {"station": "9412110", "predictions": [], "coverage_end": "2026-09-27T00:00:00Z"},
               "data_retrieved_at": "2026-09-27T00:00:00Z"}
        row = self.tide(predictions(72), predictions(73), {"schema_version": 1, "sources": {"tides": old}})
        self.assertEqual(row["status"], "retained")
        self.assertEqual(row["data"], old["data"])

    def test_checker_names_fresh_backup_and_exits_zero(self):
        feed = {"generated_at": NOW.isoformat(), "sources": {"buoy-x": {
                "id": "buoy-x", "status": "ok", "kind": "observation", "station": "46299",
                "fallback_for": "46215", "data": {"sample_at": NOW.isoformat()}}}}
        bits, lines = source_verdict(feed, 6, "Synthetic feed")
        self.assertEqual(bits & FAILING, 0)
        self.assertIn("backup 46299 for 46215", "\n".join(lines))
        with patch("scripts.check_feed_freshness.published_regions", return_value=[]), \
             self.assertRaises(SystemExit) as exit:
            main([], now=NOW, fetch=lambda url: feed)
        self.assertEqual(exit.exception.code, 0)
        feed["sources"]["buoy-x"].update(status="retained", data={"sample_at": "2026-09-01T00:00:00Z"})
        self.assertNotEqual(source_verdict(feed, 6, "Synthetic feed")[0] & FAILING, 0)

    def test_chain_order_skips_multiple_stale_candidates(self):
        seen = []
        def read(station, old):
            seen.append(station)
            return {"kind": "observation", "status": "ok" if station == "3" else "stale",
                    "max_age_hours": 2, "data": {"sample_at": NOW.isoformat()}}
        row = ordered_source(["1", "2", "3", "4"], read, NOW)
        self.assertEqual(seen, ["1", "2", "3"])
        self.assertEqual((row["station"], row["fallback_for"]), ("3", "1"))

    def test_invalid_config_fails_before_network(self):
        for chain in ([], ["46299", "46215"], ["46215", "46215"], ["46215", "bad"]):
            region = self.region()
            region["stations"]["roles"]["nearshore_buoy"]["stations"] = chain
            with self.subTest(chain=chain), self.assertRaises(ValueError):
                validate_station_roles(region)
        self.assertEqual(station_chain({"tide": "9412110"}, "tide"), ["9412110"])


# Synthetic legacy snapshots were generated with the pre-change collectors on
# bd5b2295. Compare serialized bytes, including field order and optional fields.
def legacy_config():
    return {"region": {"id": "morro-bay", "name": "Synthetic coast", "timezone": "UTC",
            "bounds": [-121, 35, -120, 36], "forecast_points": [], "landing_names": [],
            "marine_zones": {"coastal": "PZZ645", "offshore": "PZZ670"},
            "mpa": {"bounds": [-121, 35, -120, 36], "minimum_features": 1},
            "stations": {"nearshore_buoy": "46215", "nearshore_buoy_name": "Synthetic nearshore",
                         "offshore_buoy": "46028", "offshore_buoy_name": "Synthetic offshore",
                         "tide": "9412110", "tide_name": "Synthetic harbor", "tide_note": "Reference only"}},
            "grids": {}, "watches": {}, "model_ids": [], "regulations": {}, "legal_source_ids": []}


def legacy_source(ident, name, kind, url, max_age, loader, *args, **kwargs):
    return {"id": ident, "name": name, "kind": kind, "url": url, "max_age_hours": max_age,
            "status": "failed", "data": None, "requests": []}


class LegacyStationBytesTests(TestCase):
    def test_live_and_daily_single_station_are_byte_identical(self):
        for module, filename in ((live, "legacy-live.json"), (daily, "legacy-daily.json")):
            with self.subTest(feed=filename), patch.object(module, "settings", return_value=legacy_config()), \
                 patch.object(module, "source", side_effect=legacy_source), \
                 patch.object(module, "stamp", return_value=NOW.isoformat()), \
                 patch("skippercast.pipeline.collect.stamp", return_value=NOW.isoformat()), \
                 patch.object(daily, "regulatory_snapshot", return_value={}), \
                 patch.dict(os.environ, {"GITHUB_RUN_ID": ""}):
                feed = module.collect(NOW, days=0) if module is daily else module.collect(NOW)
            actual = (json.dumps(feed, separators=(",", ":"), allow_nan=False) + "\n").encode()
            self.assertEqual(actual, (FIXTURES / "station-failover" / filename).read_bytes())
            self.assertTrue(all("station" not in s and "fallback_for" not in s for s in feed["sources"].values()))


    def test_mixed_legacy_results_are_byte_identical(self):
        previous = legacy_mixed_previous()
        MemoryClient.responses = {"46215": ValueError("synthetic outage"), "46215.spec": buoy(), "46028": buoy(8)}
        with patch.object(live, "settings", return_value=legacy_config()), \
             patch.object(live, "source", side_effect=fixed_source), \
             patch.object(live, "stamp", return_value=NOW.isoformat()), \
             patch.object(daily, "stamp", return_value=NOW.isoformat()), \
             patch.dict(os.environ, {"GITHUB_RUN_ID": ""}):
            feed = live.collect(NOW, previous)
        actual = (json.dumps(feed, separators=(",", ":"), allow_nan=False) + "\n").encode()
        self.assertEqual(actual, (FIXTURES / "station-failover" / "legacy-live-mixed.json").read_bytes())
        self.assertEqual(feed["sources"]["diablo"]["status"], "retained")
        self.assertEqual(feed["sources"]["diablo-spectrum"]["status"], "ok")
        self.assertEqual(feed["sources"]["offshore"]["status"], "stale")
        self.assertTrue(all("station" not in s and "fallback_for" not in s for s in feed["sources"].values()))


def legacy_mixed_previous():
    from skippercast.pipeline.parsers import ndbc
    return {"schema_version": 1, "sources": {"diablo": {
            "data": ndbc(buoy(), "46215"), "last_success_at": NOW.isoformat(), "data_retrieved_at": NOW.isoformat()}}}
