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


def row(start=None, end=None, **extra):
    data = {"coverage_start": start if start is not None else iso(-timedelta(hours=3)),
            "coverage_end": end if end is not None else iso(timedelta(hours=20)),
            "sample_at": NOW.isoformat()}
    return {"kind": "prediction", "status": "ok", "max_age_hours": 48, "data": data, **extra}


class FreshBoundsTests(TestCase):
    def test_non_string_bounds_are_unusable_and_untouched(self):
        self.assertTrue(fresh(row(), NOW))
        for bad in (None, True, 17, 1.5, [], {}):
            for key in ("coverage_start", "coverage_end"):
                with self.subTest(key=key, bad=bad):
                    r = row()
                    r["data"][key] = bad
                    before = deepcopy(r)
                    self.assertFalse(fresh(r, NOW))
                    self.assertEqual(r, before)

    def test_absent_and_invalid_string_bounds_stay_unusable(self):
        for key in ("coverage_start", "coverage_end"):
            for bad in ("", "not a date"):
                r = row()
                r["data"][key] = bad
                self.assertFalse(fresh(r, NOW))
            r = row()
            del r["data"][key]
            self.assertFalse(fresh(r, NOW))

    def test_valid_boundaries_unchanged(self):
        self.assertTrue(fresh(row(end=iso(timedelta(0))), NOW))
        self.assertFalse(fresh(row(end=iso(-timedelta(seconds=1))), NOW))
        self.assertTrue(fresh(row(start=iso(timedelta(days=1))), NOW))
        self.assertFalse(fresh(row(start=iso(timedelta(days=1, seconds=1))), NOW))
        self.assertTrue(fresh(row(start="2026-09-28T05:00:00-07:00", end="2026-09-29T05:00:00+00:00"), NOW))


class OrderedSourceTests(TestCase):
    def test_malformed_retained_row_does_not_block_backup(self):
        bad = row(start=17, status="retained")
        good = row()
        good["requests"] = [{"url": "b"}]
        bad["requests"] = [{"url": "a"}]
        seen = []

        def read(station, old):
            seen.append(station)
            return {"9412110": bad, "9412999": good}[station]
        out = ordered_source(["9412110", "9412999"], read, NOW)
        self.assertEqual(seen, ["9412110", "9412999"])
        self.assertEqual((out["station"], out["fallback_for"], out["status"]), ("9412999", "9412110", "ok"))
        self.assertEqual(out["requests"], [{"url": "a"}, {"url": "b"}])

    def test_first_backup_malformed_in_three_station_chain(self):
        rows = {"a": row(end=None, status="retained"), "b": row(), "c": row()}
        rows["a"]["data"]["coverage_end"] = []
        rows["b"]["data"]["coverage_start"] = None
        out = ordered_source(["a", "b", "c"], lambda s, old: rows[s], NOW)
        self.assertEqual((out["station"], out["fallback_for"]), ("c", "a"))

    def test_all_unusable_keeps_existing_retained_result(self):
        old = {"station": "a", "data": {"station": "a", "coverage_start": 17,
                                        "coverage_end": "2026-09-27T00:00:00Z"},
               "data_retrieved_at": "2026-09-27T00:00:00Z"}
        failed = {"kind": "prediction", "status": "error", "max_age_hours": 48, "data": None, "issue": "outage"}
        out = ordered_source(["a", "b"], lambda s, prev: dict(failed), NOW, old)
        self.assertEqual((out["status"], out["station"], out["data"]), ("retained", "a", old["data"]))
        self.assertNotIn("fallback_for", out)


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

    def previous(self, start):
        return {"station": "9412110", "data_retrieved_at": NOW.isoformat(), "last_success_at": NOW.isoformat(),
                "data": {"station": "9412110", "predictions": [], "sample_at": NOW.isoformat(),
                         "coverage_start": start, "coverage_end": iso(timedelta(hours=20))}}

    def test_valid_retained_primary_is_kept(self):
        out = self.tide(ValueError("outage"), predictions(), self.previous(iso(-timedelta(hours=3))))
        self.assertEqual((out["status"], out["station"]), ("retained", "9412110"))
        self.assertNotIn("fallback_for", out)

    def test_bad_previous_coverage_uses_backup(self):
        out = self.tide(ValueError("outage"), predictions(), self.previous(17))
        self.assertEqual((out["status"], out["station"], out["fallback_for"]), ("ok", "9412999", "9412110"))
        self.assertEqual(out["data"]["station"], "9412999")
        self.assertIn("9412999", out["data"]["note"])
        self.assertIn("9412999", out["url"])
        self.assertEqual(len(out["requests"]), 2)
