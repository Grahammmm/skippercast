"""Offshore SST fronts (BF-sst-fronts): each front carries its observation time and an uncertainty band,
and nothing is published from a tile with no usable, current observation time."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest

from skippercast.pipeline.sst_fronts import SstFrontError, publish

HEALTH = {"feeds": {"sst-fronts": {"max_age_hours": 48}}}
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
FIELDS = ["latitude", "longitude", "temperature_c", "analysis_error_c", "temperature_gradient_c_per_km", "thermal_contrast_supported"]
ERROR = 0.4
ROOT = Path(__file__).resolve().parents[2]


def tile(rows, time, temp=lambda i, j: 14.0 if j < 6 else 16.0, cols=range(12)):
    cells = [[round(35 + i * 0.01, 5), round(-121 + j * 0.01, 5), temp(i, j), ERROR, None, None] for i in rows for j in cols]
    return {"fields": FIELDS, "resolution_degrees": [0.01, 0.01], "frames": [{"time": time, "cells": cells}]}


def at(hours=0, seconds=0):
    return (NOW - timedelta(hours=hours, seconds=seconds)).timestamp()


def fronts(*tiles, health=HEALTH):
    return publish("test-coast", [(f"t{n}", t) for n, t in enumerate(tiles)], health, NOW)


class FrontsTests(unittest.TestCase):
    def test_a_front_carries_its_observation_time_and_an_uncertainty_band(self):
        doc = fronts(tile(range(12), at(6)))
        self.assertEqual(len(doc["fronts"]), 1)
        front = doc["fronts"][0]
        self.assertEqual(front["observed_at"], "2026-11-03T06:00:00Z")
        self.assertEqual(doc["observed_at"], front["observed_at"])
        self.assertEqual(front["uncertainty_c"], ERROR)
        self.assertGreater(front["strength_c_per_km"], 0)
        # The band is the analysis error over the gradient, not a guessed figure.
        self.assertAlmostEqual(front["band_half_width_km"], ERROR / front["strength_c_per_km"], places=2)
        self.assertEqual(front["geometry"]["type"], "LineString")
        self.assertGreater(len(front["geometry"]["coordinates"]), 1)
        self.assertEqual(doc["max_age_hours"], 48)

    def test_unusable_observation_times_yield_no_front(self):
        def frame(time):
            t = tile(range(12), time)
            if time == "absent":
                del t["frames"][0]["time"]
            return t
        for label, time, key in (("missing", "absent", "missing_time"), ("null", None, "missing_time"), ("unparseable", "yesterday-ish", "unparseable_time"),
                                 ("nan", float("nan"), "unparseable_time"), ("future", at(-1), "future"), ("one second past the limit", at(48, 1), "stale")):
            with self.subTest(label):
                doc = fronts(frame(time))
                self.assertEqual(doc["fronts"], [])
                self.assertIsNone(doc["observed_at"])
                self.assertEqual(doc["refused_frames"][key], 1)

    def test_exactly_at_the_limit_still_publishes(self):
        doc = fronts(tile(range(12), at(48)))
        self.assertEqual(len(doc["fronts"]), 1)
        self.assertEqual(doc["fronts"][0]["observed_at"], "2026-11-01T12:00:00Z")

    def test_a_uniform_field_has_no_front_not_a_zero_strength_one(self):
        doc = fronts(tile(range(12), at(3), temp=lambda i, j: 15.0))
        self.assertEqual(doc["fronts"], [])
        self.assertEqual(doc["observed_at"], "2026-11-03T09:00:00Z")

    def test_a_change_within_the_analysis_error_is_not_a_front(self):
        doc = fronts(tile(range(12), at(3), temp=lambda i, j: 14.0 if j < 6 else 14.5))
        self.assertEqual(doc["fronts"], [])

    def test_non_finite_and_out_of_range_temperatures_are_refused_by_name(self):
        for label, bad in (("nan", float("nan")), ("infinite", float("inf")), ("too hot", 80.0), ("too cold", -40.0), ("text", "warm")):
            with self.subTest(label):
                with self.assertRaisesRegex(SstFrontError, "temperature_c"):
                    fronts(tile(range(12), at(3), temp=lambda i, j: bad if (i, j) == (4, 4) else 15.0))

    def test_a_front_crossing_a_tile_boundary_is_one_front(self):
        doc = fronts(tile(range(0, 6), at(6)), tile(range(6, 12), at(6)))
        self.assertEqual(len(doc["fronts"]), 1)
        self.assertEqual(doc["fronts"][0]["cells"], 12)

    def test_tiles_of_an_older_observation_are_not_stitched_to_the_newest(self):
        doc = fronts(tile(range(0, 4), at(6)), tile(range(4, 12), at(30)))
        self.assertEqual(doc["observed_at"], "2026-11-03T06:00:00Z")
        self.assertEqual(doc["fronts"], [])  # four cells alone are too short to be an edge; the older rows are not joined to them

    def test_a_missing_age_limit_fails_loudly(self):
        for health in ({}, {"feeds": {}}, {"feeds": {"sst-fronts": {}}}, {"feeds": {"sst-fronts": {"max_age_hours": None}}},
                       {"feeds": {"sst-fronts": {"max_age_hours": 0}}}, {"feeds": {"sst-fronts": {"max_age_hours": True}}},
                       {"feeds": {"sst-fronts": {"max_age_hours": float("inf")}}}):
            with self.subTest(health=health):
                with self.assertRaisesRegex(SstFrontError, "max_age_hours"):
                    fronts(tile(range(12), at(3)), health=health)

    def test_the_catalog_names_the_fronts_feed_limit(self):
        health = json.loads((ROOT / "catalog" / "feed-health.json").read_text())
        doc = fronts(tile(range(12), at(3)), health=health)
        self.assertEqual(doc["max_age_hours"], health["feeds"]["sst-fronts"]["max_age_hours"])


if __name__ == "__main__":
    unittest.main()
