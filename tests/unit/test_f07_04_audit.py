"""F07-04: backfill maintenance must not reset the static-data retention clock."""
from contextlib import closing
from datetime import date, datetime, timezone
import json
import os

import pytest

from skippercast.fleet.ais import backfill as bf
from skippercast.fleet.ais.sources.base import AisPosition, AisStatic
from skippercast.fleet.ais.store import AisStore, retention_limits
from skippercast.fleet.config import load_region

DAY = date(2026, 4, 1)
OBSERVED = int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp()) * 1000
INGESTED = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()) * 1000
DAY_MS = 86_400_000
BBOX = ((-1.0, -1.0), (1.0, 1.0))
MMSI = 999000001
LIMITS = retention_limits(load_region("CA"))


class SyntheticSource:
    def history(self, day, bbox, mmsis, *, counts):
        counts.update(positions=1, statics=1)
        yield AisPosition(MMSI, OBSERVED, 0.0, 0.0, None, None, None, None,
                          "PositionReport", "marinecadastre", INGESTED)
        yield AisStatic(MMSI, OBSERVED, "TEST VESSEL", None, None, None,
                        None, None, None, None, "A", "marinecadastre")


def _counts(store):
    with closing(store.connect(DAY)) as conn:
        return tuple(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                     for table in ("positions", "statics"))


@pytest.mark.parametrize("legacy", ["v1", "missing-manifest"])
def test_static_retention_uses_original_clock_after_position_expiry(tmp_path, legacy):
    store = AisStore(tmp_path)
    bf.ingest_day(SyntheticSource(), store, DAY, BBOX, [MMSI], now_ms=INGESTED)
    assert _counts(store) == (1, 1)
    manifest_path = tmp_path / "days" / f"{DAY}.json"
    path = store.day_path(DAY)
    if legacy == "missing-manifest":
        manifest_path.unlink()
        # An orphaned day uses the original file mtime as its best available clock.
        os.utime(path, (INGESTED / 1000, INGESTED / 1000))
    else:
        manifest = json.loads(manifest_path.read_text())
        manifest.pop("positions_complete", None)
        manifest_path.write_text(json.dumps(manifest))
        assert bf.ingest_day(None, store, DAY, BBOX, [MMSI]) == {"day": str(DAY), "skipped": True}

    assert bf.apply_retention(store, LIMITS, INGESTED + 30 * DAY_MS) == {"deleted": [], "emptied": {}}
    assert _counts(store) == (1, 1)
    day31 = INGESTED + 31 * DAY_MS
    assert bf.apply_retention(store, LIMITS, day31) == {"deleted": [], "emptied": {str(DAY): ["positions"]}}
    assert _counts(store) == (0, 1)
    # Represent a SQLite maintenance write at day 31 regardless of the host clock.
    os.utime(path, (day31 / 1000, day31 / 1000))
    assert bf.apply_retention(store, LIMITS, INGESTED + 90 * DAY_MS) == {"deleted": [], "emptied": {}}
    assert _counts(store) == (0, 1)
    assert bf.apply_retention(store, LIMITS, INGESTED + 91 * DAY_MS) == {"deleted": [str(DAY)], "emptied": {}}
    assert not path.exists()
    assert not manifest_path.exists()


def test_expired_positions_can_be_refetched_and_cached(tmp_path):
    store = AisStore(tmp_path)
    source = SyntheticSource()
    bf.ingest_day(source, store, DAY, BBOX, [MMSI], now_ms=INGESTED)
    day31 = INGESTED + 31 * DAY_MS
    bf.apply_retention(store, LIMITS, day31)
    assert _counts(store) == (0, 1)

    # Same selection, with no --force: this must actually restore the position.
    result = bf.ingest_day(source, store, DAY, BBOX, [MMSI], now_ms=day31)
    assert result == {"day": str(DAY), "positions": 1, "statics": 1}
    assert _counts(store) == (1, 1)
    assert bf.ingest_day(None, store, DAY, BBOX, [MMSI]) == {"day": str(DAY), "skipped": True}
    assert bf.apply_retention(store, LIMITS, INGESTED + 91 * DAY_MS) == {
        "deleted": [], "emptied": {str(DAY): ["positions"]},
    }
    assert _counts(store) == (0, 1)  # A successful replacement, unlike maintenance, has a new clock.
