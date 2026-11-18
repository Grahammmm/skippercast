"""MB-12: the relief budget check exits non-zero only on a synthetic over-budget fixture."""
import json
import struct
import tempfile
import unittest
from pathlib import Path

from scripts import check_relief_budget as crb


def fake_pmtiles(path: Path, data_len: int, tiles: int) -> None:
    head = bytearray(127)
    head[:7] = b'PMTiles'
    head[7] = 3
    struct.pack_into('<QQ', head, 64, data_len, tiles)
    head[100], head[101] = 10, 15
    path.write_bytes(bytes(head) + b'\0' * 10)


class ReliefBudgetTests(unittest.TestCase):
    def run_fixture(self, regions, z17=None):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'fixture.json'
            f.write_text(json.dumps({'regions': regions}))
            return crb.main(['--fixture', str(f), '--z17-size', str(z17 or Path(tmp) / 'absent.md')])

    def test_view_tile_counts(self):
        self.assertEqual(crb.tiles_in_view(1200, 800), 30)
        self.assertEqual(crb.tiles_in_view(390, 844), 15)

    def test_within_budget_fixture_exits_zero(self):
        ok = {'r': {'mean_tile_bytes': 50_000, 'archive_bytes': 10_000_000, 'contours_overview_bytes': 50_000, 'contours_full_bytes': 800_000}}
        self.assertEqual(self.run_fixture(ok), 0)

    def test_each_over_budget_fixture_exits_nonzero(self):
        for bad in ({'mean_tile_bytes': 60_000}, {'archive_bytes': 1_600_000_000},
                    {'contours_overview_bytes': 300_001}, {'contours_full_bytes': 1_000_001}):
            self.assertEqual(self.run_fixture({'r': bad}), 1, bad)

    def test_phone_budget_binds_before_desktop(self):
        # 55,000 B/tile: desktop 30 tiles = 1.65 MB is over; 54,000 B: desktop 1.62 MB over, 53,000: 1.59 ok, phone 0.795 ok.
        self.assertEqual(self.run_fixture({'r': {'mean_tile_bytes': 53_000}}), 0)
        self.assertEqual(self.run_fixture({'r': {'mean_tile_bytes': 54_000}}), 1)

    def test_real_run_over_budget_still_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            fake_pmtiles(d / 'laguna-B.pmtiles', 126 * 90_000, 126)
            code = crb.main(['--design-dir', str(d), '--repo', str(d), '--z17-size', str(d / 'none.md')])
            self.assertEqual(code, 0)
            self.assertEqual(crb.main(['--design-dir', str(d), '--repo', str(d), '--z17-size', str(d / 'none.md'), '--strict']), 1)

    def test_header_parse_and_bad_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'a.pmtiles'
            fake_pmtiles(p, 1000, 10)
            r = crb.region_from_archive(p)
            self.assertEqual((r['tile_count'], r['mean_tile_bytes']), (10, 100))
            p.write_bytes(b'nope')
            with self.assertRaises(ValueError):
                crb.pmtiles_header(p)

    def test_z17_absent_is_stated_and_present_is_echoed(self):
        with tempfile.TemporaryDirectory() as tmp:
            absent = Path(tmp) / 'Z17-SIZE.md'
            self.assertIn('NOT REPORTED', crb.z17_report(absent)[0])
            absent.write_text('# z17\n| region | bytes |\n| laguna | 5075684 |\n')
            self.assertIn('| laguna | 5075684 |', crb.z17_report(absent))


if __name__ == '__main__':
    unittest.main()
