"""basemap regions.py refuses bad --seconds and --build before any fetch, and names an unreadable plan/manifest (RF2310-3)."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from unittest.mock import patch

from scripts.basemap import regions
from tests.unit.test_basemap_regions import LISTING

NO_FETCH = AssertionError('listing() must not be called')


def run(argv):
    """main(argv) with stdout/stderr captured; returns (exit code or returned, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            regions.main(argv)
        except SystemExit as stop:
            return stop.code, out.getvalue(), err.getvalue()
    return 'returned', out.getvalue(), err.getvalue()


class InputTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.plan = self.dir / 'plan.json'
        self.manifest = self.dir / 'manifest.json'

    def write_plan(self):
        self.plan.write_text(json.dumps(regions.plan('20261008', LISTING)))
        (self.dir / 'ca-coast-20261008.pmtiles').write_bytes(b'PMTiles\x03' + bytes(4096))

    def test_seconds_outside_0_to_86400_or_not_finite_is_a_usage_error_before_any_read(self):
        for bad in ('nan', 'inf', '-inf', '-1', '86401', 'abc', ''):
            with self.subTest(seconds=bad), patch.object(regions, 'listing', side_effect=NO_FETCH), \
                    patch.object(Path, 'read_text', side_effect=AssertionError('no file read')):
                stop, _, err = run(['manifest', '--dir', str(self.dir), f'--seconds={bad}'])
                self.assertEqual(stop, 2)
                self.assertIn('must be a number of seconds from 0 to 86400', err)
        self.assertFalse(self.manifest.exists())

    def test_seconds_boundaries_are_accepted(self):
        self.write_plan()
        for seconds, expected in (('0', 0), ('86400', 86400), ('36.9', 36)):
            with self.subTest(seconds=seconds), patch.object(regions, 'listing', side_effect=NO_FETCH):
                stop, out, _ = run(['manifest', '--dir', str(self.dir), '--seconds', seconds])
                self.assertEqual(stop, 'returned')
                self.assertIn(f'in {expected} s', out)
                self.assertEqual(json.loads(self.manifest.read_text())['build_seconds'], expected)

    def test_plan_needs_a_dated_build_before_any_fetch(self):
        for build in ([], ['--build', '2026-11-01'], ['--build', '2026110'], ['--build', '202611011'],
                      ['--build', '']):
            with self.subTest(build=build), patch.object(regions, 'listing', side_effect=NO_FETCH) as fetch:
                stop, _, err = run(['plan', '--dir', str(self.dir), *build])
                self.assertEqual(stop, 2)
                self.assertIn('plan needs --build YYYYMMDD', err)
                fetch.assert_not_called()
        self.assertFalse(self.plan.exists())
        with patch.object(regions, 'listing', return_value=LISTING) as fetch:
            stop, _, _ = run(['plan', '--dir', str(self.dir), '--build', '20261008'])
        self.assertEqual(stop, 'returned')
        fetch.assert_called_once_with()
        self.assertEqual(json.loads(self.plan.read_text())['build'], '20261008')

    def write_region(self, directory, **descriptor):
        path = self.dir / 'regions' / directory / 'region.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(descriptor))
        return path

    def test_plan_preserves_matching_active_and_preview_order_and_excludes_draft(self):
        # Create the preview first; plan order follows directory names, not creation order.
        self.write_region('fixture-b', id='fixture-b', status='preview', bounds=[2, 3, 4, 5])
        self.write_region('fixture-a', id='fixture-a', status='active', bounds=[0, 1, 2, 3])
        self.write_region('fixture-draft', id='fixture-a', status='draft')

        planned = regions.plan('20261008', LISTING, root=self.dir)

        self.assertEqual(planned['regions'], [
            {'id': 'fixture-a', 'status': 'active', 'bbox': [0, 1, 2, 3]},
            {'id': 'fixture-b', 'status': 'preview', 'bbox': [2, 3, 4, 5]},
        ])
        detail = regions.detail_region(planned['regions'])
        self.assertEqual(detail['properties']['regions'], ['fixture-a', 'fixture-b'])
        self.assertEqual([polygon[0][0] for polygon in detail['geometry']['coordinates']], [[0, 1], [2, 3]])

    def test_plan_refuses_ambiguous_ids_before_using_their_bounds(self):
        self.write_region('fixture-a', id='fixture-a', status='active', bounds=[0, 1, 2, 3])
        # A partial copy may keep A's id but contain B's valid bounds; it must not add a second A.
        for fields, reason in (
            ({'id': 'fixture-a', 'bounds': [2, 3, 4, 5]}, "Duplicate region id 'fixture-a'"),
            ({'id': 'other', 'bounds': []}, "does not match directory 'fixture-b'"),
            ({'id': ''}, 'nonempty string id'),
            ({}, 'nonempty string id'),
            ({'id': 42}, 'nonempty string id'),
        ):
            with self.subTest(descriptor=fields):
                path = self.write_region('fixture-b', status='preview', **fields)
                with self.assertRaises(ValueError) as rejected:
                    regions.plan('20261008', LISTING, root=self.dir)
                self.assertIn(str(path), str(rejected.exception))
                self.assertIn(reason, str(rejected.exception))

    def test_unreadable_plan_is_named(self):
        for content in (None, '{"build": "2026', '[]', '"plan"', b'\xff\xfe'):
            with self.subTest(content=content):
                if content is None:
                    self.assertFalse(self.plan.exists())
                elif isinstance(content, bytes):
                    self.plan.write_bytes(content)
                else:
                    self.plan.write_text(content)
                for command in ('manifest', 'publish'):
                    stop, _, _ = run([command, '--dir', str(self.dir)])
                    self.assertEqual(stop, 'plan.json unreadable; run plan first')
        self.assertFalse(self.manifest.exists())

    def test_publish_names_an_unreadable_manifest_before_r2(self):
        self.write_plan()
        r2 = mock.MagicMock()
        env = {'CLOUDFLARE_API_TOKEN': 'test-token', 'CLOUDFLARE_ACCOUNT_ID': 'test-account'}
        for content in (None, '{"key": ', '[]'):
            for environ in (env, {}):
                with self.subTest(content=content, env=bool(environ)), \
                        patch.dict(os.environ, environ, clear=True), patch.dict(sys.modules, {'publish_r2': r2}), \
                        patch.object(regions, 'publish', side_effect=AssertionError('no publish')):
                    if content is not None:
                        self.manifest.write_text(content)
                    stop, _, _ = run(['publish', '--dir', str(self.dir)])
                    self.assertEqual(stop, 'manifest.json unreadable; run manifest first')
        r2.client.assert_not_called()


if __name__ == '__main__':
    unittest.main()
