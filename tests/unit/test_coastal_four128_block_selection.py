"""The four128 window set is the fully valid 2x2 block the pre-scan selected (T08-FIX3).

Attempt 4's block at origin [3890,3360] held because window B [4018,3488] had 18
and window D [4018,3360] had 962 mask-invalid BAG cells. grant_identity admits the
larger profile only as a contiguous 2x2 block, so the whole block moved (G option
A; Fable ruling, t_c8b57dcc comment by fable-2nd-look 21:50 PDT). The block rule
runs over the pre-scan receipt's candidate table and never opens the source. These
tests use synthetic tables; the real receipt is only read when present on the
maintainer machine (CI uses the pins).
"""
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from skippercast.coastal.authenticated_v1.profiles import CONTAINED, LARGER, grant_identity
from skippercast.coastal.coordinator.ordered_trial import LARGER_AFFINE, LARGER_BOUNDS, LARGER_WINDOWS
from tests._support import FIXTURES, ROOT

SCRIPT = ROOT / "research" / "scripts" / "coastal_four128_window_scan.py"
PRESCAN = Path.home() / "skippercast-data/2026-10-07-pge-south/outputs/t08-four128-20261019/window-prescan"
RULED_WINDOWS = [[3762, 3488, 128, 128], [3890, 3488, 128, 128], [3762, 3360, 128, 128], [3890, 3360, 128, 128]]
RULED_BOUNDS = [728615, 3818923, 729127, 3819435]
OLD_WINDOWS = [[3890, 3488, 128, 128], [4018, 3488, 128, 128], [3890, 3360, 128, 128], [4018, 3360, 128, 128]]


def load_scan():
    spec = importlib.util.spec_from_file_location("coastal_four128_window_scan", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def table(valid, contained=None):
    """The 8 x 8 lattice; windows in valid (col, row) -> max uncertainty are fully valid."""
    contained = contained or {}
    return [dict(window=[c, r, 128, 128], fully_valid=(c, r) in valid,
                 segment_contained_10m=contained.get((c, r), True),
                 uncertainty_max_m=valid.get((c, r), 0.25))
            for r in range(3360 - 384, 3360 + 640, 128) for c in range(3890 - 384, 3890 + 640, 128)]


def block(c, r, umax):
    return {(c, r): umax, (c + 128, r): umax, (c, r + 128): umax, (c + 128, r + 128): umax}


def grant(windows, profile, **extra):
    return dict(schema="t", source={}, source_root="-", source_relative_path="-",
                execution_profile=profile, window_set=[list(w) for w in windows], **extra)


class WindowSet(unittest.TestCase):
    def test_ruled_block_is_pinned(self):
        self.assertEqual(LARGER_WINDOWS, RULED_WINDOWS)
        self.assertEqual(LARGER_BOUNDS, RULED_BOUNDS)
        self.assertEqual(LARGER_AFFINE, [2, 0, 721091, 0, -2, 3826155])
        cols = [w[0] for w in LARGER_WINDOWS]
        rows = [w[1] for w in LARGER_WINDOWS]
        # The brief's union formula, from the affine.
        self.assertEqual(LARGER_BOUNDS, [721091 + 2 * min(cols), 3826155 - 2 * (max(rows) + 128),
                                         721091 + 2 * (max(cols) + 128), 3826155 - 2 * min(rows)])
        self.assertEqual(load_scan().union_bounds(LARGER_WINDOWS), LARGER_BOUNDS)

    def test_four_windows_do_not_overlap_and_tile_the_bounds(self):
        scan = load_scan()
        for i, a in enumerate(LARGER_WINDOWS):
            for b in LARGER_WINDOWS[i + 1:]:
                self.assertFalse(scan.overlaps(a, b), (a, b))
        x0, y0, x1, y1 = LARGER_BOUNDS
        boxes = [scan.native_bounds(w[0], w[1]) for w in LARGER_WINDOWS]
        for bx in boxes:
            self.assertTrue(x0 <= bx[0] < bx[2] <= x1 and y0 <= bx[1] < bx[3] <= y1, bx)
        self.assertEqual(sum((b[2] - b[0]) * (b[3] - b[1]) for b in boxes), (x1 - x0) * (y1 - y0))
        self.assertEqual(sum(w[2] * w[3] for w in LARGER_WINDOWS), 65536)
        self.assertEqual(sorted({b[0] for b in boxes} | {b[2] for b in boxes}), [x0, (x0 + x1) // 2, x1])
        self.assertEqual(sorted({b[1] for b in boxes} | {b[3] for b in boxes}), [y0, (y0 + y1) // 2, y1])

    def test_grant_identity_admits_the_block_in_a_b_c_d_order(self):
        for profile, extra in ((LARGER, {}), (CONTAINED, dict(window_side=128, window_count=4))):
            with self.subTest(profile=profile):
                self.assertEqual(grant_identity(grant(LARGER_WINDOWS, profile, **extra))["window_set"],
                                 LARGER_WINDOWS)
                with self.assertRaises(ValueError):
                    grant_identity(grant(LARGER_WINDOWS[::-1], profile, **extra))
        self.assertTrue(load_scan().grant_admits(LARGER_WINDOWS))
        # The row-3616 single-window replacement the first rule picked is refused by the grant.
        with self.assertRaises(ValueError):
            grant_identity(grant([[3890, 3488, 128, 128], [4146, 3616, 128, 128], [3890, 3360, 128, 128],
                                  [4018, 3360, 128, 128]], LARGER))

    def test_old_block_is_gone_from_the_execution_constants(self):
        self.assertNotIn([4018, 3488, 128, 128], LARGER_WINDOWS)
        self.assertNotIn([4018, 3360, 128, 128], LARGER_WINDOWS)
        # New B and D are attempt 4's A and C (their diagnostics stay comparable).
        self.assertEqual([LARGER_WINDOWS[1], LARGER_WINDOWS[3]], [OLD_WINDOWS[0], OLD_WINDOWS[2]])


class BlockRule(unittest.TestCase):
    def setUp(self):
        self.scan = load_scan()

    def tearDown(self):
        sys.modules.pop("coastal_four128_window_scan", None)

    def origins(self, valid, contained=None):
        return [b["origin"] for b in self.scan.ranked_blocks(table(valid, contained))]

    def test_distance_wins_over_uncertainty(self):
        valid = {**block(4146, 3360, 0.10), **block(3762, 3360, 0.50)}
        self.assertEqual(self.origins(valid), [[3762, 3360], [4146, 3360]])
        chosen = self.scan.select_block(table(valid))
        self.assertEqual((chosen["chebyshev_from_origin"], chosen["max_uncertainty_m"]), (1, 0.50))
        self.assertEqual(chosen["windows"], RULED_WINDOWS)
        self.assertEqual(chosen["native_bounds"], RULED_BOUNDS)

    def test_equal_distance_goes_to_lowest_max_uncertainty(self):
        valid = {**block(3762, 3232, 0.40), **block(4018, 3488, 0.30)}
        self.assertEqual(self.origins(valid), [[4018, 3488], [3762, 3232]])
        # One window of a block raises that block's maximum.
        valid[(4146, 3616)] = 0.45
        self.assertEqual(self.origins(valid), [[3762, 3232], [4018, 3488]])

    def test_equal_distance_and_uncertainty_go_to_lowest_row_then_col(self):
        valid = {**block(3762, 3232, 0.30), **block(4018, 3488, 0.30)}
        self.assertEqual(self.origins(valid), [[3762, 3232], [4018, 3488]])
        valid = {**block(4146, 3104, 0.30), **block(3634, 3104, 0.30)}  # same row, distance 2
        self.assertEqual(self.origins(valid), [[3634, 3104], [4146, 3104]])

    def test_invalid_or_uncontained_windows_break_a_block(self):
        valid = {**block(3762, 3360, 0.30), **block(4146, 3360, 0.30)}
        self.assertEqual(self.origins(valid, {(3890, 3488): False}), [[4146, 3360]])
        del valid[(4274, 3488)]
        self.assertEqual(self.origins(valid), [[3762, 3360]])
        del valid[(3762, 3360)]
        self.assertIsNone(self.scan.select_block(table(valid)))
        # The attempt-4 block cannot win while B is invalid, however low its uncertainty.
        valid = {**block(3890, 3360, 0.01), **block(3762, 3360, 0.30)}
        del valid[(4018, 3488)]
        self.assertEqual(self.origins(valid), [[3762, 3360]])

    def test_malformed_tables_are_refused(self):
        rows = table(block(3762, 3360, 0.3))
        with self.assertRaisesRegex(ValueError, "duplicate window"):
            self.scan.ranked_blocks(rows + rows[:1])
        off = [dict(r, window=[r["window"][0] + 1] + r["window"][1:]) for r in rows]
        with self.assertRaisesRegex(ValueError, "off the lattice"):
            self.scan.ranked_blocks(off)


class SelectBlockMode(unittest.TestCase):
    """--select-block reads a pinned receipt and its erratum and never opens the source."""

    def setUp(self):
        self.scan = load_scan()
        self.tmp = tempfile.TemporaryDirectory(dir=FIXTURES)  # TMPDIR may sit under a scratch dir
        self.dir = Path(self.tmp.name)
        valid = {**block(3762, 3360, 0.388), **block(3762, 3488, 0.388)}
        rows = table(valid)
        reference = [r for r in rows if r["window"][:2] in ([3890, 3488], [3890, 3360], [4018, 3360])]
        receipt = dict(schema=self.scan.SCHEMA, status="CHOSEN_BREAKS_WINDOW_ORDER", source=dict(opens=1),
                       controls=dict(B=dict(match=True)), reference_fixed_windows=reference,
                       candidates=[r for r in rows if r not in reference])
        self.receipt = self.dir / "prescan-receipt.json"
        self.receipt.write_bytes(json.dumps(receipt).encode())
        self.receipt_sha = hashlib.sha256(self.receipt.read_bytes()).hexdigest()
        erratum = dict(receipt=dict(path="prescan-receipt.json", sha256=self.receipt_sha),
                       candidate_table_affected=False)
        (self.dir / self.scan.ERRATUM_NAME).write_bytes(json.dumps(erratum).encode())
        self.erratum_sha = hashlib.sha256((self.dir / self.scan.ERRATUM_NAME).read_bytes()).hexdigest()

    def tearDown(self):
        self.tmp.cleanup()
        sys.modules.pop("coastal_four128_window_scan", None)

    def pinned(self, receipt=None, erratum=None):
        return mock.patch.multiple(self.scan, RECEIPT_SHA256=receipt or self.receipt_sha,
                                   ERRATUM_SHA256=erratum or self.erratum_sha)

    def test_writes_the_selection_beside_the_receipt(self):
        with self.pinned(), mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = self.scan.main(["--select-block", str(self.receipt), "--code-head", "abc"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.scan.OPENS, [])
        printed = json.loads(out.getvalue())
        self.assertIs(printed["source_opened"], False)
        data = (self.dir / "block-selection.json").read_bytes()
        self.assertEqual(printed["sha256"], hashlib.sha256(data).hexdigest())
        doc = json.loads(data)
        self.assertEqual(doc["rule"], self.scan.BLOCK_RULE)
        self.assertEqual(doc["ruling"], "t_c8b57dcc comment by fable-2nd-look 21:50 PDT")
        self.assertEqual((doc["receipt"]["sha256"], doc["erratum"]["sha256"]), (self.receipt_sha, self.erratum_sha))
        self.assertEqual([b["origin"] for b in doc["ranked_blocks"]], [[3762, 3360], [3762, 3488]])
        self.assertEqual(doc["chosen"]["origin"], [3762, 3360])
        self.assertEqual([w["label"] for w in doc["chosen"]["windows"]], list("ABCD"))
        self.assertEqual((doc["LARGER_WINDOWS"], doc["LARGER_BOUNDS"]), (LARGER_WINDOWS, LARGER_BOUNDS))
        self.assertIs(doc["grant_identity_admits"], True)
        self.assertIs(doc["ordered_trial_matches"], True)
        self.assertEqual((doc["source_opened"], doc["source_bytes_read"], doc["network_requests"]), (False, 0, 0))
        # Never overwritten.
        with self.pinned(), self.assertRaisesRegex(ValueError, "overwrite"):
            self.scan.main(["--select-block", str(self.receipt)])

    def test_unpinned_receipt_or_erratum_is_refused(self):
        with self.pinned(receipt="0" * 64), self.assertRaisesRegex(ValueError, "charged-run receipt"):
            self.scan.select_block_document(self.receipt)
        with self.pinned(erratum="0" * 64), self.assertRaisesRegex(ValueError, "pinned erratum"):
            self.scan.select_block_document(self.receipt)
        self.assertFalse((self.dir / "block-selection.json").exists())

    def test_select_block_takes_no_source(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
            self.scan.main(["--select-block", str(self.receipt), "--source", str(self.dir / "source.bag")])
        self.assertEqual(self.scan.OPENS, [])


class RealReceiptOnThisMachine(unittest.TestCase):
    """Read-only recomputation from the charged run's receipt when present (CI uses the pins)."""

    def test_rule_over_the_real_candidate_table(self):
        path = PRESCAN / "prescan-receipt.json"
        if not path.is_file():
            return
        scan = load_scan()
        try:
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), scan.RECEIPT_SHA256)
            doc = json.loads(path.read_bytes())
            records = doc["candidates"] + doc["reference_fixed_windows"]
            by_window = {tuple(r["window"][:2]): r for r in records}
            for w in LARGER_WINDOWS:
                r = by_window[(w[0], w[1])]
                self.assertEqual((r["fully_valid"], r["eligible"], r["mask_invalid"], r["segment_contained_10m"]),
                                 (True, 16384, 0, True), w)
            self.assertEqual((by_window[(4018, 3488)]["eligible"], by_window[(4018, 3488)]["mask_invalid"]),
                             (16366, 18))
            self.assertEqual((by_window[(4018, 3360)]["eligible"], by_window[(4018, 3360)]["mask_invalid"]),
                             (15422, 962))
            blocks = scan.ranked_blocks(records)
            self.assertEqual(len(blocks), 15)
            self.assertEqual([b["origin"] for b in blocks[:2]], [[3762, 3360], [3762, 3488]])
            self.assertEqual(blocks[0]["max_uncertainty_m"], blocks[1]["max_uncertainty_m"])
            self.assertEqual((blocks[0]["windows"], blocks[0]["native_bounds"]), (LARGER_WINDOWS, LARGER_BOUNDS))
            selection = PRESCAN / "block-selection.json"
            if selection.is_file():
                written = json.loads(selection.read_bytes())
                self.assertEqual((written["LARGER_WINDOWS"], written["LARGER_BOUNDS"]), (LARGER_WINDOWS, LARGER_BOUNDS))
                self.assertEqual(written["receipt"]["sha256"], scan.RECEIPT_SHA256)
        finally:
            sys.modules.pop("coastal_four128_window_scan", None)


if __name__ == "__main__":
    unittest.main()
