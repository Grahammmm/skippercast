"""SC175: complete qualify_row API, synthetic metadata only, scoped offline imports.

Producer shape: tests/contract/test_seafloor_manifest.py receipt construction;
measured adapter fields: seafloor/adapters/multibeam_grid.py; raster identity:
seafloor/normalized.py. synthetic_extension deliberately tests deeper retention,
not a claim that the current raster producer emits those additional fields.
"""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import importlib
import importlib.abc
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests._support import ROOT as REPO

FIXTURE = REPO / 'tests/fixtures/sc175-qualification-copy/ordinary.json'
REVIEW_KEYS = (
    'adapter_version', 'source_sha256', 'cog_sha256', 'requested_bounds_wgs84',
    'valid_pixels_in_requested_bounds', 'nominal_0_300ft_pixels_in_requested_bounds',
    'native_resolution_m', 'vertical_datum', 'uncertainty_type', 'interpolation_mask')
GRID_KEYS = ('native_sampling', 'grid_spacing_m', 'preparation_receipt_sha256')
IMPORTED_ORIGINS = {}
RIGHTS_URL = 'https://example.org/synthetic-policy'
ORDINARY_NOTES = (
    'Opened through original-native-adapters-v1; native-resolution COG cached by source hash. '
    'Usable original producer-gridded depth in the reviewed window; no habitat or legal clearance. '
    'Interpolation mask and acquisition independence unresolved; do not count as independent corroboration.')
GRID_NOTES = (
    'Reviewed measured-support bins derived from original irregular soundings. '
    'Grid spacing is not native acquisition resolution or calibrated accuracy. '
    'Unknown datum/accuracy/correction history retained; one acquisition lineage.')
PRIVATE_NOTES = ' Private physical processing only; rights are not granted and publication/export remain prohibited.'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def shapes():
    seed = json.loads(FIXTURE.read_text())
    for family, private in [('ordinary-public', False), ('ordinary-private', True), ('measured-private', True)]:
        for raster in (False, True):
            row, receipt = deepcopy(seed['row']), deepcopy(seed['receipt'])
            if family.startswith('measured'):
                row.update(format='measured-multibeam-grid', license='unknown')
                receipt.update(adapter_version='measured-multibeam-grid-v1',
                               native_resolution_m='unknown', grid_spacing_m=[5.0, 5.0],
                               native_sampling='irregular-original-soundings',
                               preparation_receipt_sha256='d'*64)
            elif private:
                row['license'] = 'unknown'
            if raster:
                receipt['raster_identity'] = deepcopy(seed['raster_identity'])
            yield family + ('-raster' if raster else '-absent'), row, receipt, private


def original_output(row, receipt, *, rights_url, physical_only):
    """Independent serialized original behavior oracle; not used as the API under test."""
    output = deepcopy(row)
    output.update(status='physical-only' if physical_only else 'usable', hold_reason='unknown',
                  bytes=receipt['source_bytes'], horizontal_crs=receipt['horizontal_crs'],
                  vertical_datum=receipt['vertical_datum'],
                  resolution_m=max(receipt['grid_spacing_m'] if row['format'] == 'measured-multibeam-grid'
                                   else receipt['native_resolution_m']))
    output['adapter_review'] = {key: deepcopy(receipt[key]) for key in REVIEW_KEYS}
    if row['format'] == 'measured-multibeam-grid':
        output['adapter_review'].update({key: deepcopy(receipt[key]) for key in GRID_KEYS})
    output['adapter_review']['rights_source_url'] = rights_url
    if 'raster_identity' in receipt:
        output['adapter_review']['raster_identity'] = deepcopy(receipt['raster_identity'])
    output['notes'] = GRID_NOTES if row['format'] == 'measured-multibeam-grid' else ORDINARY_NOTES
    if physical_only:
        output['notes'] += PRIVATE_NOTES
    return output


def shallow_copy_constructor(real, row, receipt, **kwargs):
    """Named reversible control: retain real gates, recreate only the original alias."""
    output = real(row, receipt, **kwargs)
    for key in output['adapter_review']:
        if key in receipt:
            output['adapter_review'][key] = receipt[key]
    for dest, source in [('bytes', 'source_bytes'), ('horizontal_crs', 'horizontal_crs'),
                         ('vertical_datum', 'vertical_datum')]:
        output[dest] = receipt[source]
    return output


def collections(value, prefix=()):
    if isinstance(value, (dict, list)):
        yield prefix
        items = value.items() if isinstance(value, dict) else enumerate(value)
        for key, item in items:
            yield from collections(item, prefix + (key,))


def at(value, path):
    for key in path:
        value = value[key]
    return value


def mutate(value):
    if isinstance(value, dict):
        value['sc175_mutation'] = ['changed']
    else:
        value.append('sc175_mutation')


class ExternalImportStop(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'anthropic', 'ollama', 'hermes_tools'}:
            raise RuntimeError('SC175 unexpected model/tool import: ' + fullname)
        return None


@contextmanager
def product_scope(root):
    """Install reversible sentinels before ANY product import; restore ambient peers.

    Static closure inspected: package initializers, paths, util.time, contracts,
    manifest and rights. No eager I/O or children; contracts.REPO binds repo_root.
    Evict/restore real product modules to qualify initialization even in a peer suite.
    No fake product modules, source slicing or process-global audit hooks.
    """
    saved = {key: value for key, value in sys.modules.items()
             if key == 'skippercast' or key.startswith('skippercast.')}
    old_path, old_meta, old_bytecode = sys.path[:], sys.meta_path[:], sys.dont_write_bytecode
    def stop(*args, **kwargs):
        raise RuntimeError('SC175 unexpected external effect')
    try:
        with ExitStack() as stack:
            for obj, name in [(socket, 'socket'), (socket, 'create_connection'),
                              (socket, 'getaddrinfo'), (subprocess, 'Popen'),
                              (os, 'system'), (os, 'fork'), (os, 'posix_spawn'), (os, 'posix_spawnp')]:
                if hasattr(obj, name):
                    stack.enter_context(patch.object(obj, name, stop))
            sys.meta_path.insert(0, ExternalImportStop())
            sys.dont_write_bytecode = True
            for key in saved:
                sys.modules.pop(key)
            paths = importlib.import_module('skippercast.paths')
            stack.enter_context(patch.object(paths, 'repo_root', return_value=root))
            module = importlib.import_module('skippercast.seafloor.manifest')
            rights = importlib.import_module('skippercast.seafloor.rights')
            contracts = importlib.import_module('skippercast.platform.contracts')
            for name, imported in list(sys.modules.items()):
                if name == 'skippercast' or name.startswith('skippercast.'):
                    origin = Path(imported.__file__).resolve()
                    if not origin.is_relative_to(REPO / 'src'):
                        raise RuntimeError('SC175 product origin outside candidate: ' + name)
                    IMPORTED_ORIGINS[name] = str(origin)
            if contracts.REPO != root or module.load_manifest.__defaults__ != (root,):
                raise RuntimeError('SC175 synthetic bound root not established')
            for name in ('read_json', 'atomic_json'):
                stack.enter_context(patch.object(contracts, name, stop))
                stack.enter_context(patch.object(module, name, stop))
            yield module, rights
    finally:
        for key in list(sys.modules):
            if key == 'skippercast' or key.startswith('skippercast.'):
                sys.modules.pop(key)
        sys.modules.update(saved)
        sys.path[:] = old_path
        sys.meta_path[:] = old_meta
        sys.dont_write_bytecode = old_bytecode


class QualificationCopyTests(unittest.TestCase):
    def setUp(self):
        self.peer = (dict(os.environ), sys.path[:], sys.meta_path[:], sys.dont_write_bytecode,
                     socket.socket, subprocess.Popen,
                     {k: v for k, v in sys.modules.items() if k == 'skippercast' or k.startswith('skippercast.')})
        # mkdtemp deliberately retains evidence; no cleanup/deletion, import-time writes or global hooks.
        self.root = Path(tempfile.mkdtemp(prefix='sc175-'))
        self.scope = product_scope(self.root)
        self.module, self.rights = self.scope.__enter__()
        self.addCleanup(self.close_scope)

    def close_scope(self):
        self.scope.__exit__(None, None, None)
        after = (dict(os.environ), sys.path[:], sys.meta_path[:], sys.dont_write_bytecode,
                 socket.socket, subprocess.Popen,
                 {k: v for k, v in sys.modules.items() if k == 'skippercast' or k.startswith('skippercast.')})
        self.assertEqual(self.peer, after, 'SC175 harmless peer state changed')

    def assert_isolated(self, constructor, row, receipt, private, field, path, direction):
        row, receipt = deepcopy(row), deepcopy(receipt)
        output = constructor(row, receipt, rights_url=RIGHTS_URL, physical_only=private)
        before = canonical(output if direction == 'receipt-to-output' else receipt)
        target = receipt[field] if direction == 'receipt-to-output' else output['adapter_review'][field]
        mutate(at(target, path))
        after = canonical(output if direction == 'receipt-to-output' else receipt)
        self.assertEqual(before, after, 'SC175_ALIAS ' + field + repr(path) + ' ' + direction)

    def test_regression(self):
        for label, row, receipt, private in shapes():
            expected = original_output(row, receipt, rights_url=RIGHTS_URL, physical_only=private)
            for field, value in expected['adapter_review'].items():
                if field not in receipt:
                    continue
                for path in collections(value):
                    for direction in ('receipt-to-output', 'output-to-receipt'):
                        with self.subTest(shape=label, field=field, path=path, direction=direction):
                            self.assert_isolated(self.module.qualify_row, row, receipt, private, field, path, direction)

    def test_compatibility(self):
        for label, row, receipt, private in shapes():
            with self.subTest(case='serialization', shape=label):
                actual = self.module.qualify_row(row, receipt, rights_url=RIGHTS_URL, physical_only=private)
                self.assertEqual(canonical(actual), canonical(original_output(row, receipt, rights_url=RIGHTS_URL, physical_only=private)))
                self.assertEqual('raster_identity' in actual['adapter_review'], 'raster_identity' in receipt)
                self.assertEqual(self.module.physical_source(actual), not private)
                self.assertTrue(self.module.physical_source(actual, physical_only=True))
            invalids = [('source_id', 'other'), ('source_sha256', 'e'*64),
                        ('adapter_version', 'wrong'), ('nominal_0_300ft_pixels_in_requested_bounds', 0),
                        ('nominal_0_300ft_pixels_in_requested_bounds', -1),
                        ('nominal_0_300ft_pixels_in_requested_bounds', 21),
                        ('valid_pixels_in_requested_bounds', 0)]
            for field, value in invalids:
                with self.subTest(case='receipt-failure', shape=label, field=field, value=value):
                    bad = deepcopy(receipt); bad[field] = value
                    before = canonical([row, bad])
                    error = ('native_receipt_counts_invalid' if field in {
                        'nominal_0_300ft_pixels_in_requested_bounds',
                        'valid_pixels_in_requested_bounds'} else 'matching native adapter receipt')
                    with self.assertRaisesRegex(ValueError, error):
                        self.module.qualify_row(row, bad, rights_url=RIGHTS_URL, physical_only=private)
                    self.assertEqual(before, canonical([row, bad]))
            for url in ('http://example.org/policy', 'https://localhost/policy', 'file:///policy'):
                with self.subTest(case='rights-url', shape=label, url=url):
                    with self.assertRaises(ValueError):
                        self.module.qualify_row(row, receipt, rights_url=url, physical_only=private)
        _, row, receipt, _ = next(shapes())
        with self.subTest(case='unknown-public-rights'):
            row['license'] = 'unknown'
            with self.assertRaisesRegex(ValueError, 'rights are unqualified'):
                self.module.qualify_row(row, receipt, rights_url=RIGHTS_URL)
        with self.subTest(case='measured-public-prohibited'):
            row['format'] = 'measured-multibeam-grid'
            with self.assertRaisesRegex(ValueError, 'private-only'):
                self.module.qualify_row(row, receipt, rights_url=RIGHTS_URL)
        _, row, receipt, _ = next(shapes())
        row.update(license=self.rights.CSUMB_LICENSE, publisher='CSUMB SFML', url=self.rights.POINT_LOBOS_ARCHIVE)
        row['rights_review'] = dict(policy_url=self.rights.CSUMB_POLICY, source_sha256=row['sha256'],
            producer='CSUMB SFML', allowed_use='noncommercial', attribution=self.rights.CSUMB_CREDIT,
            navigation_use=False, for_profit_permission='required-not-obtained', reviewed_on='2020-01-01')
        with self.subTest(case='reviewed-producer-positive'):
            self.assertEqual(self.module.qualify_row(row, receipt, rights_url=self.rights.CSUMB_POLICY)['status'], 'usable')
        with self.subTest(case='policy-url-mismatch'):
            with self.assertRaisesRegex(ValueError, 'policy URL conflicts'):
                self.module.qualify_row(row, receipt, rights_url=RIGHTS_URL)

    def test_negative_control(self):
        real = self.module.qualify_row
        def broken(row, receipt, **kwargs):
            return shallow_copy_constructor(real, row, receipt, **kwargs)
        for label, row, receipt, private in shapes():
            for direction in ('receipt-to-output', 'output-to-receipt'):
                with self.subTest(shape=label, direction=direction, case='alias-detected'):
                    with self.assertRaisesRegex(AssertionError, 'SC175_ALIAS'):
                        self.assert_isolated(broken, row, receipt, private, 'requested_bounds_wgs84', (), direction)
            # The deciding assertion is identical on the restored real constructor.
            for direction in ('receipt-to-output', 'output-to-receipt'):
                with self.subTest(shape=label, case='genuine-restored-isolation', direction=direction):
                    self.assert_isolated(real, row, receipt, private, 'requested_bounds_wgs84', (), direction)
            with self.subTest(shape=label, case='genuine-restored'):
                self.assertIs(real, self.module.qualify_row)
                self.assertEqual(canonical(real(row, receipt, rights_url=RIGHTS_URL, physical_only=private)),
                                 canonical(original_output(row, receipt, rights_url=RIGHTS_URL, physical_only=private)))

    def test_preservation(self):
        for label, row, receipt, private in shapes():
            with self.subTest(shape=label, case='construction-inputs-unchanged'):
                before = canonical([row, receipt])
                output = self.module.qualify_row(row, receipt, rights_url=RIGHTS_URL, physical_only=private)
                self.assertEqual(before, canonical([row, receipt]))
            for path in collections(row):
                with self.subTest(shape=label, case='row-output-detached', path=path):
                    row_copy, receipt_copy = deepcopy(row), deepcopy(receipt)
                    before = canonical([row_copy, receipt_copy])
                    output = self.module.qualify_row(row_copy, receipt_copy, rights_url=RIGHTS_URL, physical_only=private)
                    mutate(at(output, path))
                    self.assertEqual(before, canonical([row_copy, receipt_copy]))


if __name__ == '__main__':
    unittest.main(verbosity=2)
