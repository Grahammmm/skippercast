import copy
import json
import math
import unittest

from skippercast.pipeline.habitat_dynamics import frame_for_time

INVALID = {"frame": None, "mode": None, "reason": "Invalid product timing metadata"}
NOW = 1_800_000_000.0
HOUR = 3600.0


def layer(kind="analysis", age_hours=100, status="ok", **extra):
    base = {"kind": kind, "status": status, "issued_at": NOW - age_hours * HOUR,
            "frames": [{"time": NOW - 3 * HOUR, "valid_cells": 5}]}
    if kind == "forecast":
        base["frames"] = [{"time": NOW, "valid_cells": 5}, {"time": NOW + 3 * HOUR, "valid_cells": 5}]
    base.update(extra)
    return base


class FreshnessLimitAdmission(unittest.TestCase):
    def test_nonfinite_limits_never_select_frames(self):
        for kind in ("analysis", "observation", "forecast"):
            for status in ("ok", "retained"):
                for bad in (math.nan, math.inf, -math.inf, json.loads("1e999")):
                    with self.subTest(kind=kind, status=status, bad=bad):
                        self.assertEqual(frame_for_time(layer(kind, 100, status, max_age_hours=bad), NOW, NOW), INVALID)
                        self.assertEqual(frame_for_time(layer(kind, 1, status, max_age_hours=bad), NOW, NOW), INVALID)

    def test_limit_type_admission_is_not_coercion(self):
        for bad in ("36", True, False, None, [36], {"h": 36}, -1, -0.5, 10**400, -(10**400)):
            with self.subTest(bad=bad):
                item = layer(age_hours=0, max_age_hours=bad)
                before = copy.deepcopy(item)
                self.assertEqual(frame_for_time(item, NOW, NOW), INVALID)
                self.assertEqual(item, before)
        missing = layer(age_hours=0)
        self.assertEqual(frame_for_time(missing, NOW, NOW), INVALID)

    def test_finite_limits_preserve_exact_boundary(self):
        for limit in (36, 72, 96, 36.5):
            with self.subTest(limit=limit):
                at = frame_for_time(layer(age_hours=limit, max_age_hours=limit), NOW, NOW)
                self.assertEqual(at["mode"], "observed-context")
                late = frame_for_time(layer(age_hours=limit + 1 / HOUR, max_age_hours=limit), NOW, NOW)
                self.assertEqual(late, {"frame": None, "mode": None, "reason": "Source is outside its freshness window"})
        self.assertEqual(frame_for_time(layer(max_age_hours=100), NOW, NOW),
                         frame_for_time(layer(max_age_hours=100.0), NOW, NOW))

    def test_zero_limit_keeps_legacy_semantics(self):
        for zero in (0, 0.0):
            self.assertEqual(frame_for_time(layer(age_hours=0, max_age_hours=zero), NOW, NOW)["mode"], "observed-context")
            self.assertEqual(frame_for_time(layer(age_hours=1 / HOUR, max_age_hours=zero), NOW, NOW)["reason"],
                             "Source is outside its freshness window")
            self.assertEqual(frame_for_time(layer(age_hours=-1, max_age_hours=zero), NOW, NOW)["mode"], "observed-context")
            self.assertEqual(frame_for_time(layer(age_hours=-1.01, max_age_hours=zero), NOW, NOW)["reason"],
                             "Source is outside its freshness window")

    def test_valid_limit_results_unchanged(self):
        forecast = layer("forecast", 1, max_age_hours=36)
        result = frame_for_time(forecast, NOW + HOUR, NOW)
        self.assertEqual(result["mode"], "forecast")
        self.assertIs(result["frame"], forecast["frames"][0])
        self.assertEqual(frame_for_time(forecast, NOW + 10 * HOUR, NOW)["reason"], "No ocean forecast at the selected time")
        trip = frame_for_time(layer(age_hours=1, max_age_hours=36), NOW + 48 * HOUR, NOW)
        self.assertEqual(trip["reason"], "Dated surface context, not a forecast for the trip date")
        self.assertEqual(frame_for_time(layer(status="failed", max_age_hours=36), NOW, NOW)["reason"],
                         "Source unavailable or no populated cells")


if __name__ == "__main__":
    unittest.main()
