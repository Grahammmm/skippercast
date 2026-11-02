import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import collect_noaa_groundfish_areas as noaa

SCOPE = 'noaa-west-coast-groundfish-conservation-areas'
FEATURE = {'type': 'Feature', 'geometry': None, 'properties': {}}


def snapshot(**changes):
    data = {'type': 'FeatureCollection', 'schema_version': 1, 'scope': SCOPE, 'status': 'ok',
            'source_layers': [{'layer_id': 1}], 'feature_count': 2, 'features': [FEATURE, FEATURE]}
    data.update(changes)
    return data


class PreviousSnapshotTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.output = self.dir / 'out' / 'areas.json'
        self.previous = self.dir / 'previous.json'

    def run_main(self, previous=True, error=None):
        error = error or TimeoutError('provider said secret-ish text')
        argv = ['collect', '--output', str(self.output)]
        if previous:
            argv += ['--previous', str(self.previous)]
        with mock.patch.object(noaa, 'collect', side_effect=error), mock.patch('sys.argv', argv):
            with mock.patch('builtins.print'):
                noaa.main()

    def assert_unusable(self, reason, raw):
        self.previous.write_bytes(raw)
        with self.assertRaises(SystemExit) as caught:
            self.run_main()
        message = str(caught.exception.code)
        self.assertEqual(message, f'NOAA refresh failed (TimeoutError) and previous snapshot unusable: {reason}')
        self.assertNotIn('secret-ish', message)
        self.assertIsInstance(caught.exception.__cause__, TimeoutError)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_suffix('.json.tmp').exists())

    def test_unreadable_or_non_object_previous_is_named(self):
        raw = json.dumps(snapshot()).encode()
        for reason, data in (('unreadable JSON', raw[:40]), ('unreadable JSON', b'\xff\xfe{}'),
                             ('unreadable JSON', b''), ('not an object', b'[]'), ('not an object', b'"x"')):
            with self.subTest(data=data):
                self.assert_unusable(reason, data)

    def test_incomplete_previous_fields_are_named(self):
        no_features = snapshot()
        del no_features['features']
        cases = (('wrong scope', snapshot(scope='other')),
                 ('not a FeatureCollection', snapshot(type='Feature')),
                 ('features is not a list', no_features),
                 ('features is not a list', snapshot(features={'a': FEATURE})),
                 ('feature_count does not match features', snapshot(feature_count=3)),
                 ('feature_count is not an int', snapshot(feature_count='2')),
                 ('feature_count is not an int', snapshot(feature_count=True, features=[FEATURE])),
                 ('feature_count is not an int', snapshot(feature_count=2.0)),
                 ('source_layers is not a list', snapshot(source_layers={'layer_id': 1})),
                 ('source_layers is not a list', snapshot(source_layers=None)))
        for reason, data in cases:
            with self.subTest(reason=reason, data=data):
                self.assert_unusable(reason, json.dumps(data).encode())

    def test_existing_output_is_byte_identical_after_unusable_previous(self):
        self.output.parent.mkdir()
        self.output.write_bytes(b'{"keep": "me"}\n')
        self.previous.write_text(json.dumps(snapshot(feature_count=3)))
        with self.assertRaises(SystemExit):
            self.run_main()
        self.assertEqual(self.output.read_bytes(), b'{"keep": "me"}\n')

    def test_usable_previous_is_retained_with_unchanged_message(self):
        self.previous.write_text(json.dumps(snapshot()))
        with self.assertRaises(SystemExit) as caught:
            self.run_main(error=ValueError('NOAA down'))
        self.assertEqual(str(caught.exception.code),
                         'NOAA federal area refresh retained prior geometry; review source health')
        written = json.loads(self.output.read_text())
        self.assertEqual(written['status'], 'retained')
        self.assertEqual(written['refresh_issue'], 'NOAA down')
        self.assertIn('refresh_attempted_at', written)
        self.assertEqual(written['features'], [FEATURE, FEATURE])

    def test_no_previous_reraises_original_error(self):
        for previous in (False, True):  # absent flag, or flag naming a missing file
            with self.subTest(previous=previous), self.assertRaises(TimeoutError):
                self.run_main(previous=previous)
            self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
