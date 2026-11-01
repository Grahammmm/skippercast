"""RF0835-2: compiled region.json lists the Chart side files the build actually wrote (chart_files)."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from skippercast import validate
from skippercast.platform import build
from skippercast.platform.contracts import load_catalogs, load_region
from skippercast.platform.shoreline import publish_shoreline
from tests._support import ROOT
from tests.contract.test_schemas import HAVE_JSONSCHEMA, NEEDS_JSONSCHEMA


def compiled(ident):
    return json.loads((ROOT / 'dist/regions' / ident / 'region.json').read_text())


class ChartFilesTest(unittest.TestCase):
    def test_committed_copies_follow_their_files(self):
        self.assertEqual(compiled('morro-bay')['chart_files'], sorted(build.CHART_FILES))
        self.assertEqual(len(build.CHART_FILES), 7)
        self.assertEqual(compiled('monterey-point-sur')['chart_files'], [])  # present, not omitted
        for package in sorted(p for p in (ROOT / 'dist/regions').iterdir() if (p / 'region.json').is_file()):
            self.assertEqual(compiled(package.name)['chart_files'], build.chart_files(package), package.name)

    def test_list_follows_the_disk_after_a_stale_shoreline_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            out.mkdir()
            for name in ('shoreline.geojson', 'land-water.json'):
                (out / name).write_text('{}')
            self.assertEqual(build.chart_files(out), ['land-water.json', 'shoreline.geojson'])
            publish_shoreline(tmp, {'id': 'no-source'}, out)  # no catalog/shoreline source: the stale copy goes
            self.assertEqual(build.chart_files(out), ['land-water.json'])

    def test_a_directory_or_an_unknown_name_is_not_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'poster.svg').mkdir()
            (Path(tmp) / 'coastline.geojson').write_text('{}')
            self.assertEqual(build.chart_files(tmp), [])

    def test_source_region_with_chart_files_is_refused_before_any_write(self):
        needs = load_catalogs(ROOT)
        source = {**load_region('morro-bay', ROOT), 'chart_files': []}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'catalog').mkdir()
            (root / 'catalog/targets.json').write_text((ROOT / 'catalog/targets.json').read_text())
            (root / 'regions/morro-bay').mkdir(parents=True)
            (root / 'regions/morro-bay/region.json').write_text(json.dumps(source))
            with mock.patch.object(build, 'load_catalogs', return_value=needs), \
                    mock.patch.object(build, 'load_region', return_value=deepcopy(source)):
                with self.assertRaisesRegex(ValueError, 'chart_files is written by the build'):
                    build.build(root)
            self.assertFalse((root / 'dist').exists())

    @unittest.skipUnless(HAVE_JSONSCHEMA, NEEDS_JSONSCHEMA)
    def test_schema_accepts_the_compiled_copies_and_refuses_bad_lists(self):
        for ident in ('morro-bay', 'cambria-san-simeon'):
            self.assertTrue(validate.check('region', compiled(ident)))
        region = compiled('morro-bay')
        for bad in (['coastline.geojson'], ['poster.svg', 'poster.svg'], 'poster.svg', [1]):
            with self.subTest(bad=bad), self.assertRaises(validate.ContractError):
                validate.check('region', {**region, 'chart_files': bad})


if __name__ == '__main__':
    unittest.main()
