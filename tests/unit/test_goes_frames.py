"""FE-44: GOES longwave frame-time index, offline against a trimmed nowCOAST capabilities excerpt."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import tempfile
from unittest import TestCase, mock

from skippercast.http import FakeSession, TransportError
from skippercast.pipeline import goes_frames as gf
from tests._support import FIXTURES, ROOT

CAPABILITIES = (FIXTURES / "goes" / "capabilities.xml").read_bytes()
NOW = datetime(2026, 10, 8, 17, 46, tzinfo=timezone.utc)
ISO_UTC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


def document(times, layer=gf.LAYER):
    return (f'<WMS_Capabilities xmlns="http://www.opengis.net/wms"><Capability><Layer><Name>satellite</Name>'
            f'<Layer><Name>goes_visible_imagery</Name><Dimension name="time">2030-01-01T00:00:00Z</Dimension></Layer>'
            f'<Layer><Name>{layer}</Name><Dimension name="time" units="ISO8601">{",".join(times)}</Dimension></Layer>'
            f'</Layer></Capability></WMS_Capabilities>').encode()


class CapabilitiesFixture(TestCase):
    def test_fixture_yields_the_layer_time_list(self):
        image = gf.parse_capabilities(CAPABILITIES, NOW)
        times = image["availableTimes"]
        self.assertEqual(len(times), gf.MAX_TIMES)
        self.assertEqual(times[0], "2026-10-08T15:43:00.000Z")
        self.assertEqual(times[-1], "2026-10-08T17:38:00.000Z")
        self.assertEqual(image["observedAt"], times[-1])
        self.assertEqual(image["fetchedAt"], "2026-10-08T17:46:00.000Z")
        # Only the named layer's dimension: the hourly global mosaic times are not mixed in.
        self.assertNotIn("2026-10-08T17:00:00.000Z", times)
        self.assertTrue(all(b - a == 300_000 for a, b in zip(map(gf.epoch, times), map(gf.epoch, times[1:]))))

    def test_record_matches_the_packages_coast_cloud_image_type(self):
        source = (ROOT / "packages/coast/src/ocean-types.ts").read_text()
        body = re.search(r"export type CloudImage = \{(.*?)\};", source, re.S).group(1)
        fields = dict(re.findall(r"(\w+):([^;]+);", body))
        image = gf.parse_capabilities(CAPABILITIES, NOW)
        self.assertEqual(set(image), set(fields))
        for key, kind in fields.items():
            literal = re.fullmatch(r"'(.*)'", kind.strip())
            if literal:
                self.assertEqual(image[key], literal.group(1), key)
            elif kind == "string":
                self.assertIsInstance(image[key], str, key)
            elif kind == "string[]":
                self.assertTrue(all(isinstance(t, str) for t in image[key]), key)
            else:
                self.fail(f"unhandled CloudImage field type {key}: {kind}")
        # cloudSource only accepts an observedAt that is listed verbatim.
        self.assertIn(image["observedAt"], image["availableTimes"])


class TimeList(TestCase):
    def test_times_are_iso_utc_sorted_and_deduplicated(self):
        listed = ["2026-10-08T17:38:00Z", "2026-10-08T17:28:00.000Z", "2026-10-08T17:38:00.000Z",
                  "2026-10-08T10:33:00-07:00", " 2026-10-08T17:28:00+00:00", "2026-10-08T17:33:00.000Z"]
        image = gf.parse_capabilities(document(listed), NOW)
        self.assertEqual(image["availableTimes"], ["2026-10-08T17:28:00.000Z", "2026-10-08T17:33:00.000Z",
                                                   "2026-10-08T17:38:00.000Z"])
        self.assertTrue(all(ISO_UTC.match(t) for t in image["availableTimes"]))

    def test_unzoned_ranges_and_future_times_are_never_listed(self):
        listed = ["2026-10-08T17:30:00", "2026-10-08T15:00:00Z/2026-10-08T17:00:00Z/PT5M", "not-a-time",
                  "2026-10-08T17:50:00Z", "2026-10-08T18:30:00Z", "2026-10-08T17:20:00Z"]
        image = gf.parse_capabilities(document(listed), NOW)
        # 17:50 is within the five-minute publisher-clock tolerance; 18:30 is a future time and is dropped.
        self.assertEqual(image["availableTimes"], ["2026-10-08T17:20:00.000Z", "2026-10-08T17:50:00.000Z"])
        self.assertEqual(image["observedAt"], "2026-10-08T17:50:00.000Z")


class AgeGate(TestCase):
    def test_newest_frame_older_than_90_minutes_is_refused(self):
        newest = datetime(2026, 10, 8, 17, 38, tzinfo=timezone.utc)
        gf.parse_capabilities(CAPABILITIES, newest + timedelta(minutes=90))
        with self.assertRaisesRegex(ValueError, "stale"):
            gf.parse_capabilities(CAPABILITIES, newest + timedelta(minutes=90, seconds=1))

    def test_only_future_frames_is_refused(self):
        with self.assertRaisesRegex(ValueError, "stale"):
            gf.parse_capabilities(document(["2026-10-08T19:00:00Z"]), NOW)

    def test_missing_layer_or_dimension_is_refused(self):
        with self.assertRaisesRegex(ValueError, "metadata"):
            gf.parse_capabilities(document(["2026-10-08T17:38:00Z"], layer="goes_shortwave_imagery"), NOW)
        with self.assertRaisesRegex(ValueError, "metadata"):
            gf.parse_capabilities(b"<WMS_Capabilities><Layer><Name>goes_longwave_imagery</Name></Layer></WMS_Capabilities>", NOW)

    def test_doctype_is_refused(self):
        with self.assertRaisesRegex(ValueError, "DOCTYPE"):
            gf.parse_capabilities(b'<!DOCTYPE x [<!ENTITY a "b">]>' + document(["2026-10-08T17:38:00Z"]), NOW)


class Collector(TestCase):
    def test_collect_reads_only_the_fixed_capabilities_url(self):
        session = FakeSession({gf.CAPABILITIES_URL: CAPABILITIES})
        image = gf.collect(session, NOW)
        self.assertEqual(image["observedAt"], "2026-10-08T17:38:00.000Z")
        [(method, url, options)] = session.calls
        self.assertEqual((method, url), ("GET", gf.CAPABILITIES_URL))
        self.assertEqual(options["allowed_hosts"], [gf.HOST])
        self.assertEqual(options["max_bytes"], gf.MAX_BODY)

    def run_main(self, route):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "goes-times.json"
            output.write_text('{"prior":true}\n')
            with mock.patch.object(gf.http, "Session", lambda **_: FakeSession({gf.CAPABILITIES_URL: route})):
                code = gf.main(["--output", str(output)], now=NOW)
            return code, json.loads(output.read_text())

    def test_main_writes_a_fresh_index(self):
        code, written = self.run_main(CAPABILITIES)
        self.assertEqual(code, 0)
        self.assertEqual(written, gf.parse_capabilities(CAPABILITIES, NOW))

    def test_main_keeps_the_last_index_on_failure(self):
        stale = document(["2020-01-01T00:00:00Z"])
        for route in (TransportError("down"), stale, b"<WMS_Capabilities"):  # transport, stale, malformed
            code, written = self.run_main(route)
            self.assertEqual(code, 1)
            self.assertEqual(written, {"prior": True})


class Catalog(TestCase):
    def test_catalog_entry_and_host_parity_with_packages_coast(self):
        sources = {s["id"]: s for s in json.loads((ROOT / "catalog/sources.json").read_text())["sources"]}
        entry = sources["noaa-goes-nowcoast"]
        self.assertEqual(entry["allowed_hosts"], [gf.HOST])
        self.assertEqual(entry["rights"]["commercial_use"], "allowed")
        self.assertTrue(entry["rights"]["attribution_required"])
        hosts = (ROOT / "packages/coast/src/map-sources.ts").read_text()
        self.assertIn(f"'https://{gf.HOST}'", re.search(r"mapSourceHosts\s*=\s*\[([^\]]*)\]", hosts).group(1))
