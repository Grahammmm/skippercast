"""The Python test layout stays what docs/engineering/testing.md describes.

Layers are directories (tests/unit, tests/contract, tests/integration, tests/gis and
research/tests with its gis/ subfolder); pytest markers come from the directory, so
a test that lands in the wrong place silently changes which CI job runs it.
"""
import ast
import re
import unittest

from tests._support import GIS_PACKAGES, ROOT

LAYERS = {'tests/unit', 'tests/contract', 'tests/integration', 'tests/gis',
          'research/tests', 'research/tests/gis'}


def layer_modules():
    return sorted([*(ROOT / 'tests').rglob('test_*.py'), *(ROOT / 'research/tests').rglob('test_*.py')])


def top_level_imports(path):
    for node in ast.parse(path.read_text(encoding='utf-8'), str(path)).body:
        if isinstance(node, ast.Import):
            yield from (alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module.split('.')[0]


class LayoutTest(unittest.TestCase):
    def test_every_module_is_in_a_layer(self):
        misplaced = [p.relative_to(ROOT).as_posix() for p in layer_modules()
                     if p.parent.relative_to(ROOT).as_posix() not in LAYERS]
        self.assertEqual(misplaced, [])

    def test_every_layer_is_a_package(self):
        # Packages give each module a unique dotted name (tests.unit.test_x) under pytest
        # and `python -m unittest`, which the research workflows still use.
        for layer in ('tests', *sorted(LAYERS)):
            with self.subTest(layer):
                self.assertTrue((ROOT / layer / '__init__.py').is_file())

    def test_no_path_hacks_or_file_relative_roots(self):
        pattern = re.compile(r'sys\.path\.(insert|append)|Path\(__file__\)\.(resolve|parent)')
        offenders = [p.relative_to(ROOT).as_posix() for p in layer_modules()
                     if pattern.search(p.read_text(encoding='utf-8'))]
        self.assertEqual(offenders, [], 'import ROOT/FIXTURES from tests._support or research.lib.paths')

    def test_gis_imports_only_in_gis_directories(self):
        offenders = [f'{p.relative_to(ROOT).as_posix()}: {name}' for p in layer_modules() if p.parent.name != 'gis'
                     for name in top_level_imports(p) if name in GIS_PACKAGES]
        self.assertEqual(offenders, [], 'a module that imports the survey stack belongs in a gis/ directory')

    def test_product_tests_never_read_the_real_clock(self):
        # Use tests._support.NOW / FakeClock and the code's now=/clock= parameters instead.
        # test_util_helpers keeps byte-for-byte reference copies of the helpers it replaced.
        pattern = re.compile(r'datetime\.(now|utcnow)\(|date\.today\(|time\.time\(\)')
        offenders = [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / 'tests').rglob('test_*.py'))
                     if p.name != 'test_util_helpers.py' and pattern.search(p.read_text(encoding='utf-8'))]
        self.assertEqual(offenders, [])

    def test_gis_package_list_matches_the_survey_requirements(self):
        # Distribution name -> import name where they differ.
        imports = {'pylerc': 'lerc', 'pyshp': 'shapefile', 'laspy[lazrs]': 'laspy'}
        pins = [line.split('==')[0] for line in (ROOT / 'requirements-survey.txt').read_text().splitlines()
                if line and not line.startswith('#')]
        self.assertEqual(sorted(imports.get(pin, pin) for pin in pins), sorted(GIS_PACKAGES))


if __name__ == '__main__':
    unittest.main()
