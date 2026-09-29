"""The package declares what src/ imports, and requirements files match its extras."""
import ast
import os
from pathlib import Path
import re
import sys
import tomllib
import unittest
from unittest.mock import patch

from skippercast import paths
from skippercast.platform.contracts import REPO
from tests._support import ROOT


PROJECT = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
EXTRAS = PROJECT['optional-dependencies']
# requirements-<name>.txt is kept (workflows install from it) and must equal extra <name>.
MIRRORED = ('ocean', 'sst', 'survey', 'publish', 'test', 'seafloor')

# Top-level import name -> the distribution that provides it.
DISTRIBUTION = {
    'affine': 'affine', 'boto3': 'boto3', 'botocore': 'boto3', 'eccodes': 'eccodes', 'gribapi': 'eccodes',
    'h5py': 'h5py', 'jsonschema': 'jsonschema', 'referencing': 'jsonschema',  # installed with jsonschema 'laspy': 'laspy', 'lazrs': 'lazrs', 'lerc': 'pylerc',
    'netCDF4': 'netCDF4', 'numpy': 'numpy', 'pypdf': 'pypdf', 'pyproj': 'pyproj', 'rasterio': 'rasterio',
    'scipy': 'scipy', 'shapefile': 'pyshp', 'shapely': 'shapely', 'truststore': 'truststore',
}
# Not distributions: the package itself, and the repository's scripts/ directory, which two
# seafloor modules still import from a source checkout (engineering audit finding A9).
FIRST_PARTY = {'skippercast', 'scripts'}


def name(requirement):
    return re.match(r'[A-Za-z0-9_.-]+', requirement).group(0).lower()


def expand_extra(extra, seen=()):
    """Pinned requirements of one extra, following skippercast[...] self-references."""
    pins = set()
    for requirement in EXTRAS[extra]:
        if name(requirement) == PROJECT['name']:
            inner = re.search(r'\[(.*)\]', requirement).group(1).split(',')
            for other in inner:
                assert other.strip() not in seen, 'cyclic extra'
                pins |= expand_extra(other.strip(), (*seen, extra))
        else:
            pins.add(requirement.replace(' ', ''))
    return pins


def requirements_file(path):
    """Pinned requirements of a requirements file, following -r includes."""
    pins = set()
    for line in path.read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        if line.startswith('-r '):
            pins |= requirements_file(path.parent / line[3:].strip())
        else:
            pins.add(line.replace(' ', ''))
    return pins


def third_party_imports():
    """{top-level module: [files]} for absolute imports in src/ that are not stdlib."""
    found = {}
    for path in sorted((ROOT / 'src').rglob('*.py')):
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            else:
                continue
            for module in modules:
                top = module.split('.')[0]
                if top not in sys.stdlib_module_names and top not in FIRST_PARTY:
                    found.setdefault(top, []).append(path.relative_to(ROOT).as_posix())
    return found


class ExtrasTests(unittest.TestCase):
    def test_every_requirements_file_matches_its_extra(self):
        files = {p.name for p in ROOT.glob('requirements-*.txt')}
        self.assertEqual(files, {f'requirements-{extra}.txt' for extra in MIRRORED})
        for extra in MIRRORED:
            with self.subTest(extra=extra):
                self.assertEqual(requirements_file(ROOT / f'requirements-{extra}.txt'), expand_extra(extra))

    def test_every_pin_is_exact(self):
        for extra in EXTRAS:
            for pin in expand_extra(extra):
                self.assertRegex(pin, r'^[A-Za-z0-9_.-]+(\[[a-z,]+\])?==[0-9][0-9A-Za-z.]*$', f'{extra}: {pin}')

    def test_dev_installs_every_runtime_extra(self):
        dev = expand_extra('dev')
        for extra in ('ocean', 'sst', 'survey', 'publish', 'test', 'seafloor'):
            self.assertLessEqual(expand_extra(extra), dev, extra)

    def test_core_package_has_no_required_dependencies(self):
        self.assertEqual(PROJECT['dependencies'], [])

    def test_every_third_party_import_in_src_is_declared(self):
        declared = {name(pin) for extra in EXTRAS for pin in expand_extra(extra)}
        imports = third_party_imports()
        self.assertIn('numpy', imports)  # the scan works
        for module, files in sorted(imports.items()):
            with self.subTest(module=module):
                self.assertIn(module, DISTRIBUTION, f'{module} (imported by {files[0]}) has no distribution mapping')
                self.assertIn(DISTRIBUTION[module].lower(), declared,
                              f'{module} (imported by {files[0]}) is not declared in any extra')


class RepoRootTests(unittest.TestCase):
    def test_default_is_this_checkout(self):
        with patch.dict(os.environ, {'SKIPPERCAST_ROOT': ''}):
            self.assertEqual(paths.repo_root(), ROOT)
        self.assertTrue((paths.repo_root() / 'regions').is_dir())

    def test_environment_override(self):
        with patch.dict(os.environ, {'SKIPPERCAST_ROOT': '/srv/skippercast/../skippercast'}):
            self.assertEqual(paths.repo_root(), Path('/srv/skippercast').resolve())

    def test_module_roots_use_it(self):
        from skippercast.forecast import local
        from skippercast.pipeline import regulations
        if not os.environ.get('SKIPPERCAST_ROOT'):
            self.assertEqual(REPO, ROOT)
        self.assertEqual(local.REPO, REPO)
        self.assertEqual(regulations.REGISTRY, REPO / 'dist/data/regulations.json')
        for module in ('platform/contracts.py', 'forecast/local.py', 'pipeline/regulations.py'):
            self.assertNotIn('parents[3]', (ROOT / 'src/skippercast' / module).read_text(), module)


if __name__ == '__main__':
    unittest.main()
