import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from skippercast.coastal.handoff import common

SCHEMA = "coastal-private-input-review-v2"


class EpochBooleanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="epoch-bool-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def review(self, **overrides):
        doc = {
            "schema": SCHEMA,
            "independent": True,
            "reviewer_id": "fixture-reviewer",
            "facts_digest": "facts-123",
            "checked_at": 0,
            "valid_until": 1,
            "decision": "accept",
            "holds_added": [],
        }
        doc.update(overrides)
        path = self.root / "review.json"
        path.write_bytes(json.dumps(doc, sort_keys=True).encode())
        return common.ref(self.root, path, SCHEMA)

    def holds(self, artifact, digest="facts-123", now=0.5, **kw):
        return common.review_holds(self.root, artifact, digest, now=now, **kw)

    def test_epoch_refuses_both_json_booleans(self):
        for text in ("false", "true"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                common.epoch(json.loads(text))
        for value, expected in ((0, 0.0), (1, 1.0), (0.0, 0.0), (1.0, 1.0)):
            self.assertEqual(expected, common.epoch(value))

    def test_boolean_checked_at_cannot_qualify_contemporary_review(self):
        now = "2026-11-16T12:00:00Z"
        good = self.review(checked_at="2026-11-16T00:00:00Z", valid_until="2026-11-17T00:00:00Z")
        self.assertEqual([], self.holds(good, now=now))
        bad = self.review(checked_at=False, valid_until="2026-11-17T00:00:00Z")
        self.assertEqual(["review_time_invalid"], self.holds(bad, now=now))

    def test_boolean_valid_until_cannot_qualify_epoch_window(self):
        self.assertEqual([], self.holds(self.review()))
        self.assertEqual(["review_time_invalid"], self.holds(self.review(valid_until=True)))

    def test_boolean_now_and_horizon_are_invalid_review_times(self):
        artifact = self.review()
        self.assertEqual(["review_time_invalid"], self.holds(artifact, now=False))
        self.assertEqual(["review_time_invalid"], self.holds(artifact, minimum_valid_until=False))

    def test_time_hold_preserves_independent_holds(self):
        artifact = self.review(
            checked_at=False, reviewer_id="coastal.bot", holds_added=["source_review_required", "source_review_required"]
        )
        self.assertEqual(
            ["independent_review_binding_invalid", "review_time_invalid", "source_review_required"],
            self.holds(artifact, digest="other"),
        )

    def test_accepted_clock_forms_and_strict_boundaries_unchanged(self):
        aware = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(aware.timestamp(), common.epoch(aware))
        self.assertEqual(aware.timestamp(), common.epoch("2026-01-01T00:00:00Z"))
        self.assertEqual(aware.timestamp(), common.epoch("2026-01-01T01:00:00+01:00"))
        with self.assertRaises(ValueError):
            common.epoch(datetime(2026, 1, 1))
        with self.assertRaises(ValueError):
            common.epoch(float("inf"))
        artifact = self.review()
        raw = (self.root / "review.json").read_bytes()
        self.assertEqual([], self.holds(artifact, now=0))
        self.assertEqual(["review_expired_or_future"], self.holds(artifact, now=1))
        self.assertEqual(["review_insufficient_validity"], self.holds(artifact, minimum_valid_until=1))
        self.assertEqual(raw, (self.root / "review.json").read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), hashlib.sha256((self.root / "review.json").read_bytes()).hexdigest())
