"""F21-13 / SCA-609 / SCA-460: AIS receipts must preserve source, field, value and time.

Run ``python -m tests.unit.test_f21_13_audit`` for the offline replay.
Exit 1 reports a provenance gap.

The replay uses the production writers: ``AisStore`` for the raw static messages
and ``MatchState.add`` for the one-row-per-MMSI ``match_statics`` snapshot, which
keeps older non-empty fields while taking the newest message's source and time.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from skippercast.fleet.ais import process
from skippercast.fleet.ais.match import MatchState
from skippercast.fleet.ais.sources.base import AisStatic
from skippercast.fleet.ais.store import AisStore
from tests.unit.test_fleet_schedule_evidence import observation, se


MMSI = 999000609
START = datetime(2026, 11, 1, tzinfo=timezone.utc)
SPLIT = START + timedelta(hours=1)
NOW = START + timedelta(hours=3)
REGION = SimpleNamespace(id="CA", timezone="America/Los_Angeles")
NAME = observation()["boat_name"]
T_A, T_B = "2026-11-01T00:00:00Z", "2026-11-01T01:00:00Z"


def message(when, source, call_sign):
    return AisStatic(MMSI, int(when.timestamp() * 1000), NAME, call_sign, None, None, None, None, None, None,
                     "A", source)


# Two distinct static messages from two sources, each with its own call sign.
TWO_CALL_SIGNS = ((message(START, "fixture-a", "FIXTUREA"), message(SPLIT, "fixture-b", "FIXTUREB")),
                  (("fixture-a", "call_sign", "FIXTUREA", T_A), ("fixture-b", "call_sign", "FIXTUREB", T_B)))
# Source A reports a call sign; source B later reports the name without one. The
# merged snapshot then holds A's call sign under B's source and time.
LATER_SOURCE_WITHOUT_CALL_SIGN = ((message(START, "fixture-a", "FIXTUREA"), message(SPLIT, "fixture-b", None)),
                                  (("fixture-a", "call_sign", "FIXTUREA", T_A),))


def replay(root, messages):
    fleet = root / "fleet"
    ais = fleet / REGION.id / "ais"
    AisStore(ais).write(statics=messages)
    state = process.State(ais / "state.sqlite")
    try:
        MatchState(state).add(messages, (), (), ZoneInfo(REGION.timezone))
    finally:
        state.close()
    before = {path: path.read_bytes() for path in ais.rglob("*.sqlite")}
    trip = observation()
    # The real writer runs against the production schema in memory, never a fleet database.
    with closing(sqlite3.connect(":memory:")) as evidence:
        evidence.row_factory = sqlite3.Row
        evidence.executescript(se.SCHEMA)
        se.record_observation(evidence, trip)
        assert se.assess_ais(evidence, ais / "state.sqlite", fleet, REGION, NOW) == (1, 1)
        actual = tuple(tuple(row) for row in evidence.execute("""
            SELECT source_id, field_name, field_value, observed_at_utc
            FROM identity_evidence WHERE field_name = 'call_sign'
            ORDER BY source_id, field_name, field_value, observed_at_utc
        """))
    assert {path: path.read_bytes() for path in ais.rglob("*.sqlite")} == before, "static input changed during replay"
    return actual


def test_two_sources_keep_each_call_sign_with_its_source_and_time(tmp_path):
    # Contract: each call sign is stored with the source and time of the message that carried it.
    # Bug caught: an MMSI-level cross-product stores four claims at the first time instead of two.
    messages, expected = TWO_CALL_SIGNS
    assert replay(tmp_path, messages) == expected


def test_call_sign_retained_by_the_snapshot_is_not_credited_to_a_later_source(tmp_path):
    # Contract: a field is never paired with a source or time of a message that did not carry it.
    # Bug caught: reading match_statics credits A's call sign to B at B's time.
    messages, expected = LATER_SOURCE_WITHOUT_CALL_SIGN
    assert replay(tmp_path, messages) == expected


def report(label, actual, expected):
    ok = actual == expected
    unexpected_pairs = {row[:3] for row in actual} - {row[:3] for row in expected}
    times = {row[3] for row in actual}
    print(f"{label}: {'PASS' if ok else 'GAP'}; expected {len(expected)} receipts, "
          f"observed receipts={len(actual)}, distinct observation times={len(times)}; "
          f"unobserved source/field/value combinations={len(unexpected_pairs)}")
    return ok


def baseline(root):
    ok = True
    for label, (messages, expected) in (("two call signs", TWO_CALL_SIGNS),
                                        ("call sign retained by snapshot", LATER_SOURCE_WITHOUT_CALL_SIGN)):
        scratch = root / label.replace(" ", "-")
        scratch.mkdir()
        ok = report(label, replay(scratch, messages), expected) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    with TemporaryDirectory(prefix="f21-13-") as directory:
        raise SystemExit(baseline(Path(directory)))
