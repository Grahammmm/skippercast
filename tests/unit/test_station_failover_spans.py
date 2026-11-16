from copy import deepcopy
from datetime import timedelta
from unittest import TestCase
from unittest.mock import patch

from tests._support import NOW
from tests.unit.test_station_failover import MemoryClient, fixed_source, legacy_config, predictions
from skippercast.pipeline import collect as daily
from skippercast.pipeline.failover import fresh, ordered_source


def iso(delta):
    return (NOW + delta).isoformat().replace("+00:00", "Z")


def row(start, end, **extra):
    data = {"coverage_start": start, "coverage_end": end, "sample_at": NOW.isoformat()}
    return {"kind": "prediction", "status": "ok", "max_age_hours": 48, "data": data, **extra}


def inverted(**extra):
    return row(iso(timedelta(hours=12)), iso(timedelta(hours=6)), **extra)


def ordered(**extra):
    return row(iso(-timedelta(hours=3)), iso(timedelta(hours=20)), **extra)


class SpanTests(TestCase):
    def test_inverted_prediction_span_is_not_fresh(self):
        for status in ("ok", "retained"):
            r = inverted(status=status)
            before = deepcopy(r)
            self.assertFalse(fresh(r, NOW))
            self.assertEqual(r, before)
        self.assertFalse(fresh(row(iso(-timedelta(hours=2)), iso(-timedelta(hours=5))), NOW))
        for bad in (None, 17, ""):
            self.assertFalse(fresh(row(bad, iso(timedelta(hours=6))), NOW))
        self.assertTrue(fresh(ordered(), NOW))

    def test_inverted_retained_primary_tries_backup(self):
        good = ordered()
        good["requests"] = [{"url": "b"}]
        bad = inverted(status="retained")
        bad["requests"] = [{"url": "a"}]
        seen = []

        def read(station, old):
            seen.append(station)
            return {"a": bad, "b": good}[station]
        out = ordered_source(["a", "b"], read, NOW)
        self.assertEqual(seen, ["a", "b"])
        self.assertEqual((out["station"], out["fallback_for"], out["status"]), ("b", "a", "ok"))
        self.assertEqual(out["requests"], [{"url": "a"}, {"url": "b"}])

    def test_first_backup_inverted_in_three_station_chain(self):
        rows = {"a": inverted(status="retained"), "b": inverted(), "c": ordered()}
        out = ordered_source(["a", "b", "c"], lambda s, old: rows[s], NOW)
        self.assertEqual((out["station"], out["fallback_for"]), ("c", "a"))

    def test_ordering_uses_instants_and_preserves_equal_bounds(self):
        # lexical order differs from instant order: 05:00-07:00 is 12:00Z, 10:00+00:00 is earlier
        self.assertFalse(fresh(row("2026-09-28T05:00:00-07:00", "2026-09-28T10:00:00+00:00"), NOW))
        self.assertTrue(fresh(row("2026-09-28T10:00:00+00:00", "2026-09-28T05:00:00-07:00"), NOW))
        self.assertTrue(fresh(row("2026-09-28T19:00:00+07:00", "2026-09-28T12:00:00Z"), NOW))
        self.assertTrue(fresh(row(iso(timedelta(hours=5)), iso(timedelta(hours=5))), NOW))
        self.assertTrue(fresh(row(iso(-timedelta(hours=1)), iso(timedelta(0))), NOW))
        self.assertTrue(fresh(row(iso(timedelta(days=1)), iso(timedelta(days=2))), NOW))
        self.assertFalse(fresh(row(iso(-timedelta(hours=2)), iso(-timedelta(seconds=1))), NOW))
        self.assertFalse(fresh(row(iso(timedelta(days=1, seconds=1)), iso(timedelta(days=2))), NOW))

    def test_all_unusable_retains_original_evidence(self):
        old = {"station": "a", "data_retrieved_at": "2026-09-27T00:00:00Z", "last_success_at": "2026-09-27T00:00:00Z",
               "data": {"station": "a", "coverage_start": iso(timedelta(hours=12)),
                        "coverage_end": iso(timedelta(hours=6)), "sample_at": NOW.isoformat()}}
        failed = {"kind": "prediction", "status": "error", "max_age_hours": 48, "data": None, "issue": "outage"}
        snapshot = deepcopy(old)
        out = ordered_source(["a", "b"], lambda s, prev: dict(failed), NOW, old)
        self.assertEqual((out["status"], out["station"], out["data"]), ("retained", "a", snapshot["data"]))
        self.assertEqual(out["data_retrieved_at"], snapshot["data_retrieved_at"])
        self.assertNotIn("fallback_for", out)
        self.assertEqual(old, snapshot)


class DailyCollectorTests(TestCase):
    def tide(self, primary, backup, previous):
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
            return daily.collect(NOW, {"schema_version": 1, "sources": {"tides": previous}}, days=0)["sources"]["tides"]

    def previous(self, start, end):
        return {"station": "9412110", "data_retrieved_at": NOW.isoformat(), "last_success_at": NOW.isoformat(),
                "data": {"station": "9412110", "predictions": [], "sample_at": NOW.isoformat(),
                         "coverage_start": start, "coverage_end": end}}

    def test_daily_outage_with_inverted_previous_span_uses_backup(self):
        out = self.tide(ValueError("outage"), predictions(),
                        self.previous(iso(timedelta(hours=12)), iso(timedelta(hours=6))))
        self.assertEqual((out["status"], out["station"], out["fallback_for"]), ("ok", "9412999", "9412110"))
        self.assertEqual(out["data"]["station"], "9412999")
        self.assertIn("9412999", out["data"]["note"])
        self.assertIn("9412999", out["url"])
        self.assertEqual(len(out["requests"]), 2)

    def test_daily_ordered_previous_span_stays_retained(self):
        out = self.tide(ValueError("outage"), predictions(),
                        self.previous(iso(-timedelta(hours=3)), iso(timedelta(hours=20))))
        self.assertEqual((out["status"], out["station"]), ("retained", "9412110"))
        self.assertNotIn("fallback_for", out)
        self.assertEqual(len(out["requests"]), 1)
