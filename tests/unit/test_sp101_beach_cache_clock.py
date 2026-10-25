"""Synthetic producer-shaped cache-clock regressions; no ambient process changes."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from unittest import TestCase, mock

from skippercast.http import FakeSession
from skippercast.pipeline import beach_health as bh

NOW = datetime(2026, 10, 8, 15, tzinfo=timezone.utc)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/sp101_beach_cache_clock"
BASE = {"schemaVersion": 1, "countyId": "slo", "regionId": "morro-bay",
        "generatedAt": "2026-10-08T15:00:00Z", "waterQuality": [], "sources": [{
            "id": "synthetic-beach-status", "label": "Invented beach status",
            "url": "https://feeds.example.invalid/beach", "kind": "observation",
            "outcome": "ok", "fetchedAt": "2026-10-08T15:00:00Z"}]}


class RegressionTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "beach-health.json"
        self.cases = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))

    def write_doc(self, doc):
        self.path.write_bytes(json.dumps(doc, separators=(",", ":")).encode("utf-8"))

    def assert_due_unchanged(self, expected):
        original = self.path.read_bytes()
        self.assertIs(bh.due(self.path, NOW), expected)
        self.assertEqual(self.path.read_bytes(), original)

    def test_primary_regression(self):
        doc = copy.deepcopy(BASE)
        doc["sources"][0]["fetchedAt"] = "2026-10-08T14:59:00"
        self.write_doc(doc)
        original = self.path.read_bytes()
        try:
            actual = bh.due(self.path, NOW)
        except Exception as error:
            actual = error
        self.assertEqual(self.path.read_bytes(), original)
        self.assertIs(actual, True, f"naive successful fetchedAt must be due, got {actual!r}")

    def test_healthy_control(self):
        self.write_doc(BASE)
        self.assert_due_unchanged(False)

    def test_invalid_and_naive_timestamps_are_due(self):
        for value in self.cases["invalid_timestamps"]:
            with self.subTest(fetchedAt=value):
                doc = copy.deepcopy(BASE)
                doc["sources"][0]["fetchedAt"] = value
                self.write_doc(doc)
                self.assert_due_unchanged(True)

    def test_missing_timestamp_is_due(self):
        doc = copy.deepcopy(BASE)
        del doc["sources"][0]["fetchedAt"]
        self.write_doc(doc)
        self.assert_due_unchanged(True)

    def test_malformed_sources_are_due(self):
        for sources in self.cases["malformed_sources"]:
            with self.subTest(sources=sources):
                doc = copy.deepcopy(BASE)
                doc["sources"] = sources
                self.write_doc(doc)
                self.assert_due_unchanged(True)
        for doc in ({}, [], None):
            with self.subTest(document=doc):
                self.write_doc(doc)
                self.assert_due_unchanged(True)

    def test_error_or_missing_outcome_is_due(self):
        for outcome in ("error", None):
            with self.subTest(outcome=outcome):
                doc = copy.deepcopy(BASE)
                doc["sources"][0]["outcome"] = outcome
                self.write_doc(doc)
                self.assert_due_unchanged(True)
        doc = copy.deepcopy(BASE)
        del doc["sources"][0]["outcome"]
        self.write_doc(doc)
        self.assert_due_unchanged(True)

    def test_invalid_files_are_due(self):
        self.assertIs(bh.due(self.path, NOW), True)
        self.assertFalse(self.path.exists())
        for raw in (b"\xff\xfe", b"{invalid json"):
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                self.assert_due_unchanged(True)
        directory = Path(self.tmp.name) / "unreadable-directory"
        directory.mkdir()
        self.assertIs(bh.due(directory, NOW), True)

    def test_unreadable_file_is_due(self):
        self.write_doc(BASE)
        original_read = Path.read_text

        def denied(path, *args, **kwargs):
            if path == self.path:
                raise PermissionError("synthetic unreadable cache")
            return original_read(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", denied):
            self.assert_due_unchanged(True)

    def test_aware_offsets_and_poll_window(self):
        self.assertEqual(bh.POLL_MINUTES, 55)
        for label, timestamp, expected in self.cases["window"]:
            with self.subTest(case=label):
                doc = copy.deepcopy(BASE)
                doc["sources"][0]["fetchedAt"] = timestamp
                self.write_doc(doc)
                self.assert_due_unchanged(expected)

    def test_publish_keeps_healthy_cache_with_injected_fake(self):
        path = Path(self.tmp.name) / "regions/morro-bay/beach-health.json"
        path.parent.mkdir(parents=True)
        path.write_bytes(json.dumps(BASE, separators=(",", ":")).encode("utf-8"))
        original = path.read_bytes()
        session = FakeSession({})
        self.assertEqual(bh.publish(self.tmp.name, session, NOW, regions=["morro-bay"]),
                         {"morro-bay": "kept"})
        self.assertEqual(session.calls, [])
        self.assertEqual(path.read_bytes(), original)
