"""write_checkpoint never recreates a missing completed or uncertain checkpoint (RF0111-9)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from skippercast.coastal import output_writer, receipts
from skippercast.coastal.handoff.common import digest
from skippercast.coastal.output_writer import (
    COMPACT_V3_PROFILE, ManagedOutputs, declaration)

KW = dict(role="control", max_bytes=64, intent="cp")
REFUSED = "checkpoint prior state changed or uncertain"


def grant_for(root):
    return dict(output_root=str(root), output_retention=declaration(0, 1 << 30, profile=COMPACT_V3_PROFILE))


class CheckpointIntegrity(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.root = base / "out"
        self.root.mkdir()
        self.away = base / "away"
        self.away.mkdir()
        self.grant = grant_for(self.root)
        self.outputs = ManagedOutputs.create(self.root, self.grant, digest(self.grant))

    def ledger(self):
        return (self.root / "managed-output.json").read_bytes()

    def move_away(self, name):
        (self.root / name).rename(self.away / name.replace("/", "_"))

    def assert_refused_unchanged(self, name, value=None, **extra):
        before = self.ledger()
        staged = sorted(p.name for p in self.root.rglob("*") if p.is_file())
        with self.assertRaisesRegex(ValueError, REFUSED):
            self.outputs.write_checkpoint(name, value or {"v": 9}, **{**KW, **extra})
        self.assertEqual(self.ledger(), before)
        self.assertEqual(sorted(p.name for p in self.root.rglob("*") if p.is_file()), staged)

    def fail_publication(self, name, value):
        with mock.patch.object(output_writer.BoundedFile, "write", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                self.outputs.write_checkpoint(name, value, **KW)
        self.assertEqual(self.outputs._read()["files"][name]["state"], "uncertain")

    def test_completed_checkpoint_missing_is_not_initial_creation(self):
        self.outputs.write_checkpoint("cp.json", {"v": 1}, **KW)
        self.move_away("cp.json")
        self.assert_refused_unchanged("cp.json")
        self.assertFalse((self.root / "cp.json").exists())
        self.assertEqual((self.away / "cp.json").read_bytes(), b'{"v":1}\n')

    def test_uncertain_checkpoint_missing_stays_held(self):
        self.fail_publication("cp.json", {"v": 1})
        self.assert_refused_unchanged("cp.json")
        self.assertFalse((self.root / "cp.json").exists())

    def test_uncertain_checkpoint_present_stays_held_and_retries_cannot_reset(self):
        self.outputs.write_checkpoint("cp.json", {"v": 1}, **KW)
        self.fail_publication("cp.json", {"v": 2})
        self.assertTrue((self.root / "cp.json").exists())
        self.assert_refused_unchanged("cp.json")
        self.move_away("cp.json")
        self.assert_refused_unchanged("cp.json")

    def test_fresh_and_explicit_reserved_first_creation_work(self):
        self.outputs.write_checkpoint("a.json", {"v": 1}, **KW)
        self.outputs.reserve_file("b.json", **KW)
        self.outputs.write_checkpoint("b.json", {}, **KW)
        for name, raw in (("a.json", b'{"v":1}\n'), ("b.json", b"{}\n")):
            entry = self.outputs._read()["files"][name]
            self.assertEqual((self.root / name).read_bytes(), raw)
            self.assertEqual((entry["state"], entry["updates"]), ("complete", 1))

    def test_verified_updates_and_hash_fences_preserved(self):
        import hashlib
        self.outputs.write_checkpoint("cp.json", {}, **KW)
        good = hashlib.sha256(b"{}\n").hexdigest()
        before = self.ledger()
        with self.assertRaisesRegex(ValueError, "hash fence"):
            self.outputs.write_checkpoint("cp.json", {"v": 1}, previous_sha256="0" * 64, **KW)
        self.assertEqual(self.ledger(), before)
        self.outputs.write_checkpoint("cp.json", {"v": 1}, **KW)
        self.outputs.write_checkpoint("cp.json", {"v": 2}, previous_sha256=hashlib.sha256(b'{"v":1}\n').hexdigest(), **KW)
        self.assertEqual((self.root / "cp.json").read_bytes(), b'{"v":2}\n')
        self.assertNotEqual(good, "")
        # tampered prior bytes refuse
        (self.root / "cp.json").write_bytes(b'{"v":7}\n')
        self.assert_refused_unchanged("cp.json")

    def test_supplied_hash_with_absent_complete_prior_refuses(self):
        self.outputs.write_checkpoint("cp.json", {"v": 1}, **KW)
        self.move_away("cp.json")
        self.assert_refused_unchanged("cp.json", previous_sha256="0" * 64)

    def test_reserved_present_and_identity_changes_refuse(self):
        self.outputs.reserve_file("r.json", **KW)
        (self.root / "r.json").write_bytes(b"x")
        with self.assertRaises(ValueError):
            self.outputs.write_checkpoint("r.json", {"v": 1}, **KW)
        self.assertEqual((self.root / "r.json").read_bytes(), b"x")
        self.outputs.write_checkpoint("c.json", {"v": 1}, **KW)
        with self.assertRaises(ValueError):
            self.outputs.write_checkpoint("c.json", {"v": 2}, **{**KW, "intent": "other"})
        with self.assertRaises(ValueError):
            self.outputs.write_checkpoint("c.json", {"v": 2}, max_updates=1, **KW)

    def test_receipts_atomic_json_cannot_recreate_missing_prior(self):
        config = dict(grant=self.grant, grant_digest=digest(self.grant), role="control", max_bytes=64)
        target = self.root / "rec.json"
        with receipts.managed_writes(config):
            receipts.atomic_json(target, {"v": 1})
            self.move_away("rec.json")
            before = self.ledger()
            with self.assertRaisesRegex(ValueError, REFUSED):
                receipts.atomic_json(target, {"v": 2})
            self.assertEqual(self.ledger(), before)
            self.assertFalse(target.exists())
        self.assertIsNone(receipts.managed_writer())


if __name__ == "__main__":
    unittest.main()
