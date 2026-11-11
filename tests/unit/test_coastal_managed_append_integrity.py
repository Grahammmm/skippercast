"""append_bytes refuses a missing completed/uncertain managed log (RF0825-8)."""
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from skippercast.coastal.handoff.common import digest
from skippercast.coastal.output_writer import COMPACT_V3_PROFILE, ManagedOutputs, declaration

KW = dict(role="control", max_bytes=64, intent="probe-log")
REFUSAL = "log partial/changed bytes preserved"


class AppendIntegrity(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name).resolve()
        self.root = base / "out"
        self.root.mkdir()
        self.evidence = base / "evidence"
        self.evidence.mkdir()
        grant = dict(output_root=str(self.root),
                     output_retention=declaration(0, 1 << 30, profile=COMPACT_V3_PROFILE))
        self.out = ManagedOutputs.create(self.root, grant, digest(grant))

    def ledger(self):
        return (self.root / "managed-output.json").read_bytes()

    def lose(self, name="run.log"):
        shutil.move(str(self.root / name), str(self.evidence / name))

    def assert_refused_unchanged(self, name="run.log"):
        before = self.ledger()
        with self.assertRaisesRegex(ValueError, REFUSAL):
            self.out.append_bytes(name, b"third\n", **KW)
        self.assertFalse((self.root / name).exists())
        self.assertEqual(before, self.ledger())

    def test_completed_nonempty_log_missing_refuses_without_recreation(self):
        self.out.append_bytes("run.log", b"first\n", **KW)
        self.out.append_bytes("run.log", b"second\n", **KW)
        self.lose()
        self.assert_refused_unchanged()
        self.assertEqual(b"first\nsecond\n", (self.evidence / "run.log").read_bytes())

    def test_completed_empty_log_missing_is_not_fresh(self):
        self.out.append_bytes("run.log", b"", **KW)
        self.lose()
        self.assert_refused_unchanged()

    def test_uncertain_log_missing_stays_uncertain(self):
        with self.assertRaises(RuntimeError):
            with self.out.writer("run.log", **KW) as stream:
                stream.write(b"x")
                raise RuntimeError("boom")
        entry = self.out._read()["files"]["run.log"]
        self.assertEqual("uncertain", entry["state"])
        self.lose()
        self.assert_refused_unchanged()
        self.assertEqual("uncertain", self.out._read()["files"]["run.log"]["state"])

    def test_uncertain_log_present_refuses(self):
        with self.assertRaises(RuntimeError):
            with self.out.writer("run.log", **KW) as stream:
                stream.write(b"x")
                raise RuntimeError("boom")
        before = self.ledger()
        with self.assertRaisesRegex(ValueError, REFUSAL):
            self.out.append_bytes("run.log", b"y", **KW)
        self.assertEqual(before, self.ledger())
        self.assertEqual(b"x", (self.root / "run.log").read_bytes())

    def test_fresh_and_reserved_absent_allow_first_append(self):
        self.out.append_bytes("fresh.log", b"a", **KW)
        self.out.reserve_file("res.log", **KW)
        self.out.append_bytes("res.log", b"b", **KW)
        files = self.out._read()["files"]
        for name, data in (("fresh.log", b"a"), ("res.log", b"b")):
            self.assertEqual("complete", files[name]["state"])
            self.assertEqual(64, files[name]["bytes"])
            self.assertEqual(data, (self.root / name).read_bytes())

    def test_reserved_present_is_not_adopted(self):
        self.out.reserve_file("res.log", **KW)
        (self.root / "res.log").write_bytes(b"external")
        before = self.ledger()
        with self.assertRaisesRegex(ValueError, REFUSAL):
            self.out.append_bytes("res.log", b"z", **KW)
        self.assertEqual(before, self.ledger())

    def test_verified_existing_append_preserves_prefix(self):
        self.out.append_bytes("run.log", b"one\n", **KW)
        self.out.append_bytes("run.log", b"", **KW)
        self.out.append_bytes("run.log", b"two\n", **KW)
        data = b"one\ntwo\n"
        self.assertEqual(data, (self.root / "run.log").read_bytes())
        entry = self.out._read()["files"]["run.log"]
        self.assertEqual(len(data), entry["actual_bytes"])
        self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"])

    def test_changed_prefix_and_ceiling_still_refuse(self):
        self.out.append_bytes("run.log", b"abcd", **KW)
        (self.root / "run.log").write_bytes(b"abXd")
        with self.assertRaisesRegex(ValueError, REFUSAL):
            self.out.append_bytes("run.log", b"e", **KW)
        (self.root / "run.log").write_bytes(b"abcd")
        with self.assertRaisesRegex(ValueError, "append ceiling exceeded"):
            self.out.append_bytes("run.log", b"x" * 100, **KW)

    def test_refusal_keeps_reserved_charge(self):
        self.out.append_bytes("run.log", b"a", **KW)
        charged = self.out._read()["files"]["run.log"]["bytes"]
        self.lose()
        with self.assertRaisesRegex(ValueError, REFUSAL):
            self.out.append_bytes("run.log", b"b", **KW)
        self.assertEqual(charged, self.out._read()["files"]["run.log"]["bytes"])


if __name__ == "__main__":
    unittest.main()
