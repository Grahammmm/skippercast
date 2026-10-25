import hashlib
import json
import os
import unittest
from pathlib import Path

from skippercast.coastal.handoff import common


class ReviewerIdentityTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.environ["SC144_RUN_ROOT"]) / "synthetic-root"
        self.root.mkdir(parents=True, exist_ok=True)
        self.review = self.make_review({"reviewer_id": " fixture-reviewer "})

    def make_review(self, overrides=None):
        doc = {
            "schema": "coastal-private-input-review-v2",
            "independent": True,
            "reviewer_id": "fixture-reviewer",
            "facts_digest": "facts-123",
            "checked_at": "2026-10-25T10:00:00+00:00",
            "valid_until": "2026-10-25T12:00:00+00:00",
            "decision": "accept",
            "holds_added": [],
        }
        if overrides:
            doc.update(overrides)
        raw = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
        path = self.root / "review.json"
        path.write_bytes(raw)
        artifact = common.ref(self.root, path, "coastal-private-input-review-v2")
        return artifact, hashlib.sha256(raw).hexdigest()

    def holds(self, review=None, digest="facts-123", **kw):
        artifact, _ = review if review is not None else self.review
        return common.review_holds(self.root, artifact, digest, now="2026-10-25T11:00:00+00:00", **kw)

    def test_T01_valid_spelling_preserved_and_accepted(self):
        artifact, _ = self.make_review({"reviewer_id": "  Named Reviewer  "})
        self.assertEqual([], self.holds((artifact, None)))
        self.assertEqual("  Named Reviewer  ", common.load(self.root, artifact)["reviewer_id"])

    def test_T02_accepted_decisions_windows_and_added_hold(self):
        for decision in ("qualified_private_terrain", "accept"):
            artifact, _ = self.make_review({"decision": decision, "holds_added": ["source_review_required"]})
            self.assertEqual(["source_review_required"], self.holds((artifact, None)))
        artifact, _ = self.make_review({"valid_until": "2026-10-25T11:30:00+00:00"})
        self.assertEqual([], self.holds((artifact, None), minimum_valid_until="2026-10-25T11:15:00+00:00"))

    def test_T03_invalid_identity_shapes_fail_closed_without_crash(self):
        cases = (None, False, 7, "", "   \t", [], {})
        for value in cases:
            with self.subTest(value=value):
                artifact, _ = self.make_review({"reviewer_id": value})
                self.assertIn("independent_review_binding_invalid", self.holds((artifact, None)))
        artifact, _ = self.make_review()
        doc = common.load(self.root, artifact)
        del doc["reviewer_id"]
        raw = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
        (self.root / "review.json").write_bytes(raw)
        artifact = common.ref(self.root, self.root / "review.json", "coastal-private-input-review-v2")
        self.assertIn("independent_review_binding_invalid", self.holds((artifact, None)))

    def test_T04_producer_label_fails_closed(self):
        artifact, _ = self.make_review({"reviewer_id": "coastal.publisher"})
        self.assertIn("independent_review_binding_invalid", self.holds((artifact, None)))

    def test_T05_invalid_identity_preserves_independent_holds(self):
        artifact, _ = self.make_review({"reviewer_id": " ", "valid_until": "2026-10-25T10:30:00+00:00", "holds_added": None})
        self.assertEqual(["independent_review_binding_invalid", "review_expired_or_future", "review_holds_invalid"], self.holds((artifact, None), digest="wrong"))

    def test_T06_malformed_reference_original_fail_closed_path(self):
        with self.assertRaises((ValueError, KeyError)):
            common.review_holds(self.root, {"path": "missing.json", "sha256": "0" * 64, "bytes": 1, "contract": "coastal-private-input-review-v2"}, "facts-123", now="2026-10-25T11:00:00+00:00")

    def test_T07_valid_control(self):
        artifact, _ = self.make_review({"reviewer_id": "independent-reviewer"})
        self.assertEqual([], self.holds((artifact, None)))


if __name__ == "__main__":
    unittest.main()
