"""--previous handling of the USGS DOI pair: unusable is ignored, max age 1..365, atomic retained copy."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from research.scripts import audit_usgs_doi_metadata as audit_mod
from research.scripts import discover_usgs_doi_releases as doi_mod

IDS = [f'P9TEST{n}' for n in range(10)]
DOIS = {f'https://doi.org/10.5066/{ident}': ident for ident in IDS}
INDEX_PAGE = ''.join(f'<a href="{doi}">California State Waters Map Series Data Catalog — Area {ident}</a>'
                     for doi, ident in DOIS.items()).encode()
LANDING = 'https://cmgds.marine.usgs.gov/data-releases/datarelease/10.5066-P9TEST0/'
XML_URL = 'https://cmgds.marine.usgs.gov/data-releases/media/2020/10.5066-P9TEST0/Bathymetry_X_metadata.xml'
XML = (b'<metadata><bounding><westbc>-122.5</westbc><eastbc>-122.4</eastbc>'
       b'<southbc>37.2</southbc><northbc>37.4</northbc></bounding></metadata>')
RELEASES = {'scope': 'usgs-state-waters-doi-product-links', 'releases': [
    {'release_id': 'P9TEST0', 'landing_url': LANDING, 'study_areas': ['X'], 'products': [
        {'kind': 'bathymetry', 'archive_url': XML_URL[:-13] + '.zip', 'metadata_url': XML_URL, 'filename': 'Bathymetry_X.zip'}]}]}
# list key -> (module, entry point that takes previous last, row key)
SCRIPTS = {'releases': (doi_mod, 'discover', 'release_id'), 'records': (audit_mod, 'audit', 'metadata_url')}


def ago(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def fresh(kind, **changes):
    row = {'release_id': 'P9TEST0', 'doi': 'https://doi.org/10.5066/P9TEST0', 'products': []} if kind == 'releases' else \
        {'release_id': 'P9TEST0', 'kind': 'bathymetry', 'filename': 'Bathymetry_X.zip', 'metadata_url': XML_URL}
    data = {'schema_version': 1, 'health': {'status': 'ok', 'issues': []}, 'last_complete_scan_at': ago(hours=1),
            'additional_sha256': None, kind: [row]}
    data.update(changes)
    return {key: value for key, value in data.items() if value is not ...}


def pages(url):
    if url == doi_mod.INDEX:
        return url, INDEX_PAGE
    if url in DOIS:
        return f'https://cmgds.marine.usgs.gov/data-releases/datarelease/10.5066-{DOIS[url]}/', b'<p>release</p>'
    return url, XML


class PreviousScanTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)
        (self.tmp / 'releases.json').write_text(json.dumps(RELEASES))

    def run_main(self, kind, previous=None, *extra, fail=False):
        mod, entry, _ = SCRIPTS[kind]
        path, out = self.tmp / f'previous-{kind}.json', self.tmp / f'out-{kind}.json'
        out.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        if previous is not None:
            path.write_bytes(previous if isinstance(previous, bytes) else json.dumps(previous, indent=2).encode())
        real, calls, fetched = getattr(mod, entry), [], []

        def fetcher(url):
            fetched.append(url)
            if fail and (url in DOIS or url == XML_URL):
                raise OSError('offline')
            return pages(url)

        def fake(*args, **kwargs):
            calls.append(args[-1])
            return real(*args, fetcher=fetcher, **kwargs)
        argv = ['script', '--output', str(out), '--previous', str(path), *extra]
        argv += ['--releases', str(self.tmp / 'releases.json')] if kind == 'records' else \
            ['--additional', str(self.tmp / 'no-additions.json')]
        err, code = io.StringIO(), 0
        with mock.patch.object(sys, 'argv', argv), mock.patch.object(mod, entry, fake), \
                redirect_stderr(err), redirect_stdout(io.StringIO()):
            try:
                mod.main()
            except SystemExit as stop:
                code = stop.code
        return code, err.getvalue(), calls, fetched, out

    def assert_rescanned(self, result, reason, passed):
        code, err, calls, fetched, out = result
        self.assertEqual(code, 0)
        self.assertEqual(err.strip(), f'previous scan ignored: {reason}' if reason else '')
        self.assertEqual(calls, [passed])
        self.assertTrue(fetched)
        self.assertIn('collected_at', json.loads(out.read_text()))

    def test_unreadable_previous_is_ignored_with_one_line(self):
        for kind in SCRIPTS:
            for raw in (b'{"health": {"status": "ok"', b'\xff\xfe{}', b'[]', b'"x"'):
                with self.subTest(kind=kind, raw=raw):
                    self.assert_rescanned(self.run_main(kind, raw), 'unreadable', None)
            with self.subTest(kind=kind, raw='absent'):
                self.assert_rescanned(self.run_main(kind), None, None)

    def test_bad_scan_time_is_named_and_rescanned(self):
        cases = [('2026-10-01T00:00:00', 'scan time has no UTC offset'), ('soon', 'bad scan time'), (5, 'bad scan time'),
                 (..., 'no scan time'), (None, 'no scan time'), (ago(days=-1), 'scan time is in the future')]
        for kind in SCRIPTS:
            for when, reason in cases:
                with self.subTest(kind=kind, when=when):
                    previous = fresh(kind, last_complete_scan_at=when)
                    self.assert_rescanned(self.run_main(kind, previous), reason, None)
                with self.subTest(kind=kind, when=when, fetch='failed'):
                    result = self.run_main(kind, previous, fail=True)
                    self.assert_rescanned(result, reason, None)
                    written = json.loads(result[4].read_text())
                    self.assertIsNone(written['last_complete_scan_at'])
                    self.assertNotIn(previous[kind][0], written[kind])

    def test_stale_degraded_or_misshaped_health_rescans_quietly(self):
        for kind in SCRIPTS:
            for previous in (fresh(kind, last_complete_scan_at=ago(days=2)), fresh(kind, health={'status': 'degraded'}),
                             fresh(kind, health='ok')):
                with self.subTest(kind=kind, previous=previous):
                    self.assert_rescanned(self.run_main(kind, previous, '--max-age-days', '1'), None, previous)

    def test_unusable_list_is_ignored_and_never_retained(self):
        for kind, (_, _, key) in SCRIPTS.items():
            for rows in (1, {}, [{key: 5}], [1], ...):
                with self.subTest(kind=kind, rows=rows):
                    result = self.run_main(kind, fresh(kind, **{kind: rows}), fail=True)
                    self.assert_rescanned(result, f'{kind} not a usable list', None)
                    self.assertEqual({row['status'] for row in json.loads(result[4].read_text())[kind]}, {'failed'})

    def test_max_age_days_bounded(self):
        for kind in SCRIPTS:
            for value in ('0', '-1', '366', 'x', '1.5', ''):
                with self.subTest(kind=kind, value=value):
                    code, err, calls, fetched, out = self.run_main(kind, fresh(kind), '--max-age-days', value)
                    self.assertEqual(code, 2)
                    self.assertIn('--max-age-days', err)
                    self.assertEqual((calls, fetched, out.exists()), ([], [], False))
            for value in ('1', '365', ' 30 '):
                with self.subTest(kind=kind, value=value):
                    code, _, calls, _, out = self.run_main(kind, fresh(kind), '--max-age-days', value)
                    self.assertEqual((code, calls, out.exists()), (0, [], True))

    def test_fresh_complete_previous_retained_byte_identical(self):
        for kind in SCRIPTS:
            with self.subTest(kind=kind):
                previous = fresh(kind)
                code, err, calls, fetched, out = self.run_main(kind, previous)
                self.assertEqual((code, err, calls, fetched), (0, '', [], []))
                self.assertEqual(out.read_bytes(), json.dumps(previous, indent=2).encode())
                self.assertEqual(sorted(path.name for path in self.tmp.glob('*.tmp')), [])

    def test_doi_additions_hash_mismatch_rescans_without_reason(self):
        previous = fresh('releases', additional_sha256='other-additions')
        self.assert_rescanned(self.run_main('releases', previous), None, previous)
        previous = fresh('releases', additional_sha256='other-additions', last_complete_scan_at='soon')
        self.assert_rescanned(self.run_main('releases', previous), None, previous)


if __name__ == '__main__':
    unittest.main()
