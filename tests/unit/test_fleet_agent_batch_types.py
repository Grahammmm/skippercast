"""Fleet manifest batch_size admission: only a plain int in 1-20 (synthetic vessels, tmp dirs only)."""
import json
from pathlib import Path
import tempfile
import unittest

from skippercast.fleet import agent
from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.resolve import Snapshot
from skippercast.fleet.runs import Run
from tests.unit.test_fleet_agent import REGION, vessel_row

NOW = "2026-10-11T10:17:00Z"
MESSAGE = "batch_size must be 1-20"


def chosen(n):
    return [(vessel_row(i), ["new"]) for i in range(1, n + 1)]


def build(size, rows):
    with tempfile.TemporaryDirectory() as tmp:
        run = Run("CA", "20261011T101700Z-abcdef", var=Path(tmp))
        return agent.manifests("CA", run.id, run.dir, NOW, rows, batch_size=size)


class BatchTypeTests(unittest.TestCase):
    def test_manifest_batch_size_rejects_wrong_types(self):
        bad = [True, False, 1.0, 1.5, float("nan"), float("inf"), float("-inf"), "1", "20", None, [1], (1,), {"n": 1}]
        for rows in ([], chosen(3)):
            for size in bad:
                with self.subTest(size=repr(size), boats=len(rows)):
                    with self.assertRaises(ValueError) as caught:
                        build(size, rows)
                    self.assertEqual(str(caught.exception), MESSAGE)

    def test_manifest_batch_size_boundaries(self):
        for size in (0, -1, 21):
            with self.subTest(size=size), self.assertRaises(ValueError) as caught:
                build(size, chosen(2))
            self.assertEqual(str(caught.exception), MESSAGE)
        self.assertEqual(build(1, []), [])
        self.assertEqual(build(20, []), [])
        docs = build(1, chosen(3))
        self.assertEqual([d["batch_id"] for d in docs], ["batch-001", "batch-002", "batch-003"])
        self.assertEqual([[b["name"] for b in d["boats"]] for d in docs], [["Boat 1"], ["Boat 2"], ["Boat 3"]])
        docs = build(20, chosen(21))
        self.assertEqual([len(d["boats"]) for d in docs], [20, 1])

    def test_invalid_plan_preserves_existing_artifacts(self):
        vessels = [vessel_row(i) for i in range(1, 3)]
        load = lambda sink, region: Snapshot(vessels)  # noqa: E731
        with tempfile.TemporaryDirectory() as tmp:
            run = Run("CA", "20261011T101700Z-abcdef", var=Path(tmp))
            ctx = RunContext(region=REGION, net=None, run_dir=run.dir, clock=lambda: NOW)
            for size in (True, 1.0, 1.5, "2"):
                with self.subTest(fresh=repr(size)), self.assertRaises(ValueError):
                    agent.plan_agent(ctx, None, load=load, batch_size=size)
                self.assertFalse((run.dir / "manifests").exists())
                self.assertFalse((run.dir / "profiles").exists())
                self.assertFalse((run.dir / "agent-plan.json").exists())
            agent.plan_agent(ctx, None, load=load, batch_size=1)
            files = sorted((run.dir / "manifests").glob("*.json")) + [run.dir / "agent-plan.json"]
            before = {p.name: p.read_bytes() for p in files}
            self.assertEqual(len(before), 3)
            for size in (True, 1.0, 1.5, "2"):
                with self.subTest(existing=repr(size)), self.assertRaises(ValueError):
                    agent.plan_agent(ctx, None, load=load, batch_size=size)
                self.assertEqual({p.name: p.read_bytes() for p in files}, before)

    def test_valid_plan_batching_unchanged(self):
        vessels = [vessel_row(i) for i in range(1, 3)]
        snapshot_rows = list(vessels)
        with tempfile.TemporaryDirectory() as tmp:
            run = Run("CA", "20261011T101700Z-abcdef", var=Path(tmp))
            ctx = RunContext(region=REGION, net=None, run_dir=run.dir, clock=lambda: NOW)
            for size, expected in ((1, [1, 1]), (20, [2])):
                counts = agent.plan_agent(ctx, None, load=lambda sink, region: Snapshot(vessels), batch_size=size)
                docs = [json.loads(p.read_text()) for p in sorted((run.dir / "manifests").glob("*.json"))]
                self.assertEqual([len(d["boats"]) for d in docs], expected)
                self.assertEqual((counts["selected"], counts["batches"]), (2, len(expected)))
                plan = json.loads((run.dir / "agent-plan.json").read_text())
                self.assertEqual(plan["batch_size"], size)
        self.assertEqual(vessels, snapshot_rows)
        rows = chosen(2)
        before = list(rows)
        build(1, rows)
        self.assertEqual(rows, before)


if __name__ == "__main__":
    unittest.main()
