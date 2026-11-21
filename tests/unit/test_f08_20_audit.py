"""F08-20: AISStream's seconds field cannot prove actual latency."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from skippercast.fleet.ais.segment import is_suspect
from skippercast.fleet.ais.sources.aisstream import normalise
from skippercast.fleet.ais.sources.base import AisPosition


def test_whole_minute_delay_is_indistinguishable_from_on_time():
    receipt = datetime(2026, 1, 1, 12, 1, 17, tzinfo=timezone.utc)
    on_time = receipt
    delayed = receipt - timedelta(minutes=1)

    def decode(actual_fix):
        # Only the second is transmitted. The synthetic fix minute is not on the wire.
        return normalise({
            "MessageType": "PositionReport",
            "MetaData": {"time_utc": receipt.isoformat()},
            "Message": {"PositionReport": {
                "UserID": 999000001, "Latitude": 0, "Longitude": 0,
                "Timestamp": actual_fix.second,
            }},
        })

    [on_time_position] = decode(on_time)
    [delayed_position] = decode(delayed)
    assert isinstance(delayed_position, AisPosition)
    assert delayed_position == on_time_position
    assert delayed_position.ts == delayed_position.received_at == int(receipt.timestamp() * 1000)
    assert not is_suspect(delayed_position)

    # With the synthetic ground truth supplied independently, the same gap is detectable.
    independently_dated = replace(delayed_position, ts=int(delayed.timestamp() * 1000))
    assert is_suspect(independently_dated)
