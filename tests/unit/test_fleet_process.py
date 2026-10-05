"""skippercast.fleet.ais.process: the AIS processor job (CF-45, design.md section 11).

Synthetic throughout: a made-up MMSI (999xxxxxx) sailing out of a square harbor
geofence drawn in open ocean, written fix by fix into a raw store under a
temporary FLEET_VAR, and a fake Worker that records what the processor sends.
The region is the committed CA config with those ports, so its thresholds,
seasons and timezone are exercised. The workflows' shape is checked here too.
"""
from dataclasses import replace
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from skippercast.fleet.ais import process
from skippercast.fleet.ais.events import iso_utc
from skippercast.fleet.ais.process import HOUR, MINUTE, State, VesselRef, derive, downsample
from skippercast.fleet.ais.sources.base import AisPosition, AisStatic
from skippercast.fleet.ais.store import AisStore
from skippercast.fleet.config import Port, load_region
from skippercast.fleet.ops import id32
from tests._support import ROOT

MMSI = 999000123
VESSEL = id32("CA", "test-boat-1")
T0 = 1_791_190_800_000   # 2026-10-05T09:00:00Z, on the hour


def square(lat, lon, half_deg):
    s, n, w, e = lat - half_deg, lat + half_deg, lon - half_deg, lon + half_deg
    return ((w, s), (e, s), (e, n), (w, n), (w, s))


PORT = Port('port-a', 'Port A', (10.0, -150.0), None, None, ('ocean',), square(10.0, -150.0, 0.02), 'drawn')
REGION = replace(load_region('CA'), ports=(PORT,))


def track(t0=T0, mmsi=MMSI, come_back=True):
    """In port 30 min, out 25 min at 8 kn, drift 40 min, troll 30 min, back in at 8 kn, in port 30 min: 2 fixes a minute."""
    fixes, lat, lon, t = [], 10.0, -150.0, t0

    def emit(sog, cog):
        fixes.append(AisPosition(mmsi, t, round(lat, 7), round(lon, 7), sog, cog, None, None, 'PositionReport',
                                 'aisstream', t + 2_000))

    def run(minutes, heading, sog, wiggle=0):
        nonlocal lat, lon, t
        for k in range(minutes * 2):
            h = heading + (wiggle if (k // 4) % 2 else -wiggle)
            d = sog / 120.0
            lat += d * math.cos(math.radians(h)) / 60.0
            lon += d * math.sin(math.radians(h)) / (60.0 * math.cos(math.radians(lat)))
            t += 30_000
            emit(sog, h % 360)

    run(30, 0, 0.0)
    run(25, 90, 8.0)
    run(40, 0, 0.5, wiggle=120)
    run(30, 0, 6.0, wiggle=80)
    if come_back:
        while abs(lon + 150.0) > 0.01 or abs(lat - 10.0) > 0.01:
            dy, dx = (10.0 - lat) * 60.0, (-150.0 - lon) * 60.0 * math.cos(math.radians(lat))
            run(1, math.degrees(math.atan2(dx, dy)) % 360, 8.0)
        run(30, 0, 0.0)
    return fixes


class FakeWorker:
    """Records every call; the snapshot lists one vessel with the test MMSI."""

    def __init__(self, vessels=None):
        self.calls = []
        self.vessels = [{"id": VESSEL, "mmsi": str(MMSI), "vessel_class": "inspected-party", "port_id": "port-a",
                         "status": "active"}] if vessels is None else vessels

    def get(self, path, **params):
        self.calls.append(("GET", path, params))
        return {"vessels": self.vessels, "next": "r:"}

    def post(self, path, body):
        self.calls.append(("POST", path, json.loads(json.dumps(body))))
        return {"ok": True}

    def posts(self, path, key=None):
        return [b for m, p, b in self.calls if m == "POST" and p == path and (key is None or key in b)]


class ProcessTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "CA" / "ais"
        self.store = AisStore(self.root)

    def run_once(self, worker, now_ms, **options):
        return process.run(REGION, worker, root=self.root, now_ms=now_ms, hook_table=options.pop("hook_table", {}),
                           **options)


class DeriveTests(ProcessTestCase):
    def test_downsample_keeps_the_first_fix_of_each_minute(self):
        rows = downsample(track()[:10])
        self.assertEqual([p.ts // MINUTE for p in rows], sorted({p.ts // MINUTE for p in track()[:10]}))

    def test_a_trip_with_its_segments_and_events_and_the_derived_ids(self):
        d = derive(track(), MMSI, VesselRef(VESSEL, "inspected-party", "port-a"), REGION, source="aisstream",
                   window_from=T0, window_to=T0 + 6 * HOUR, now_ms=T0 + 6 * HOUR, computed_at=iso_utc(T0 + 6 * HOUR))
        self.assertEqual(len(d.trips), 1)
        trip = d.trips[0]
        self.assertEqual((trip["status"], trip["depart_port_id"], trip["return_port_id"]), ("closed", "port-a", "port-a"))
        self.assertEqual(trip["id"], id32(str(MMSI), trip["departed_at"], "aisstream"))
        self.assertEqual((trip["rights"], trip["season"], trip["local_date"]), ("internal-only", "2026", "2026-10-05"))
        self.assertEqual(trip["vessel_id"], VESSEL)
        kinds = [s["kind"] for s in d.segments]
        self.assertIn("fishing-drift", kinds)
        for seg in d.segments:
            self.assertEqual(seg["id"], id32(trip["id"], str(seg["seq"])))
        self.assertTrue(d.events)
        for event in d.events:
            self.assertEqual(event.basis, "inferred-from-movement")
            self.assertEqual(event.vessel_id, VESSEL)
            self.assertIn(event.segment_id, {s["id"] for s in d.segments})
        self.assertEqual(d.resume_ms, T0 + 6 * HOUR, "no open trip: the next window starts at this one's end")

    def test_an_open_trip_holds_the_resume_time_at_its_departure(self):
        d = derive(track(come_back=False), MMSI, VesselRef(VESSEL), REGION, source="aisstream", window_from=T0,
                   window_to=T0 + 3 * HOUR, now_ms=T0 + 3 * HOUR, computed_at=iso_utc(T0))
        self.assertEqual([t["status"] for t in d.trips], ["open"])
        self.assertIsNone(d.trips[0]["returned_at"])
        self.assertEqual(iso_utc(d.resume_ms), d.trips[0]["departed_at"])

    def test_a_long_window_splits_at_departures_and_tiles_the_window(self):
        d = derive([p for day in range(4) for p in track(T0 + day * 6 * HOUR)], MMSI, VesselRef(VESSEL), REGION,
                   source="aisstream", window_from=T0, window_to=T0 + 24 * HOUR, now_ms=T0 + 24 * HOUR,
                   computed_at=iso_utc(T0))
        self.assertEqual(len(d.trips), 4)
        units = process._units(d, limit=1)
        self.assertEqual([len(u["trips"]) for u in units], [1, 1, 1, 1])
        self.assertEqual(units[0]["window"][1], T0)
        self.assertEqual(units[-1]["window"][2], T0 + 24 * HOUR)
        for a, b in zip(units, units[1:]):
            self.assertEqual(a["window"][2], b["window"][1])
            self.assertEqual(iso_utc(b["window"][1]), b["trips"][0]["departed_at"])


class RunTests(ProcessTestCase):
    def test_reprocessing_a_window_twice_sends_identical_rows(self):
        self.store.write(positions=track())
        window, now = (T0 - HOUR, T0 + 12 * HOUR), T0 + 24 * HOUR
        first, second = FakeWorker(), FakeWorker()
        self.run_once(first, now, window=window)
        self.run_once(second, now, window=window)
        sent = first.posts("activity", "replace")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent, second.posts("activity", "replace"))
        self.assertEqual(sent[0]["replace"], [{"mmsi": str(MMSI), "from": iso_utc(window[0]), "to": iso_utc(window[1])}])
        self.assertEqual(len(sent[0]["trips"]), 1)
        self.assertEqual(first.posts("heartbeat"), [], "a re-run window sends no heartbeat")
        self.assertEqual(first.posts("activity", "processed"), [], "nor marks the scheduled processor as run")
        # The first run seeds the season's cells whole (with a prune); the same events again change no cell.
        self.assertIn("prune", first.posts("activity", "aggregates")[0]["aggregates"])
        self.assertEqual(second.posts("activity", "aggregates"), [])

    def test_a_scheduled_run_in_order_with_hooks_and_resume(self):
        self.store.write(positions=track(come_back=False))
        (self.root / "heartbeat.json").write_text(json.dumps({
            "schema_version": 1, "region": "CA", "source": "aisstream", "written_at": iso_utc(T0 + 2 * HOUR),
            "started_at": "2026-10-05T00:00:00Z", "last_message_at": iso_utc(T0 + 2 * HOUR), "reconnects": 2,
            "drops": {"positions": 0, "discovery": 5, "statics": 1, "write_error": 0}, "queue_max": 50000}))
        order = []
        hook_table = {"refresh_watch": lambda ctx: order.append("refresh_watch"),
                      "match": lambda ctx: order.append("match") or {MMSI: VesselRef(VESSEL, "six-pack")}}
        worker = FakeWorker(vessels=[])
        now = T0 + 2 * HOUR + 10 * MINUTE
        counts = self.run_once(worker, now, hook_table=hook_table)
        self.assertEqual(order, ["refresh_watch", "match"])
        paths = [(m, p, next((k for k in ("replace", "aggregates", "processed") if k in b), None) if m == "POST" else None)
                 for m, p, b in worker.calls]
        self.assertEqual(paths[0], ("POST", "heartbeat", None))
        self.assertEqual(paths[-1], ("POST", "activity", "processed"))
        self.assertLess(paths.index(("POST", "activity", "replace")), paths.index(("POST", "activity", "aggregates")))
        trips = worker.posts("activity", "replace")[0]["trips"]
        self.assertEqual([t["status"] for t in trips], ["open"])
        self.assertEqual(counts["trips"]["trips"], 1)

        beat = worker.posts("heartbeat")[0]
        self.assertEqual(beat["heartbeat"]["dropped"], 6)
        self.assertNotIn("drops", beat["heartbeat"])
        hours = {h["hour"]: h for h in beat["hours"]}
        self.assertEqual(hours[iso_utc(T0)]["watched_messages"], sum(p.ts < T0 + HOUR for p in track(come_back=False)))
        self.assertEqual(hours[iso_utc(T0 + 2 * HOUR)]["reconnects"], 2)
        self.assertEqual(beat["messages_24h"], len(track(come_back=False)))

        # Next run: the open trip's window again (from its departure minus 1 h); listener counters as deltas.
        departed = trips[0]["departed_at"]
        (self.root / "heartbeat.json").write_text(json.dumps({
            "written_at": iso_utc(now), "started_at": "2026-10-05T00:00:00Z", "reconnects": 3, "drops": {"statics": 1}}))
        later = FakeWorker(vessels=[])
        self.run_once(later, now + 30 * MINUTE, hook_table=hook_table)
        window = later.posts("activity", "replace")[0]["replace"][0]
        self.assertEqual(window["from"], iso_utc(process._ms(departed) - HOUR))
        self.assertEqual(later.posts("activity", "replace")[0]["trips"][0]["id"], trips[0]["id"])
        current = {h["hour"]: h for h in later.posts("heartbeat")[0]["hours"]}[iso_utc(T0 + 2 * HOUR)]
        self.assertEqual(current["reconnects"], 3, "2 before plus 1 since")

    def test_an_mmsi_on_two_registry_vessels_is_left_out(self):
        worker = FakeWorker(vessels=[{"id": VESSEL, "mmsi": str(MMSI)}, {"id": id32("CA", "x"), "mmsi": str(MMSI)},
                                     {"id": id32("CA", "y"), "mmsi": "999000124", "vessel_class": "six-pack"},
                                     {"id": id32("CA", "z"), "mmsi": None}])
        self.assertEqual(process.registry_targets(worker, "CA"), {999000124: VesselRef(id32("CA", "y"), "six-pack")})

    def test_hour_counts_cover_every_table_and_the_longest_silence(self):
        self.store.write(positions=[AisPosition(MMSI, T0 + 60_000, 10.0, -150.0, 0.0, 0.0, None, None, 'p', 'aisstream', T0 + 61_000)],
                         discovery=[AisPosition(999000200, T0 + 20 * MINUTE, 10.0, -150.0, 0.0, 0.0, None, None, 'p', 'aisstream', T0 + 20 * MINUTE)],
                         statics=[AisStatic(999000300, T0 + 30 * MINUTE, 'TEST', None, None, 37, 5, 5, 2, 2, 'B', 'aisstream')])
        counts = process.hour_counts(self.store, T0, T0 + 2 * HOUR)
        self.assertEqual(counts, {"messages": 3, "watched_messages": 1, "vessels": 3, "max_gap_s": 30 * 60})
        self.assertEqual(process.hour_counts(self.store, T0 + HOUR, T0 + 2 * HOUR)["max_gap_s"], 3600)

    def test_state_mirror_replaces_a_window_of_events(self):
        state = State(self.root / "state.sqlite")
        self.addCleanup(state.close)
        d = derive(track(), MMSI, VesselRef(VESSEL), REGION, source="aisstream", window_from=T0,
                   window_to=T0 + 6 * HOUR, now_ms=T0 + 6 * HOUR, computed_at=iso_utc(T0))
        departures = {t["id"]: (MMSI, process._ms(t["departed_at"])) for t in d.trips}
        state.replace_events("aisstream", [(MMSI, T0, T0 + 6 * HOUR)], d.events, departures)
        self.assertEqual([e.id for e in state.season_events("2026")], sorted(e.id for e in d.events))
        state.replace_events("marinecadastre", [(MMSI, T0, T0 + 6 * HOUR)], [], {})
        self.assertEqual(len(state.season_events("2026")), len(d.events), "another source's window leaves these")
        state.replace_events("aisstream", [(MMSI, T0, T0 + 6 * HOUR)], [], {})
        self.assertEqual(state.season_events("2026"), [])


class HookTests(unittest.TestCase):
    def test_process_runs_without_any_watch_or_match_module(self):
        """Acceptance 5: with skippercast.fleet.ais.match and .watch unimportable, a full scheduled run completes.

        The child runs in the repository root, so ``tests`` imports from there.
        """
        script = f"""
import sys
sys.modules['skippercast.fleet.ais.match'] = None
sys.modules['skippercast.fleet.ais.watch'] = None
from tests.unit.test_fleet_process import FakeWorker, REGION, T0, HOUR, track
from skippercast.fleet.ais import process
from skippercast.fleet.ais.store import AisStore
import pathlib, tempfile
root = pathlib.Path(tempfile.mkdtemp()) / 'CA' / 'ais'
AisStore(root).write(positions=track())
assert process.hooks() == {{}}
worker = FakeWorker()
counts = process.run(REGION, worker, root=root, now_ms=T0 + 8 * HOUR)
assert counts['trips']['trips'] == 1, counts
assert worker.posts('activity', 'processed'), worker.calls
print('ok')
"""
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=ROOT, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], "ok")
        source = (ROOT / "src/skippercast/fleet/ais/process.py").read_text()
        self.assertEqual(re.findall(r"^\s*(?:from|import)\s+\S*\b(?:match|watch)\b.*$", source, re.M), [],
                         "process.py never imports them at module level")


def _header(path):
    text = (ROOT / ".github" / "workflows" / path).read_text()
    return text, "\n".join(line for line in text.split("\njobs:", 1)[0].splitlines() if not line.lstrip().startswith("#"))


class WorkflowTests(unittest.TestCase):
    def test_fleet_health_runs_hosted_with_exactly_two_permissions(self):
        text, header = _header("fleet-health.yml")
        self.assertEqual(re.findall(r"^\s*runs-on:\s*(.+?)\s*$", text, re.M), ["ubuntu-latest"])
        block = re.search(r"\npermissions:\n((?:  .*\n)+)", header + "\n").group(1)
        granted = sorted(re.sub(r"\s*#.*", "", line).strip() for line in block.splitlines())
        self.assertEqual(granted, ["id-token: write", "issues: write"])
        self.assertEqual(text.count("permissions:"), 1, "no job widens them")
        self.assertNotIn("actions/checkout", text, "nothing from the repository runs on it")
        self.assertIn("fleet-ais-stale", text)
        self.assertIn("/api/fleet/jobs/health", text)
        for trigger in ("push:", "pull_request"):
            self.assertNotIn(trigger, header)

    def test_fleet_ais_runs_on_our_runner_every_30_minutes(self):
        text, header = _header("fleet-ais.yml")
        self.assertIn('cron: "3,33 * * * *"', header)
        self.assertIn("permissions: {}", header)
        self.assertIn("if: vars.ENABLE_FLEET == 'true' && vars.DATA_RUNNER != ''", text)
        self.assertIn("group: fleet-ais", header)
        self.assertIn("cancel-in-progress: false", header)
        self.assertIn("id-token: write", text)
        self.assertNotRegex(text, r"(contents|actions|issues|pull-requests): write")
        for trigger in ("push:", "pull_request"):
            self.assertNotIn(trigger, header)
        policy = json.loads((ROOT / "deployments" / "production.json").read_text())
        self.assertTrue({"fleet-ais.yml", "fleet-health.yml"} <= set(policy["scheduler"]["workflows"]))


if __name__ == "__main__":
    unittest.main()
