"""RF1500-21: zoned SST observation times become UTC before pooling, so tile order cannot change the output."""

from datetime import timedelta, timezone
import unittest

from skippercast.pipeline.sst_fronts import observation_time
from tests.gis.test_sst_fronts import at, fronts, tile

STAMP = "2026-11-03T06:00:00Z"
EPOCH = at(6)
# One instant (2026-11-03 06:00 UTC) written four ways, two of them across a calendar date.
SAME_INSTANT = (STAMP, "2026-11-03T06:00:00+00:00", "2026-11-03T08:00:00+02:00", "2026-11-02T22:00:00-08:00")
CONTROL = fronts(tile(range(12), EPOCH))


def uniform(time):
    return tile(range(12), time, temp=lambda i, j: 15.0)


class ObservationTimeTests(unittest.TestCase):
    def test_iso_offsets_return_utc(self):
        for text in SAME_INSTANT:
            with self.subTest(text):
                when = observation_time(text)
                self.assertEqual(when.utcoffset(), timedelta(0))
                self.assertIs(when.tzinfo, timezone.utc)
                self.assertEqual(when.timestamp(), EPOCH)
                self.assertEqual(when.isoformat(), "2026-11-03T06:00:00+00:00")

    def test_invalid_and_naive_inputs_stay_unusable(self):
        for value in ("2026-11-03T06:00:00", "not a date", "", True, float("nan"), float("inf"), None, [], {}):
            with self.subTest(repr(value)):
                self.assertIsNone(observation_time(value))

    def test_utc_conversion_overflow_is_refused_inside_the_parser(self):
        for text in ("0001-01-01T00:00:00+02:00", "9999-12-31T23:59:59-02:00"):
            with self.subTest(text):
                self.assertIsNone(observation_time(text))

    def test_numeric_epoch_is_unchanged(self):
        self.assertEqual(observation_time(EPOCH), observation_time(STAMP))
        self.assertEqual(observation_time(int(EPOCH)).utcoffset(), timedelta(0))


class PublishTests(unittest.TestCase):
    def test_equivalent_stamps_publish_identical_nonempty_document(self):
        self.assertEqual(len(CONTROL["fronts"]), 1)
        self.assertEqual(CONTROL["observed_at"], STAMP)
        for time in (EPOCH,) + SAME_INSTANT:
            with self.subTest(time):
                doc = fronts(tile(range(12), time))
                self.assertEqual(doc, CONTROL)
                self.assertEqual(doc["observed_at"], STAMP)
                self.assertEqual(doc["fronts"][0]["observed_at"], STAMP)

    def test_equal_instant_tiles_are_order_independent(self):
        older = uniform("2026-11-02T10:00:00+05:00")  # 05:00 UTC the same day: a distinct, older instant
        top, bottom = "2026-11-03T08:00:00+02:00", "2026-11-02T22:00:00-08:00"
        a, b = tile(range(0, 6), top), tile(range(6, 12), bottom)
        forward, backward = fronts(a, b), fronts(b, a)
        self.assertEqual(forward, backward)
        self.assertEqual(forward["observed_at"], STAMP)
        self.assertEqual(forward["fronts"][0]["observed_at"], STAMP)
        self.assertEqual(forward["fronts"][0]["cells"], 12)
        self.assertEqual(forward["fronts"], CONTROL["fronts"])
        # An older instant is not pooled: pooled, its uniform cells would conflict with the edge's.
        for order in ((a, b, older), (older, b, a), (b, older, a)):
            self.assertEqual(fronts(*order), forward)

    def test_offset_age_boundaries_are_instant_based(self):
        cases = (
            ("now", "2026-11-03T04:00:00-08:00", None),
            ("future by one second", "2026-11-03T04:00:01-08:00", "future"),
            ("exactly 48 hours old", "2026-11-02T01:00:00+13:00", None),
            ("48 hours and one second old", "2026-10-31T21:59:59-14:00", "stale"),
        )
        for label, time, refused in cases:
            with self.subTest(label):
                doc = fronts(tile(range(12), time))
                if refused is None:
                    self.assertEqual(len(doc["fronts"]), 1)
                    self.assertEqual(doc["refused_frames"], {"missing_time": 0, "unparseable_time": 0, "future": 0, "stale": 0})
                else:
                    self.assertEqual(doc["fronts"], [])
                    self.assertIsNone(doc["observed_at"])
                    self.assertEqual(doc["refused_frames"][refused], 1)
                    self.assertEqual(sum(doc["refused_frames"].values()), 1)
        self.assertEqual(fronts(tile(range(12), "2026-11-02T01:00:00+13:00"))["observed_at"], "2026-11-01T12:00:00Z")

    def test_unusable_times_keep_their_refusal_counters(self):
        for label, time, key in (("naive", "2026-11-03T06:00:00", "unparseable_time"), ("text", "not a date", "unparseable_time"),
                                 ("null", None, "missing_time"), ("bool", True, "unparseable_time"),
                                 ("nan", float("nan"), "unparseable_time"), ("inf", float("inf"), "unparseable_time"),
                                 ("overflow", "0001-01-01T00:00:00+02:00", "unparseable_time")):
            with self.subTest(label):
                doc = fronts(tile(range(12), time))
                self.assertEqual(doc["fronts"], [])
                self.assertIsNone(doc["observed_at"])
                self.assertEqual(doc["refused_frames"][key], 1)
                self.assertEqual(sum(doc["refused_frames"].values()), 1)

    def test_fractional_seconds_select_the_later_instant(self):
        early, late = "2026-11-03T06:00:00.250000Z", "2026-11-03T08:00:00.750000+02:00"
        later_alone = fronts(tile(range(12), late))
        self.assertEqual(later_alone["observed_at"], STAMP)
        # The earlier microsecond is a different instant, so the later one is not pooled with it
        # (pooled, its uniform cells would conflict with the edge's) and does not win by order.
        for order in ((uniform(early), tile(range(12), late)), (tile(range(12), late), uniform(early))):
            self.assertEqual(fronts(*order), later_alone)
        # Equivalent-offset expressions of the later instant still pool.
        pooled = fronts(tile(range(0, 6), late), tile(range(6, 12), "2026-11-02T22:00:00.750000-08:00"))
        self.assertEqual(pooled["fronts"][0]["cells"], 12)
        self.assertEqual(pooled["fronts"][0]["observed_at"], STAMP)


if __name__ == "__main__":
    unittest.main()
