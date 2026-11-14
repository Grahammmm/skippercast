"""A malformed `sources` container degrades only the current-field source, never the independent GOES cloud."""
import copy
import json
import tempfile
from pathlib import Path
from unittest import TestCase

from skippercast.pipeline import coast_snapshots as cs
from tests.unit.test_coast_snapshots import NOW, goes, intelligence

MS = NOW.timestamp() * 1000
BAD = [["bad"], [], "bad", "", 1, 0, True, False]


class SourceContainer(TestCase):
    def test_container_types_are_named_refusals(self):
        for bad in BAD:
            with self.subTest(sources=bad):
                with self.assertRaisesRegex(ValueError, "Invalid or stale regional ocean feed"):
                    cs.currents({**intelligence(), "sources": bad}, MS)
        for ok in ({}, None):
            with self.subTest(sources=ok):
                self.assertEqual(cs.currents({**intelligence(), "sources": ok}, MS), [])
        doc = intelligence()
        del doc["sources"]
        self.assertEqual(cs.currents(doc, MS), [])

    def test_bad_sources_preserve_independent_cloud(self):
        control = cs.assemble(intelligence(), goes(), NOW)
        for bad in BAD:
            with self.subTest(sources=bad):
                feed, record = {**intelligence(), "sources": bad}, goes()
                before = copy.deepcopy((feed, record))
                packet = cs.assemble(feed, record, NOW)
                self.assertEqual((feed, record), before)
                self.assertEqual(packet["currents"], [])
                self.assertEqual([(s["id"], s["status"]) for s in packet["sources"]],
                                 [("skippercast-noaa-ocean", "error"), ("noaa-goes", "ok")])
                self.assertEqual(packet["cloud"], control["cloud"])
                self.assertEqual(packet["sources"][1], control["sources"][1])
                self.assertEqual(set(packet), set(control))

    def test_bad_sources_and_bad_cloud_report_two_errors(self):
        for record in (None, goes("2026-10-01T00:00:00.000Z")):
            packet = cs.assemble({**intelligence(), "sources": ["bad"]}, record, NOW)
            self.assertEqual((packet["currents"], packet["cloud"]), ([], None))
            self.assertEqual([s["status"] for s in packet["sources"]], ["error", "error"])

    def test_valid_map_and_malformed_entry_compatibility(self):
        control = cs.assemble(intelligence(), goes(), NOW)
        self.assertEqual([f["id"] for f in control["currents"]], ["wcofs", "hfr-1"])
        doc = intelligence()
        doc["sources"]["wcofs"] = ["bad"]
        packet = cs.assemble(doc, goes(), NOW)
        self.assertEqual(packet["currents"], control["currents"][1:])
        self.assertEqual(packet["sources"][0]["status"], "ok")

    def test_main_serializes_degraded_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feed = root / "regions" / cs.REGION / "intelligence.json"
            feed.parent.mkdir(parents=True)
            feed.write_text(json.dumps({**intelligence(), "sources": ["bad"]}))
            (root / "goes-times.json").write_text(json.dumps(goes()))
            before = feed.read_bytes()
            self.assertEqual(cs.main(["--root", tmp], now=NOW), 0)
            self.assertEqual(feed.read_bytes(), before)
            packet = json.loads((feed.parent / "coast-ocean.json").read_text())
            self.assertEqual(packet["currents"], [])
            self.assertEqual(packet["cloud"], cs.assemble(intelligence(), goes(), NOW)["cloud"])
            self.assertEqual([s["status"] for s in packet["sources"]], ["error", "ok"])
