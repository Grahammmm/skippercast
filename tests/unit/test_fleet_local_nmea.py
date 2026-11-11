"""skippercast.fleet.ais.sources.local_nmea: AIVDM from our own receiver (AISLIVE-03).

The committed fixture tests/fixtures/local_nmea/synthetic.nmea is built by the encoder
below (made-up MMSIs 999000001..999000009); a test checks the file still equals what
the encoder writes, so the expected values sit next to the encoder.
"""
import asyncio
from contextlib import aclosing
from datetime import date
import os
from tests._support import FIXTURES
import socket
import unittest
from unittest import mock

from skippercast.fleet.ais import match, process
from skippercast.fleet.ais.sources import SOURCES, get_source
from skippercast.fleet.ais.sources.base import AisPosition, AisSource, AisStatic, NotConfigured, Unsupported
from skippercast.fleet.ais.sources.local_nmea import (ENV_URL, Assembler, Fragment, LocalNmeaSource, MalformedMessage,
                                                      MalformedSentence, decode, normalise, parse_sentence)

FIXTURE = FIXTURES / "local_nmea" / "synthetic.nmea"
BBOX = ((32.0, -118.0), (33.5, -116.5))
# 2026-11-05 20:00:30.5 UTC
NOW = 1793908830.5
NOW_MS = 1793908830500
MINUTE = NOW_MS - NOW_MS % 60_000


# ---- a synthetic AIVDM encoder (test-only) ----
def u(value, length):
    return format(value & ((1 << length) - 1), f"0{length}b")


def text(value, length):
    out = ""
    for char in value.ljust(length, "@")[:length]:
        out += u(ord(char) - 64 if char >= "@" else ord(char), 6)
    return out


def armour(bits):
    fill = -len(bits) % 6
    bits += "0" * fill
    chars = []
    for at in range(0, len(bits), 6):
        value = int(bits[at:at + 6], 2) + 48
        chars.append(chr(value + 8 if value > 87 else value))
    return "".join(chars), fill


def sentence(payload, fill=0, count=1, index=1, seq="", channel="A", talker="AIVDM", bad=False):
    body = f"{talker},{count},{index},{seq},{channel},{payload},{fill}"
    check = 0
    for char in body:
        check ^= ord(char)
    return f"!{body}*{(check ^ 0xFF if bad else check):02X}"


def degrees(value, scale=600_000):
    return round(value * scale)


def position(kind, mmsi, lat=32.7, lon=-117.2, sog=55, cog=900, heading=91, second=30, nav=0):
    if kind in (1, 2, 3):
        return (u(kind, 6) + u(0, 2) + u(mmsi, 30) + u(nav, 4) + u(0, 8) + u(sog, 10) + u(0, 1)
                + u(degrees(lon), 28) + u(degrees(lat), 27) + u(cog, 12) + u(heading, 9) + u(second, 6) + u(0, 25))
    head = u(kind, 6) + u(0, 2) + u(mmsi, 30) + u(0, 8) + u(sog, 10) + u(0, 1)
    head += u(degrees(lon), 28) + u(degrees(lat), 27) + u(cog, 12) + u(heading, 9) + u(second, 6)
    return head + u(0, 168 - len(head) if kind == 18 else 4)


def type19(mmsi, name, ship_type, dims, **kw):
    bits = position(19, mmsi, **kw)[:143]
    bits += text(name, 20) + u(ship_type, 8) + u(dims[0], 9) + u(dims[1], 9) + u(dims[2], 6) + u(dims[3], 6)
    return bits + u(0, 312 - len(bits))


def type5(mmsi, imo, call_sign, name, ship_type, dims):
    bits = u(5, 6) + u(0, 2) + u(mmsi, 30) + u(0, 2) + u(imo, 30) + text(call_sign, 7) + text(name, 20)
    bits += u(ship_type, 8) + u(dims[0], 9) + u(dims[1], 9) + u(dims[2], 6) + u(dims[3], 6)
    return bits + u(0, 424 - len(bits))


def type24a(mmsi, name):
    return u(24, 6) + u(0, 2) + u(mmsi, 30) + u(0, 2) + text(name, 20) + u(0, 8)


def type24b(mmsi, ship_type, call_sign, dims):
    bits = u(24, 6) + u(0, 2) + u(mmsi, 30) + u(1, 2) + u(ship_type, 8) + text("VND", 3) + u(0, 24) + text(call_sign, 7)
    return bits + u(dims[0], 9) + u(dims[1], 9) + u(dims[2], 6) + u(dims[3], 6) + u(0, 6)


def single(bits, **kw):
    payload, fill = armour(bits)
    return sentence(payload, fill, **kw)


def two_fragments(bits, seq="3"):
    payload, fill = armour(bits)
    cut = len(payload) // 2
    return [sentence(payload[:cut], 0, count=2, index=1, seq=seq), sentence(payload[cut:], fill, count=2, index=2, seq=seq)]


def fixture_lines():
    lines = [single(position(1, 999000001)), single(position(2, 999000002, lat=32.8, sog=0, nav=1)),
             single(position(3, 999000003, lat=32.9, heading=511, cog=3600, sog=1023, nav=15))]
    lines += two_fragments(type5(999000004, 9999999, "WDX0001", "SEA EXAMPLE", 37, (10, 5, 3, 3)))
    lines += [single(position(18, 999000005, lat=33.0)),
              single(type19(999000006, "BETA EXAMPLE", 30, (6, 4, 2, 2), lat=33.1)),
              single(type24a(999000007, "GAMMA EXAMPLE")),
              single(type24b(999000008, 30, "WDX0008", (7, 3, 2, 2))),
              single(position(1, 999000009), talker="AIVDO"),
              single(position(1, 999000001), bad=True),
              sentence("0", 0, count=2, index=2, seq="5")]
    return lines


FIXTURE_TEXT = "\n".join(fixture_lines()) + "\n"


def collect(source, bbox=BBOX, mmsis=None):
    async def run():
        return [record async for record in source.stream(bbox, mmsis)]
    return asyncio.run(asyncio.wait_for(run(), 15))


def tcp_source(payload: bytes, **kw):
    """A source whose TCP peer sends ``payload`` and closes (a real localhost socket on port 0)."""
    async def run(source, bbox, mmsis):
        async def handler(reader, writer):
            writer.write(payload)
            await writer.drain()
            writer.close()
        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        source._url = f"tcp://127.0.0.1:{port}"
        try:
            return [record async for record in source.stream(bbox, mmsis)]
        finally:
            server.close()
            await server.wait_closed()
    return run


def make(**kw):
    kw.setdefault("clock", lambda: NOW)
    kw.setdefault("url", "tcp://127.0.0.1:1")
    return LocalNmeaSource(**kw)


def feed(source, lines, bbox=BBOX, mmsis=None):
    assembler = Assembler()
    out = []
    for line in lines:
        out += source._line(line, assembler, bbox, mmsis)
    return out


class FixtureTest(unittest.TestCase):
    def test_committed_fixture_is_the_encoder_output_and_synthetic(self):
        self.assertEqual(FIXTURE.read_text(), FIXTURE_TEXT)
        records = feed(make(), FIXTURE_TEXT.splitlines())
        for mmsi in {r.mmsi for r in records}:
            self.assertTrue(999000001 <= mmsi <= 999000009, mmsi)

    def test_every_type_decodes_to_the_expected_fields(self):
        source, errors = make(), []
        source.on_malformed = errors.append
        records = feed(source, FIXTURE_TEXT.splitlines())
        self.assertEqual(len(errors), 1)    # the bad checksum; the lone second fragment is dropped silently
        by = {(type(r).__name__, r.mmsi, getattr(r, "msg_type", None)): r for r in records}
        self.assertEqual(len(records), 9)
        self.assertEqual(by[("AisPosition", 999000001, "PositionReport")], AisPosition(
            999000001, MINUTE + 30_000, 32.7, -117.2, 5.5, 90.0, 91, 0, "PositionReport", "local-nmea", NOW_MS))
        two = by[("AisPosition", 999000002, "PositionReport")]
        self.assertEqual((two.sog, two.nav_status, two.lat), (0.0, 1, 32.8))
        three = by[("AisPosition", 999000003, "PositionReport")]
        self.assertEqual((three.sog, three.cog, three.heading, three.nav_status), (None, None, None, None))
        self.assertEqual(by[("AisStatic", 999000004, None)], AisStatic(
            999000004, NOW_MS, "SEA EXAMPLE", "WDX0001", 9999999, 37, 10, 5, 3, 3, "A", "local-nmea"))
        b = by[("AisPosition", 999000005, "StandardClassBPositionReport")]
        self.assertEqual((b.lat, b.lon, b.sog, b.nav_status, b.source), (33.0, -117.2, 5.5, None, "local-nmea"))
        self.assertEqual(by[("AisPosition", 999000006, "ExtendedClassBPositionReport")].lat, 33.1)
        self.assertEqual(by[("AisStatic", 999000006, None)], AisStatic(
            999000006, NOW_MS, "BETA EXAMPLE", None, None, 30, 6, 4, 2, 2, "B", "local-nmea"))
        self.assertEqual(by[("AisStatic", 999000007, None)], AisStatic(
            999000007, NOW_MS, "GAMMA EXAMPLE", None, None, None, None, None, None, None, "B", "local-nmea"))
        self.assertEqual(by[("AisStatic", 999000008, None)], AisStatic(
            999000008, NOW_MS, None, "WDX0008", None, 30, 7, 3, 2, 2, "B", "local-nmea"))
        self.assertEqual(source.counts["own_ship_dropped"], 1)
        self.assertNotIn(999000009, {r.mmsi for r in records})


class SentenceTest(unittest.TestCase):
    def test_parse_and_checksum(self):
        line = single(position(1, 999000001))
        fragment = parse_sentence(line)
        self.assertEqual((fragment.own, fragment.count, fragment.index, fragment.channel), (False, 1, 1, "A"))
        self.assertTrue(parse_sentence(single(position(1, 999000001), talker="AIVDO")).own)
        self.assertIsNone(parse_sentence("$GPGGA,1,2,3*00"))
        self.assertIsNone(parse_sentence(""))
        for bad in (single(position(1, 999000001), bad=True), line.split("*")[0], line[:-1], line + "0" * 80,
                    sentence("15M", 0, count=1, index=2)):
            with self.subTest(bad=bad[:30]), self.assertRaises(MalformedSentence):
                parse_sentence(bad)

    def test_bad_checksum_reports_and_yields_nothing(self):
        errors = []
        records = feed(make(on_malformed=errors.append), [single(position(1, 999000001), bad=True)])
        self.assertEqual((records, len(errors)), ([], 1))
        self.assertIsInstance(errors[0], MalformedSentence)

    def test_aivdo_is_dropped_and_counted(self):
        source = make()
        self.assertEqual(feed(source, [single(position(1, 999000009), talker="AIVDO")]), [])
        self.assertEqual(source.counts["own_ship_dropped"], 1)

    def test_prefix_lookalikes_are_ignored(self):
        good = single(position(1, 999000001))
        self.assertEqual(len(feed(make(), [good])), 1)
        errors = []
        source = make(on_malformed=errors.append)
        for talker in ("AIVDMX", "AIVDMjunk", "AIVDOX", "aivdm", "AIVD"):
            for bad in (False, True):
                line = single(position(1, 999000001), talker=talker, bad=bad)
                with self.subTest(talker=talker, bad=bad):
                    self.assertIsNone(parse_sentence(line))
                    self.assertEqual(feed(source, [line]), [])
        self.assertIsNone(parse_sentence(single(position(1, 999000001), talker="AIVDMX") + "0" * 80))
        self.assertEqual((errors, source.counts.get("own_ship_dropped", 0)), ([], 0))
        with self.assertRaises(MalformedSentence):
            parse_sentence("!AIVDM*00")

    def test_lookalike_fragments_cannot_touch_an_active_group(self):
        first, last = two_fragments(type5(999000003, 1234567, "CALL", "SYNTH ONE", 30, (10, 5, 3, 2)))
        fake_first = first.replace("AIVDM", "AIVDMX", 1)
        fake_last = last.replace("AIVDM", "AIVDMX", 1)
        # recompute checksums for the mutated sentences
        def fix(line):
            body = line[1:].partition("*")[0]
            check = 0
            for char in body:
                check ^= ord(char)
            return f"!{body}*{check:02X}"
        fake_first, fake_last = fix(fake_first), fix(fake_last)
        source = make()
        assembler = Assembler()
        out = []
        for line in (fake_first, first, fake_first, fake_last, last):
            out += source._line(line, assembler, BBOX, None)
        self.assertEqual(len(out), 1)
        self.assertEqual(assembler.dropped, 0)
        self.assertEqual(feed(make(), [fake_first, fake_last]), [])

    def test_payload_outside_the_armour_is_malformed(self):
        errors = []
        self.assertEqual(feed(make(on_malformed=errors.append), [sentence("15M^^^", 0)]), [])
        self.assertEqual(len(errors), 1)
        with self.assertRaises(MalformedMessage):
            decode("15M", 0)    # too short


class AssemblerTest(unittest.TestCase):
    def setUp(self):
        self.a, self.b = (parse_sentence(s) for s in two_fragments(type5(999000004, 1, "WDX0001", "SEA EXAMPLE", 37, (1, 1, 1, 1))))

    def test_two_fragments_assemble(self):
        assembler = Assembler()
        self.assertIsNone(assembler.add(self.a, 0))
        payload, fill = assembler.add(self.b, 1000)
        self.assertEqual(decode(payload, fill)["name"], "SEA EXAMPLE")

    def test_out_of_order_missing_and_mixed_sequence_are_dropped(self):
        assembler = Assembler()
        self.assertIsNone(assembler.add(self.b, 0))                     # second first
        self.assertIsNone(assembler.add(self.a, 100))
        other = Fragment(self.b.own, 2, 2, "4", "A", self.b.payload, self.b.fill)
        self.assertIsNone(assembler.add(other, 200))                    # another sequence id
        self.assertEqual(assembler.dropped, 2)
        late = Assembler()
        late.add(self.a, 0)
        self.assertIsNone(late.add(self.b, 10_001))                     # timed out by the injected clock
        self.assertEqual(late.dropped, 2)                               # the expired group, then the orphan
        self.assertIsNone(Assembler().add(Fragment(False, 3, 2, "1", "A", "0", 0), 0))

    def test_other_channel_is_another_group(self):
        assembler = Assembler()
        assembler.add(self.a, 0)
        self.assertIsNone(assembler.add(Fragment(False, 2, 2, "3", "B", self.b.payload, self.b.fill), 1))


class NormaliseTest(unittest.TestCase):
    def test_unavailable_position_is_reported(self):
        for lat, lon in ((91.0, -117.2), (32.7, 181.0)):
            errors = []
            decoded = decode(*armour(position(1, 999000001, lat=lat, lon=lon)))
            self.assertEqual(normalise(decoded, NOW_MS, errors.append), [])
            self.assertEqual(len(errors), 1)

    def test_type19_without_a_position_keeps_its_static(self):
        errors = []
        records = normalise(decode(*armour(type19(999000006, "BETA EXAMPLE", 30, (6, 4, 2, 2), lat=91.0))), NOW_MS, errors.append)
        self.assertEqual([type(r) for r in records], [AisStatic])
        self.assertEqual(len(errors), 1)

    def test_invalid_mmsi_is_reported(self):
        errors = []
        self.assertEqual(normalise(decode(*armour(position(1, 0))), NOW_MS, errors.append), [])
        self.assertEqual(len(errors), 1)

    def test_not_available_speed_course_heading(self):
        fix = normalise(decode(*armour(position(1, 999000001, sog=1023, cog=3600, heading=511, nav=15))), NOW_MS)[0]
        self.assertEqual((fix.sog, fix.cog, fix.heading, fix.nav_status), (None, None, None, None))

    def test_second_60_is_the_receipt_time_and_a_future_second_moves_back_a_minute(self):
        def ts(second):
            return normalise(decode(*armour(position(1, 999000001, second=second))), NOW_MS)[0].ts
        self.assertEqual(ts(60), NOW_MS)
        self.assertEqual(ts(63), NOW_MS)
        self.assertEqual(ts(30), MINUTE + 30_000)
        self.assertEqual(ts(45), MINUTE - 15_000)

    def test_unhandled_type_gives_nothing(self):
        self.assertEqual(normalise({"type": 4}, NOW_MS), [])
        self.assertEqual(feed(make(), [single(u(4, 6) + u(0, 162))]), [])


class FilterTest(unittest.TestCase):
    LINES = [single(position(1, 999000001)), single(position(1, 999000002, lat=40.0)),
             single(type24a(999000003, "GAMMA EXAMPLE"))]

    def test_outside_bbox_dropped(self):
        source = make()
        self.assertEqual({r.mmsi for r in feed(source, self.LINES)}, {999000001, 999000003})
        self.assertEqual(source.counts["outside_bbox"], 1)

    def test_mmsi_filter(self):
        self.assertEqual({r.mmsi for r in feed(make(), self.LINES, mmsis={999000003})}, {999000003})

    def test_message_type_filter(self):
        source = make(message_types=["PositionReport"])
        self.assertEqual({r.mmsi for r in feed(source, self.LINES)}, {999000001})
        self.assertEqual(source.counts["filtered"], 1)
        with self.assertRaises(ValueError):
            make(message_types=["Nope"])


class StreamTest(unittest.TestCase):
    def test_tcp_stream_yields_the_fixture_then_ends_when_the_peer_closes(self):
        source = make()
        records = asyncio.run(asyncio.wait_for(tcp_source(FIXTURE.read_bytes())(source, BBOX, None), 15))
        self.assertEqual(len(records), 9)
        self.assertEqual({r.source for r in records}, {"local-nmea"})
        self.assertEqual(source.counts["own_ship_dropped"], 1)

    def test_tcp_overlong_line_is_malformed_and_the_stream_goes_on(self):
        errors = []
        source = make(on_malformed=errors.append)
        payload = b"!AIVDM," + b"1" * 100_000 + b"\r\n" + FIXTURE.read_bytes()
        records = asyncio.run(asyncio.wait_for(tcp_source(payload)(source, BBOX, None), 15))
        self.assertEqual(len(records), 9)
        self.assertTrue(errors)

    def test_udp_stream_over_localhost(self):
        async def run():
            source = make(url="udp://127.0.0.1:0")
            got = []

            async def reader():
                async with aclosing(source.stream(BBOX, None)) as stream:
                    async for record in stream:
                        got.append(record)
                        if len(got) == 9:
                            return
            task = asyncio.create_task(reader())
            await asyncio.wait_for(source.ready.wait(), 5)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                for line in FIXTURE_TEXT.splitlines():
                    sender.sendto((line + "\r\n").encode(), source.local_address)
            await asyncio.wait_for(task, 10)
            return got
        records = asyncio.run(run())
        self.assertEqual({r.mmsi for r in records}, set(range(999000001, 999000009)))

    def test_not_configured(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ENV_URL, None)
            with self.assertRaises(NotConfigured):
                collect(LocalNmeaSource())
        for url in ("http://127.0.0.1:1", "ws://127.0.0.1:1", "tcp://127.0.0.1", "udp://:5000", "tcp://127.0.0.1:x"):
            with self.subTest(url=url), self.assertRaises(NotConfigured):
                collect(LocalNmeaSource(url=url))

    def test_url_from_the_environment(self):
        with mock.patch.dict(os.environ, {ENV_URL: "udp://0.0.0.0:10110"}):
            self.assertEqual(LocalNmeaSource().endpoint(), ("udp", "0.0.0.0", 10110))

    def test_history_is_unsupported(self):
        with self.assertRaises(Unsupported):
            make().history(date(2026, 11, 5), BBOX, None)


class RegistrationTest(unittest.TestCase):
    def test_registered_with_internal_only_rights(self):
        self.assertIn("local-nmea", SOURCES)
        source = get_source("local-nmea", url="udp://127.0.0.1:0")
        self.assertIsInstance(source, AisSource)
        self.assertTrue(source.realtime)
        self.assertEqual(process.SOURCE_RIGHTS["local-nmea"], "internal-only")
        self.assertTrue(match.SOURCE_URLS["local-nmea"].startswith("https://github.com/Grahammmm/skippercast/"))


if __name__ == "__main__":
    unittest.main()
