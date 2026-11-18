"""Over-age status-ok backup sources count toward a whole-kind critical outage."""
import unittest

from scripts import check_feed_freshness as cff

BUILT = "2026-01-01T12:00:00Z"


def source(sid, hours, kind="observation", status="ok", backup=False, **extra):
    stamp = f"2026-01-01T{12 - hours:02d}:00:00Z" if hours is not None else None
    item = {"id": sid, "kind": kind, "status": status, "checked_at": BUILT,
            "data": {"sample_at": stamp} if stamp else {}, **extra}
    if backup:
        item.update(station="synthetic-backup", fallback_for="synthetic-primary")
    return item


def feed(*sources):
    return {"generated_at": BUILT, "sources": {s["id"]: s for s in sources}}


def verdict(*sources):
    data = feed(*sources)
    bits, lines = cff.source_verdict(data, 3, "Synthetic")
    return bits, lines, cff.failing_kinds(data, 3)


class OldBackupTests(unittest.TestCase):
    def test_old_ok_backup_fails_whole_critical_kind(self):
        bits, lines, failing = verdict(source("a", 11, backup=True))
        self.assertEqual(failing, ["observation"])
        self.assertEqual(bits, cff.DEGRADED)
        self.assertTrue(any(line.startswith("- FAIL") for line in lines))
        self.assertIn("ok, backup synthetic-backup", lines[1])

    def test_old_backup_with_healthy_primary_is_partial(self):
        bits, _, failing = verdict(source("a", 11, backup=True), source("b", 0))
        self.assertEqual((bits, failing), (cff.PARTIAL, []))
        bits, _, failing = verdict(source("a", 11, backup=True), source("b", 10, backup=True))
        self.assertEqual((bits, failing), (cff.DEGRADED, ["observation"]))

    def test_fresh_and_exact_limit_backups_only_warn(self):
        for hours in (1, 3):
            bits, lines, failing = verdict(source("a", hours, backup=True))
            self.assertEqual((bits, failing), (0, []))
            self.assertIn("degraded service", lines[1])
            self.assertIn("none critical past 3 h", lines[0])

    def test_missing_backup_clock_and_noncritical_control(self):
        self.assertEqual(verdict(source("a", None, backup=True))[2], ["observation"])
        bits, _, failing = verdict(source("a", 11, kind="synthetic-noncritical", backup=True),
                                   source("b", None, kind="synthetic-noncritical", backup=True))
        self.assertEqual((bits, failing), (0, []))

    def test_nonbackup_and_retained_controls(self):
        self.assertEqual(verdict(source("a", 11))[:1] + verdict(source("a", 11))[2:], (0, []))
        self.assertEqual(verdict(source("a", 11, fallback_for=""))[2], [])
        self.assertEqual(verdict(source("a", 11, status="retained"))[2], ["observation"])
        self.assertEqual(verdict(source("a", 11, status="stale"))[2], ["observation"])


if __name__ == "__main__":
    unittest.main()
