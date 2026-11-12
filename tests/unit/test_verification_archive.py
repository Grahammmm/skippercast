"""A prospective history must survive publication and fail closed if incomplete."""
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skippercast.pipeline import verification_archive
from skippercast.pipeline.verification_archive import load_archive, write_archive, prune_archive, MAX_RAW_BYTES

NOW = 1790092800
REGION = 'morro-bay'


class _SpyStream:
    """Delegating binary stream that records every read request and its returned size."""

    def __init__(self, stream, log):
        self._stream, self._log = stream, log

    def read(self, size=-1):
        data = self._stream.read(size)
        self._log.append((size, len(data)))
        return data

    def __enter__(self):
        self._stream.__enter__()
        return self

    def __exit__(self, *exc):
        return self._stream.__exit__(*exc)

    def __getattr__(self, name):
        return getattr(self._stream, name)


@contextmanager
def grow_after_fstat(target, extra):
    """Append to the real regular file right after its descriptor is stat'ed for admission."""
    real = os.fstat
    stat = Path(target).stat()
    state = {'done': False}

    def fstat(fd):
        result = real(fd)
        if not state['done'] and (result.st_dev, result.st_ino) == (stat.st_dev, stat.st_ino):
            state['done'] = True
            with open(target, 'ab') as stream:
                stream.write(extra)
        return result

    with patch('skippercast.pipeline.verification_archive.os.fstat', fstat):
        yield state


@contextmanager
def spy_reads(log):
    real = os.fdopen

    def fdopen(fd, mode='r', *args, **kwargs):
        stream = real(fd, mode, *args, **kwargs)
        return _SpyStream(stream, log) if mode == 'rb' else stream

    with patch('skippercast.pipeline.verification_archive.os.fdopen', fdopen):
        yield


def row(index=0):
    return {'id': f'forecast-{index}', 'station': '46215', 'model': 'ncep_gfswave016',
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

    def test_json_at_cap_and_cap_plus_one(self):
        path = self.root / 'm.json'
        path.write_bytes(b'{"value": 1}' + b' ' * 52)
        self.assertEqual(path.stat().st_size, 64)
        self.assertEqual(verification_archive._read_json(path, 64), {'value': 1})
        path.write_bytes(b'{"value": 1}' + b' ' * 53)
        with self.assertRaisesRegex(ValueError, 'exceeds its size bound'):
            verification_archive._read_json(path, 64)
        path.write_bytes(b'{"value": ')
        with self.assertRaises(json.JSONDecodeError):
            verification_archive._read_json(path, 64)

    def test_linked_manifest_is_refused(self):
        write_archive(self.root, REGION, [row()], [], NOW)
        (self.root / 'linked.json').symlink_to(self.root / 'verification-state.json')
        with self.assertRaisesRegex(ValueError, 'linked'):
            verification_archive._read_json(self.root / 'linked.json', 1 << 20)

    def test_post_fstat_growth_is_refused_before_decode(self):
        path = self.root / 'm.json'
        path.write_bytes(b'{"value": 1}')
        log = []
        with grow_after_fstat(path, b' ' * 127) as state, spy_reads(log), \
                patch('skippercast.pipeline.verification_archive.json.loads') as loads:
            with self.assertRaisesRegex(ValueError, 'exceeds its size bound'):
                verification_archive._read_json(path, 64)
        self.assertTrue(state['done'])
        self.assertEqual(path.stat().st_size, 139)
        loads.assert_not_called()
        self.assertTrue(log)
        self.assertTrue(all(requested == 65 for requested, _ in log))
        self.assertLessEqual(sum(returned for _, returned in log), 65)

    def test_load_archive_growth_cannot_return_legacy_history(self):
        legacy = {'schema_version': 1, 'region_id': REGION, 'forecasts': [row()], 'observations': [obs()]}
        path = self.root / 'verification-state.json'
        path.write_text(json.dumps(legacy))
        cap = path.stat().st_size + 16
        with patch('skippercast.pipeline.verification_archive.MAX_LEGACY_BYTES', cap):
            self.assertEqual(load_archive(self.root, REGION, required=True), legacy)
            with grow_after_fstat(path, b' ' * 256) as state:
                with self.assertRaisesRegex(ValueError, 'exceeds its size bound'):
                    load_archive(self.root, REGION, required=True)
        self.assertTrue(state['done'])

    def test_prior_read_failure_does_not_install_new_manifests(self):
        write_archive(self.root, REGION, [row()], [], NOW)
        path = self.root / 'verification-state.json'
        sentinel = self.root / 'verification-archive' / 'sentinel.txt'
        sentinel.write_bytes(b'unrelated bytes')
        shards = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file())
        with patch('skippercast.pipeline.verification_archive.MAX_LEGACY_BYTES', path.stat().st_size + 16):
            with grow_after_fstat(path, b' ' * 256) as state:
                with self.assertRaisesRegex(ValueError, 'exceeds its size bound'):
                    write_archive(self.root, REGION, [row(), row(1)], [], NOW + 60)
        self.assertTrue(state['done'])
        self.assertFalse((self.root / 'verification-state.previous.json').exists())
        self.assertEqual(sentinel.read_bytes(), b'unrelated bytes')
        self.assertEqual(sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file()), shards)
        self.assertEqual(json.loads(path.read_bytes()).get('forecasts_count'), 1)

    def test_prune_growth_never_removes_shards(self):
        write_archive(self.root, REGION, [row()], [], NOW)
        write_archive(self.root, REGION, [row(), row(1)], [], NOW + 60)
        unmanaged = self.root / 'verification-archive' / 'forecasts' / 'unmanaged.json.gz'
        unmanaged.write_bytes(b'kept')
        before = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file())
        for name, constant in (('verification-state.json', 'MAX_LEGACY_BYTES'),
                               ('verification-state.previous.json', 'MAX_MANIFEST_BYTES')):
            with self.subTest(manifest=name):
                path = self.root / name
                cap = max((self.root / n).stat().st_size for n in ('verification-state.json', 'verification-state.previous.json')) + 16
                with patch('skippercast.pipeline.verification_archive.' + constant, cap):
                    with grow_after_fstat(path, b' ' * 256) as state:
                        with self.assertRaisesRegex(ValueError, 'exceeds its size bound'):
                            prune_archive(self.root)
                self.assertTrue(state['done'])
                path.write_bytes(path.read_bytes().rstrip(b' '))
                self.assertEqual(sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file()), before)
        self.assertEqual(unmanaged.read_bytes(), b'kept')


if __name__ == '__main__':
    unittest.main()
