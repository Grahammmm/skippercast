"""RF0834-5: an established watched row held by the same unique registry vessel survives missing statics.

Synthetic throughout (the invented boats, MMSIs and ports of ``test_fleet_match``); offline, a fake Worker and a
temporary store. Statics that expire or a processor state that is rebuilt must not demote the row or take the MMSI out
of the listener's ``watch.json``; a retained row is never a new admission.
"""
from pathlib import Path
import tempfile
import unittest

from skippercast.fleet.ais import process
from skippercast.fleet.ais.match import Seen, decide
from skippercast.fleet.ais.process import DAY, VesselRef
from skippercast.fleet.ais.store import AisStore
from skippercast.fleet.ais.watch import read_watch
from tests.unit.test_fleet_match import (
    HELD, HELD_MMSI, NOW, REGION, SEA, T0, FakeWorker, fleet, full_static, vessel)

REF = VesselRef(HELD, "inspected-party", "port-b")
SEEN = {HELD_MMSI: Seen(T0 - 5 * DAY, T0, "aisstream", 40)}


def established(vessels=None, **overrides):
    """The watched fcc-uls row ``decide`` itself builds from agreeing statics and one home-port day."""
    statics = {HELD_MMSI: full_static(HELD_MMSI, "HELD EXAMPLE", call_sign="WDX0002")}
    decision = decide(REGION, fleet() if vessels is None else vessels, (), statics, SEEN,
                      {HELD_MMSI: {"port-b": 1}}, {}, NOW)
    row, = decision.rows
    assert (row["status"], row["match_method"], decision.targets) == ("watched", "fcc-uls", {HELD_MMSI: REF})
    return {**row, **overrides}


def decide_without_statics(prior, *, vessels=None, reviews=(), sightings=True):
    return decide(REGION, fleet() if vessels is None else vessels, reviews, {}, SEEN if sightings else {}, {},
                  {HELD_MMSI: prior} if prior else {}, NOW)


class RetentionTests(unittest.TestCase):
    def test_same_registry_owner_retains_watched_without_statics(self):
        prior = established()
        for sightings in (True, False):   # positions remain / state lost both statics and sightings
            with self.subTest(sightings=sightings):
                decision = decide_without_statics(prior, sightings=sightings)
                self.assertEqual((decision.rows, decision.facts, decision.reviews), ([], [], []))
                self.assertEqual(decision.targets, {HELD_MMSI: REF})
        self.assertEqual(prior, established(), "the stored row is not rewritten")

    def test_missing_statics_does_not_admit_a_new_registry_binding(self):
        # Nothing established: never heard, or only a candidate/rejected row, gains no target and no watched row.
        for label, prior in (("no row", None), ("candidate", established(status="candidate", confidence=0.5)),
                             ("rejected", established(status="rejected", confidence=0.0))):
            for sightings in (True, False):
                with self.subTest(prior=label, sightings=sightings):
                    decision = decide_without_statics(prior, sightings=sightings)
                    self.assertEqual(decision.targets, {})
                    self.assertFalse([r for r in decision.rows if r["status"] == "watched"])
                    self.assertEqual((decision.facts, decision.reviews), ([], []))
        # Positions only, never judged: the existing candidate-without-static row, no target.
        decision = decide_without_statics(None)
        self.assertEqual(decision.targets, {})

    def test_retention_refuses_changed_or_ambiguous_ownership(self):
        twin = vessel(SEA, "Sea Example", mmsi=HELD_MMSI, call_sign="WDX0001")
        other = vessel("f" * 32, "Other Example", mmsi=HELD_MMSI, port="port-b")
        for label, vessels, prior in (
                ("different prior owner", fleet(), established(vessel_id=SEA)),
                ("duplicate owners", fleet() + [other], established()),
                ("registry MMSI moved to another vessel", [twin, vessel(HELD, "Held Example", port="port-b")],
                 established()),
                ("excluded owner", [{**v, "status": "excluded"} if v["id"] == HELD else v for v in fleet()],
                 established()),
                ("deleted owner", [v for v in fleet() if v["id"] != HELD], established()),
                ("weak method", fleet(), established(match_method="call-sign")),
                ("low confidence", fleet(), established(confidence=0.5)),
                ("nonfinite confidence", fleet(), established(confidence=float("nan"))),
                ("confidence above one", fleet(), established(confidence=1.5))):
            for sightings in (True, False):
                with self.subTest(case=label, sightings=sightings):
                    decision = decide_without_statics(prior, vessels=vessels, sightings=sightings)
                    self.assertNotIn(HELD_MMSI, decision.targets)
                    self.assertFalse([r for r in decision.rows if r["status"] == "watched"])
        # A rejection decision for the pair also stops it.
        rejected = [{"kind": "mmsi", "status": "decided", "subject_id": HELD,
                     "decision": {"action": "reject-mmsi", "vessel_id": HELD, "mmsi": str(HELD_MMSI)}}]
        decision = decide_without_statics(established(), reviews=rejected)
        self.assertNotIn(HELD_MMSI, decision.targets)

    def test_fresh_disagreement_still_demotes_and_reports(self):
        statics = {HELD_MMSI: full_static(HELD_MMSI, "NOT THE BOAT", call_sign="ZZZ9999")}
        decision = decide(REGION, fleet(), (), statics, SEEN, {HELD_MMSI: {"port-b": 1}}, {HELD_MMSI: established()}, NOW)
        row, = decision.rows
        self.assertEqual((row["status"], row["confidence"]), ("candidate", 0.5))
        self.assertEqual([r["proposal_json"]["reason"] for r in decision.reviews], ["registry-statics-disagree"])
        self.assertEqual(decision.targets, {})
        # Fresh agreeing statics with a home-port day still watch, as before.
        statics = {HELD_MMSI: full_static(HELD_MMSI, "HELD EXAMPLE")}
        decision = decide(REGION, fleet(), (), statics, SEEN, {HELD_MMSI: {"port-b": 1}}, {HELD_MMSI: established()}, NOW)
        self.assertEqual([r["status"] for r in decision.rows], ["watched"])
        # Statics present but the owner no longer matches: the sweep path still demotes (statics are not 'missing').
        statics = {HELD_MMSI: full_static(HELD_MMSI, "NOT THE BOAT")}
        decision = decide(REGION, fleet(), (), statics, SEEN, {}, {HELD_MMSI: established()}, NOW)
        self.assertEqual([r["status"] for r in decision.rows], ["candidate"])

    def test_watch_only_missing_statics_retention_is_unchanged(self):
        prior = established(vessel_id=SEA)
        decision = decide(REGION, fleet(), (), {}, {}, {}, {999000399: {**prior, "mmsi": "999000399"}}, NOW)
        self.assertEqual((decision.rows, decision.targets), ([], {999000399: VesselRef(SEA, "inspected-party", "port-a")}))


class ProcessRebuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "CA" / "ais"
        AisStore(self.root)   # an external, empty raw store: no statics and no sightings survive

    def test_processor_rebuild_keeps_registry_watch_json(self):
        prior = established()
        worker = FakeWorker(watch=[prior])
        process.run(REGION, worker, root=self.root, now_ms=NOW)
        self.assertEqual(worker.watch[str(HELD_MMSI)], prior, "the persisted row is unchanged")
        self.assertEqual(sorted(read_watch(self.root / "watch.json", "CA").watched), [HELD_MMSI])
        self.assertEqual([row for body in worker.posted("watch") for row in body.get("rows", [])], [], "no replacement row sent")

    def test_processor_rebuild_still_drops_a_row_whose_owner_changed(self):
        worker = FakeWorker(watch=[established(vessel_id=SEA)])
        process.run(REGION, worker, root=self.root, now_ms=NOW)
        self.assertEqual(worker.watch[str(HELD_MMSI)]["status"], "candidate")
        self.assertEqual(sorted(read_watch(self.root / "watch.json", "CA").watched), [])


if __name__ == "__main__":
    unittest.main()
