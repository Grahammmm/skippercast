"""RF0620-7: a misshaped coastal-sectors catalog is named before any atlas read; nothing is written."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
from unittest import TestCase
from unittest.mock import patch

from skippercast.platform import sectors as sectors_module
from skippercast.platform.sectors import compile_sectors
from tests._support import ROOT

PACKET = 'dist/data/coastal-sectors.json'
INPUTS = ('catalog/coastal-sectors.json', 'catalog/coasts.json', 'dist/regions/index.json')


def _temp_root(temporary):
    """Copy the catalogs, built index, region configs, atlases and the compiled packet into a temp root."""
    root = Path(temporary)
    (root / 'catalog').mkdir()
    (root / 'dist/regions').mkdir(parents=True)
    (root / 'dist/data').mkdir(parents=True)
    for name in ('catalog/coasts.json', 'catalog/coastal-sectors.json', 'dist/regions/index.json', PACKET):
        shutil.copy(ROOT / name, root / name)
    for entry in json.loads((ROOT / 'dist/regions/index.json').read_text())['regions']:
        config = ROOT / 'regions' / entry['id'] / 'region.json'
        target = root / 'regions' / entry['id'] / 'region.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(config, target)
        atlas = json.loads(config.read_text())['assets']['atlas']
        output = root / 'dist' / atlas
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / 'dist' / atlas, output)
    return root


def _source():
    return json.loads((ROOT / 'catalog/coastal-sectors.json').read_text())


class CoastalSectorShapeTests(TestCase):
    def _refused(self, source, pattern, coasts=None):
        """Compile a damaged catalog in a temp root; return the atlas/region paths read before the refusal."""
        with TemporaryDirectory() as temporary:
            root = _temp_root(temporary)
            (root / 'catalog/coastal-sectors.json').write_text(json.dumps(source))
            if coasts is not None:
                (root / 'catalog/coasts.json').write_text(json.dumps(coasts))
            before = (root / PACKET).read_bytes()
            seen = []
            real = sectors_module.read_json

            def recording(path):
                seen.append(Path(path).relative_to(root).as_posix())
                return real(path)

            with patch.object(sectors_module, 'read_json', recording):
                with self.assertRaisesRegex(ValueError, pattern):
                    compile_sectors(root)
            self.assertEqual((root / PACKET).read_bytes(), before)
            self.assertEqual(sorted(root.glob('dist/data/*.tmp*')), [])
            # Only the three catalog/index inputs may be read: no regions/*/region.json, no atlas.
            return [p for p in seen if p not in INPUTS]

    def test_number_id_is_named_by_index(self):
        source = _source()
        source['sectors'][3]['id'] = 7
        self.assertEqual(self._refused(source, r'^coastal-sectors: #3: id must be text$'), [])

    def test_missing_or_non_text_coast_and_name_are_named_by_id(self):
        source = _source()
        del source['sectors'][0]['coast']
        self.assertEqual(self._refused(source, r'^coastal-sectors: del-norte: coast must be text$'), [])
        source = _source()
        source['sectors'][1]['name'] = None
        self.assertEqual(
            self._refused(source, r'^coastal-sectors: crescent-city-humboldt: name must be text$'), [])
        source = _source()
        source['sectors'][2]['coast'] = ['northern']
        self.assertEqual(self._refused(source, r'^coastal-sectors: humboldt-cape: coast must be text$'), [])

    def test_misshaped_latitude_is_named(self):
        for latitude in ([36], '36,37', [True, 37], [37, 36], [36, 36], ['36', 37], [36, 37, 38], None):
            with self.subTest(latitude=latitude):
                source = _source()
                source['sectors'][0]['latitude'] = latitude
                self.assertEqual(self._refused(source, r'^coastal-sectors: del-norte: latitude '), [])

    def test_missing_latitude_is_named(self):
        source = _source()
        del source['sectors'][4]['latitude']
        self.assertEqual(self._refused(source, r'^coastal-sectors: fort-bragg-arena: latitude '), [])

    def test_misshaped_survey_discovery_is_named(self):
        for leads in (['https://x'], [{'name': 'no url'}], [{'url': 5}], 'https://x', None):
            with self.subTest(leads=leads):
                source = _source()
                source['survey_discovery'] = leads
                self.assertEqual(self._refused(source, r'^coastal-sectors: survey_discovery '), [])

    def test_misshaped_sectors_list_is_named(self):
        for value in (None, {'id': 'x'}, ['del-norte']):
            with self.subTest(sectors=value):
                source = _source()
                source['sectors'] = value
                self.assertEqual(self._refused(source, r'^coastal-sectors: sectors must be a list'), [])

    def test_coast_package_missing_from_built_index_is_named_before_any_region_read(self):
        coasts = json.loads((ROOT / 'catalog/coasts.json').read_text())
        coasts['regions'][-1]['packages'].append('nope-pkg')
        coast_id = coasts['regions'][-1]['id']
        read = self._refused(
            _source(),
            rf'^coastal-sectors: coast {coast_id} package nope-pkg is not in dist/regions/index\.json$',
            coasts=coasts)
        self.assertEqual(read, [])

    def test_valid_temp_copy_compiles_to_the_committed_packet(self):
        with TemporaryDirectory() as temporary:
            root = _temp_root(temporary)
            (root / PACKET).unlink()
            compile_sectors(root)
            self.assertEqual((root / PACKET).read_bytes(), (ROOT / PACKET).read_bytes())
