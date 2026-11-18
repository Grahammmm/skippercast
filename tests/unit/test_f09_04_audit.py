"""SCA-542 / F09-04 offline controls: a decided ``new-vessel`` review must create its vessel only once.

Contract protected: replaying the same fingerprint + decided new-vessel review against a later snapshot that
already holds the first creation yields the SAME vessel id and slug (no second profile for one boat), while a
distinct reviewed namesake still gets its own id.  Believable bug: ``_Resolver.create`` sees the first creation's
id in the snapshot and appends ``~<hash>``, minting a second id for the same decision.

Layout: the checker ``one_vessel`` is proven on synthetic good/bad observations (positive and negative control);
the real resolver replay is an ``expectedFailure`` (an unexpected pass fails the run) so CI stays green while the gap
is open and the marker must be removed once the resolver is fixed.  All data is invented (example.com names, made-up fingerprints).
"""
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
        self.assertEqual(one_vessel([result.created[0], again.created[0]], [vessel["slug"], vessel["slug"]]), [])

    def test_distinct_reviewed_namesake_gets_separate_id(self):
        # Guard: the fix must not collapse genuinely different boats that share a name.
        candidate, review, result, vessel = self.first_pass()
        other = cand("Reel Example", "operator-site", ident="other", port="port-san-luis")
        snap = snapshot_with(vessel, decided_new(other))
        second = resolve(snap, [other], CONFIG, NOW)
        self.assertEqual(len(second.created), 1)
        self.assertNotEqual(second.created[0], vessel["id"])

    @unittest.expectedFailure  # F09-04 open: replay mints a second id; remove once resolve.create reuses the creation
    def test_replay_over_snapshot_with_first_creation_keeps_one_vessel(self):
        candidate, review, result, vessel = self.first_pass()
        replay = resolve(snapshot_with(vessel, review), [candidate], CONFIG, NOW)
        got = replay.assignments[fingerprint(candidate)]
        slugs = [vessel["slug"]] + [o["slug"] for o in of(replay, "vessel.upsert") if o["id"] == got]
        self.assertEqual(one_vessel([vessel["id"], got], slugs), [])
        self.assertEqual(replay.created, [])


if __name__ == "__main__":
    unittest.main()
