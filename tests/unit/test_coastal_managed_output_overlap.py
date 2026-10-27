"""ManagedOutputs._read() checks path overlap in linear time (T08-FIX4).

Attempt 5 of the 2026-10-19 four128 trial timed out at D-acquire because every
ledger operation re-read the ledger and compared each entry's path with every
earlier one (O(n^2) Path.is_relative_to calls: 0.92 s per read at 356 entries).
register_disjoint() keeps the same refusal ('managed output paths overlap') with
set lookups over each path's parents. These tests pin that the new check agrees
with the old pairwise predicate, stays fast at mission size, and still accepts
the preserved attempt-5 ledger unchanged.
"""
import hashlib
import json
import random
import tempfile
import time
import unittest
from pathlib import Path

from skippercast.coastal.handoff.common import digest
from skippercast.coastal.output_writer import (
    COMPACT_V3_PROFILE, MAX_FILES, ManagedOutputs, declaration, register_disjoint)

# Read-only: the preserved attempt-5 mission on the maintainer machine. Never copied
# into the repository; absent in CI, where the synthetic ledgers below carry the check.
ATTEMPT5_LEDGER = (Path.home() / "skippercast-data/2026-10-07-pge-south/outputs/t08-four128-20261019"
                   / "mission-attempt5-failed-D-acquire-native-timeout" / "managed-output.json")
ATTEMPT5_SHA256 = "60e54095b6c161446f282302049b22d6a71f6923e4d5062e876a756699024cc0"
ATTEMPT5_ENTRIES = 356


def pairwise_first_overlap(names):
    """The pre-FIX4 predicate verbatim: index of the first overlapping name, or None."""
    paths = []
    for index, name in enumerate(names):
        path = Path(name)
        if any(path.is_relative_to(other) or other.is_relative_to(path) for other in paths):
            return index
        paths.append(path)
    return None


def linear_first_overlap(names):
    registered, ancestors = set(), set()
    for index, name in enumerate(names):
        try:
            register_disjoint(Path(name), registered, ancestors)
        except ValueError as exc:
            assert str(exc) == "managed output paths overlap", exc
            return index
    return None


def mission_names(count):
    """Disjoint names shaped like a four128 mission ledger (checkpoints, metadata, tiles)."""
    names = []
    for i in range(count):
        window, stage = "ABCD"[i % 4], ("acquire", "qualify", "map", "review")[(i // 4) % 4]
        kind = i % 5
        if kind == 0:
            names.append(f".managed-checkpoints/control/launcher-{window}-{stage}-{i:03d}.json")
        elif kind == 1:
            names.append(f"metadata/qualify-{window}-{stage}-{i:03d}.json")
        elif kind == 2:
            names.append(f"execution/var/coastal/{window}/{stage}/tile-{i:03d}.tif")
        elif kind == 3:
            names.append(f"control/step-{window}-{stage}-{i:03d}.json")
        else:
            names.append(f"native/{window}/cells/{i:03d}/surface.npy")
    return names


def entry(name, *, role="control", size=4096, state="reserved"):
    intent = hashlib.sha256(name.encode()).hexdigest()
    return dict(role=role, bytes=size, intent=intent, state=state,
                binding=digest(dict(path=name, role=role, bytes=size, intent=intent)))


class OverlapPredicateEquivalence(unittest.TestCase):
    def test_crafted_cases_agree_with_the_pairwise_check(self):
        cases = {
            ("a", "a/b"): 1,          # child after its parent file
            ("a/b", "a"): 1,          # parent after its child file
            ("a", "ab"): None,        # shared string prefix is not a path prefix
            ("ab", "a"): None,
            ("a/b", "a/b/c"): 1,      # deeper descendant
            ("a/b/c", "a/b"): 1,      # deeper ancestor
            ("a/b/c", "a"): 1,
            ("a", "a/b/c"): 1,
            ("a/b", "a/c", "a/bc", "b/a"): None,  # siblings and lookalikes
            ("a/b", "a//b"): 1,       # same path, different spelling (Path normalises)
            ("a/b", "a/./b"): 1,
            ("x/y", "p", "x/y/z/w", "q"): 2,      # first overlap index is preserved
            ("x", "y", "z", "y/q"): 3,
        }
        for names, expected in cases.items():
            with self.subTest(names=names):
                self.assertEqual(pairwise_first_overlap(names), expected)
                self.assertEqual(linear_first_overlap(names), expected)

    def test_synthetic_mission_ledger_is_disjoint_under_both_checks(self):
        names = mission_names(400)
        self.assertEqual(len(set(names)), 400)
        self.assertIsNone(pairwise_first_overlap(names))
        self.assertIsNone(linear_first_overlap(names))
        # Appending any existing parent or a child of an existing file is refused by both.
        base = [Path(name) for name in names]
        for extra in ("metadata", "native/A", "metadata/qualify-B-acquire-001.json/x"):
            with self.subTest(extra=extra):
                path = Path(extra)
                self.assertTrue(any(path.is_relative_to(other) or other.is_relative_to(path) for other in base))
                self.assertEqual(linear_first_overlap(names + [extra]), 400)

    def test_random_paths_agree_with_the_pairwise_check(self):
        rng = random.Random(20261019)
        parts = ("a", "b", "ab", "c", "a.b")
        for trial in range(2000):
            names = ["/".join(rng.choice(parts) for _ in range(rng.randint(1, 4)))
                     for _ in range(rng.randint(1, 12))]
            with self.subTest(trial=trial, names=names):
                self.assertEqual(linear_first_overlap(names), pairwise_first_overlap(names))


class LedgerReadCost(unittest.TestCase):
    def test_read_of_a_400_entry_ledger_is_fast_and_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            grant = dict(output_root=str(root),
                         output_retention=declaration(0, 1 << 30, profile=COMPACT_V3_PROFILE))
            outputs = ManagedOutputs.create(root, grant, digest(grant))
            names = mission_names(400)
            self.assertLessEqual(len(names), MAX_FILES)
            with outputs.lock():
                state = outputs._read()
                state["files"] = {name: entry(name) for name in names}
                outputs._save(state)
            started = time.perf_counter()
            state = outputs._read()
            elapsed = time.perf_counter() - started
            self.assertEqual(list(state["files"]), sorted(names))  # the ledger is saved with sorted keys
            # The pairwise check took ~1.2 s here; generous bound for slow CI runners.
            self.assertLess(elapsed, 0.5)

            # An overlapping entry in the stored ledger is still refused with the same message.
            with outputs.lock():
                state["files"]["metadata"] = entry("metadata")
                outputs._save(state)
            with self.assertRaisesRegex(ValueError, "^managed output paths overlap$"):
                outputs._read()

    def test_reserve_file_refuses_overlap_as_before(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            grant = dict(output_root=str(root),
                         output_retention=declaration(0, 1 << 30, profile=COMPACT_V3_PROFILE))
            outputs = ManagedOutputs.create(root, grant, digest(grant))
            outputs.reserve_file("metadata/a.json", role="control", max_bytes=16, intent="a")
            outputs.reserve_file("metadata/ab.json", role="control", max_bytes=16, intent="ab")
            for name in ("metadata", "metadata/a.json/x"):
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "managed output paths overlap"):
                    outputs.reserve_file(name, role="control", max_bytes=16, intent="x")


class PreservedAttempt5Ledger(unittest.TestCase):
    def test_attempt5_ledger_is_accepted_unchanged(self):
        """Read-only. Off the maintainer machine (CI) the ledger is absent and this is a no-op,
        like the other preserved-ledger checks (strict CI skips are allow-listed only)."""
        if not ATTEMPT5_LEDGER.is_file():
            return
        before = ATTEMPT5_LEDGER.stat()
        data = ATTEMPT5_LEDGER.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), ATTEMPT5_SHA256)
        ledger = json.loads(data)
        names = list(ledger["files"])
        self.assertEqual(len(names), ATTEMPT5_ENTRIES)
        self.assertIsNone(pairwise_first_overlap(names))
        self.assertIsNone(linear_first_overlap(names))

        # The real _read() over the preserved bytes, bound to the ledger's own identity
        # (its grant is not re-created here); it only stats and reads the file.
        outputs = object.__new__(ManagedOutputs)
        outputs.root = ATTEMPT5_LEDGER.parent.resolve(strict=True)
        outputs.path = outputs.root / "managed-output.json"
        outputs.lock_path = outputs.root / "managed-output.lock"
        outputs.profile, outputs.plan = ledger["schema"], ledger["plan"]
        outputs.limits, outputs.grant_digest = ledger["plan"]["limits"], ledger["grant_digest"]
        started = time.perf_counter()
        state = outputs._read()
        elapsed = time.perf_counter() - started
        self.assertEqual(state, ledger)
        self.assertLess(elapsed, 0.5)
        after = ATTEMPT5_LEDGER.stat()
        self.assertEqual((after.st_size, after.st_mtime_ns), (before.st_size, before.st_mtime_ns))
        self.assertEqual(hashlib.sha256(ATTEMPT5_LEDGER.read_bytes()).hexdigest(), ATTEMPT5_SHA256)


if __name__ == "__main__":
    unittest.main()
