"""import_manifest reports a local original it cannot read per source and keeps importing the batch.

Contract: a refusal (unreadable original, malformed manifest row) is one entry in ``refused`` with a
reason naming the problem; the other sources are still tried and an earlier verified cache entry stays.
"""
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from skippercast.seafloor import local_sources
from skippercast.seafloor.local_sources import LocalSourceRoot, import_manifest

URLS = {'a': 'https://pubs.usgs.gov/fixture/first.tif', 'b': 'https://pubs.usgs.gov/fixture/second.tif'}


class UnreadableOriginalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.local = self.base / 'downloads'
        (self.local / '_geofetch').mkdir(parents=True)
        self.cache = self.base / 'cache'
        self.files, self.entries, self.rows = {}, [], {}
        for key, payload in (('a', b'first original'), ('b', b'second original, longer')):
            path = self.local / f'{key}.tif'
            path.write_bytes(payload)
            sha = hashlib.sha256(payload).hexdigest()
            self.files[key] = path
            self.entries.append({'id': f'cat-{key}', 'url': URLS[key], 'sha256': sha,
                                 'size': len(payload), 'dest': path.name})
            self.rows[key] = {'id': f'src-{key}', 'url': URLS[key], 'status': 'usable', 'sha256': sha,
                              'bytes': len(payload), 'format': 'usgs-geotiff'}
        (self.local / '_geofetch/catalog.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in self.entries))
        self.root = LocalSourceRoot(self.local)

    def cache_files(self):
        return sorted(str(p.relative_to(self.cache)) for p in self.cache.rglob('*')
                      if p.is_file()) if self.cache.exists() else []

    def lock(self, key):
        """Make one original unreadable; skip when permissions do not bind this user (root)."""
        path = self.files[key]
        path.chmod(0)
        self.addCleanup(path.chmod, stat.S_IRUSR | stat.S_IWUSR)
        if os.access(path, os.R_OK):
            self.skipTest('file mode 000 is still readable (running as root)')

    def test_unreadable_first_original_is_refused_and_the_second_still_imports(self):
        # Bug caught: a PermissionError escapes the loop, losing the report and skipping later sources.
        self.lock('a')
        report = import_manifest([self.rows['a'], self.rows['b']], self.cache, self.root)
        self.assertEqual([r['source_id'] for r in report['imported']], ['src-b'])
        self.assertEqual(report['not_catalogued'], [])
        (refused,) = report['refused']
        self.assertEqual((refused['source_id'], refused['url']), ('src-a', URLS['a']))
        # Bug caught: the refusal is swallowed without saying why (empty or generic reason).
        self.assertIn('PermissionError', refused['reason'])
        self.assertIn('Permission denied', refused['reason'])
        # Bug caught: a partial .part file or a cache entry is left for the refused source.
        self.assertEqual(self.cache_files(), [f"{self.rows['b']['sha256']}/source.json",
                                              f"{self.rows['b']['sha256']}/source.tif"])

    def test_io_error_while_hashing_is_refused_per_source_even_as_root(self):
        # Bug caught: only permission errors are handled; any other OSError (EIO) still aborts the batch.
        real = local_sources.sha256

        def flaky(path):
            if Path(path).name == 'a.tif':
                raise OSError(errno.EIO, 'Input/output error')
            return real(path)
        with mock.patch.object(local_sources, 'sha256', flaky):
            report = import_manifest([self.rows['a'], self.rows['b']], self.cache, self.root)
        self.assertEqual([r['source_id'] for r in report['imported']], ['src-b'])
        self.assertEqual([r['source_id'] for r in report['refused']], ['src-a'])
        self.assertIn('Input/output error', report['refused'][0]['reason'])
        self.assertNotIn('.part', ' '.join(self.cache_files()))

    def test_earlier_verified_cache_entry_survives_a_later_unreadable_source(self):
        # Bug caught: a refusal removes or rewrites the verified cache entry of an earlier source.
        first = import_manifest([self.rows['b']], self.cache, self.root)
        cached = Path(first['imported'][0]['cache'])
        self.lock('a')
        report = import_manifest([self.rows['b'], self.rows['a']], self.cache, self.root)
        self.assertEqual([r['source_id'] for r in report['imported']], ['src-b'])
        self.assertEqual([r['source_id'] for r in report['refused']], ['src-a'])
        self.assertEqual(hashlib.sha256(cached.read_bytes()).hexdigest(), self.rows['b']['sha256'])

    def test_interrupt_is_not_swallowed_by_the_broadened_except(self):
        # Bug caught: the handler widens to BaseException/Exception-like catch-all and eats Ctrl-C.
        with mock.patch.object(local_sources, 'import_local', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                import_manifest([self.rows['a']], self.cache, self.root)

    def test_malformed_manifest_rows_are_refused_not_fatal(self):
        # Bug caught: a row without id or url raises KeyError and aborts the batch.
        no_url = {k: v for k, v in self.rows['a'].items() if k != 'url'}
        no_id = {k: v for k, v in self.rows['a'].items() if k != 'id'}
        report = import_manifest([no_url, no_id, self.rows['b']], self.cache, self.root)
        self.assertEqual([r['source_id'] for r in report['imported']], ['src-b'])
        self.assertEqual([(r['source_id'], r['url'], 'url' in r['reason'], 'id' in r['reason'])
                          for r in report['refused']],
                         [('src-a', None, True, False), (None, URLS['a'], False, True)])
        self.assertEqual(self.cache_files(), [f"{self.rows['b']['sha256']}/source.json",
                                              f"{self.rows['b']['sha256']}/source.tif"])
        # Selecting by id never trips over a malformed row.
        self.assertEqual(len(import_manifest([no_id, self.rows['b']], self.cache, self.root,
                                             ids=['src-b'])['imported']), 1)

    def test_healthy_batch_report_is_unchanged(self):
        # Control: no refusal, so the report shape and values match the pre-change success report.
        report = import_manifest([self.rows['a'], self.rows['b']], self.cache, self.root)
        expected = [{'source_id': f'src-{k}', 'catalog_id': f'cat-{k}', 'sha256': self.rows[k]['sha256'],
                     'bytes': self.rows[k]['bytes'],
                     'cache': str(self.cache / self.rows[k]['sha256'] / 'source.tif')} for k in 'ab']
        self.assertEqual(report, {'imported': expected, 'not_catalogued': [], 'refused': []})


if __name__ == '__main__':
    unittest.main()
