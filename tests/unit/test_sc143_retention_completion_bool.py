"""SC143 retention settlement contract; synthetic roots only."""
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from skippercast.coastal.retention import LIMITS, TOTAL, Retention


class Truthy:
    def __bool__(self):
        return True


class RetentionCompletionBooleanTests(unittest.TestCase):
    negative_control_result = {}

    @classmethod
    def setUpClass(cls):
        inherited = os.environ.get("SC143_RUN_ROOT")
        if inherited:
            cls._temporary = None
            cls._base = Path(inherited).resolve()
        else:
            cls._temporary = tempfile.TemporaryDirectory(prefix="sc143-retention-")
            cls._base = Path(cls._temporary.name).resolve()
        cls._base.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if cls._temporary is not None:
            cls._temporary.cleanup()

    def setUp(self):
        self.root = self._base / (self._testMethodName + "-" + str(os.getpid()))
        self.root.mkdir(parents=True, exist_ok=False)
        self.ledger = Retention.create(self.root, "plan-digest-fixture")

    def reserve(self, slot):
        entry = self.ledger.reserve(slot, "intent-" + slot, "outputs/" + slot, role=slot)
        target = self.root / entry["directory"]
        target.mkdir(parents=True, exist_ok=False)
        (target / "retained.bin").write_bytes((slot + "-synthetic-output").encode())
        return entry

    def test_boolean_outcomes_persist_and_reservation_is_immutable(self):
        self.reserve("mapping")
        self.reserve("render")
        expected_sizes = {"mapping": len(b"mapping-synthetic-output"),
                          "render": len(b"render-synthetic-output")}
        for slot, completed, expected in (("mapping", True, "complete"),
                                          ("render", False, "uncertain")):
            with self.subTest(slot=slot):
                original = dict(self.ledger.read()["reservations"][slot])
                returned = self.ledger.settle(slot, completed=completed)
                self.assertEqual(returned["slots"][slot], expected_sizes[slot])
                self.assertEqual(returned["observed_bytes"],
                                 sum(returned["slots"].values()) + returned["control_bytes"])
                reopened = Retention(self.root, "plan-digest-fixture")
                state = reopened.read()
                self.assertEqual(state["reservations"][slot]["state"], expected)
                self.assertEqual(state["reservations"][slot]["observed_bytes"], expected_sizes[slot])
                for key in ("bytes", "intent_digest", "role", "directory"):
                    self.assertEqual(state["reservations"][slot][key], original[key])
                self.assertEqual(state["plan_digest"], "plan-digest-fixture")
                self.assertEqual(state["limits"], LIMITS)
                self.assertEqual(state["total_bytes"], TOTAL)
                reopened.reserve(slot, "intent-" + slot, "outputs/" + slot, role=slot)
                self.assertEqual(reopened.read()["reservations"][slot]["bytes"], original["bytes"])
                reopened.settle(slot, completed=completed)
                self.assertEqual(reopened.read()["reservations"][slot]["bytes"], original["bytes"])
                self.assertEqual(len(reopened.read()["reservations"]), 2)

    def _tree_snapshot(self):
        result = {}
        for path in sorted(self.root.rglob("*")):
            relative = path.relative_to(self.root).as_posix()
            if path.is_file():
                result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                result[relative] = "directory"
        return result

    def test_nonbooleans_fail_before_side_effects_for_both_states(self):
        malformed = (None, 0, 1, 0.0, 1.0, "", "false", [], [1], {}, {"x": 1}, Truthy())
        for initial_state in ("reserved", "uncertain"):
            with self.subTest(initial_state=initial_state):
                slot = "mapping" if initial_state == "reserved" else "render"
                self.reserve(slot)
                if initial_state == "uncertain":
                    self.ledger.settle(slot, completed=False)
                for index, value in enumerate(malformed):
                    with self.subTest(initial_state=initial_state, value=repr(value)):
                        before = self._tree_snapshot()
                        with patch.object(self.ledger, "audit", side_effect=AssertionError("audit entered")) as audit, patch.object(self.ledger, "lock", side_effect=AssertionError("lock entered")) as lock:
                            with self.assertRaisesRegex(ValueError, "completed.*bool"):
                                self.ledger.settle(slot, completed=value)
                        audit.assert_not_called()
                        lock.assert_not_called()
                        self.assertEqual(self._tree_snapshot(), before)
                        self.assertTrue(any(name.endswith("retained.bin") for name in before))

    def test_negative_control_detects_truthiness_regression(self):
        slot = "mapping"
        self.reserve(slot)
        original = Retention.settle
        expected_red = None

        def bypass_boolean_preflight(instance, selected, *, completed):
            before = instance.audit()
            with instance.lock():
                state = instance.read()
                entry = state["reservations"][selected]
                entry["state"] = "complete" if completed else "uncertain"
                entry["observed_bytes"] = before["slots"][selected]
                from skippercast.coastal.handoff.common import write
                write(instance.path, state)
            return before

        try:
            with patch.object(Retention, "settle", bypass_boolean_preflight):
                self.ledger.settle(slot, completed="false")
                state = Retention(self.root, "plan-digest-fixture").read()
                try:
                    self.assertEqual(state["reservations"][slot]["state"], "uncertain")
                except AssertionError as exc:
                    expected_red = str(exc)
            if not expected_red:
                self.fail("negative control did not detect the truthiness defect")
            self.assertIn("complete", expected_red)
            RetentionCompletionBooleanTests.negative_control_result = {
                "mutant_detected": True, "positive_passed": False,
                "expected_red_assertion": expected_red}
            self.ledger.settle(slot, completed=False)
            self.assertEqual(Retention(self.root, "plan-digest-fixture").read()
                             ["reservations"][slot]["state"], "uncertain")
            RetentionCompletionBooleanTests.negative_control_result["positive_passed"] = True
        finally:
            self.assertIs(Retention.settle, original)


if __name__ == "__main__":
    unittest.main()
