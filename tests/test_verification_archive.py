"""A prospective history must survive publication and fail closed if incomplete."""
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skippercast.pipeline.verification_archive import load_archive, write_archive, prune_archive, MAX_RAW_BYTES

NOW = 1790092800
REGION = 'morro-bay'


def row(index=0):
    return {'id': f'forecast-{index}', 'station': '46215', 'model': 'ncep_gfswave025',
            'cycle': NOW - 21600, 'time': NOW + index * 3600, 'value': 3,
            'variable': 'wave_height', 'unit': 'ft', 'acquired_at': NOW - 20000}


def obs():
    return {'id': 'obs-1', 'station': '46215', 'time': NOW, 'value': 2, 'unit': 'ft', 'variable': 'wave_height'}


class VerificationArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def manifest(self, root=None):
        return json.loads(((root or self.root) / 'verification-state.json').read_text())

    def test_new_region_and_required_missing_state_are_distinct(self):
        self.assertEqual(load_archive(self.root, REGION)['forecasts'], [])
        with self.assertRaisesRegex(ValueError, 'missing'):
            load_archive(self.root, REGION, required=True)

    def test_v1_migration_preserves_every_row_and_a_previous_generation(self):
        legacy = {'schema_version': 1, 'region_id': REGION, 'forecasts': [row()], 'observations': [obs()]}
        (self.root / 'verification-state.json').write_text(json.dumps(legacy))
        self.assertEqual(load_archive(self.root, REGION), legacy)
        new = write_archive(self.root, REGION, [row(), row(1)], [obs()], NOW)
        self.assertEqual(new['schema_version'], 2)
        self.assertEqual(new['storage'], 'gzip-shards-v1')
        self.assertEqual(load_archive(self.root, REGION)['forecasts'], [row(), row(1)])
        self.assertEqual(load_archive(self.root, REGION, manifest_name='verification-state.previous.json'), legacy)
        self.assertLess((self.root / 'verification-state.json').stat().st_size, 10000)

    def test_gzip_shards_are_deterministic_when_rows_arrive_in_different_order(self):
        a, b = self.root / 'a', self.root / 'b'
        ma = write_archive(a, REGION, [row(), row(1)], [obs()], NOW)
        mb = write_archive(b, REGION, [row(1), row()], [obs()], NOW + 60)
        self.assertEqual(ma['shards'], mb['shards'])
        for entry in ma['shards']:
            self.assertEqual((a / entry['path']).read_bytes(), (b / entry['path']).read_bytes())

    def test_every_shard_obeys_row_and_expanded_size_bounds(self):
        with patch('skippercast.pipeline.verification_archive.MAX_ROWS', 2):
            manifest = write_archive(self.root, REGION, [row(i) for i in range(7)], [], NOW)
            self.assertEqual(len(manifest['shards']), 4)
            self.assertTrue(all(e['count'] <= 2 and e['raw_bytes'] <= MAX_RAW_BYTES for e in manifest['shards']))
            self.assertEqual(len(load_archive(self.root, REGION)['forecasts']), 7)

    def test_raw_size_bound_splits_before_compression(self):
        with patch('skippercast.pipeline.verification_archive.MAX_RAW_BYTES', 800):
            manifest = write_archive(self.root, REGION, [row(i) for i in range(8)], [], NOW)
            self.assertGreater(len(manifest['shards']), 1)
            self.assertTrue(all(e['raw_bytes'] <= 800 for e in manifest['shards']))

    def test_one_unbounded_record_fails_without_publishing_a_manifest(self):
        with self.assertRaisesRegex(ValueError, 'record exceeds'):
            write_archive(self.root, REGION, [{**row(), 'unbounded': 'x' * MAX_RAW_BYTES}], [], NOW)
        self.assertFalse((self.root / 'verification-state.json').exists())

    def test_missing_corrupt_and_wrong_region_archives_do_not_restart(self):
        manifest = write_archive(self.root, REGION, [row()], [], NOW)
        path = self.root / manifest['shards'][0]['path']
        original = path.read_bytes()
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing'):
            load_archive(self.root, REGION)
        path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with self.assertRaisesRegex(ValueError, 'checksum'):
            load_archive(self.root, REGION)
        path.write_bytes(original)
        with self.assertRaisesRegex(ValueError, 'another region'):
            load_archive(self.root, 'wrong-region')

    def test_duplicate_manifest_paths_and_total_mismatch_fail(self):
        manifest = write_archive(self.root, REGION, [row()], [], NOW)
        path = self.root / 'verification-state.json'
        manifest['forecasts_count'] = 2
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'total count'):
            load_archive(self.root, REGION)
        manifest['forecasts_count'] = 1
        manifest['shards'].append(dict(manifest['shards'][0]))
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            load_archive(self.root, REGION)

    def test_path_traversal_and_symlinks_are_rejected(self):
        manifest = write_archive(self.root, REGION, [row()], [], NOW)
        source = self.root / manifest['shards'][0]['path']
        manifest['shards'][0]['path'] = '../outside.json.gz'
        (self.root / 'verification-state.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'path'):
            load_archive(self.root, REGION)
        manifest['shards'][0]['path'] = source.relative_to(self.root).as_posix()
        (self.root / 'verification-state.json').write_text(json.dumps(manifest))
        outside = self.root / 'outside.gz'
        source.rename(outside)
        source.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            load_archive(self.root, REGION)

    def test_compression_bomb_cannot_expand_beyond_bound(self):
        manifest = write_archive(self.root, REGION, [row()], [], NOW)
        entry = manifest['shards'][0]
        data = gzip.compress(b'x' * (MAX_RAW_BYTES + 1), mtime=0)
        (self.root / entry['path']).write_bytes(data)
        entry['sha256'] = hashlib.sha256(data).hexdigest()
        entry['compressed_bytes'] = len(data)
        (self.root / 'verification-state.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'expanded size'):
            load_archive(self.root, REGION)

    def test_current_and_previous_only_pruning_never_deletes_unmanaged_files(self):
        first = write_archive(self.root, REGION, [row()], [], NOW)
        second = write_archive(self.root, REGION, [row(), row(1)], [], NOW + 60)
        keep_path = self.root / 'verification-archive' / 'user-notes.json.gz'
        keep_path.write_text('not a managed shard')
        third = write_archive(self.root, REGION, [row(), row(1), row(2)], [], NOW + 120)
        self.assertFalse((self.root / first['shards'][0]['path']).exists())
        self.assertTrue((self.root / second['shards'][0]['path']).exists())
        self.assertTrue((self.root / third['shards'][0]['path']).exists())
        self.assertTrue(keep_path.exists())
        self.assertEqual(load_archive(self.root, REGION, manifest_name='verification-state.previous.json')['forecasts'], [row(), row(1)])
        self.assertEqual(prune_archive(self.root), 0)

    def test_fresh_output_copies_prior_immutable_shards_and_checks_them(self):
        prior, new = self.root / 'prior', self.root / 'new'
        first = write_archive(prior, REGION, [row()], [], NOW)
        write_archive(new, REGION, [row(), row(1)], [], NOW + 60, prior)
        self.assertTrue((new / first['shards'][0]['path']).is_file())
        self.assertEqual(len(load_archive(new, REGION)['forecasts']), 2)
        (prior / first['shards'][0]['path']).unlink()
        with self.assertRaisesRegex(ValueError, 'Missing'):
            write_archive(self.root / 'failed', REGION, [], [], NOW + 120, prior)
        self.assertFalse((self.root / 'failed' / 'verification-state.json').exists())

    def test_failed_new_shard_write_keeps_previous_manifest_valid(self):
        first = write_archive(self.root, REGION, [row()], [], NOW)
        with patch('skippercast.pipeline.verification_archive._write_generation', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                write_archive(self.root, REGION, [row(), row(1)], [], NOW + 60)
        self.assertEqual(self.manifest(), first)
        self.assertEqual(load_archive(self.root, REGION)['forecasts'], [row()])


if __name__ == '__main__':
    unittest.main()
