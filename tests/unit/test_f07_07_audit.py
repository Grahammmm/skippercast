"""F07-07 / SCA-580: a backfill day file and its manifest are not committed together.

Offline fixture: a synthetic source, made-up MMSIs, a temporary store. The day
file is renamed into place first and its manifest written later, so a fault
between the two leaves a one-vessel day beside the previous two-vessel
manifest, and the wider replay is then skipped as already ingested. The strict
xfail states the wanted outcome (previous generation or an explicit cache miss)
and turns into a failure, to be removed, once the pair commits together.
"""
from contextlib import closing
from datetime import date, datetime, timezone

import pytest

from skippercast.fleet.ais import backfill as bf
from skippercast.fleet.ais.sources.base import AisPosition
from skippercast.fleet.ais.store import AisStore

DAY = date(2026, 6, 20)
BBOX = ((9.0, -151.0), (11.0, -149.0))
T0 = round(datetime(2026, 6, 20, 16, 0, tzinfo=timezone.utc).timestamp() * 1000)
BOTH = (999000001, 999000002)
NARROW = (999000001,)


class Source:
    """Yields one position per requested MMSI."""

    def history(self, day, bbox, mmsis=None, counts=None):
        for mmsi in sorted(mmsis):
            yield AisPosition(mmsi, T0, 10.0, -150.0, 0.0, None, None, None, "PositionReport", "marinecadastre", T0)
        if counts is not None:
            counts["positions"] = len(mmsis)


def _stored_mmsis(store):
    with closing(store.connect(DAY)) as conn:
        return sorted(row[0] for row in conn.execute("SELECT DISTINCT mmsi FROM positions"))


def _interrupted_narrow_replay(tmp_path, monkeypatch):
    store = AisStore(tmp_path / "backfill")
    bf.ingest_day(Source(), store, DAY, BBOX, BOTH, now_ms=T0)
    assert _stored_mmsis(store) == list(BOTH)

    def fail(*_args, **_kwargs):
        raise OSError("synthetic fault between day rename and manifest write")

    with monkeypatch.context() as patch:
        patch.setattr(bf, "_write_json", fail)
        with pytest.raises(OSError):
            bf.ingest_day(Source(), store, DAY, BBOX, NARROW, force=True, now_ms=T0 + 1)
    return store


def test_valid_control_complete_generation_is_a_hit_and_replay_skips(tmp_path):
    store = AisStore(tmp_path / "backfill")
    bf.ingest_day(Source(), store, DAY, BBOX, BOTH, now_ms=T0)
    assert _stored_mmsis(store) == list(BOTH)
    assert bf._ingested(store, DAY, bf._wanted(BBOX, BOTH)) is True
    assert bf.ingest_day(Source(), store, DAY, BBOX, BOTH)["skipped"] is True


def test_affected_control_interruption_leaves_day_and_manifest_disagreeing(tmp_path, monkeypatch):
    store = _interrupted_narrow_replay(tmp_path, monkeypatch)
    # Observation: the day holds one vessel while the manifest still records two,
    # and the wider selection is reported as ingested.
    assert _stored_mmsis(store) == list(NARROW)
    assert bf._ingested(store, DAY, bf._wanted(BBOX, BOTH)) is True


@pytest.mark.xfail(strict=True, reason="F07-07: day file and selection receipt commit separately")
def test_interruption_yields_previous_generation_or_cache_miss(tmp_path, monkeypatch):
    store = _interrupted_narrow_replay(tmp_path, monkeypatch)
    hit = bf._ingested(store, DAY, bf._wanted(BBOX, BOTH))
    # Either the previous complete (two-vessel) generation survives, or it is a miss.
    assert (not hit) or _stored_mmsis(store) == list(BOTH)
