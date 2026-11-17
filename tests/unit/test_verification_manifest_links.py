"""Dangling manifest links must be refused, never treated as absent history."""
from pathlib import Path
import tempfile
import unittest

from skippercast.pipeline.verification_archive import load_archive, write_archive, prune_archive

NOW = 1790092800
REGION = 'morro-bay'
LINKED = 'linked'
ROW = {'id': 'f0', 'station': '46215', 'model': 'ncep_gfswave016', 'cycle': NOW - 21600,
       'time': NOW, 'value': 3, 'variable': 'wave_height', 'unit': 'ft', 'acquired_at': NOW - 20000}


def shards(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob('*.json.gz'))


class DanglingManifestLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def two_generations(self):
        write_archive(self.root, REGION, [ROW], [], NOW)
        write_archive(self.root, REGION, [dict(ROW, id='f1', time=NOW + 86400 * 3, cycle=NOW + 86400 * 3 - 21600)], [], NOW + 60)

    def dangle(self, root, name):
        link = root / name
        link.unlink(missing_ok=True)
        link.symlink_to(root / 'nowhere.json')
        return link

    def test_dangling_selected_manifest_is_not_empty_history(self):
        for name in ('verification-state.json', 'verification-state.previous.json'):
            link = self.dangle(self.root, name)
            for required in (False, True):
                with self.assertRaisesRegex(ValueError, LINKED):
                    load_archive(self.root, REGION, required, manifest_name=name)
            self.assertTrue(link.is_symlink())
            self.assertFalse((self.root / 'nowhere.json').exists())

    def test_dangling_prior_manifest_cannot_restart_writer(self):
        link = self.dangle(self.root, 'verification-state.json')
        with self.assertRaisesRegex(ValueError, LINKED):
            write_archive(self.root, REGION, [ROW], [], NOW)
        self.assertTrue(link.is_symlink())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['verification-state.json'])
        prior, out = self.root / 'prior', self.root / 'out'
        prior.mkdir()
        self.dangle(prior, 'verification-state.json')
        with self.assertRaisesRegex(ValueError, LINKED):
            write_archive(out, REGION, [ROW], [], NOW, previous_directory=prior)
        self.assertFalse(out.exists())

    def test_dangling_previous_manifest_blocks_pruning(self):
        self.two_generations()
        before = shards(self.root)
        sentinel = self.root / 'verification-archive' / 'keep.txt'
        sentinel.write_text('x')
        link = self.dangle(self.root, 'verification-state.previous.json')
        with self.assertRaisesRegex(ValueError, LINKED):
            prune_archive(self.root)
        self.assertEqual(shards(self.root), before)
        self.assertTrue(link.is_symlink())
        self.assertTrue(sentinel.exists())

    def test_dangling_current_manifest_blocks_pruning(self):
        self.two_generations()
        before = shards(self.root)
        self.dangle(self.root, 'verification-state.json')
        with self.assertRaisesRegex(ValueError, LINKED):
            prune_archive(self.root)
        self.assertEqual(shards(self.root), before)

    def test_absent_and_regular_manifest_controls(self):
        self.assertEqual(load_archive(self.root, REGION)['forecasts'], [])
        self.assertEqual(prune_archive(self.root), 0)
        write_archive(self.root, REGION, [ROW], [], NOW)
        self.assertEqual(load_archive(self.root, REGION)['forecasts'], [ROW])
        self.two_generations()
        self.assertEqual(prune_archive(self.root), 0)
