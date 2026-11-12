"""Offline regressions: impossible numeric timezone offsets in MetaData.time_utc are refused."""
import asyncio
from datetime import datetime, timedelta, timezone
import json

import pytest

from skippercast.fleet.ais.sources.aisstream import (
    MESSAGE_TYPES, AisstreamSource, MalformedMessage, normalise, parse_time_utc,
)
from skippercast.fleet.ais.sources.base import AisPosition

BBOX = ((34, -122), (36, -119))
BASE = "2026-02-28T12:00:00"
RECEIVED = int(datetime(2026, 2, 28, 12, tzinfo=timezone.utc).timestamp() * 1000)
BAD = ["+24:00", "-24:00", "+99:00", "-99:99", "+00:60", "-00:60", "+0060", "-2400", "+12:99"]


def envelope(kind="PositionReport", time_utc=BASE + "Z"):
    return {"MessageType": kind, "MetaData": {"time_utc": time_utc}, "Message": {
        kind: {"UserID": 999000101, "Latitude": 35, "Longitude": -120,
               "Name": "SYNTHETIC VESSEL"}}}


@pytest.mark.parametrize("offset", BAD)
@pytest.mark.parametrize("suffix", ["", " UTC"])
def test_offset_component_ranges_refuse(offset, suffix):
    text = BASE + offset + suffix
    with pytest.raises(MalformedMessage) as err:
        parse_time_utc(text)
    assert str(err.value) == "MetaData.time_utc is not a timestamp"
    assert offset not in str(err.value)


@pytest.mark.parametrize("hours,minutes", [(23, 59), (0, 0), (7, 0), (1, 30)])
@pytest.mark.parametrize("sign", [1, -1])
def test_valid_extreme_and_zero_offsets_preserved(sign, hours, minutes):
    delta = timedelta(hours=hours, minutes=minutes)
    expected = int((datetime(2026, 2, 28, 12, tzinfo=timezone.utc) - sign * delta).timestamp() * 1000)
    mark = "+" if sign > 0 else "-"
    colon = f"{mark}{hours:02d}:{minutes:02d}"
    compact = f"{mark}{hours:02d}{minutes:02d}"
    assert parse_time_utc(BASE + colon) == expected
    assert parse_time_utc(BASE + compact) == expected
    assert parse_time_utc(BASE + " " + compact + " UTC") == expected


def test_fraction_calendar_and_fallback_unchanged():
    assert parse_time_utc("2026-02-28 12:00:00.123456789 +0000 UTC") == RECEIVED + 123
    assert parse_time_utc(BASE + "Z") == RECEIVED
    assert parse_time_utc(BASE) == RECEIVED
    with pytest.raises(MalformedMessage):
        parse_time_utc("2026-02-30T12:00:00Z")
    raw = envelope()
    del raw["MetaData"]["time_utc"]
    assert normalise(raw, received_at=RECEIVED + 7)[0].received_at == RECEIVED + 7
    # an explicit malformed offset never falls back to the supplied receipt time
    with pytest.raises(MalformedMessage):
        normalise(envelope(time_utc=BASE + "+00:60"), received_at=RECEIVED)


@pytest.mark.parametrize("kind", MESSAGE_TYPES)
@pytest.mark.parametrize("form", ["dict", "text", "bytes"])
def test_normalizer_never_emits_bad_receipt(kind, form):
    def wrap(data):
        return {"dict": data, "text": json.dumps(data), "bytes": json.dumps(data).encode()}[form]
    with pytest.raises(MalformedMessage):
        normalise(wrap(envelope(kind, BASE + "+24:00")), received_at=RECEIVED)
    control = envelope(kind, BASE + "+01:30")
    snapshot = json.loads(json.dumps(control))
    assert normalise(wrap(control), received_at=RECEIVED)
    assert control == snapshot


class EndOfFrames(Exception):
    pass


class Socket:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.sent = []
        self.closed = 0

    async def send(self, text):
        self.sent.append(json.loads(text))

    async def recv(self):
        frame = next(self.frames, EndOfFrames())
        if isinstance(frame, BaseException):
            raise frame
        return frame

    async def close(self):
        self.closed += 1


@pytest.mark.parametrize("callback_enabled", [False, True])
def test_bad_offset_skipped_before_following_valid_record(callback_enabled):
    async def run():
        errors = []
        connects = []
        socket = Socket([envelope(time_utc=BASE + "-99:99"), envelope()])

        async def connect(url):
            connects.append(url)
            return socket

        source = AisstreamSource("synthetic-key", connect=connect,
                                 on_malformed=errors.append if callback_enabled else None)
        stream = source.stream(BBOX)
        record = await anext(stream)
        assert isinstance(record, AisPosition) and record.received_at == RECEIVED
        assert len(connects) == len(socket.sent) == 1
        assert len(errors) == int(callback_enabled)
        assert all(type(error) is MalformedMessage for error in errors)
        await stream.aclose()
        assert socket.closed == 1
    asyncio.run(run())


def test_unknown_types_ignored_without_timestamp_parsing():
    raw = {"MessageType": "SubscriptionConfirmation", "MetaData": {"time_utc": BASE + "+99:99"}}
    assert normalise(raw, received_at=RECEIVED) == []
