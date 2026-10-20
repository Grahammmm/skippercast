"""ManagedOutputs does one ledger read per op and no redundant tree walks (SC-8e, item 102).

four128 attempt 6 unit CPU grew from 2.4 to 10.6 s over 12 stages: every
managed write re-read the ledger (one binding digest per entry) and walked the
whole output root several times. reserve_file() audited before and after adding
its entry, and writer() reserved under one lock, then read and audited again
under a second. Reservation and publication now share one lock hold, one read
and one walk per reservation. The prewrite audit, the postwrite audit and every
refusal stay. These tests pin the counts before and after the change, and check
that the split audit (_observe + _charge) refuses exactly what the old inline
walk refused.
"""
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from skippercast.coastal import output_writer
from skippercast.coastal.handoff.common import digest
from skippercast.coastal.output_writer import (
    COMPACT_V3_PROFILE, METADATA_MAX, OVERHEAD, ManagedOutputs, declaration)

# Per op: (os.walk calls, binding digests as (a, b) meaning a*N + b, N = ledger
# entries before the op). BEFORE is measured on main at bde9c6dff (pre-SC-8e).
BEFORE = {
    "write_bytes new":        (5, (3, 4)),
    "write_bytes reuse":      (2, (2, 1)),
    "writer new":             (4, (2, 2)),
    "reserve_file new":       (2, (1, 1)),
    "reserve_file existing":  (1, (1, 1)),
    "append_bytes new":       (4, (2, 2)),
    "append_bytes existing":  (3, (2, 1)),
    "write_checkpoint new":   (6, (3, 6)),
    "write_checkpoint update": (4, (3, 3)),
}
AFTER = {
    "write_bytes new":        (2, (1, 1)),
    "write_bytes reuse":      (1, (1, 1)),
    "writer new":             (2, (1, 1)),
    "reserve_file new":       (1, (1, 1)),
    "reserve_file existing":  (1, (1, 1)),
    "append_bytes new":       (2, (1, 1)),
    "append_bytes existing":  (2, (1, 1)),
    "write_checkpoint new":   (3, (1, 3)),
    "write_checkpoint update": (2, (1, 3)),
}


def make_outputs(tmp):
    root = Path(tmp).resolve() / "out"
    root.mkdir()
    grant = dict(output_root=str(root), output_retention=declaration(0, 1 << 30, profile=COMPACT_V3_PROFILE))
    return ManagedOutputs.create(root, grant, digest(grant))


def inline_audit(self, state):
    """The pre-SC-8e ManagedOutputs._audit verbatim (one walk, checks inline)."""
    charged = {role: 0 for role in self.limits}; charged['control'] = OVERHEAD
    for e in state['files'].values(): charged[e['role']] += e['bytes']
    observed = 0; unknown = 0
    for directory, dirs, files in os.walk(self.root, followlinks=False):
        for name in (*dirs, *files):
            p = Path(directory) / name; info = p.lstat()
            if stat.S_ISLNK(info.st_mode) or (name in files and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)):
                raise ValueError('single-link regular managed tree required')
            if name not in files: continue
            observed += info.st_size; rel = p.relative_to(self.root).as_posix()
            if rel in state['files']:
                if info.st_size > state['files'][rel]['bytes']: raise ValueError('managed retained file exceeded ceiling')
            elif rel in ('managed-output.json', 'managed-output.pending'):
                if info.st_size > METADATA_MAX: raise ValueError('metadata retained ceiling exceeded')
            elif rel == 'managed-output.lock':
                if info.st_size != 0: raise ValueError('lock retained ceiling exceeded')
            else: unknown += info.st_size
    charged['control'] += unknown
    if any(charged[r] > self.limits[r] for r in self.limits) or sum(charged.values()) > self.plan['total_bytes']:
        raise ValueError('aggregate managed output allowance exhausted')
    if self.plan['prior_retained_bytes'] + sum(charged.values()) > self.plan['cumulative_cap_bytes']:
        raise ValueError('cumulative retained carry exceeded')
    return dict(charged_bytes=sum(charged.values()), charged_by_role=charged,
                observed_bytes=observed, unmanaged_control_bytes=unknown,
                prior_retained_bytes=self.plan['prior_retained_bytes'],
                prewrite_enforcement='managed writer API only', disk_quota=False,
                physical_io_measured=False)


def outcome(fn, *args):
    try:
        return ("ok", fn(*args))
    except (ValueError, OSError) as exc:
        return ("refused", type(exc).__name__, str(exc))


class WalksAndDigestsPerOp(unittest.TestCase):
    def count(self, outputs, fn):
        entries = len(outputs._read()["files"])
        with mock.patch.object(output_writer.os, "walk", wraps=os.walk) as walk, \
                mock.patch.object(output_writer, "digest", wraps=output_writer.digest) as dig:
            fn()
        return entries, walk.call_count, dig.call_count

    def test_each_op_does_one_read_and_no_redundant_walk(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = make_outputs(tmp)
            for i in range(10):
                outputs.write_bytes(f"seed/{i}.bin", b"s", role="control", max_bytes=8, intent=f"seed-{i}")

            def writer_new():
                with outputs.writer("w.bin", role="control", max_bytes=8, intent="w") as stream:
                    stream.write(b"w")

            ops = [
                ("write_bytes new", lambda: outputs.write_bytes("a.bin", b"a", role="control", max_bytes=8, intent="a")),
                ("write_bytes reuse", lambda: outputs.write_bytes("a.bin", b"a", role="control", max_bytes=8, intent="a")),
                ("writer new", writer_new),
                ("reserve_file new", lambda: outputs.reserve_file("r.bin", role="control", max_bytes=8, intent="r")),
                ("reserve_file existing", lambda: outputs.reserve_file("r.bin", role="control", max_bytes=8, intent="r")),
                ("append_bytes new", lambda: outputs.append_bytes("run.log", b"1\n", role="control", max_bytes=64, intent="log")),
                ("append_bytes existing", lambda: outputs.append_bytes("run.log", b"2\n", role="control", max_bytes=64, intent="log")),
                ("write_checkpoint new", lambda: outputs.write_checkpoint("ck.json", {"v": 1}, role="control", max_bytes=64, intent="ck")),
                ("write_checkpoint update", lambda: outputs.write_checkpoint("ck.json", {"v": 2}, role="control", max_bytes=64, intent="ck")),
            ]
            for label, fn in ops:
                with self.subTest(op=label):
                    entries, walks, digests = self.count(outputs, fn)
                    after_walks, (a, b) = AFTER[label]
                    before_walks, (c, d) = BEFORE[label]
                    self.assertEqual((walks, digests), (after_walks, a * entries + b))
                    self.assertLessEqual(walks, before_walks)
                    self.assertLessEqual(digests, c * entries + d)
            # One managed write: at least 3 walks and 2 registry reads before, now 2 walks and 1 read.
            self.assertEqual((BEFORE["write_bytes new"][0], AFTER["write_bytes new"][0]), (5, 2))
            self.assertEqual((BEFORE["writer new"][0], AFTER["writer new"][0]), (4, 2))
            # Only the bare reservation and the checkpoint temporary stay reserved.
            state = outputs._read()
            self.assertEqual({k for k, e in state["files"].items() if e["state"] != "complete"},
                             {"r.bin", ".managed-checkpoints/ck.json"})
            self.assertEqual(Path(outputs.root, "run.log").read_bytes(), b"1\n2\n")


class SplitAuditMatchesInlineAudit(unittest.TestCase):
    """_audit = _charge(_observe()) returns or refuses exactly as the old inline walk."""

    def compare(self, outputs):
        state = outputs._read()
        old = outcome(inline_audit, outputs, state)
        new = outcome(outputs._audit, state)
        self.assertEqual(new, old)
        return new

    def test_trees(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = make_outputs(tmp)
            root = outputs.root
            for i in range(6):
                outputs.write_bytes(f"d{i % 2}/f{i}.bin", b"x" * 8, role="control", max_bytes=16, intent=f"f{i}")
            outputs.reserve_file("d0/reserved.bin", role="native", max_bytes=1024, intent="r")
            self.assertEqual(self.compare(outputs)[0], "ok")

            (root / "loose.txt").write_bytes(b"unmanaged" * 10)  # unmanaged growth is charged to control
            result = self.compare(outputs)
            self.assertEqual((result[0], result[1]["unmanaged_control_bytes"]), ("ok", 90))

            cases = []
            big = root / "d1" / "big.bin"

            def grow_big():  # sparse unmanaged growth past the control ceiling
                big.touch()
                os.truncate(big, 15 << 20)
            cases.append(("aggregate", grow_big, lambda: big.unlink()))
            grown = root / "d0" / "f0.bin"
            cases.append(("retained", lambda: grown.write_bytes(b"x" * 17), lambda: grown.write_bytes(b"x" * 8)))
            lock = outputs.lock_path
            cases.append(("lock", lambda: lock.write_bytes(b"1"), lambda: lock.write_bytes(b"")))
            link = root / "d1" / "link"
            cases.append(("symlink", lambda: link.symlink_to(root / "d0" / "f0.bin"), lambda: link.unlink()))
            hard = root / "hard.bin"
            cases.append(("hardlink", lambda: os.link(root / "d1" / "f1.bin", hard), lambda: hard.unlink()))
            fifo = root / "d0" / "fifo"
            cases.append(("fifo", lambda: os.mkfifo(fifo), lambda: fifo.unlink()))
            expected = {
                "aggregate": "aggregate managed output allowance exhausted",
                "retained": "managed retained file exceeded ceiling",
                "lock": "lock retained ceiling exceeded",
                "symlink": "single-link regular managed tree required",
                "hardlink": "single-link regular managed tree required",
                "fifo": "single-link regular managed tree required",
            }
            for label, make, undo in cases:
                with self.subTest(tree=label):
                    make()
                    try:
                        self.assertEqual(self.compare(outputs), ("refused", "ValueError", expected[label]))
                    finally:
                        undo()
                    self.assertEqual(self.compare(outputs)[0], "ok")

            # Several faults at once: the first in walk order wins, as before.
            grown.write_bytes(b"x" * 17)
            link.symlink_to(root / "d0" / "f0.bin")
            lock.write_bytes(b"1")
            self.assertEqual(self.compare(outputs)[0], "refused")


class RefusalsStayBeforeReservationAndAfterWrite(unittest.TestCase):
    def ledger(self, outputs):
        return outputs.path.read_bytes()

    def test_tree_fault_refuses_before_any_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = make_outputs(tmp)
            outputs.write_bytes("a.bin", b"a", role="control", max_bytes=8, intent="a")
            before = self.ledger(outputs)
            link = outputs.root / "link"
            link.symlink_to(outputs.root / "a.bin")
            for label, op in (
                    ("write_bytes", lambda: outputs.write_bytes("b.bin", b"b", role="control", max_bytes=8, intent="b")),
                    ("reserve_file", lambda: outputs.reserve_file("b.bin", role="control", max_bytes=8, intent="b")),
                    ("append_bytes", lambda: outputs.append_bytes("b.log", b"b", role="control", max_bytes=8, intent="b")),
                    ("write_checkpoint", lambda: outputs.write_checkpoint("b.json", {}, role="control", max_bytes=8, intent="b"))):
                with self.subTest(op=label), self.assertRaisesRegex(ValueError, "^single-link regular managed tree required$"):
                    op()
                self.assertEqual(self.ledger(outputs), before)
                self.assertFalse((outputs.root / "b.bin").exists())
            link.unlink()

            sparse = outputs.root / "sparse.bin"
            sparse.touch()
            os.truncate(sparse, 15 << 20)  # unmanaged growth past the 14.5 MiB control ceiling
            with self.assertRaisesRegex(ValueError, "^aggregate managed output allowance exhausted$"):
                outputs.write_bytes("b.bin", b"b", role="control", max_bytes=8, intent="b")
            self.assertEqual(self.ledger(outputs), before)
            sparse.unlink()

            # A reservation that would itself exceed the role ceiling is refused unsaved.
            with self.assertRaisesRegex(ValueError, "^aggregate managed output allowance exhausted$"):
                outputs.write_bytes("c.bin", b"c", role="control", max_bytes=15 << 20, intent="c")
            self.assertEqual(self.ledger(outputs), before)
            # An unregistered existing file is preserved and refused as before.
            (outputs.root / "d.bin").write_bytes(b"d")
            with self.assertRaisesRegex(ValueError, "^unregistered existing file preserved$"):
                outputs.write_bytes("d.bin", b"d", role="control", max_bytes=8, intent="d")
            self.assertEqual(self.ledger(outputs), before)

    def test_growth_during_a_write_is_caught_by_the_postwrite_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = make_outputs(tmp)
            sparse = outputs.root / "sparse.bin"
            with self.assertRaisesRegex(ValueError, "^aggregate managed output allowance exhausted$"):
                with outputs.writer("a.bin", role="control", max_bytes=8, intent="a") as stream:
                    stream.write(b"a")
                    sparse.touch()
                    os.truncate(sparse, 15 << 20)
            # As before: the publication is saved, then the audit refuses.
            self.assertEqual(outputs._read()["files"]["a.bin"]["state"], "complete")
            with self.assertRaisesRegex(ValueError, "^aggregate managed output allowance exhausted$"):
                outputs.audit()

    def test_failed_body_marks_uncertain_and_keeps_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = make_outputs(tmp)
            with self.assertRaisesRegex(RuntimeError, "^stop$"):
                with outputs.writer("a.bin", role="control", max_bytes=8, intent="a") as stream:
                    stream.write(b"a")
                    raise RuntimeError("stop")
            self.assertEqual(outputs._read()["files"]["a.bin"]["state"], "uncertain")
            with self.assertRaisesRegex(ValueError, "^existing managed output preserved; verify reuse explicitly$"):
                outputs.write_bytes("a.bin", b"a", role="control", max_bytes=8, intent="a")
            with self.assertRaisesRegex(ValueError, "^managed file identity changed; no refund or new lease$"):
                outputs.write_bytes("a.bin", b"a", role="control", max_bytes=9, intent="a")


if __name__ == "__main__":
    unittest.main()
