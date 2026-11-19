"""F07-06 / SCA-604: a scoped replay is not a replacement of the whole UTC day.

Normal pytest checks the valid reference. For the opt-in baseline receipt run:
    python -B -m tests.unit.test_f07_06_audit
Exit 1 means a contract gap. All writes are to disposable synthetic caches.
"""
from contextlib import closing
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from skippercast.fleet.ais import backfill, process
from skippercast.fleet.ais.sources.base import AisPosition, AisStatic
from skippercast.fleet.ais.store import retention_limits


DAY = date(2000, 1, 1)
START, END = backfill.window_ms(DAY, DAY, "UTC")
DAY_MS = END - START
REGION = SimpleNamespace(
    id="ZZ", timezone="UTC", ais=SimpleNamespace(south=-1, west=-1, north=1, east=1),
    thresholds={"retention": {"raw_days": 1, "static_days": 2, "discovery_days": 1}},
)
BBOX = ((-1, -1), (1, 1))
A, B = 999000001, 999000002


def _records(mmsi, label, speed):
    ts = START + 1_000
    return (
        AisPosition(mmsi, ts, 0, 0, speed, None, None, None, "csv", "marinecadastre", ts),
        AisStatic(mmsi, ts, label, None, None, None, None, None, None, None, "A", "marinecadastre"),
    )


INITIAL = {A: _records(A, "A-old", 1), B: _records(B, "B-old", 2)}
REPLAY = {**INITIAL, A: _records(A, "A-new", 3)}
LABELS = {record: label for label, rows in (("A-old", INITIAL[A]), ("B-old", INITIAL[B]), ("A-new", REPLAY[A]))
          for record in rows}
# Each observation is (positions, statics). B expires on its original clock,
# one day before A. A-old must be replaced, not duplicated or left unchanged.
REMOVED = ((('A-new',), ('A-new',)), (('A-new',), ('A-new',)), ((), ('A-new',)))
ELIGIBLE = ((('A-new', 'B-old'), ('A-new', 'B-old')), (('A-new',), ('A-new', 'B-old')), ((), ('A-new',)))


def _exercise(root, *, removed, independent):
    vessels: dict[int, dict[str, str | bool]] = {
        m: {"id": label, "mmsi": str(m), "status": "active"} for m, label in ((A, "A"), (B, "B"))
    }

    def snapshot(path, **_params):
        assert path == "snapshot"
        return {"vessels": list(vessels.values())}

    worker = SimpleNamespace(get=snapshot)  # no write API or transport

    def ingest(cache, scope, records, now, *, force=False):
        def history(day, bbox, wanted, counts):
            assert (day, bbox, wanted) == (DAY, BBOX, scope)
            counts.update(positions=len(wanted), statics=len(wanted))
            for mmsi in sorted(wanted):
                yield from records[mmsi]

        with patch.object(process, "run", return_value={}) as derive:
            result = backfill.backfill(REGION, worker, first=DAY, last=DAY, root=cache,
                                       source=SimpleNamespace(history=history), mmsis=scope, now_ms=now, force=force)
        assert not result["failed"] and not result["missing"]
        assert len(result["days"]) == 1 and result["days"][0]["positions"] == len(scope)
        derive.assert_called_once()
        assert derive.call_args.kwargs["mmsis"] == sorted(scope)
        assert derive.call_args.kwargs["expected_targets"].keys() == scope

    def store(cache):
        return backfill.backfill_store(cache)

    def observe(caches):
        return tuple(tuple(sorted(LABELS.get(row, "unexpected record") for cache in caches
                                  for row in getattr(store(cache), read)(START, END)))
                     for read in ("read_positions", "read_statics"))

    # A valid reference uses two independent cache generations. The affected
    # control uses the unchanged shared cache entry point with the same source.
    selected = root / "selected" if independent else root
    other = root / "other"
    caches = [selected, other] if independent else [selected]
    if independent:
        ingest(other, {B}, INITIAL, END)
    ingest(selected, {A} if independent else {A, B}, INITIAL, END)
    assert observe(caches) == (("A-old", "B-old"), ("A-old", "B-old"))

    if removed:
        # Model an already-applied removal, not a production erasure API. The
        # upstream fixture still offers B; a later scoped replay must not revive it.
        vessels[B].update(status="excluded", removal_requested=True)
        if independent:
            caches.remove(other)
        else:
            with closing(store(selected).connect(DAY)) as conn, conn:
                conn.execute("DELETE FROM positions WHERE mmsi = ?", (B,))
                conn.execute("DELETE FROM statics WHERE mmsi = ?", (B,))
        assert observe(caches) == (("A-old",), ("A-old",))

    # The reference's A-only generation already matches the request, so force
    # its refresh. The shared baseline is an ordinary wide-to-narrow replay.
    ingest(selected, {A}, REPLAY, END + DAY_MS, force=independent)
    if removed:
        assert vessels[B]["removal_requested"] is True and vessels[B]["status"] == "excluded"
    observed = [observe(caches)]
    for age in (2, 3):
        for cache in caches:
            backfill.apply_retention(store(cache), retention_limits(REGION), END + age * DAY_MS)
        observed.append(observe(caches))
    return tuple(observed)


CASES = [(False, ELIGIBLE), (True, REMOVED)]


@pytest.mark.parametrize("removed,expected", CASES, ids=["eligible-B", "removed-B"])
def test_scoped_replay_contract_reference(tmp_path, removed, expected):
    assert _exercise(tmp_path, removed=removed, independent=True) == expected


def _baseline():
    gap = False
    print("F07-06: (positions, statics) after replay, at B's position expiry, at B's static expiry")
    for removed, expected in CASES:
        with TemporaryDirectory() as tmp:
            actual = _exercise(Path(tmp), removed=removed, independent=False)
        gap |= actual != expected
        print(f"{'removed' if removed else 'eligible'} B: {'PASS' if actual == expected else 'GAP'}")
        print(f"  expected {expected}\n  observed {actual}")
    return int(gap)


if __name__ == "__main__":
    raise SystemExit(_baseline())
