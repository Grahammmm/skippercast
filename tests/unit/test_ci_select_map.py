"""ci_select map loading: malformed pattern collections must fail, never narrow CI."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import ci_select

REAL = json.loads(ci_select.MAP.read_text())


class MapTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def write_map(self, *rules):
        path = self.tmp / 'map.json'
        path.write_text(json.dumps(dict(REAL, rules=list(rules) + REAL['rules'])))
        patcher = mock.patch.object(ci_select, 'MAP', path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def rule(self, patterns, areas=('core', 'web')):
        return {'patterns': patterns, 'areas': list(areas)}


class PatternCollectionTest(MapTestCase):
    def test_scalar_pattern_cannot_authorize_survey_skip(self):
        self.assertEqual(ci_select.select(['q']), dict.fromkeys(ci_select.AREAS, True))
        self.write_map(self.rule('?'))
        with self.assertRaises(ValueError):
            ci_select.load_map()

    def test_pattern_collection_requires_nonempty_array(self):
        for bad in ('web/*', '?', {'?': 'unused'}, [], '', None, False, 7):
            with self.subTest(bad=bad):
                self.write_map(self.rule(bad))
                with self.assertRaises(ValueError):
                    ci_select.load_map()

    def test_every_pattern_member_is_nonempty_string(self):
        for bad in ([None], [False], [1], [{}], [[]], [''], ['web/*', None]):
            with self.subTest(bad=bad):
                self.write_map(self.rule(bad))
                with self.assertRaises(ValueError):
                    ci_select.load_map()

    def test_valid_pattern_lists_preserve_matching(self):
        self.write_map(
            self.rule(['?'], ['web']),
            self.rule(['q'], ['core']),
            self.rule(['a/*', 'b/[xy].txt', 'my file *'], ['core']),
        )
        ci_select.load_map()
        rules = ci_select.load_map()['rules']
        self.assertEqual(ci_select.select(['q'], rules), {'core': False, 'survey': False, 'web': True})
        self.assertEqual(ci_select.select(['b/x.txt'], rules)['core'], True)
        self.assertEqual(ci_select.select(['b/x.txt'], rules)['survey'], False)
        self.assertEqual(ci_select.select(['my file 1'], rules)['survey'], False)
        self.assertEqual(ci_select.select([], rules), dict.fromkeys(ci_select.AREAS, True))
        self.assertEqual(ci_select.select(['qq/unknown/zz'], rules), dict.fromkeys(ci_select.AREAS, True))


class EntrypointTest(MapTestCase):
    def test_invalid_map_entrypoints_emit_no_classification(self):
        self.write_map(self.rule('?'))
        out_file, summary = self.tmp / 'out', self.tmp / 'summary'
        env = {'GITHUB_OUTPUT': str(out_file), 'GITHUB_STEP_SUMMARY': str(summary)}
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(ci_select, 'changed_paths', return_value=['q']), \
                mock.patch('sys.argv', ['ci_select.py', '--event', 'pull_request']), \
                contextlib.redirect_stdout(stdout), self.assertRaises(ValueError):
            ci_select.main()
        self.assertNotIn('survey=', stdout.getvalue())
        self.assertFalse(out_file.exists())
        self.assertFalse(summary.exists())
        stdout = io.StringIO()
        with mock.patch('sys.argv', ['ci_select.py', '--fixtures']), \
                contextlib.redirect_stdout(stdout), self.assertRaises(ValueError):
            ci_select.main()
        self.assertNotIn('passed', stdout.getvalue())

    def test_checked_in_map_and_gate_are_unchanged(self):
        ci_select.load_map()
        ci_select.fixtures()


if __name__ == '__main__':
    unittest.main()
