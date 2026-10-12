"""FE-84: the coast ocean packet assembled from SkipperCast's intelligence feed and GOES index (synthetic inputs)."""

import copy
from datetime import datetime, timezone
import json
import re
import tempfile
from pathlib import Path
from unittest import TestCase

from skippercast.pipeline import coast_snapshots as cs
from tests._support import ROOT

NOW = datetime(2026, 10, 8, 21, 0, tzinfo=timezone.utc)
T = int(NOW.timestamp())  # epoch seconds, the intelligence feed's frame clock


def intelligence():
    """A small synthetic `intelligence.json` in the shape `refresh_regions.py intelligence` publishes."""
    radar = {"status": "ok", "data_retrieved_at": "2026-10-08T20:40:46Z", "data": {
        "kind": "observation", "sample_at": "2026-10-08T17:00:00Z", "resolution_km": 1, "surface_only": True,
        "grid_stride": 4, "fields": cs.FIELDS_RADAR, "frames": [
            {"time": T - 5 * 3600, "cells": [[35.3, -121.0, 0.5, 90.0, 1.2, 3]]},
            {"time": T - 4 * 3600, "cells": [[35.3, -121.0, 0.4, 360.0, 0.8, 4], [35.31, -121.0, 0.3, 10.0, 2.5, 3],
                                             [35.32, -121.0, 0.3, 10.0, 1.0, 1]]}]}}
    model = {"status": "ok", "data_retrieved_at": "2026-10-08T18:12:39Z", "data": {
        "kind": "forecast", "issued_at": "2026-10-08T03:00:00Z", "resolution_km": 4, "surface_only": True,
        "horizontal_datum": "NAD83", "vertical_layer": "surface (0 m)", "fields": cs.FIELDS_FORECAST, "frames": [
            {"time": int(datetime(2026, 10, 8, 18, tzinfo=timezone.utc).timestamp()), "cells": [[35.0, -121.5, 0.2, 180.0]],
             "source_file": "wcofs.t03z.20261008.regulargrid.f015.nc"},
            {"time": int(datetime(2026, 10, 8, 21, tzinfo=timezone.utc).timestamp()), "cells": [[35.0, -121.5, 0.25, 185.0]],
             "source_file": "../private.nc"}]}}
    return {"schema_version": 1, "region_id": "morro-bay", "generated_at": "2026-10-08T20:37:09Z",
            "sources": {"hfr-1": radar, "wcofs": model, "hfr-6": {"status": "error", "issue": "HTTP 503"}}}


def goes(observed="2026-10-08T20:38:00.000Z"):
    return {"id": "goes-longwave", "kind": "observation", "observedAt": observed, "fetchedAt": "2026-10-08T20:41:02.000Z",
            "availableTimes": ["2026-10-08T20:33:00.000Z", observed], "layer": "goes_longwave_imagery",
            "url": "https://nowcoast.noaa.gov/", "attribution": "NOAA / NESDIS · GOES East & West longwave infrared",
            "license": "public-domain-us-gov", "limitations": "Observed frames only."}


def type_keys(name):
    source = (ROOT / "packages/coast/src/ocean-types.ts").read_text()
    body = re.search(rf"export type {name} = \{{(.*?)\}};", source, re.S).group(1)
    return {key.rstrip("?") for key in re.findall(r"(\w+\??):", body)}


class Currents(TestCase):
    def test_reviewed_fields_keep_native_frames_and_their_own_clocks(self):
        packet = cs.assemble(intelligence(), goes(), NOW)
        self.assertEqual([f["id"] for f in packet["currents"]], ["wcofs", "hfr-1"])  # hfr-6 errored upstream
        model, radar = packet["currents"]
        self.assertEqual((model["fetchedAt"], model["issuedAt"], model["sampleAt"]),
                         ("2026-10-08T18:12:39.000Z", "2026-10-08T03:00:00.000Z", None))
        self.assertEqual((radar["fetchedAt"], radar["sampleAt"]), ("2026-10-08T20:40:46.000Z", "2026-10-08T17:00:00.000Z"))
        self.assertEqual([f["validAt"] for f in model["frames"]], ["2026-10-08T18:00:00.000Z", "2026-10-08T21:00:00.000Z"])
        self.assertEqual(model["frames"][0]["sourceFile"], "wcofs.t03z.20261008.regulargrid.f015.nc")
        self.assertNotIn("sourceFile", model["frames"][1])  # an unexpected file name is never passed through
        # HDOP above 2 and a single contributing radar are left out; a 360° bearing is northward.
        self.assertEqual([c["towardDeg"] for c in radar["frames"][1]["cells"]], [0.0])
        cell = radar["frames"][0]["cells"][0]
        self.assertEqual((cell["uMs"], cell["vMs"], cell["hdop"], cell["radarCount"]), (0.25722, 0.0, 1.2, 3))
        self.assertEqual(set(model), type_keys("CurrentField"))
        self.assertEqual(model["horizontalDatum"], "NAD83")
        self.assertEqual(radar["horizontalDatum"], "WGS84")

    def test_a_stale_or_foreign_feed_publishes_an_error_source_and_no_currents(self):
        for change in ({"generated_at": "2026-10-08T14:59:00Z"}, {"region_id": "monterey-point-sur"}, {"schema_version": 2}):
            packet = cs.assemble({**intelligence(), **change}, goes(), NOW)
            self.assertEqual(packet["currents"], [])
            source = packet["sources"][0]
            self.assertEqual((source["id"], source["status"], source["error"]),
                             ("skippercast-noaa-ocean", "error", "Invalid or stale regional ocean feed"))
        packet = cs.assemble(None, goes(), NOW)
        self.assertEqual(packet["sources"][0]["fetchedAt"], "2026-10-08T21:00:00.000Z")

    def test_retained_old_or_malformed_fields_are_dropped_one_by_one(self):
        doc = intelligence()
        doc["sources"]["wcofs"]["status"] = "retained"  # last success kept upstream: not a current product
        self.assertEqual([f["id"] for f in cs.currents(doc, NOW.timestamp() * 1000)], ["hfr-1"])
        doc = intelligence()
        doc["sources"]["hfr-1"]["data"]["frames"][0]["cells"][0][0] = 36.5  # outside the SLO marine bounds
        doc["sources"]["wcofs"]["data"]["frames"][1]["time"] += 3600  # off the native three-hour step
        packet = cs.assemble(doc, goes(), NOW)
        self.assertEqual(packet["currents"], [])
        self.assertEqual(packet["sources"][0]["error"], "No fresh reviewed current fields")
        doc = intelligence()
        doc["sources"]["hfr-1"]["data"]["sample_at"] = "2026-10-08T14:00:00Z"  # over six hours old
        doc["sources"]["wcofs"]["data"]["vertical_layer"] = "10 m"
        self.assertEqual(cs.assemble(doc, goes(), NOW)["currents"], [])
        doc = intelligence()
        doc["sources"]["wcofs"]["data_retrieved_at"] = "2026-10-08T14:59:00Z"  # fetched over six hours ago
        self.assertEqual([f["id"] for f in cs.assemble(doc, goes(), NOW)["currents"]], ["hfr-1"])


class Cloud(TestCase):
    def test_a_current_index_is_kept_verbatim_and_a_stale_one_is_an_error(self):
        packet = cs.assemble(intelligence(), goes(), NOW)
        self.assertEqual(packet["cloud"], goes())
        self.assertEqual(packet["sources"][1], {"id": "noaa-goes", "url": cs.CAPABILITIES_URL,
                                                "fetchedAt": "2026-10-08T20:41:02.000Z", "status": "ok"})
        for record in (goes("2026-10-08T19:20:00.000Z"), {**goes(), "observedAt": "2026-10-08T20:50:00.000Z"}, None):
            packet = cs.assemble(intelligence(), record, NOW)
            self.assertIsNone(packet["cloud"])
            self.assertEqual(packet["sources"][1]["status"], "error")


class Packet(TestCase):
    def test_main_writes_the_ocean_data_packet_beside_the_region_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "regions/morro-bay").mkdir(parents=True)
            (root / "regions/morro-bay/intelligence.json").write_text(json.dumps(intelligence()))
            (root / "goes-times.json").write_text(json.dumps(goes()))
            self.assertEqual(cs.main(["--root", tmp], now=NOW), 0)
            packet = json.loads((root / "regions/morro-bay/coast-ocean.json").read_text())
        self.assertEqual(set(packet), type_keys("OceanData"))
        self.assertEqual((packet["schemaVersion"], packet["countyId"], packet["generatedAt"]), (1, "slo", "2026-10-08T21:00:00.000Z"))
        self.assertEqual([s["status"] for s in packet["sources"]], ["ok", "ok"])
        for source in packet["sources"]:
            self.assertEqual(set(source) - {"error"}, type_keys("OceanSource") - {"error"})

    def test_inputs_are_not_changed(self):
        doc, record = intelligence(), goes()
        before = copy.deepcopy((doc, record))
        cs.assemble(doc, record, NOW)
        self.assertEqual((doc, record), before)
