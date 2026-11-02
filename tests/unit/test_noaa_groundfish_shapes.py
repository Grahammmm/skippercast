import functools
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from scripts import collect_noaa_groundfish_areas as noaa

CFR = 'https://www.ecfr.gov/current/title-50/section-660.70'
POLYGON = {'type': 'Polygon', 'coordinates': [[[-123, 38], [-122.9, 38], [-122.9, 38.1], [-123, 38]]]}
LAYERS = [{'id': i, 'name': f'GEA_Example_{i}'} for i in range(9)]
LAYERS += [{'id': 18, 'name': 'GEA_Cordell_Bank_20260623'}]
LAYERS += [{'id': 20 + i, 'name': f'YRCA_Example_{i}'} for i in range(10)]
LAYERS += [{'id': 40, 'name': 'CCA_Eastern_20231201'}, {'id': 41, 'name': 'CCA_Western_20231201'}]
FIRST = 'GEA_Example_0'  # layer id 0, the one the overrides below replace


def feature(name=FIRST, oid=1, **props):
    data = {'AREA_GROUP': name.split('_')[0], 'OBJECTID': oid, 'SITE_NAME': name, 'CFR_BOUNDARY_URL': CFR}
    data.update(props)
    return {'type': 'Feature', 'geometry': POLYGON, 'properties': data}


def collection(*features):
    return {'type': 'FeatureCollection', 'features': list(features)}


def fake(service=None, count=None, geo=None, layers=LAYERS):
    """Fake NOAA getter: every layer has count 1 and one good feature unless layer 0 is overridden."""
    def fetch(url):
        if url.endswith('?f=pjson'):
            return ({'layers': layers} if service is None else service), 'service-hash'
        ident = int(urlsplit(url).path.split('/')[-2])
        name = next(row['name'] for row in layers if row['id'] == ident)
        if 'returnCountOnly' in parse_qs(urlsplit(url).query):
            return (count if ident == 0 and count is not None else {'count': 1}), 'count-hash'
        return (geo if ident == 0 and geo is not None else collection(feature(name))), 'geometry-hash'
    return fetch


class MisshapedNoaaAnswerTest(unittest.TestCase):
    def test_good_answers_complete_with_unchanged_ids_and_sources(self):
        data = noaa.collect(getter=fake())
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['feature_count'], 22)
        self.assertEqual([f['properties']['id'] for f in data['features']],
                         [f'noaa-gca-{row["id"]}-1' for row in LAYERS])
        self.assertEqual([(s['layer_id'], s['layer_name'], s['feature_count']) for s in data['source_layers']],
                         [(row['id'], row['name'], 1) for row in LAYERS])
        two = noaa.collect(getter=fake(count={'count': 2}, geo=collection(feature(oid=1), feature(oid=2))))
        self.assertEqual([f['properties']['id'] for f in two['features']][:2], ['noaa-gca-0-1', 'noaa-gca-0-2'])

    def test_service_not_an_object_is_named(self):
        for service in ([], 'x', 7, [{'layers': []}]):
            with self.subTest(service=service):
                with self.assertRaisesRegex(ValueError, r'^Invalid NOAA federal groundfish service$'):
                    noaa.collect(getter=fake(service=service))

    def test_misshaped_layer_rows_are_named(self):
        n = len(LAYERS)
        for bad in ('GEA_x', {'id': 1, 'name': 5}, {'id': 1}, ['GEA_x'],
                    {'id': '3/../9', 'name': 'GEA_Bad'}, {'id': True, 'name': 'GEA_Bad'},
                    {'id': -1, 'name': 'YRCA_Bad'}, {'id': 10001, 'name': 'CCA_Bad'}, {'name': 'GEA_Bad'}):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, rf'^NOAA federal area layer row {n} misshaped$'):
                    noaa.selected_layers(LAYERS + [bad])
                with self.assertRaisesRegex(ValueError, rf'layer row {n} misshaped'):
                    noaa.collect(getter=fake(layers=LAYERS + [bad]))
        edge = [{'id': 10000, 'name': 'GEA_Edge'}, {'id': 'skip/me', 'name': 'Unselected_layer'}]
        self.assertEqual(len(noaa.selected_layers(LAYERS + edge)), 23)

    def test_misshaped_count_or_geometry_is_named(self):
        for count in ([], 'x', {'count': 0}):
            with self.subTest(count=count):
                with self.assertRaisesRegex(ValueError, f'^Unexpected NOAA feature count for {FIRST}$'):
                    noaa.collect(getter=fake(count=count))
        for geo in ({'type': 'FeatureCollection', 'features': {}}, {'type': 'FeatureCollection'}, [], 'x',
                    {'type': 'FeatureCollection', 'features': 'a'}):
            with self.subTest(geo=geo):
                with self.assertRaisesRegex(ValueError, f'^Incomplete NOAA geometry for {FIRST}$'):
                    noaa.collect(getter=fake(geo=geo))

    def test_misshaped_feature_or_bad_objectid_is_named(self):
        no_oid = feature()
        del no_oid['properties']['OBJECTID']
        cases = [('x', 1), (dict(feature(), properties=[]), 1), (dict(feature(), properties='p'), 1),
                 (dict(feature(), properties=None), 1), (no_oid, 1), (feature(oid='1'), 1),
                 (feature(oid=True), 1), (feature(oid=-1), 1), (feature(oid=1.0), 1),
                 (dict(feature(), geometry=['x']), 1), (feature(oid=1), 2)]
        for bad, count in cases:
            with self.subTest(bad=bad, count=count):
                features = [bad] if count == 1 else [feature(oid=1), bad]
                with self.assertRaisesRegex(ValueError, f'^Invalid NOAA polygon or classification for {FIRST}$'):
                    noaa.collect(getter=fake(count={'count': count}, geo=collection(*features)))


class MainRetainsPreviousTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.output = Path(tmp.name) / 'areas.json'
        self.previous = Path(tmp.name) / 'previous.json'

    def run_main(self, argv):
        broken = functools.partial(noaa.collect, getter=fake(service=[]))
        with mock.patch.object(noaa, 'collect', broken), mock.patch('sys.argv', ['collect'] + argv):
            with mock.patch('builtins.print'):
                noaa.main()

    def test_misshaped_service_retains_usable_previous(self):
        previous = noaa.collect(getter=fake())
        self.previous.write_text(json.dumps(previous))
        with self.assertRaises(SystemExit) as caught:
            self.run_main(['--output', str(self.output), '--previous', str(self.previous)])
        self.assertEqual(str(caught.exception.code),
                         'NOAA federal area refresh retained prior geometry; review source health')
        written = json.loads(self.output.read_text())
        self.assertEqual(written['status'], 'retained')
        self.assertEqual(written['refresh_issue'], 'Invalid NOAA federal groundfish service')
        self.assertEqual(written['features'], previous['features'])

    def test_misshaped_service_without_previous_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, r'^Invalid NOAA federal groundfish service$'):
            self.run_main(['--output', str(self.output)])
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
