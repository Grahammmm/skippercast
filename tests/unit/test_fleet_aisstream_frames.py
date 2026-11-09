"""Offline malformed-envelope continuity and error-accounting regressions."""
import asyncio
from datetime import datetime, timezone
import json
import traceback

import pytest

from skippercast.fleet.ais.sources.aisstream import (
    MESSAGE_TYPES, AisstreamError, AisstreamSource, MalformedMessage,
    normalise, parse_time_utc,
)
from skippercast.fleet.ais.sources.base import AisPosition, AisStatic

BBOX = ((34, -122), (36, -119))
TIME = "2026-02-28T12:00:00Z"
RECEIVED = int(datetime(2026, 2, 28, 12, tzinfo=timezone.utc).timestamp() * 1000)
SHAPES = [None, [], [1], "", "bad", 0, 1, False, True]


def envelope(kind="PositionReport"):
    return {"MessageType": kind, "MetaData": {"time_utc": TIME}, "Message": {
        kind: {"UserID": 999000101, "Latitude": 35, "Longitude": -120,
               "Name": "SYNTHETIC VESSEL"}}}


@pytest.mark.parametrize("kind", MESSAGE_TYPES)
@pytest.mark.parametrize("shape", SHAPES)
def test_message_container_shapes_are_named_malformed(kind, shape):
    for message in (shape, {kind: shape}, {}):
        raw = envelope(kind)
        raw["Message"] = message
        with pytest.raises(MalformedMessage) as caught:
            normalise(raw)
        assert str(caught.value) == f"{kind}: missing Message.{kind} or MetaData"
    raw.pop("Message")
    with pytest.raises(MalformedMessage):
        normalise(raw)
    raw["MessageType"] = "SubscriptionConfirmation"
    raw["Message"] = shape
    assert normalise(raw) == []


@pytest.mark.parametrize("raw", [b"\xffSYNTHETIC-SENSITIVE", bytearray(b"\xffSYNTHETIC-SENSITIVE")])
def test_invalid_utf8_is_named_malformed(raw):
    with pytest.raises(MalformedMessage) as caught:
        normalise(raw)
    assert str(caught.value) == "not UTF-8"
    diagnostic = "".join(traceback.format_exception(caught.value))
    assert "SYNTHETIC-SENSITIVE" not in diagnostic
    assert "UnicodeDecodeError" not in diagnostic
    text = json.dumps(envelope())
    assert normalise(text) == normalise(text.encode()) == normalise(bytearray(text.encode()))


@pytest.mark.parametrize("text", ["2026-02-30T12:00:00Z", "2025-02-29T12:00:00Z",
                                  "2026-13-01T12:00:00Z", "2026-02-28T24:00:00Z"])
def test_impossible_calendar_timestamp_is_named_malformed(text):
    with pytest.raises(MalformedMessage, match="^MetaData.time_utc is not a timestamp$"):
        parse_time_utc(text)


@pytest.mark.parametrize("text", ["2024-02-29T12:00:00.123456789Z",
                                  "2024-02-29 13:30:00.123456789 +0130 UTC",
                                  "2024-02-29T10:30:00.123456789-01:30"])
def test_valid_timestamp_syntax_fraction_and_offset_unchanged(text):
    expected = int(datetime(2024, 2, 29, 12, tzinfo=timezone.utc).timestamp()) * 1000 + 123
    assert parse_time_utc(text) == expected


def test_missing_time_uses_receipt_or_clock():
    raw = envelope()
    raw["MetaData"] = {}
    assert normalise(raw, received_at=RECEIVED)[0].received_at == RECEIVED
    assert normalise(raw, clock=lambda: datetime(2026, 2, 28, 12, tzinfo=timezone.utc))[0].received_at == RECEIVED


def bad_frames():
    calendar = envelope()
    calendar["MetaData"]["time_utc"] = "2026-02-30T12:00:00Z"
    return [dict(envelope(), Message=[1]), dict(envelope(), Message="bad"),
            b"\xff", bytearray(b"\xff"), calendar, "not json"]


class EndOfFrames(Exception):
    pass


class Socket:
    def __init__(self, frames, send_error=None):
        self.frames = iter(frames)
        self.send_error = send_error
        self.sent = []
        self.closed = 0

    async def send(self, text):
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(json.loads(text))

    async def recv(self):
        frame = next(self.frames, EndOfFrames())
        if isinstance(frame, BaseException):
            raise frame
        return frame

    async def close(self):
        self.closed += 1


def source_for(socket, callback=None):
    connects = []

    async def connect(url):
        connects.append(url)
        return socket

    return AisstreamSource("synthetic-key", connect=connect, on_malformed=callback), connects


@pytest.mark.parametrize("bad", bad_frames())
@pytest.mark.parametrize("callback_enabled", [False, True])
def test_bad_frame_then_valid_record_stays_on_one_connection(bad, callback_enabled):
    async def run():
        errors = []
        socket = Socket([bad, envelope(), envelope("ShipStaticData")])
        source, connects = source_for(socket, errors.append if callback_enabled else None)
        stream = source.stream(BBOX)
        assert await anext(stream) == AisPosition(
            mmsi=999000101, ts=RECEIVED, lat=35.0, lon=-120.0, sog=None,
            cog=None, heading=None, nav_status=None, msg_type="PositionReport",
            source="aisstream", received_at=RECEIVED)
        assert await anext(stream) == AisStatic(
            mmsi=999000101, ts=RECEIVED, name="SYNTHETIC VESSEL", call_sign=None,
            imo=None, ship_type=None, dim_bow=None, dim_stern=None, dim_port=None,
            dim_starboard=None, ais_class="A", source="aisstream")
        assert len(connects) == len(socket.sent) == 1
        assert socket.closed == 0
        assert len(errors) == int(callback_enabled)
        assert all(type(error) is MalformedMessage for error in errors)
        with pytest.raises(EndOfFrames):
            await anext(stream)
        assert socket.closed == 1
    asyncio.run(run())


def test_each_bad_frame_is_counted_once_and_explicit_close_cleans_up():
    async def run():
        errors = []
        frames = bad_frames()
        socket = Socket([*frames, envelope()])
        source, connects = source_for(socket, errors.append)
        stream = source.stream(BBOX)
        assert isinstance(await anext(stream), AisPosition)
        assert len(errors) == len(frames)
        assert all(type(error) is MalformedMessage for error in errors)
        assert len(connects) == 1
        await stream.aclose()
        assert socket.closed == 1
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["provider", "recv", "send", "cancelled", "callback"])
def test_provider_transport_and_cancellation_are_not_swallowed(failure):
    async def run():
        errors = []
        expected = {"provider": AisstreamError, "recv": OSError, "send": OSError,
                    "cancelled": asyncio.CancelledError, "callback": RuntimeError}[failure]
        terminal = expected("synthetic failure")
        frames = [{"error": "synthetic provider failure"}] if failure == "provider" else [terminal]
        if failure == "callback":
            frames = ["not json"]

        def callback(error):
            errors.append(error)
            if failure == "callback":
                raise terminal

        socket = Socket(frames, send_error=terminal if failure == "send" else None)
        source, connects = source_for(socket, callback)
        with pytest.raises(expected) as caught:
            await anext(source.stream(BBOX))
        if failure != "provider":
            assert caught.value is terminal
        assert socket.closed == len(connects) == 1
        assert len(errors) == int(failure == "callback")
    asyncio.run(run())
