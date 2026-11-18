"""F08-04: offline schedule-watch lifecycle at the real match hook."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from skippercast.fleet.ais import match, process, schedule
from skippercast.fleet.ais.watch import read_watch
from tests.unit.test_fleet_match import (
    CANDIDATE, HELD, HELD_MMSI, OTHER, PORT_A, PORT_B, REGION, SEA, TWIN, FakeWorker, static, vessel,
)

EVIDENCE_DAY = date(2026, 9, 5)
MATCHED = tuple(EVIDENCE_DAY - timedelta(days=i) for i in (16, 12, 8, 4, 0))
PORTS = (replace(PORT_A, region="feed-a"), replace(PORT_B, region="feed-b"))


@pytest.fixture
def match_run(tmp_path, monkeypatch):
    region = replace(REGION, ports=PORTS)
    for port in region.ports:
        directory = tmp_path / "regions" / port.region
        directory.mkdir(parents=True)
        (directory / "region.json").write_text(json.dumps({"daily_feed": port.region}))
    monkeypatch.setattr(schedule, "landing_ports", lambda root: {p.name.lower(): p.id for p in PORTS})

    worker = FakeWorker([
        vessel(SEA, "Sea Example"),
        vessel(TWIN, "Twin Example", port=PORT_B.id),
        vessel(HELD, "Held Example", mmsi=HELD_MMSI, pinned=("mmsi",)),
    ])
    feeds = {}
    requested = []

    def fetch(url):
        requested.append(url)
        result = feeds.get(url)
        if result is None:
            raise OSError("synthetic outage")
        return result

    monkeypatch.setattr(match, "load_report_days", lambda region, vessels: schedule.load_report_days(
        region, vessels, fetch=fetch, root=tmp_path))
    no_history = SimpleNamespace(read_statics=lambda *args: (), read_positions=lambda *args, **kwargs: ())

    def run(day, *, matches=(), home=True, forget_statics=False):
        # Reopen the same private database on every run, as the scheduled job does.
        now = round(datetime(day.year, day.month, day.day, 19, tzinfo=timezone.utc).timestamp() * 1000)
        state = process.State(tmp_path / "state.sqlite")
        try:
            mstate = match.MatchState(state)
            state.put("match_scanned_ms", now - process.SETTLE_MS)
            if forget_statics:
                state.db.execute("DELETE FROM match_statics WHERE mmsi=?", (CANDIDATE,))
            elif matches:
                mstate.add([static(m, now - process.HOUR, name) for m, name in (
                    (CANDIDATE, "Sea Example"), (OTHER, "Twin Example"), (HELD_MMSI, "Held Example"),
                )], (), region.ports, match.ZoneInfo(region.timezone))
            for mmsi, port in ((CANDIDATE, PORT_A), (OTHER, PORT_B)):
                state.db.executemany("INSERT OR IGNORE INTO match_away VALUES(?,?)",
                                     [(mmsi, d.isoformat()) for d in matches])
                if home:
                    state.db.execute("INSERT OR REPLACE INTO match_presence VALUES(?,?,?)",
                                     (mmsi, port.id, day.isoformat()))
            requested.clear()
            targets = match.match(SimpleNamespace(
                region=region, state=state, now_ms=now, store=no_history, worker=worker, root=tmp_path, run_id="synthetic",
            ))
            assert sorted(requested) == ["feed-a", "feed-b"]
            assert set(targets) == set(read_watch(tmp_path / "watch.json", region.id).watched)
            assert worker.watch[str(HELD_MMSI)]["match_method"] == "admin"
            assert HELD_MMSI in targets
            return set(targets) - {HELD_MMSI}
        finally:
            state.close()

    return run, feeds, worker


def report(boat, port, days):
    return {"reports": [{"boat": boat, "port": port.name, "date": d.isoformat()} for d in days]}


@pytest.mark.parametrize("forget_statics", [False, True])
def test_total_outage_cannot_renew_past_the_last_verified_day(match_run, forget_statics):
    run, feeds, worker = match_run
    feeds["feed-a"] = report("Sea Example", PORT_A, MATCHED)
    # The feed is read later than the last matching day. Grace follows the evidence, not the read time.
    assert run(EVIDENCE_DAY + timedelta(days=3), matches=MATCHED) == {CANDIDATE}
    feeds.clear()
    # Home-port observations age out; the persisted matching day is the only grace clock.
    for offset in (7, 30):
        assert run(EVIDENCE_DAY + timedelta(days=offset), home=False, forget_statics=forget_statics) == {CANDIDATE}
    assert run(EVIDENCE_DAY + timedelta(days=31), home=False, forget_statics=forget_statics) == set()
    assert worker.watch[str(CANDIDATE)]["status"] == "candidate"


def test_partial_outage_is_unknown_only_for_the_affected_home_port(match_run):
    run, feeds, worker = match_run
    feeds["feed-a"] = report("Sea Example", PORT_A, MATCHED)
    assert run(EVIDENCE_DAY, matches=MATCHED) == {CANDIDATE}
    # A malformed response is not a readable empty report list. The other feed can still promote.
    feeds["feed-a"] = {"reports": None}
    feeds["feed-b"] = report("Twin Example", PORT_B, MATCHED)
    assert run(EVIDENCE_DAY + timedelta(days=1)) == {CANDIDATE, OTHER}
    # Empty but readable: no recent support for the covered binding, so it lapses immediately.
    feeds["feed-b"] = {"reports": []}
    assert run(EVIDENCE_DAY + timedelta(days=2)) == {CANDIDATE}
    assert worker.watch[str(OTHER)]["status"] == "candidate"
    assert run(EVIDENCE_DAY + timedelta(days=31)) == set()
    # A recovered feed with just one matching day cannot promote the expired binding.
    latest = EVIDENCE_DAY + timedelta(days=32)
    feeds["feed-a"] = report("Sea Example", PORT_A, [latest])
    assert run(latest, matches=[latest]) == set()
    recovered = tuple(d + timedelta(days=33) for d in MATCHED)
    feeds["feed-a"] = report("Sea Example", PORT_A, recovered)
    assert run(recovered[-1], matches=recovered) == {CANDIDATE}
    feeds.clear()
    assert run(recovered[-1] + timedelta(days=30), home=False) == {CANDIDATE}
    assert run(recovered[-1] + timedelta(days=31), home=False) == set()


def test_legacy_watch_with_no_verified_day_cannot_renew_on_unknown(match_run):
    run, _, worker = match_run
    assert run(EVIDENCE_DAY, matches=MATCHED) == set()  # AIS alone is not schedule evidence
    worker.watch[str(CANDIDATE)].update(status="watched", match_method="schedule-correlation", confidence=0.85)
    assert run(EVIDENCE_DAY + timedelta(days=1)) == set()
    assert worker.watch[str(CANDIDATE)]["status"] == "candidate"


def test_outage_grace_does_not_transfer_to_a_changed_home_port(match_run):
    run, feeds, worker = match_run
    feeds["feed-a"] = report("Sea Example", PORT_A, MATCHED)
    assert run(EVIDENCE_DAY, matches=MATCHED) == {CANDIDATE}
    worker.vessels[0]["port_id"] = PORT_B.id
    feeds.clear()
    assert run(EVIDENCE_DAY + timedelta(days=1)) == set()


def test_only_a_verified_matching_day_extends_the_grace_clock(match_run):
    run, feeds, _ = match_run
    feeds["feed-a"] = report("Sea Example", PORT_A, MATCHED)
    assert run(EVIDENCE_DAY, matches=MATCHED) == {CANDIDATE}
    verified = EVIDENCE_DAY + timedelta(days=5)
    feeds["feed-a"] = report("Sea Example", PORT_A, [verified])
    assert run(verified, matches=[verified]) == {CANDIDATE}  # one new day for an established binding
    feeds.clear()
    unverified = verified + timedelta(days=1)
    # Matching-looking rows from an unrelated feed cannot fill the home-port coverage gap.
    feeds["feed-b"] = report("Sea Example", PORT_A, [unverified])
    assert run(unverified, matches=[unverified]) == {CANDIDATE}
    assert run(verified + timedelta(days=30), home=False) == {CANDIDATE}
    assert run(verified + timedelta(days=31), home=False) == set()
