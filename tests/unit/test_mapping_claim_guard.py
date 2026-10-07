import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from research.scripts.mapping_claim_guard import GuardError, update_job, validate_checkpoint


def job(job_id="a", **overrides):
    value = {
        "id": job_id, "region": "fictional-coast", "reach": "reach-01",
        "source_ids": ["synthetic-555-0101", "synthetic-555-0102"],
        "method": "method-v1", "native_window": [0, 0, 512, 512],
        "owner": "worker-a", "branch": "codex/worker-a",
        "output_path": "/private/tmp/mapping-guard/worker-a",
        "dispatch_state": "acknowledged", "state": "running",
        "attempt": 1, "dispatch_id": "dispatch-a-1", "process_id": "process-a-1", "receipt_paths": [],
    }
    value.update(overrides)
    return value


def checkpoint(*jobs):
    return {"coordinator": "coordinator-a", "jobs": list(jobs), "handoff_note": "preserve me", "window": "overnight"}


def stop_receipt(root, record, **overrides):
    content = {k: record[k] for k in ("id", "owner", "attempt", "dispatch_id", "process_id")}
    content.update(stopped=True, verified_by="coordinator-a", stopped_utc="2026-10-07T10:00:00Z")
    content.update(overrides)
    path = root / "stopped.json"
    raw = json.dumps(content).encode()
    path.write_bytes(raw)
    return {"path": str(path), "verified": True, "verified_by": "coordinator-a",
            "stopped_utc": content["stopped_utc"], "sha256": hashlib.sha256(raw).hexdigest()}


class MappingClaimGuardTests(unittest.TestCase):
    def test_old_overlapping_claim_is_refused_even_when_source_pair_order_differs(self):
        # Synthetic reproduction of the previous queue failure: two jobs reserve
        # the same source pair and native window but use separate output folders.
        left = job()
        right = job("b", owner="worker-b", output_path="/private/tmp/mapping-guard/worker-b",
                    source_ids=["synthetic-555-0102", "synthetic-555-0101"])
        with self.assertRaisesRegex(GuardError, "overlapping source/reach/method/window"):
            validate_checkpoint(checkpoint(left, right))

    def test_partially_overlapping_native_rectangles_are_refused(self):
        left = job()
        right = job("b", owner="worker-b", output_path="/private/tmp/mapping-guard/worker-b",
                    native_window=[256, 0, 512, 512])
        with self.assertRaisesRegex(GuardError, "overlapping source/reach/method/window"):
            validate_checkpoint(checkpoint(left, right))

    def test_disjoint_native_rectangles_are_allowed_and_opaque_windows_rejected(self):
        left = job()
        right = job("b", owner="worker-b", output_path="/private/tmp/mapping-guard/worker-b",
                    native_window=[512, 0, 512, 512])
        validate_checkpoint(checkpoint(left, right))
        with self.assertRaisesRegex(GuardError, "native_window must be"):
            validate_checkpoint(checkpoint(job(native_window="window-1")))

    def test_writable_path_collision_is_refused_independent_of_claim_identity(self):
        left = job()
        right = job("b", owner="worker-b", reach="reach-02", output_path=left["output_path"])
        with self.assertRaisesRegex(GuardError, "overlapping writable output path"):
            validate_checkpoint(checkpoint(left, right))

    def test_relative_absolute_and_parent_child_writable_paths_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = job(output_path="out")
            right = job("b", owner="worker-b", reach="reach-02", output_path=str(root / "out"))
            with self.assertRaisesRegex(GuardError, "overlapping writable output path"):
                validate_checkpoint(checkpoint(left, right), base_dir=root)
            right["output_path"] = "out/child"
            with self.assertRaisesRegex(GuardError, "overlapping writable output path"):
                validate_checkpoint(checkpoint(left, right), base_dir=root)

    def test_interrupted_dispatch_keeps_claim_and_cannot_be_stolen_by_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.json"
            path.write_text(json.dumps(checkpoint(job(dispatch_state="dispatching"))))
            with self.assertRaisesRegex(GuardError, "verified stopped-process receipt"):
                update_job(path, "a", {"owner": "worker-b"}, actor="coordinator-a")
            saved = json.loads(path.read_text())
            self.assertEqual(saved["jobs"][0]["owner"], "worker-a")
            validate_checkpoint(saved)

    def test_running_job_reassignment_requires_verified_existing_stop_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.json"
            path.write_text(json.dumps(checkpoint(job())))
            with self.assertRaisesRegex(GuardError, "verified stopped-process receipt"):
                update_job(path, "a", {"owner": "worker-b"}, actor="coordinator-a")
            proof = stop_receipt(Path(tmp), job())
            with self.assertRaisesRegex(GuardError, "cannot remain running"):
                update_job(path, "a", {"owner": "worker-b", "stopped_process_receipt": proof}, actor="coordinator-a")

    def test_valid_stop_receipt_allows_reassignment_after_leaving_active_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "checkpoint.json"
            path.write_text(json.dumps(checkpoint(job())))
            result = update_job(path, "a", {
                "owner": "worker-b", "state": "blocked", "dispatch_state": "queued",
                "stopped_process_receipt": stop_receipt(root, job()),
            }, actor="coordinator-a")
            self.assertEqual(result["jobs"][0]["owner"], "worker-b")
            self.assertEqual(result["jobs"][0]["state"], "blocked")
            self.assertEqual(result["jobs"][0]["execution_claim"]["owner"], "worker-a")
            second = job("b", owner="worker-c", output_path="/private/tmp/mapping-guard/worker-c")
            validate_checkpoint(checkpoint(result["jobs"][0], second), base_dir=root)
            self.assertEqual(result["handoff_note"], "preserve me")

    def test_dispatching_to_queued_does_not_itself_authorize_owner_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.json"
            path.write_text(json.dumps(checkpoint(job(state="queued", dispatch_state="dispatching"))))
            update_job(path, "a", {"dispatch_state": "queued"}, actor="coordinator-a")
            with self.assertRaisesRegex(GuardError, "verified stopped-process receipt"):
                update_job(path, "a", {"owner": "worker-b"}, actor="coordinator-a")

    def test_dispatching_to_blocked_remains_an_occupied_claim_until_stop_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.json"
            first = job(state="queued", dispatch_state="dispatching")
            path.write_text(json.dumps(checkpoint(first)))
            update_job(path, "a", {"state": "blocked"}, actor="coordinator-a")
            saved = json.loads(path.read_text())
            second = job("b", owner="worker-b", output_path="/private/tmp/mapping-guard/worker-b")
            with self.assertRaisesRegex(GuardError, "overlapping source/reach/method/window"):
                validate_checkpoint(checkpoint(saved["jobs"][0], second))

    def test_unrelated_negative_or_tampered_receipts_cannot_reassign(self):
        cases = ({"id": "other-job"}, {"owner": "worker-b"}, {"attempt": 2},
                 {"dispatch_id": "other-dispatch"}, {"process_id": "other-process"},
                 {"stopped": False}, {"stopped": "true"}, {"verified_by": "other-coordinator"})
        for changes in cases:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = root / "checkpoint.json"
                path.write_text(json.dumps(checkpoint(job())))
                before = path.read_bytes()
                proof = stop_receipt(root, job(), **changes)
                with self.assertRaisesRegex(GuardError, "verified stopped-process receipt"):
                    update_job(path, "a", {"owner": "worker-b", "state": "blocked",
                                          "dispatch_state": "queued", "stopped_process_receipt": proof}, actor="coordinator-a")
                self.assertEqual(path.read_bytes(), before)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "checkpoint.json"
            path.write_text(json.dumps(checkpoint(job())))
            proof = stop_receipt(root, job())
            Path(proof["path"]).write_text('{"stopped": true}')
            with self.assertRaisesRegex(GuardError, "verified stopped-process receipt"):
                update_job(path, "a", {"owner": "worker-b", "state": "blocked",
                                      "stopped_process_receipt": proof}, actor="coordinator-a")

    def test_status_bypass_sequences_retain_execution_claim(self):
        for first in (job(state="queued", dispatch_state="dispatching"), job()):
            with self.subTest(first=first), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "checkpoint.json"
                path.write_text(json.dumps(checkpoint(first)))
                update_job(path, "a", {"dispatch_state": "queued"}, actor="coordinator-a")
                saved = update_job(path, "a", {"state": "blocked"}, actor="coordinator-a")
                second = job("b", owner="worker-b", output_path="/private/tmp/mapping-guard/worker-b")
                with self.assertRaisesRegex(GuardError, "overlapping source/reach/method/window"):
                    validate_checkpoint(checkpoint(saved["jobs"][0], second))
                for patch in ({"execution_claim": None}, {"attempt": 2}, {"output_path": "/private/tmp/moved"}):
                    with self.assertRaises(GuardError):
                        update_job(path, "a", patch, actor="coordinator-a")

    def test_missing_execution_identity_and_invalid_json_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "checkpoint.json"
            original = job(process_id=None)
            path.write_text(json.dumps(checkpoint(original)))
            saved = update_job(path, "a", {"state": "blocked", "dispatch_state": "queued"}, actor="coordinator-a")
            proof = stop_receipt(root, job())
            with self.assertRaisesRegex(GuardError, "verified stopped-process receipt"):
                update_job(path, "a", {"owner": "worker-b", "stopped_process_receipt": proof}, actor="coordinator-a")
            second = job("b", owner="worker-b", output_path="/private/tmp/mapping-guard/worker-b")
            with self.assertRaisesRegex(GuardError, "overlapping source/reach/method/window"):
                validate_checkpoint(checkpoint(saved["jobs"][0], second))
            path.write_text(json.dumps(checkpoint(job())))
            receipt = Path(proof["path"])
            receipt.write_bytes(b"invalid JSON")
            proof["sha256"] = hashlib.sha256(receipt.read_bytes()).hexdigest()
            with self.assertRaisesRegex(GuardError, "verified stopped-process receipt"):
                update_job(path, "a", {"owner": "worker-b", "stopped_process_receipt": proof}, actor="coordinator-a")


    def test_coordinator_can_record_process_identity_at_acknowledgement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "checkpoint.json"
            original = job(state="queued", dispatch_state="dispatching", process_id=None)
            path.write_text(json.dumps(checkpoint(original)))
            result = update_job(path, "a", {"dispatch_state": "acknowledged", "process_id": "process-a-1",
                                            "state": "running"}, actor="coordinator-a")
            self.assertEqual(result["jobs"][0]["execution_claim"]["process_id"], "process-a-1")
            with self.assertRaisesRegex(GuardError, "execution identity cannot change"):
                update_job(path, "a", {"process_id": "other-process"}, actor="coordinator-a")
            result = update_job(path, "a", {"state": "blocked", "dispatch_state": "queued",
                                            "stopped_process_receipt": stop_receipt(root, job())}, actor="coordinator-a")
            second = job("b", owner="worker-b", output_path="/private/tmp/mapping-guard/worker-b")
            validate_checkpoint(checkpoint(result["jobs"][0], second), base_dir=root)


    def test_old_stop_receipt_does_not_release_later_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "checkpoint.json"
            path.write_text(json.dumps(checkpoint(job())))
            update_job(path, "a", {"state": "blocked", "dispatch_state": "queued",
                                  "stopped_process_receipt": stop_receipt(root, job())}, actor="coordinator-a")
            update_job(path, "a", {"state": "queued"}, actor="coordinator-a")
            with self.assertRaisesRegex(GuardError, "fresh execution identity"):
                update_job(path, "a", {"dispatch_state": "dispatching"}, actor="coordinator-a")
            update_job(path, "a", {"attempt": 2, "dispatch_id": "dispatch-a-2", "process_id": "process-a-2",
                                  "dispatch_state": "dispatching"}, actor="coordinator-a")
            saved = update_job(path, "a", {"dispatch_state": "queued", "state": "blocked"}, actor="coordinator-a")
            second = job("b", owner="worker-b", output_path="/private/tmp/mapping-guard/worker-b")
            with self.assertRaisesRegex(GuardError, "overlapping source/reach/method/window"):
                validate_checkpoint(checkpoint(saved["jobs"][0], second), base_dir=root)


    def test_queued_to_running_requires_dispatch_acknowledgement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.json"
            path.write_text(json.dumps(checkpoint(job(state="queued", dispatch_state="queued"))))
            with self.assertRaisesRegex(GuardError, "dispatch is acknowledged"):
                update_job(path, "a", {"state": "running"}, actor="coordinator-a")

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

    def test_checkpoint_symlink_alias_is_rejected_without_replacing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "checkpoint.json"
            alias = root / "alias.json"
            target.write_text(json.dumps(checkpoint(job(state="queued"))))
            alias.symlink_to(target)
            before = target.read_text()
            with self.assertRaisesRegex(GuardError, "must not be a symlink"):
                update_job(alias, "a", {"state": "running", "dispatch_state": "acknowledged"}, actor="coordinator-a")
            self.assertEqual(target.read_text(), before)
            self.assertTrue(alias.is_symlink())


if __name__ == "__main__":
    unittest.main()
