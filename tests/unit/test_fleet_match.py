"""skippercast.fleet.ais.match: MMSI matching and the watch list (CF-46, design.md section 11).

Synthetic throughout: invented boats, MMSIs 999xxxxxx and call signs, harbor
geofences drawn as squares in open ocean, statics and positions written into a
raw store under a temporary directory, and a fake Worker standing in for
``/api/fleet/jobs/snapshot`` and ``/api/fleet/jobs/watch``. The region is the
committed CA config with those ports, so its thresholds and timezone are used.
"""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

import contextlib
import io

from skippercast.fleet.ais import gate, match, process, schedule
from skippercast.fleet.ais.match import MatchState, Seen, Static, decide
from skippercast.fleet.ais.process import DAY, HOUR, MINUTE, VesselRef
from skippercast.fleet.ais.sources.base import AisPosition, AisStatic
from skippercast.fleet.ais.store import AisStore
from skippercast.fleet.ais.watch import read_watch
from skippercast.fleet.config import Port, load_region
from skippercast.fleet.ops import id32, review_id

T0 = 1_791_190_800_000          # 2026-10-05T09:00:00Z (02:00 in Los Angeles)
NOW = T0 + 10 * HOUR            # 12:00 local on 2026-10-05
SEA, HELD, TWIN = id32("CA", "sea-example"), id32("CA", "held-example"), id32("CA", "twin-example")
RIVAL = id32("CA", "rival-example")
TWO_WEEKS = ["2026-09-20", "2026-09-23", "2026-09-26", "2026-09-30", "2026-10-03"]   # 5 days spanning 14
ONE_WEEK = ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"]    # 5 days inside one week
HELD_MMSI, CANDIDATE, PLEASURE, OTHER = 999000301, 999000302, 999000303, 999000304


def square(lat, lon, half_deg):
    s, n, w, e = lat - half_deg, lat + half_deg, lon - half_deg, lon + half_deg
    return ((w, s), (e, s), (e, n), (w, n), (w, s))


PORT_A = Port("port-a", "Port A", (10.0, -150.0), None, None, ("ocean",), square(10.0, -150.0, 0.02), "drawn")
PORT_B = Port("port-b", "Port B", (11.0, -150.0), None, None, ("ocean",), square(11.0, -150.0, 0.02), "drawn")
REGION = replace(load_region("CA"), ports=(PORT_A, PORT_B))
AUTO = REGION.thresholds["match"]["mmsi_auto"]


def vessel(ident, name, *, mmsi=None, call_sign=None, length_ft=60.0, port="port-a", aliases=(), pinned=(), sources=()):
    return {"id": ident, "name": name, "name_norm": "".join(ch for ch in name.upper() if ch.isalnum()),
            "port_id": port, "vessel_class": "inspected-party", "status": "active", "mmsi": mmsi and str(mmsi),
            "call_sign": call_sign, "length_ft": length_ft, "aliases": [{"alias_norm": a} for a in aliases],
            "pinned": list(pinned), "sources": list(sources)}


def fleet():
    return [vessel(SEA, "Sea Example", call_sign="WDX0001"),
            vessel(HELD, "Held Example", mmsi=HELD_MMSI, call_sign="WDX0002", port="port-b")]


def static(mmsi, ts, name=None, *, call_sign=None, ship_type=None, bow=None, stern=None, ais_class="B"):
    return AisStatic(mmsi, ts, name, call_sign, None, ship_type, bow, stern, None, None, ais_class, "aisstream")


def moored(mmsi, day_offsets, port=PORT_A, hour=10, step=HOUR):
    """Three fixes ``step`` apart from ``hour`` past T0 inside ``port`` on each day ``T0 - offset days``."""
    lat, lon = port.point
    return [AisPosition(mmsi, T0 - k * DAY + hour * HOUR + h * step, lat, lon, 0.0, None, None, None,
                        "StandardClassBPositionReport", "aisstream", T0 - k * DAY + hour * HOUR + h * step + 1000)
            for k in day_offsets for h in range(3)]


class FakeWorker:
    """The snapshot (vessels then decided reviews) and the watch routes, kept in memory."""

    def __init__(self, vessels=None, reviews=(), watch=None):
        self.vessels = fleet() if vessels is None else vessels
        self.reviews = list(reviews)
        self.watch = {r["mmsi"]: dict(r) for r in (watch or [])}
        self.ops = []
        self.calls = []

    def get(self, path, **params):
        self.calls.append(("GET", path, params))
        if path == "snapshot":
            if params["cursor"].startswith("v:"):
                return {"vessels": self.vessels, "next": "r:"}
            return {"reviews": self.reviews, "next": None}
        if path == "watch":
            rows = [r for m, r in sorted(self.watch.items()) if params.get("status") in (None, r["status"])]
            return {"rows": rows, "next": None}
        raise AssertionError(path)

    def post(self, path, body):
        body = json.loads(json.dumps(body))
        self.calls.append(("POST", path, body))
        if path == "watch":
            for row in body.get("rows", []):
                before = self.watch.get(row["mmsi"])
                if before and before["status"] == "rejected" and row["status"] != "rejected" and row["match_method"] != "admin":
                    continue
                self.watch[row["mmsi"]] = row
            self.ops.extend(body.get("ops", []))
        return {"ok": True}

    def posted(self, path):
        return [b for m, p, b in self.calls if m == "POST" and p == path]


def full_static(mmsi, name, **extra):
    return Static(mmsi, T0, "aisstream", name, extra.get("call_sign"), extra.get("ship_type"), extra.get("length_m"), "B")


class DecideTests(unittest.TestCase):
    """The three stages as a pure function."""

    def decide(self, statics, *, presence=None, prior=None, vessels=None, reviews=()):
        statics = {s.mmsi: s for s in statics}
        seen = {m: Seen(T0 - 5 * DAY, T0, "aisstream", 40) for m in statics}
        return decide(REGION, fleet() if vessels is None else vessels, reviews, statics, seen, presence or {},
                      prior or {}, NOW)

    def rows(self, decision):
        return {int(r["mmsi"]): r for r in decision.rows}

    def test_a_same_name_pleasure_boat_with_the_wrong_length_stays_a_candidate(self):
        """Acceptance 1: type 37, 8 m against a 60 ft vessel, never in the port geofence."""
        boat = full_static(PLEASURE, "SEA EXAMPLE", ship_type=37, length_m=8.0)
        decision = self.decide([boat])
        row = self.rows(decision)[PLEASURE]
        self.assertEqual((row["status"], row["vessel_id"], row["match_method"]), ("candidate", SEA, "ais-static-name"))
        self.assertEqual(row["confidence"], 0.4)
        self.assertEqual(decision.targets, {})
        self.assertEqual(decision.reviews, [], "never seen at the vessel's home port: no review to clutter the queue")
        self.assertEqual(decision.facts, [], "a candidate's statics are not the vessel's facts")
        # Even moored in the home port for a week it never promotes; then it is a review.
        decision = self.decide([boat], presence={PLEASURE: {"port-a": 7}})
        self.assertEqual(self.rows(decision)[PLEASURE]["status"], "candidate")
        self.assertEqual(decision.targets, {})
        self.assertEqual([r["proposal_json"]["reason"] for r in decision.reviews], ["length-contradicts"])

    def test_three_distinct_home_port_days_promote_to_watched(self):
        """Acceptance 2."""
        boat = full_static(CANDIDATE, "Sea Example", ship_type=60, length_m=18.0)
        two = self.decide([boat], presence={CANDIDATE: {"port-a": 2, "port-b": 5}})
        self.assertEqual(self.rows(two)[CANDIDATE]["status"], "candidate", "days in another port do not count")
        self.assertEqual(self.rows(two)[CANDIDATE]["confidence"], 0.7)
        three = self.decide([boat], presence={CANDIDATE: {"port-a": 3}})
        row = self.rows(three)[CANDIDATE]
        self.assertEqual((row["status"], row["match_method"], row["vessel_id"]), ("watched", "geofence-presence", SEA))
        self.assertGreaterEqual(row["confidence"], AUTO)
        self.assertEqual(three.targets, {CANDIDATE: VesselRef(SEA, "inspected-party", "port-a")})
        # Watched stays watched while the name matches, even after the boat leaves port.
        sticky = self.decide([boat], prior={CANDIDATE: {**row}})
        self.assertEqual(self.rows(sticky)[CANDIDATE]["status"], "watched")

    def test_ship_type_and_unknown_length(self):
        cargo = full_static(OTHER, "SEA EXAMPLE", ship_type=70, length_m=18.0)
        self.assertEqual(self.decide([cargo]).rows, [], "another known type is no match")
        # A Class B boat sending no type or dimensions, berthed in the home harbor all month, is never watched:
        # promotion needs a known type of 30/37/60/69 and a known length within 20% (design § 11).
        for boat, reason in ((full_static(OTHER, "SEA EXAMPLE"), "length-unknown"),
                             (full_static(OTHER, "SEA EXAMPLE", length_m=18.0), "type-unknown"),
                             (full_static(OTHER, "SEA EXAMPLE", ship_type=37), "length-unknown")):
            away = self.decide([boat])
            self.assertEqual((self.rows(away)[OTHER]["status"], away.reviews), ("candidate", []))
            home = self.decide([boat], presence={OTHER: {"port-a": 20}})
            self.assertEqual(self.rows(home)[OTHER]["status"], "candidate", boat)
            self.assertEqual(home.targets, {})
            self.assertEqual([r["proposal_json"]["reason"] for r in home.reviews], [reason], "seen at home: a review")
        self.assertEqual(self.rows(self.decide([full_static(OTHER, "SEA EXAMPLE")]))[OTHER]["confidence"], 0.6)
        # A watched row whose statics now lack a type is demoted, not kept by stickiness.
        known = full_static(OTHER, "SEA EXAMPLE", ship_type=37, length_m=18.0)
        watched = self.rows(self.decide([known], presence={OTHER: {"port-a": 3}}))[OTHER]
        self.assertEqual(watched["status"], "watched")
        later = self.decide([full_static(OTHER, "SEA EXAMPLE")], prior={OTHER: watched})
        self.assertEqual(self.rows(later)[OTHER]["status"], "candidate")

    def test_call_sign_and_alias_match_vessels_without_an_mmsi(self):
        by_call = self.rows(self.decide([full_static(OTHER, "NEW NAME", call_sign="WDX0001", ship_type=30, length_m=18.0)]))
        self.assertEqual((by_call[OTHER]["vessel_id"], by_call[OTHER]["match_method"], by_call[OTHER]["confidence"]),
                         (SEA, "call-sign", 0.8))
        vessels = [vessel(SEA, "Sea Example", aliases=("OLDSEA",))]
        by_alias = self.rows(self.decide([full_static(OTHER, "Old Sea", ship_type=37, length_m=18.0)], vessels=vessels))
        self.assertEqual(by_alias[OTHER]["vessel_id"], SEA)

    def test_two_vessels_of_one_name_never_promote(self):
        vessels = [vessel(SEA, "Twin Example"), vessel(TWIN, "Twin Example", port="port-b")]
        boat = full_static(OTHER, "TWIN EXAMPLE", ship_type=37, length_m=18.0)
        one_home = self.rows(self.decide([boat], vessels=vessels, presence={OTHER: {"port-b": 3}}))[OTHER]
        self.assertEqual((one_home["vessel_id"], one_home["status"]), (TWIN, "watched"), "seen in only one vessel's port")
        both = self.decide([boat], vessels=vessels, presence={OTHER: {"port-a": 3, "port-b": 3}})
        self.assertEqual((self.rows(both)[OTHER]["vessel_id"], self.rows(both)[OTHER]["status"]), (None, "candidate"))
        self.assertEqual(sorted(r["subject_id"] for r in both.reviews), sorted([SEA, TWIN]))

    def test_the_registry_mmsi_is_never_overwritten(self):
        """Acceptance 3 (pure part): the registry's MMSI holds its vessel; disagreeing statics become ais facts."""
        stale = full_static(HELD_MMSI, "HELD EXAMPLE", call_sign="WDX9999", ship_type=60, length_m=40.0)
        rival = full_static(OTHER, "Held Example", ship_type=60, length_m=18.0)
        decision = self.decide([stale, rival], presence={OTHER: {"port-b": 5}})
        rows = self.rows(decision)
        self.assertEqual((rows[HELD_MMSI]["status"], rows[HELD_MMSI]["match_method"], rows[HELD_MMSI]["confidence"]),
                         ("watched", "fcc-uls", 0.9), "the name agrees, so the registry MMSI is confirmed")
        self.assertEqual((rows[OTHER]["status"], rows[OTHER]["vessel_id"]), ("candidate", HELD),
                         "a rival MMSI broadcasting the name is a candidate, however long it sits in the home port")
        self.assertEqual(decision.targets, {HELD_MMSI: VesselRef(HELD, "inspected-party", "port-b")})
        self.assertEqual([r["proposal_json"]["reason"] for r in decision.reviews], ["vessel-has-registry-mmsi"])
        self.assertEqual(sorted(f["field"] for f in decision.facts), ["ais.call_sign", "ais.length_ft"])
        for f in decision.facts:
            self.assertEqual((f["method"], f["source_id"], f["rights"], f["vessel_id"]), ("ais", "ais-static", "internal-only", HELD))
            self.assertEqual(f["value_json"]["mmsi"], str(HELD_MMSI))
        self.assertTrue(all(op["op"] in ("fact.upsert", "review.open") for op in decision.facts + decision.reviews))

    def test_registry_statics_that_disagree_on_everything_are_a_review(self):
        wrong = full_static(HELD_MMSI, "SOMETHING ELSE", call_sign="WDX9999", ship_type=37, length_m=18.0)
        decision = self.decide([wrong])
        row = self.rows(decision)[HELD_MMSI]
        self.assertEqual((row["status"], row["vessel_id"], row["confidence"]), ("candidate", HELD, 0.5))
        self.assertEqual(decision.reviews[0]["fingerprint"], f"{HELD}|{HELD_MMSI}")
        self.assertEqual(decision.reviews[0]["proposal_json"]["reason"], "registry-statics-disagree")
        self.assertEqual(sorted(f["field"] for f in decision.facts), ["ais.call_sign", "ais.name"])

    def test_admin_decisions(self):
        # An admin-set MMSI is watched whatever AIS says.
        admin = [vessel(HELD, "Held Example", mmsi=HELD_MMSI, port="port-b", pinned=("mmsi",))]
        row = self.rows(self.decide([full_static(HELD_MMSI, "ANOTHER NAME")], vessels=admin))[HELD_MMSI]
        self.assertEqual((row["status"], row["match_method"], row["confidence"]), ("watched", "admin", 1.0))
        # A decided reject-mmsi review rejects that pair for good.
        rejected = [{"kind": "mmsi", "status": "decided", "subject_id": SEA,
                     "decision": {"action": "reject-mmsi", "vessel_id": SEA, "mmsi": str(CANDIDATE)}}]
        boat = full_static(CANDIDATE, "SEA EXAMPLE", ship_type=60, length_m=18.0)
        decision = self.decide([boat], reviews=rejected, presence={CANDIDATE: {"port-a": 9}})
        self.assertEqual(self.rows(decision)[CANDIDATE]["status"], "rejected")
        self.assertEqual(decision.targets, {})

    def test_watched_rows_nothing_matched_any_more_are_demoted(self):
        gone = {"mmsi": str(OTHER), "vessel_id": SEA, "match_method": "geofence-presence", "confidence": 0.85,
                "status": "watched", "ais_name": "SEA EXAMPLE", "ais_call_sign": None, "ais_class": "B",
                "first_seen_at": "2026-09-01T00:00:00.000Z", "last_seen_at": "2026-09-20T00:00:00.000Z",
                "last_seen_source": "aisstream", "positions_30d": 0}
        renamed = self.decide([full_static(OTHER, "NOT THE SAME", ship_type=37, length_m=18.0)], prior={OTHER: gone})
        self.assertEqual(renamed.rows, [{**gone, "status": "candidate"}], "its statics no longer match: demoted")
        silent = self.decide([], prior={OTHER: gone})
        self.assertEqual(silent.rows, [], "no statics to judge by: the stored row stands")
        self.assertEqual(silent.targets, {OTHER: VesselRef(SEA, "inspected-party", "port-a")})


class RunTests(unittest.TestCase):
    """The hooks inside a real processor run, against a raw store and the fake Worker."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "CA" / "ais"
        self.store = AisStore(self.root)

    def run_once(self, worker, now_ms=NOW):
        return process.run(REGION, worker, root=self.root, now_ms=now_ms)   # hooks from skippercast.fleet.ais.match

    def watched(self):
        return sorted(read_watch(self.root / "watch.json", "CA").watched)

    def test_the_processor_loads_the_hooks(self):
        self.assertEqual(sorted(process.hooks()), ["match", "refresh_watch"])

    def test_one_run_refreshes_watch_json_and_pushes_match_updates(self):
        """Acceptances 2 and 4 through the store: class B part A and part B statics, moored fixes on 3 local days."""
        self.store.write(statics=[static(CANDIDATE, T0 - 3 * DAY, "SEA EXAMPLE@@@@"),
                                  static(CANDIDATE, T0 - 3 * DAY + MINUTE, call_sign="WDX0001", ship_type=60, bow=12, stern=6)],
                         discovery=moored(CANDIDATE, [1, 2]))
        worker = FakeWorker()
        self.run_once(worker)
        self.assertEqual(worker.watch[str(CANDIDATE)]["status"], "candidate", "two days in the home port")
        self.assertEqual(worker.watch[str(CANDIDATE)]["ais_name"], "SEA EXAMPLE")
        self.assertEqual(self.watched(), [])

        # A third local day, heard after the first run's scan; the fixes it already counted are not counted again.
        self.store.write(discovery=moored(CANDIDATE, [0], hour=10, step=5 * MINUTE))
        worker.calls.clear()
        counts = self.run_once(worker, NOW + 30 * MINUTE)
        row = worker.watch[str(CANDIDATE)]
        self.assertEqual((row["status"], row["vessel_id"], row["match_method"]), ("watched", SEA, "geofence-presence"))
        self.assertGreaterEqual(row["confidence"], AUTO)
        self.assertEqual(row["positions_30d"], 9, "each fix counted once across runs")
        self.assertEqual(self.watched(), [CANDIDATE])
        order = [(m, p) for m, p, _ in worker.calls if p in ("watch", "heartbeat")]
        self.assertEqual(order, [("POST", "heartbeat"), ("GET", "watch"), ("GET", "watch"), ("POST", "watch"), ("GET", "watch")],
                         "refresh, read the rows, push, refresh again")
        self.assertIn("trips", counts)
        generated = json.loads((self.root / "watch.json").read_text())["generated_at"]
        self.assertEqual(generated, "2026-10-05T19:30:00Z")

    def test_a_registry_mmsi_keeps_its_vessel_in_a_run(self):
        """Acceptance 3 through a run: no vessel write, and the processor keeps the registry attribution."""
        self.store.write(statics=[static(HELD_MMSI, T0 - DAY, "HELD EXAMPLE", call_sign="WDX9999", ship_type=60, bow=10, stern=8),
                                  static(OTHER, T0 - DAY, "HELD EXAMPLE", ship_type=60, bow=10, stern=8)],
                         discovery=moored(OTHER, [1, 2, 3], port=PORT_B))
        worker = FakeWorker()
        self.run_once(worker)
        self.assertEqual(worker.watch[str(HELD_MMSI)]["status"], "watched")
        self.assertEqual(worker.watch[str(OTHER)]["status"], "candidate")
        self.assertEqual(self.watched(), [HELD_MMSI])
        self.assertEqual(worker.posted("registry"), [], "matching never posts registry operations")
        self.assertEqual({op["op"] for op in worker.ops}, {"fact.upsert", "review.open"})
        fact, = [op for op in worker.ops if op["op"] == "fact.upsert"]
        self.assertEqual((fact["field"], fact["value_json"]), ("ais.call_sign", {"mmsi": str(HELD_MMSI), "value": "WDX9999"}))
        review, = [op for op in worker.ops if op["op"] == "review.open"]
        self.assertEqual(review_id(review["kind"], review["fingerprint"]), id32("mmsi", f"{HELD}|{OTHER}"))
        # A match hook that tried to hand the registry's MMSI to another vessel is ignored.
        hooks = {"match": lambda ctx: {HELD_MMSI: VesselRef(SEA, "six-pack", "port-a")}}
        positions = [AisPosition(HELD_MMSI, NOW - 2 * HOUR + k * MINUTE, 11.0 + k * 0.002, -150.0, 6.0, 0.0, None, None,
                                 "PositionReport", "aisstream", NOW) for k in range(60)]
        self.store.write(positions=positions)
        refs = []
        original = process.derive
        try:
            process.derive = lambda positions, mmsi, ref, *a, **k: refs.append((mmsi, ref)) or original(positions, mmsi, ref, *a, **k)
            process.run(REGION, FakeWorker(), root=self.root, now_ms=NOW + HOUR, hook_table=hooks)
        finally:
            process.derive = original
        self.assertEqual(refs, [(HELD_MMSI, VesselRef(HELD, "inspected-party", "port-b"))])

    def test_a_lost_state_keeps_watched_rows_without_statics(self):
        prior = {"mmsi": str(CANDIDATE), "vessel_id": SEA, "match_method": "geofence-presence", "confidence": 0.85,
                 "status": "watched", "ais_name": "SEA EXAMPLE", "ais_call_sign": None, "ais_class": "B",
                 "first_seen_at": "2026-09-01T00:00:00.000Z", "last_seen_at": "2026-10-01T00:00:00.000Z",
                 "last_seen_source": "aisstream", "positions_30d": 50}
        worker = FakeWorker(watch=[prior])
        self.run_once(worker)
        self.assertEqual(worker.watch[str(CANDIDATE)], prior, "no statics to judge by: the stored row stands")
        self.assertEqual(self.watched(), [CANDIDATE])

    def test_a_lost_state_rereads_the_real_statics(self):
        """Statics older than the first scan's lookback are re-read, so a contradiction is not lost as 'unknown'."""
        self.store.write(statics=[static(PLEASURE, T0 - 40 * DAY, "SEA EXAMPLE", ship_type=37, bow=5, stern=3)],
                         discovery=moored(PLEASURE, [1, 2, 3]))
        prior = {"mmsi": str(PLEASURE), "vessel_id": SEA, "match_method": "ais-static-name", "confidence": 0.4,
                 "status": "candidate", "ais_name": "SEA EXAMPLE", "ais_call_sign": None, "ais_class": "B",
                 "first_seen_at": "2026-08-26T00:00:00.000Z", "last_seen_at": "2026-10-04T00:00:00.000Z",
                 "last_seen_source": "aisstream", "positions_30d": 9}
        worker = FakeWorker(watch=[prior])
        self.run_once(worker)
        row = worker.watch[str(PLEASURE)]
        self.assertEqual((row["status"], row["confidence"]), ("candidate", 0.4), "8 m against 60 ft, as stored")
        self.assertEqual([op["proposal_json"]["reason"] for op in worker.ops if op["op"] == "review.open"],
                         ["length-contradicts"])
        self.assertEqual(self.watched(), [])


class ScheduleTests(unittest.TestCase):
    """Stage 4, schedule-correlation (N4): at-sea days against landing report days."""

    def decide(self, statics, *, at_sea, reports, presence=None, prior=None, vessels=None):
        statics = {s.mmsi: s for s in statics}
        seen = {m: Seen(T0 - 20 * DAY, T0, "aisstream", 400) for m in statics}
        presence = {m: {"port-a": 1} for m in statics} if presence is None else presence
        return decide(REGION, fleet() if vessels is None else vessels, (), statics, seen, presence, prior or {}, NOW,
                      at_sea=at_sea, reports=reports)

    def rows(self, decision):
        return {int(r["mmsi"]): r for r in decision.rows}

    def test_thresholds_come_from_the_region(self):
        self.assertEqual(schedule.rules(REGION), schedule.Rules(5, 14, 3, 1, 30))
        self.assertEqual(schedule.span_days(TWO_WEEKS), 14)
        self.assertEqual(schedule.span_days(ONE_WEEK), 5)
        self.assertEqual(schedule.span_days([]), 0)

    def test_five_matched_days_over_two_weeks_promote_to_watched(self):
        boat = full_static(CANDIDATE, "SEA EXAMPLE", ship_type=60, length_m=18.0)
        at_sea = {CANDIDATE: set(TWO_WEEKS) | {"2026-10-04"}}   # a day at sea without a report does not count
        decision = self.decide([boat], at_sea=at_sea, reports={SEA: set(TWO_WEEKS)})
        row = self.rows(decision)[CANDIDATE]
        self.assertEqual((row["status"], row["match_method"], row["vessel_id"]), ("watched", "schedule-correlation", SEA))
        self.assertGreaterEqual(row["confidence"], AUTO)
        self.assertEqual(decision.targets, {CANDIDATE: VesselRef(SEA, "inspected-party", "port-a")})
        self.assertEqual(decision.reviews, [])
        # Four of the five days is not enough.
        four = self.decide([boat], at_sea={CANDIDATE: set(TWO_WEEKS[1:])}, reports={SEA: set(TWO_WEEKS)})
        self.assertEqual(self.rows(four)[CANDIDATE]["status"], "candidate")
        # Once watched it stays watched while the name matches, even when this run's feed could not be read.
        sticky = self.decide([boat], at_sea={}, reports=None, prior={CANDIDATE: row})
        self.assertEqual((self.rows(sticky)[CANDIDATE]["status"], self.rows(sticky)[CANDIDATE]["match_method"]),
                         ("watched", "schedule-correlation"))

    def test_five_matched_days_inside_one_week_stay_a_candidate(self):
        boat = full_static(CANDIDATE, "SEA EXAMPLE", ship_type=60, length_m=18.0)
        decision = self.decide([boat], at_sea={CANDIDATE: set(ONE_WEEK)}, reports={SEA: set(ONE_WEEK)})
        row = self.rows(decision)[CANDIDATE]
        self.assertEqual((row["status"], row["match_method"], row["confidence"]), ("candidate", "ais-static-name", 0.7))
        self.assertEqual(decision.targets, {})

    def test_a_rival_vessel_reporting_on_the_same_days_is_a_review_never_watched(self):
        vessels = fleet() + [vessel(RIVAL, "Rival Example")]   # the same home port, port-a
        boat = full_static(CANDIDATE, "SEA EXAMPLE", ship_type=60, length_m=18.0)
        reports = {SEA: set(TWO_WEEKS), RIVAL: set(TWO_WEEKS)}
        decision = self.decide([boat], at_sea={CANDIDATE: set(TWO_WEEKS)}, reports=reports, vessels=vessels)
        row = self.rows(decision)[CANDIDATE]
        self.assertEqual((row["status"], row["vessel_id"]), ("candidate", SEA))
        self.assertEqual(decision.targets, {})
        review, = decision.reviews
        self.assertEqual((review["subject_id"], review["proposal_json"]["reason"]), (SEA, "schedule-rival"))
        self.assertEqual(review["candidate_json"]["schedule_days"], 5)
        # A rival also undoes stickiness.
        watched = {**row, "status": "watched", "match_method": "schedule-correlation", "confidence": 0.85}
        again = self.decide([boat], at_sea={CANDIDATE: set(TWO_WEEKS)}, reports=reports, vessels=vessels,
                            prior={CANDIDATE: watched})
        self.assertEqual(self.rows(again)[CANDIDATE]["status"], "candidate")
        # Another port's boat on the same days is no rival.
        elsewhere = fleet() + [vessel(RIVAL, "Rival Example", port="port-b")]
        self.assertEqual(self.rows(self.decide([boat], at_sea={CANDIDATE: set(TWO_WEEKS)}, reports=reports,
                                               vessels=elsewhere))[CANDIDATE]["status"], "watched")
        sea = {CANDIDATE: set(TWO_WEEKS)}
        close = self.decide([boat], at_sea=sea, reports={SEA: set(TWO_WEEKS), RIVAL: set(TWO_WEEKS[:4])}, vessels=vessels)
        self.assertEqual((self.rows(close)[CANDIDATE]["status"], [r["proposal_json"]["reason"] for r in close.reviews]),
                         ("candidate", ["schedule-rival"]), "5 matched days against 4: a lead of 1 is no lead")
        clear = self.decide([boat], at_sea=sea, reports={SEA: set(TWO_WEEKS), RIVAL: set(TWO_WEEKS[:2])}, vessels=vessels)
        self.assertEqual((self.rows(clear)[CANDIDATE]["status"], clear.reviews), ("watched", []), "5 against 2: a lead of 3")

    def test_days_in_port_with_a_report_count_against_the_match(self):
        boat = full_static(CANDIDATE, "SEA EXAMPLE", ship_type=60, length_m=18.0)
        sea, reports = {CANDIDATE: set(TWO_WEEKS)}, {SEA: set(TWO_WEEKS) | {"2026-10-01", "2026-10-02"}}

        def run(in_port):
            statics = {boat.mmsi: boat}
            seen = {boat.mmsi: Seen(T0 - 20 * DAY, T0, "aisstream", 400)}
            return decide(REGION, fleet(), (), statics, seen, {CANDIDATE: {"port-a": 1}}, {}, NOW, at_sea=sea,
                          reports=reports, in_port={CANDIDATE: in_port})
        one = run({"2026-10-01"})
        self.assertEqual(self.rows(one)[CANDIDATE]["status"], "watched", "one contradiction is tolerated")
        two = run({"2026-10-01", "2026-10-02"})
        self.assertEqual((self.rows(two)[CANDIDATE]["status"], [r["proposal_json"]["reason"] for r in two.reviews]),
                         ("candidate", ["schedule-rival"]))
        # A day in port that was also a day at sea (arrived that day) is no contradiction.
        self.assertEqual(self.rows(run(set(TWO_WEEKS)))[CANDIDATE]["status"], "watched")

    def test_a_watched_schedule_row_is_undone_by_a_late_rival_or_a_lapse(self):
        vessels = fleet() + [vessel(RIVAL, "Rival Example")]
        boat = full_static(CANDIDATE, "SEA EXAMPLE", ship_type=60, length_m=18.0)
        watched = {"mmsi": str(CANDIDATE), "vessel_id": SEA, "status": "watched", "match_method": "schedule-correlation",
                   "confidence": 0.85}
        # Evidence aged below min_days (2 matched days) while a rival reports on 2 of them: no longer qualifies, yet demoted.
        aged = {CANDIDATE: set(TWO_WEEKS[3:])}
        reports = {SEA: set(TWO_WEEKS), RIVAL: set(TWO_WEEKS[3:])}
        rival = self.decide([boat], at_sea=aged, reports=reports, vessels=vessels, prior={CANDIDATE: watched})
        self.assertEqual(self.rows(rival)[CANDIDATE]["status"], "candidate")
        alone = self.decide([boat], at_sea=aged, reports={SEA: set(TWO_WEEKS)}, vessels=vessels, prior={CANDIDATE: watched})
        self.assertEqual(self.rows(alone)[CANDIDATE]["status"], "watched", "thin but recent evidence, no rival: stays")
        # No matched day in the last lapse_days (30): the row lapses. NOW is 2026-10-05.
        old = ["2026-08-20", "2026-08-25"]
        lapsed = self.decide([boat], at_sea={CANDIDATE: set(old)}, reports={SEA: set(old)}, prior={CANDIDATE: watched})
        self.assertEqual(self.rows(lapsed)[CANDIDATE]["status"], "candidate")
        none = self.decide([boat], at_sea={CANDIDATE: set()}, reports={SEA: set(TWO_WEEKS)}, prior={CANDIDATE: watched})
        self.assertEqual(self.rows(none)[CANDIDATE]["status"], "candidate")

    def test_the_registry_mmsi_is_never_overwritten(self):
        rival = full_static(OTHER, "HELD EXAMPLE", ship_type=60, length_m=18.0)
        held = full_static(HELD_MMSI, "HELD EXAMPLE", ship_type=60, length_m=18.0)
        decision = self.decide([held, rival], at_sea={OTHER: set(TWO_WEEKS)}, reports={HELD: set(TWO_WEEKS)},
                               presence={OTHER: {"port-b": 2}})
        rows = self.rows(decision)
        self.assertEqual((rows[HELD_MMSI]["status"], rows[HELD_MMSI]["match_method"]), ("watched", "fcc-uls"))
        self.assertEqual((rows[OTHER]["status"], rows[OTHER]["vessel_id"]), ("candidate", HELD))
        self.assertEqual(decision.targets, {HELD_MMSI: VesselRef(HELD, "inspected-party", "port-b")})
        self.assertEqual([r["proposal_json"]["reason"] for r in decision.reviews], ["vessel-has-registry-mmsi"])

    def test_unknown_statics_do_not_block_the_schedule_but_contradictions_and_absence_do(self):
        at_sea, reports = {OTHER: set(TWO_WEEKS)}, {SEA: set(TWO_WEEKS)}
        unknown = self.decide([full_static(OTHER, "SEA EXAMPLE")], at_sea=at_sea, reports=reports)
        self.assertEqual((self.rows(unknown)[OTHER]["status"], self.rows(unknown)[OTHER]["match_method"]),
                         ("watched", "schedule-correlation"))
        self.assertGreaterEqual(self.rows(unknown)[OTHER]["confidence"], AUTO)
        short = self.decide([full_static(OTHER, "SEA EXAMPLE", ship_type=37, length_m=8.0)], at_sea=at_sea, reports=reports)
        self.assertEqual(self.rows(short)[OTHER]["status"], "candidate")
        self.assertEqual([r["proposal_json"]["reason"] for r in short.reviews], ["length-contradicts"])
        never = self.decide([full_static(OTHER, "SEA EXAMPLE")], at_sea=at_sea, reports=reports, presence={})
        self.assertEqual(self.rows(never)[OTHER]["status"], "candidate", "never seen in the home port")
        self.assertEqual([r["proposal_json"]["reason"] for r in never.reviews], ["never-in-home-port"])
        twins = [vessel(SEA, "Twin Example"), vessel(TWIN, "Twin Example")]
        both = self.decide([full_static(OTHER, "TWIN EXAMPLE", ship_type=60, length_m=18.0)], at_sea=at_sea,
                           reports={SEA: set(TWO_WEEKS), TWIN: set(TWO_WEEKS)}, vessels=twins,
                           presence={OTHER: {"port-a": 1}})
        self.assertEqual(self.rows(both)[OTHER]["status"], "candidate", "two vessels of one name never promote")
        # Without schedule inputs the matcher behaves as before.
        none = self.decide([full_static(OTHER, "SEA EXAMPLE")], at_sea=None, reports=None)
        self.assertEqual(self.rows(none)[OTHER]["status"], "candidate")

    def test_report_days_read_the_feed_as_trip_pairing_does(self):
        vessels = [vessel(SEA, "Sea Example", port="morro-bay", aliases=("SEAEX",)),
                   vessel(TWIN, "Twin Example", port="morro-bay"), vessel(RIVAL, "Twin Example", port="morro-bay"),
                   {**vessel(HELD, "Gone Example", port="morro-bay"), "status": "excluded"}]
        rows = [{"id": "1", "date": "2026-10-01", "boat": "Sea Example", "port": "Morro Bay"},
                {"id": "2", "date": "2026-10-02", "boat": "F/V SEAEX", "port": "morro bay"},      # alias, any case
                {"id": "3", "date": "2026-10-03", "boat": "Sea Example", "port": "Avila Beach"},   # another port
                {"id": "4", "date": "2026-10-04", "boat": "Twin Example", "port": "Morro Bay"},    # two vessels
                {"id": "5", "date": "2026-10-05", "boat": "Gone Example", "port": "Morro Bay"},    # excluded
                {"id": "6", "date": "Oct 6", "boat": "Sea Example", "port": "Morro Bay"}]
        self.assertEqual(schedule.report_days(rows, vessels, schedule.landing_ports()),
                         {SEA: {"2026-10-01", "2026-10-02"}})

    def test_the_feed_loader_reads_each_coastal_region_once_and_fails_soft(self):
        ca = load_region("CA")
        urls = schedule.feed_urls(ca)
        self.assertIn("https://raw.githubusercontent.com/Grahammmm/skippercast/data/regions/morro-bay/latest.json", urls)
        self.assertEqual(len(urls), len(set(urls)))
        self.assertEqual(schedule.feed_urls(REGION), [], "synthetic ports belong to no coastal region")
        vessels = [vessel(SEA, "Sea Example", port="morro-bay")]
        fetched = []

        def fetch(url):
            fetched.append(url)
            if "morro-bay" not in url:
                raise OSError("offline")
            return {"reports": [{"id": "1", "date": "2026-10-01", "boat": "Sea Example", "port": "Morro Bay"}]}

        self.assertEqual(schedule.load_report_days(ca, vessels, fetch=fetch), {SEA: {"2026-10-01"}})
        self.assertEqual(sorted(fetched), urls)

        def down(url):
            raise OSError("offline")

        self.assertIsNone(schedule.load_report_days(ca, vessels, fetch=down), "no feed read: no schedule evidence")

    def test_the_state_records_days_at_sea(self):
        state = process.State(Path(self.tmp()) / "state.sqlite")
        self.addCleanup(state.close)
        mstate = MatchState(state)
        lat, lon = PORT_A.point
        fix = lambda ts, la, lo: AisPosition(CANDIDATE, ts, la, lo, 6.0, None, None, None, "PositionReport", "aisstream", ts)
        mstate.add((), [fix(T0, lat, lon), fix(T0 + HOUR, lat + 0.2, lon),          # 2026-10-05: out and back
                        fix(T0 - DAY, lat, lon),                                     # 2026-10-04: in port only
                        fix(T0 - 2 * DAY, lat + 0.5, lon)], REGION.ports, match.ZoneInfo(REGION.timezone))
        self.assertEqual(mstate.away("2026-09-01"), {CANDIDATE: {"2026-10-03", "2026-10-05"}})
        self.assertEqual(mstate.presence("2026-09-01"), {CANDIDATE: {"port-a": 2}})
        mstate.prune("2026-10-04")
        self.assertEqual(mstate.away("2026-09-01"), {CANDIDATE: {"2026-10-05"}})

    def tmp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return directory.name

    def test_a_run_promotes_by_schedule_from_the_state_and_the_feed(self):
        root = Path(self.tmp()) / "CA" / "ais"
        AisStore(root).write(statics=[static(CANDIDATE, T0 - DAY, "SEA EXAMPLE", ship_type=60, bow=12, stern=6)])
        state = process.State(root / "state.sqlite")
        mstate = MatchState(state)
        state.db.executemany("INSERT INTO match_away VALUES(?,?)", [(CANDIDATE, d) for d in TWO_WEEKS])
        state.db.execute("INSERT INTO match_presence VALUES(?,?,?)", (CANDIDATE, "port-a", "2026-10-04"))
        state.close()
        del mstate
        calls = []
        original = match.load_report_days
        match.load_report_days = lambda region, vessels: calls.append(len(vessels)) or {SEA: set(TWO_WEEKS)}
        try:
            worker = FakeWorker()
            process.run(REGION, worker, root=root, now_ms=NOW)
        finally:
            match.load_report_days = original
        self.assertEqual(calls, [2], "the loader sees the snapshot's vessels")
        row = worker.watch[str(CANDIDATE)]
        self.assertEqual((row["status"], row["vessel_id"], row["match_method"]), ("watched", SEA, "schedule-correlation"))
        self.assertEqual(sorted(read_watch(root / "watch.json", "CA").watched), [CANDIDATE])

    def test_precision_scores_promotions_against_hidden_registry_mmsis(self):
        vessels = [vessel(SEA, "Sea Example", mmsi=CANDIDATE), vessel(TWIN, "Twin Example", mmsi=PLEASURE, port="port-b"),
                   vessel(RIVAL, "Rival Example", port="port-b")]
        other_days = ["2026-09-21", "2026-09-24", "2026-09-27", "2026-10-01", "2026-10-04"]
        statics = {CANDIDATE: full_static(CANDIDATE, "SEA EXAMPLE", ship_type=60, length_m=18.0),
                   OTHER: full_static(OTHER, "TWIN EXAMPLE", ship_type=60, length_m=18.0),     # not Twin's MMSI
                   HELD_MMSI: full_static(HELD_MMSI, "RIVAL EXAMPLE", ship_type=60, length_m=18.0)}
        seen = {m: Seen(T0 - 20 * DAY, T0, "aisstream", 100) for m in statics}
        presence = {CANDIDATE: {"port-a": 9}, OTHER: {"port-b": 1}, HELD_MMSI: {"port-b": 1}}
        at_sea = {CANDIDATE: set(TWO_WEEKS), OTHER: set(TWO_WEEKS), HELD_MMSI: set(other_days)}
        reports = {SEA: set(TWO_WEEKS), TWIN: set(TWO_WEEKS[:4]) | {"2026-10-04"}, RIVAL: set(other_days)}
        window = (statics, seen, presence, at_sea, NOW)
        counts = schedule.precision(REGION, vessels, [], [window], reports)
        self.assertEqual(counts, {"windows": 1, "schedule_matches": 2, "correct": 1, "false_matches": 0,
                                  "unverified": 1, "rival_reviews": 0, "precision": 1.0},
                         "nine home-port days cannot promote by geofence here; Twin's four matched days do not qualify")
        reports[TWIN] = set(TWO_WEEKS)
        counts = schedule.precision(REGION, vessels, [], [window, window], reports)
        self.assertEqual((counts["schedule_matches"], counts["correct"], counts["false_matches"], counts["unverified"],
                          counts["precision"]), (6, 2, 2, 2, 0.5), "OTHER now matches Twin's schedule: a false match")
        # Two boats of one port reporting on the same days: reviews, not matches.
        reports[RIVAL] = set(TWO_WEEKS)
        at_sea[HELD_MMSI] = set(TWO_WEEKS)
        counts = schedule.precision(REGION, vessels, [], [window], reports)
        self.assertEqual((counts["schedule_matches"], counts["rival_reviews"]), (1, 2))

    def test_schedule_precision_command_over_a_store(self):
        directory = Path(self.tmp())
        root = directory / "CA" / "ais"
        lat, lon = PORT_A.point
        offsets = [15, 12, 9, 5, 2]   # local days 2026-09-20 .. 2026-10-03, as TWO_WEEKS
        positions = moored(CANDIDATE, [1]) + [
            AisPosition(CANDIDATE, T0 - k * DAY + 12 * HOUR, lat + 0.3, lon, 7.0, None, None, None, "PositionReport",
                        "aisstream", T0 - k * DAY + 12 * HOUR) for k in offsets]
        AisStore(root).write(statics=[static(CANDIDATE, T0 - 16 * DAY, "SEA EXAMPLE", ship_type=60, bow=12, stern=6)],
                             positions=positions)
        (directory / "vessels.json").write_text(json.dumps([vessel(SEA, "Sea Example", mmsi=CANDIDATE, port="port-a")]))
        reports = [{"id": str(i), "date": d, "boat": "Sea Example", "port": "Port A"} for i, d in enumerate(TWO_WEEKS)]
        (directory / "reports.json").write_text(json.dumps({"reports": reports}))
        original = schedule.landing_ports
        schedule.landing_ports = lambda root=None: {"port a": "port-a"}
        out = io.StringIO()
        try:
            from skippercast.fleet import config
            saved = config.load_region
            config.load_region = lambda ident: REGION
            with contextlib.redirect_stdout(out):
                code = schedule.main(["--region", "CA", "--from", "2026-09-06", "--to", "2026-10-05",
                                      "--reports", str(directory / "reports.json"), "--vessels",
                                      str(directory / "vessels.json"), "--source", "aisstream", "--root", str(root)])
        finally:
            schedule.landing_ports = original
            config.load_region = saved
        self.assertEqual(code, 0)
        result = json.loads(out.getvalue())
        self.assertEqual((result["report_rows"], result["schedule_matches"], result["correct"], result["false_matches"],
                          result["precision"]), (5, 1, 1, 0, 1.0))
        self.assertNotIn(str(CANDIDATE), out.getvalue(), "counts only")


class GateTests(unittest.TestCase):
    """The watched gate (N4, design § 11): strong methods and confidence >= 0.85."""

    def row(self, **extra):
        return {"mmsi": str(OTHER), "vessel_id": SEA, "match_method": "geofence-presence", "confidence": 0.85,
                "status": "watched", **extra}

    def test_gate_problem(self):
        self.assertIsNone(match.gate_problem(self.row()))
        for method in ("fcc-uls", "admin", "schedule-correlation"):
            self.assertIsNone(match.gate_problem(self.row(match_method=method, confidence=0.9)), method)
        for method in ("call-sign", "ais-static-name"):
            self.assertIn("candidate-only", match.gate_problem(self.row(match_method=method, confidence=0.99)))
            self.assertIsNone(match.gate_problem(self.row(match_method=method, status="candidate")))
        self.assertIn("below", match.gate_problem(self.row(confidence=0.849)))
        self.assertIn("below", match.gate_problem(self.row(confidence=None)))
        self.assertIsNone(match.gate_problem(self.row(status="rejected", match_method="fcc-uls", confidence=0.0)))

    def test_decide_refuses_to_build_a_watched_row_that_fails_the_gate(self):
        """A region whose mmsi_auto were lowered (the loader refuses one) could not make match write a weak row."""
        weak = replace(REGION, thresholds={**REGION.thresholds,
                                           "match": {**REGION.thresholds["match"], "mmsi_auto": 0.5}})
        boat = full_static(CANDIDATE, "Sea Example", ship_type=60, length_m=18.0)
        seen = {CANDIDATE: Seen(T0, T0, "aisstream", 1)}
        with self.assertRaisesRegex(ValueError, "fails the gate: confidence 0.7 is below 0.85"):
            decide(weak, fleet(), (), {CANDIDATE: boat}, seen, {CANDIDATE: {"port-a": 3}}, {}, NOW)

    def test_watch_check_counts_by_method_and_fails_on_a_weak_watched_row(self):
        good = [self.row(mmsi="999000401"), self.row(mmsi="999000402", match_method="fcc-uls", confidence=0.9),
                self.row(mmsi="999000403", match_method="call-sign", confidence=0.8, status="candidate")]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(gate.main(["--region", "CA"], worker=FakeWorker(watch=good)), 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["counts"], {"candidate": {"call-sign": 1},
                                            "watched": {"fcc-uls": 1, "geofence-presence": 1}})
        self.assertEqual((result["failed"], result["failures"]), (0, {}))
        self.assertNotIn("999000401", out.getvalue(), "counts only")
        bad = good + [self.row(mmsi="999000404", match_method="ais-static-name", confidence=0.9),
                      self.row(mmsi="999000405", confidence=0.6)]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(gate.main(["--region", "CA"], worker=FakeWorker(watch=bad)), 1)
        result = json.loads(out.getvalue())
        self.assertEqual((result["failed"], result["failures"]), (2, {"ais-static-name": 1, "geofence-presence": 1}))

    def test_the_command_line_lists_the_new_commands(self):
        from skippercast.fleet.ais.__main__ import COMMANDS
        self.assertIn("watch-check", COMMANDS)
        self.assertIn("schedule-precision", COMMANDS)

    def test_the_region_floor(self):
        self.assertGreaterEqual(REGION.thresholds["match"]["mmsi_auto"], match.WATCHED_MIN_CONFIDENCE)


if __name__ == "__main__":
    unittest.main()
