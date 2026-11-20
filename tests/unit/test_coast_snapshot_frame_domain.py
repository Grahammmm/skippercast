"""Radar frame times outside the four-digit UTC domain drop that field only (synthetic inputs)."""

import copy
from unittest import TestCase

from skippercast.pipeline import coast_snapshots as cs
from skippercast.pipeline.goes_frames import MIN_MS
from tests.unit.test_coast_snapshots import NOW, T, goes, intelligence


def radar_frames(doc):
    return doc["sources"]["hfr-1"]["data"]["frames"]


def frames_for(doc, time):
    data = copy.deepcopy(doc["sources"]["hfr-1"]["data"])
    data["frames"][0]["time"] = time
    return cs._frames(data, "observation", cs.FIELDS_RADAR, None, NOW.timestamp() * 1000)


class FrameDomain(TestCase):
    def test_out_of_domain_radar_time_preserves_sibling_and_cloud(self):
        doc = intelligence()
        radar_frames(doc)[0]["time"] = -1e20
        before = copy.deepcopy(doc)
        packet = cs.assemble(doc, goes(), NOW)
        self.assertEqual([f["id"] for f in packet["currents"]], ["wcofs"])
        self.assertEqual(packet["cloud"], goes())
        self.assertEqual(doc, before)

    def test_frame_domain_rejects_below_minimum_and_scaled_overflow(self):
        doc = intelligence()
        for time in (MIN_MS // 1000 - 1, -1e308, 1e308, 1e20, 10**400):
            self.assertIsNone(frames_for(doc, time), time)

    def test_old_but_representable_radar_frame_keeps_existing_policy(self):
        doc = intelligence()
        radar_frames(doc)[0]["time"] = T - 30 * 24 * 3600  # a month old, still representable
        packet = cs.assemble(doc, goes(), NOW)
        self.assertEqual([f["id"] for f in packet["currents"]], ["wcofs", "hfr-1"])

    def test_healthy_packet_and_domain_endpoint_control(self):
        doc = intelligence()
        packet = cs.assemble(doc, goes(), NOW)
        self.assertEqual([f["id"] for f in packet["currents"]], ["wcofs", "hfr-1"])
        self.assertEqual(packet["cloud"], goes())
        radar_frames(doc)[0]["time"] = MIN_MS // 1000
        frames = frames_for(doc, MIN_MS // 1000)
        self.assertEqual(frames[0]["validAt"], "0001-01-01T00:00:00.000Z")
        packet = cs.assemble(doc, goes(), NOW)
        self.assertEqual([f["id"] for f in packet["currents"]], ["wcofs", "hfr-1"])
        for source in doc["sources"].values():
            source["status"] = "error"
        packet = cs.assemble(doc, goes(), NOW)
        self.assertEqual((packet["currents"], packet["sources"][0]["error"]),
                         ([], "No fresh reviewed current fields"))
