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

from skippercast.fleet.ais import match, process
from skippercast.fleet.ais.match import Seen, Static, decide
from skippercast.fleet.ais.process import DAY, HOUR, MINUTE, VesselRef
from skippercast.fleet.ais.sources.base import AisPosition, AisStatic
from skippercast.fleet.ais.store import AisStore
from skippercast.fleet.ais.watch import read_watch
from skippercast.fleet.config import Port, load_region
from skippercast.fleet.ops import id32, review_id

T0 = 1_791_190_800_000          # 2026-10-05T09:00:00Z (02:00 in Los Angeles)
NOW = T0 + 10 * HOUR            # 12:00 local on 2026-10-05
SEA, HELD, TWIN = id32("CA", "sea-example"), id32("CA", "held-example"), id32("CA", "twin-example")
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
        unknown = full_static(OTHER, "SEA EXAMPLE")
        row = self.rows(self.decide([unknown]))[OTHER]
        self.assertEqual((row["status"], row["confidence"]), ("candidate", 0.6))
        promoted = self.rows(self.decide([unknown], presence={OTHER: {"port-a": 3}}))[OTHER]
        self.assertEqual((promoted["status"], promoted["confidence"]), ("watched", AUTO))

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
        decision = self.decide([], prior={OTHER: gone})
        self.assertEqual(decision.rows, [{**gone, "status": "candidate"}])


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

    def test_a_lost_state_keeps_watched_rows(self):
        prior = {"mmsi": str(CANDIDATE), "vessel_id": SEA, "match_method": "geofence-presence", "confidence": 0.85,
                 "status": "watched", "ais_name": "SEA EXAMPLE", "ais_call_sign": None, "ais_class": "B",
                 "first_seen_at": "2026-09-01T00:00:00.000Z", "last_seen_at": "2026-10-01T00:00:00.000Z",
                 "last_seen_source": "aisstream", "positions_30d": 50}
        worker = FakeWorker(watch=[prior])
        self.run_once(worker)
        self.assertEqual(worker.watch[str(CANDIDATE)]["status"], "watched")
        self.assertEqual(self.watched(), [CANDIDATE])


if __name__ == "__main__":
    unittest.main()
