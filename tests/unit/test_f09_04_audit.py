"""SCA-542 / F09-04 offline controls: a decided ``new-vessel`` review must create its vessel only once.

Contract protected: replaying the same fingerprint + decided new-vessel review against a later snapshot that
already holds the first creation yields the SAME vessel id and slug (no second profile for one boat), while a
distinct reviewed namesake still gets its own id.  Believable bug: ``_Resolver.create`` sees the first creation's
id in the snapshot and appends ``~<hash>``, minting a second id for the same decision.

The checker ``one_vessel`` is proven on synthetic good/bad observations (positive and negative control).
All resolver inputs are invented (example.com names, made-up fingerprints).
"""
from dataclasses import replace
import unittest

from skippercast.fleet import ops
from skippercast.fleet.resolve import Snapshot, fingerprint, resolve
from tests.unit.test_fleet_resolve import CONFIG, NOW, cand, of, stored


def decided_new(candidate):
    return {"id": ops.review_id("merge", fingerprint(candidate)), "kind": "merge", "status": "decided",
            "decision": {"action": "new-vessel"}}


def snapshot_with(vessel_op_row, review):
    """A later snapshot that contains the vessel the first pass emitted (id and slug taken from its op)."""
    row = stored(vessel_op_row["name"], n=1, id=vessel_op_row["id"], slug=vessel_op_row["slug"])
    return Snapshot([row], [review])


def one_vessel(observed_ids, observed_slugs):
    """Gap list for a replay: empty means one vessel id and one stable slug."""
    gaps = []
    if len(set(observed_ids)) != 1:
        gaps.append(f"split: {len(set(observed_ids))} vessel ids")
    if len(set(observed_slugs)) != 1:
        gaps.append(f"slug drift: {sorted(set(observed_slugs))}")
    return gaps


class CheckerControls(unittest.TestCase):
    def test_valid_control_passes(self):
        self.assertEqual(one_vessel(["a" * 32, "a" * 32], ["sea-example", "sea-example"]), [])

    def test_negative_control_detects_split(self):
        self.assertEqual(one_vessel(["a" * 32, "b" * 32], ["sea-example", "sea-example-2"]),
                         ["split: 2 vessel ids", "slug drift: ['sea-example', 'sea-example-2']"])


class ResolverReplay(unittest.TestCase):
    def first_pass(self):
        candidate = cand("Reel Example", "teck-reports", port=None)
        review = decided_new(candidate)
        result = resolve(Snapshot([], [review]), [candidate], CONFIG, NOW)
        (created,) = result.created
        return candidate, review, result, next(o for o in of(result, "vessel.upsert") if o["id"] == created)

    def test_first_pass_and_same_snapshot_rerun_are_stable(self):
        candidate, review, result, vessel = self.first_pass()
        again = resolve(Snapshot([], [review]), [candidate], CONFIG, NOW)
        (got,) = of(again, "vessel.upsert")
        self.assertEqual(one_vessel([result.created[0], again.created[0]], [vessel["slug"], got["slug"]]), [])
        ops.validate_op(vessel, 0, CONFIG.region)

    def test_distinct_reviewed_namesake_gets_separate_id(self):
        # Guard: the fix must not collapse genuinely different boats that share a name.
        candidate, review, result, vessel = self.first_pass()
        other = cand("Reel Example", "operator-site", ident="other", port="port-san-luis")
        snap = snapshot_with(vessel, decided_new(other))
        second = resolve(snap, [other], CONFIG, NOW)
        self.assertEqual(len(second.created), 1)
        self.assertNotEqual(second.created[0], vessel["id"])

    def test_distinct_reviews_with_colliding_base_keys_keep_separate_ids(self):
        # Same name/port and matching keys: a base-key lookup alone would conflate these decisions.
        candidate, _, _, vessel = self.first_pass()
        other = replace(candidate, record_id="other")
        review = decided_new(other)
        first = resolve(Snapshot([], [review]), [other], CONFIG, NOW)
        second = resolve(snapshot_with(vessel, review), [other], CONFIG, NOW)
        self.assertEqual(len(second.created), 1)
        self.assertEqual(second.created, first.created)
        self.assertNotEqual(second.created[0], vessel["id"])
        (namesake,) = of(second, "vessel.upsert")
        self.assertNotEqual(namesake["slug"], vessel["slug"])
        snap = Snapshot(snapshot_with(vessel, review).vessels + snapshot_with(namesake, review).vessels, [review])
        replay = resolve(snap, [other], CONFIG, NOW)
        self.assertEqual(replay.created, [])
        (got,) = of(replay, "vessel.upsert")
        self.assertEqual((got["id"], got["slug"]), (namesake["id"], namesake["slug"]))

    def test_replay_over_snapshot_with_first_creation_keeps_one_vessel(self):
        candidate, review, _, vessel = self.first_pass()
        snapshot = snapshot_with(vessel, review)
        # A source can later supply a port for the same record, changing the base key but not the decision.
        for replayed in (candidate, replace(candidate, port_hint="port-san-luis")):
            with self.subTest(port=replayed.port_hint):
                replay = resolve(snapshot, [replayed], CONFIG, NOW)
                (got,) = of(replay, "vessel.upsert")
                self.assertEqual(one_vessel([vessel["id"], got["id"]], [vessel["slug"], got["slug"]]), [])
                self.assertEqual(replay.assignments[fingerprint(replayed)], vessel["id"])
                self.assertEqual(replay.created, [])


if __name__ == "__main__":
    unittest.main()
