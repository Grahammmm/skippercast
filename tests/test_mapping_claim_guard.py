import json
import tempfile
import unittest
from pathlib import Path

from research.scripts.mapping_claim_guard import GuardError, update_job, validate_checkpoint


def job(job_id="a", **overrides):
    value = {
        "id": job_id, "region": "fictional-coast", "reach": "reach-01",
        "source_ids": ["synthetic-555-0101", "synthetic-555-0102"],
        "method": "method-v1", "native_window": "window-1",
        "owner": "worker-a", "branch": "codex/worker-a",
        "output_path": "/private/tmp/mapping-guard/worker-a",
        "dispatch_state": "acknowledged", "state": "running",
        "attempt": 1, "receipt_paths": [],
    }
    value.update(overrides)
    return value


def checkpoint(*jobs):
    return {"coordinator": "coordinator-a", "jobs": list(jobs), "handoff_note": "preserve me", "window": "overnight"}


class MappingClaimGuardTests(unittest.TestCase):
    def test_old_overlapping_claim_is_refused_even_when_source_pair_order_differs(self):
        # Synthetic reproduction of the previous queue failure: two jobs reserve
        # the same source pair and native window but use separate output folders.
        left = job()
        right = job("b", owner="worker-b", output_path="/private/tmp/mapping-guard/worker-b",
                    source_ids=["synthetic-555-0102", "synthetic-555-0101"])
        with self.assertRaisesRegex(GuardError, "overlapping source/reach/method/window"):
            validate_checkpoint(checkpoint(left, right))

    def test_writable_path_collision_is_refused_independent_of_claim_identity(self):
        left = job()
        right = job("b", owner="worker-b", reach="reach-02", output_path=left["output_path"])
        with self.assertRaisesRegex(GuardError, "overlapping writable output path"):
            validate_checkpoint(checkpoint(left, right))

    def test_interrupted_dispatch_keeps_claim_and_cannot_be_stolen_by_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.json"
            path.write_text(json.dumps(checkpoint(job(dispatch_state="dispatching"))))
            with self.assertRaisesRegex(GuardError, "process state is reconciled"):
                update_job(path, "a", {"owner": "worker-b"}, actor="coordinator-a")
            saved = json.loads(path.read_text())
            self.assertEqual(saved["jobs"][0]["owner"], "worker-a")
            validate_checkpoint(saved)

    def test_coordinator_only_and_transition_guard_preserve_handoff_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.json"
            path.write_text(json.dumps(checkpoint(job(state="queued"))))
            with self.assertRaisesRegex(GuardError, "only the named coordinator"):
                update_job(path, "a", {"state": "running"}, actor="worker-a")
            with self.assertRaisesRegex(GuardError, "invalid state transition"):
                update_job(path, "a", {"state": "published"}, actor="coordinator-a")
            result = update_job(path, "a", {"state": "running", "dispatch_state": "acknowledged"}, actor="coordinator-a")
            self.assertEqual(result["handoff_note"], "preserve me")
            self.assertEqual(result["window"], "overnight")

    def test_published_requires_existing_receipt_files_but_is_not_clearance(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            record = job("p", state="published", receipt_paths=["rights-review.json", "restriction-check.json", "live-readback.json"])
            with self.assertRaisesRegex(GuardError, "missing existing receipt"):
                validate_checkpoint(checkpoint(record), base_dir=tmp_path)
            for receipt in record["receipt_paths"]:
                (tmp_path / receipt).write_text("synthetic receipt\n")
            # Receipt presence is not a scientific-clearance claim.
            validate_checkpoint(checkpoint(record), base_dir=tmp_path)


if __name__ == "__main__":
    unittest.main()
