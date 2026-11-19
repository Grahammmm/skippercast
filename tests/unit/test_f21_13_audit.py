"""F21-13 / SCA-609: AIS receipts must preserve source, field, value and time.

Run ``python -m tests.unit.test_f21_13_audit`` for the offline baseline.
Exit 1 reports a gap, not desired behavior. The affected joint-window case
is not a required test until the production repair (SCA-460).
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from tests.unit.test_fleet_schedule_evidence import observation, se


START = datetime(2026, 11, 1, tzinfo=timezone.utc)
SPLIT = START + timedelta(hours=1)
END = START + timedelta(hours=2)
# Two distinct static messages for one fictional MMSI. Expected observations
# are independent of the reader/writer under test.
EXPECTED = (
    ("fixture-a", "call_sign", "FIXTUREA", "2026-11-01T00:00:00Z"),
    ("fixture-b", "call_sign", "FIXTUREB", "2026-11-01T01:00:00Z"),
)


def replay(root, windows):
    state = root / "statics.sqlite"
    trip = observation()
    with closing(sqlite3.connect(state)) as conn, conn:
        conn.execute("CREATE TABLE match_statics (mmsi, ts, source, name, call_sign, ship_type, ais_class)")
        conn.executemany("INSERT INTO match_statics VALUES (?, ?, ?, ?, ?, NULL, 'A')", (
            (999000609, int(START.timestamp() * 1000), "fixture-a", trip["boat_name"], "FIXTUREA"),
            (999000609, int(SPLIT.timestamp() * 1000), "fixture-b", trip["boat_name"], "FIXTUREB"),
        ))
    before = state.read_bytes()
    # Read the scratch input through the real read-only reader; the real writer
    # runs against the production schema in memory, never a fleet database.
    with closing(sqlite3.connect(":memory:")) as evidence:
        evidence.executescript(se.SCHEMA)
        se.record_observation(evidence, trip)
        for start, end in windows:
            candidates, status = se.read_static_candidates(state, trip["boat_name"], start, end)
            assert status == "ais-match-statics"
            candidate, = candidates
            se.store_ais_identity_evidence(evidence, trip["trip_id"], 1, candidate, "2026-11-01T03:00:00Z")
        actual = tuple(evidence.execute("""
            SELECT source_id, field_name, field_value, observed_at_utc
            FROM identity_evidence WHERE field_name = 'call_sign'
            ORDER BY source_id, field_name, field_value, observed_at_utc
        """))
    assert state.read_bytes() == before, "static input changed during replay"
    return actual


def test_separate_windows_keep_each_call_sign_with_its_source_and_time(tmp_path):
    # The same two rows in disjoint windows are a valid control: even this
    # case would fail if retrieval time were used instead of observation time.
    assert replay(tmp_path, ((START, SPLIT), (SPLIT, END))) == EXPECTED


def report(label, actual):
    ok = actual == EXPECTED
    unexpected_pairs = {row[:3] for row in actual} - {row[:3] for row in EXPECTED}
    times = {row[3] for row in actual}
    print(f"{label}: {'PASS' if ok else 'GAP'}; expected 2 receipts at 2 times, "
          f"observed receipts={len(actual)}, distinct observation times={len(times)}; "
          f"unobserved source/field/value combinations={len(unexpected_pairs)}")
    return ok


def baseline(root):
    separate = root / "separate"
    joint = root / "joint"
    separate.mkdir()
    joint.mkdir()
    valid = report("separate windows", replay(separate, ((START, SPLIT), (SPLIT, END))))
    if not valid:
        return 2
    return 0 if report("joint window", replay(joint, ((START, END),))) else 1


if __name__ == "__main__":
    with TemporaryDirectory(prefix="f21-13-") as directory:
        raise SystemExit(baseline(Path(directory)))
