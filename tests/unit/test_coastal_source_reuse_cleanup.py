"""RF1005-16: BatchOwner.create descriptor cleanup, synthetic files and real fds only."""
import errno
import hashlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from skippercast.coastal.authenticated_v1 import source_reuse
from skippercast.coastal.authenticated_v1.source_reuse import BatchOwner, CONTRACT
from skippercast.coastal.budget import Budget, Limits

DATA = b"synthetic-source!"
GOOD = hashlib.sha256(DATA).hexdigest()
BAD = "0" * 64


def _is_open(fd):
    try:
        os.fstat(fd)
        return True
    except OSError as exc:
        assert exc.errno == errno.EBADF
        return False


class SourceReuseCleanupTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "synthetic-source").write_bytes(DATA)
        self.budget = Budget.create(self.root / "source.json", Limits(wall_s=600, bytes=len(DATA)))
        self.runtime = Budget.create(self.root / "runtime.json", Limits(wall_s=600))
        self.opened = []   # (kind, fd)
        self.addCleanup(self._close_leaks)

    def _close_leaks(self):
        for _, fd in self.opened:
            if _is_open(fd):
                os.close(fd)

    def _grant(self, sha=GOOD, leaf="synthetic-source"):
        return {"source_reuse_contract": CONTRACT, "source_root": str(self.root),
                "source_relative_path": leaf, "window_set": [[0, 0, 1, 1]],
                "source": {"sha256": sha, "bytes": len(DATA)}}

    def _create(self, ledger_fail_states=(), **grant_kw):
        real_atomic, real_memfd, real_open = source_reuse.atomic_json, os.memfd_create, source_reuse._open_source
        path = self.root / "batch.json"
        states = []

        def atomic(p, state):
            states.append(state["state"])
            if state["state"] in ledger_fail_states:
                raise OSError("synthetic ledger write failure")
            return real_atomic(p, state)

        def memfd(*a, **k):
            fd = real_memfd(*a, **k)
            self.opened.append(("memfd", fd))
            return fd

        def opener(*a, **k):
            fd = real_open(*a, **k)
            self.opened.append(("original", fd))
            return fd

        with mock.patch.object(source_reuse, "atomic_json", atomic), \
                mock.patch.object(os, "memfd_create", memfd), \
                mock.patch.object(source_reuse, "_open_source", opener):
            try:
                owner = BatchOwner.create(path, self._grant(**grant_kw), self.budget,
                                          runtime_budget=self.runtime,
                                          deadline_monotonic=__import__("time").monotonic() + 60)
                return owner, None, states
            except BaseException as exc:
                return None, exc, states

    def _assert_closed(self, kinds):
        got = [fd for k, fd in self.opened]
        self.assertEqual([k for k, _ in self.opened], kinds)
        for fd in got:
            self.assertFalse(_is_open(fd))

    def _reservation_charged(self):
        self.assertEqual(self.budget.decide().remaining["bytes"], 0)

    def test_copy_hash_failure_and_uncertain_write_failure_close_both_owned_fds(self):
        owner, exc, states = self._create(("uncertain",), sha=BAD)
        self.assertIsNone(owner)
        self.assertIsInstance(exc, OSError)
        self.assertIsInstance(exc.__context__, ValueError)
        self._assert_closed(["original", "memfd"])
        self.assertEqual(states[-1], "uncertain")
        self._reservation_charged()
        self.assertEqual((self.root / "synthetic-source").read_bytes(), DATA)

    def test_ordinary_copy_failure_retains_original_error_and_uncertain_receipt(self):
        owner, exc, _ = self._create(sha=BAD)
        self.assertIsNone(owner)
        self.assertIsInstance(exc, ValueError)
        self.assertIn("source changed or hash differs", str(exc))
        self._assert_closed(["original", "memfd"])
        self.assertEqual(json.loads((self.root / "batch.json").read_text())["state"], "uncertain")
        self.assertEqual((self.root / "synthetic-source").read_bytes(), DATA)

    def test_active_receipt_failure_followed_by_uncertain_failure_still_closes(self):
        owner, exc, states = self._create(("active", "uncertain"))
        self.assertIsNone(owner)
        self.assertIsInstance(exc, OSError)
        self._assert_closed(["original", "memfd"])
        self.assertEqual(states[-2:], ["active", "uncertain"])

    def test_preallocation_failure_does_not_close_unowned_fd(self):
        sentinel = os.open(self.root, os.O_RDONLY)
        self.opened.append(("sentinel", sentinel))
        owner, exc, _ = self._create(leaf="missing-source")
        self.assertIsNone(owner)
        self.assertIsInstance(exc, OSError)
        self.assertTrue(_is_open(sentinel))
        self.assertEqual([k for k, _ in self.opened], ["sentinel"])
        self.assertEqual(json.loads((self.root / "batch.json").read_text())["state"], "uncertain")
        self._reservation_charged()

    def test_successful_owner_keeps_descriptors_until_close(self):
        owner, exc, _ = self._create()
        self.assertIsNone(exc)
        self.assertEqual([k for k, _ in self.opened], ["original", "memfd"])
        original, memfd = (fd for _, fd in self.opened)
        self.assertTrue(_is_open(original))
        self.assertTrue(_is_open(memfd))
        self.assertEqual((owner.origin_fd, owner.fd), (original, memfd))
        owner.close()
        self.assertFalse(_is_open(original))
        self.assertFalse(_is_open(memfd))
        self.assertEqual(json.loads((self.root / "batch.json").read_text())["state"], "closed")


if __name__ == "__main__":
    unittest.main()
