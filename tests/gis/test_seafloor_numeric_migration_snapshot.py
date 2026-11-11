"""Numeric migration must bind staged copies to the admitted original run receipt."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.transform import from_origin

import skippercast.seafloor.migrate_cache as migrate_module
from skippercast.platform.contracts import atomic_json, read_json
from skippercast.seafloor.adopt import digest, OUTPUTS, PHYSICAL
from skippercast.seafloor.fetch import fetch_source
from skippercast.seafloor.ingest import ingest
from skippercast.seafloor.io import sha256
from skippercast.seafloor.manifest import qualify_row
from skippercast.seafloor.migrate_cache import migrate_numeric_cache
from skippercast.seafloor.run import run
from tests._support import ROOT

REAL_COPYFILE = shutil.copyfile
REAL_VERIFY = migrate_module.verify_sources
REAL_INGEST = migrate_module.ingest
REACH = 'fixture-r01'


def build_legacy_cache(root):
    """Synthetic reach whose cache carries a legacy (numeric-only) physical identity."""
    for folder in ('catalog', 'dist/data', 'var/seafloor/reference'):
        (root/folder).mkdir(parents=True)
    (root/'requirements-survey.txt').write_text('fixture')
    (root/'catalog/survey.schema.json').write_bytes((ROOT/'catalog/survey.schema.json').read_bytes())
    atomic_json(root/'dist/data/atlas.json', {'areas': [], 'targets': []})
    template = deepcopy(next(r for r in read_json(ROOT/'catalog/surveys.json')['surveys']
        if r['status'] == 'usable' and r['format'] == 'usgs-geotiff'
        and r['license'] == 'public-domain-us-gov'))
    template.pop('adapter_review')
    template.pop('resolution_profile', None)
    rows = []
    for ident, kind, value in (('depth', 'bathymetry', -50), ('classes', 'substrate', 3)):
        path = root/f'{ident}.tif'
        with rasterio.open(path, 'w', driver='GTiff', width=160, height=160, count=1,
                dtype='float32', crs=3310, transform=from_origin(-30, 280, 2, 2), nodata=np.nan) as out:
            out.write(np.full((160, 160), value, 'float32'), 1)
        row = dict(template, id=ident, kind=kind, url=f'https://pubs.usgs.gov/{ident}.tif',
            archive_member='unknown', sha256=sha256(path), bytes=path.stat().st_size,
            derived_from=[], status='candidate', resolution_m=2)
        if kind == 'bathymetry':
            t = Transformer.from_crs(3310, 4326, always_xy=True)
            bounds = [*t.transform(-50, -50), *t.transform(300, 300)]
            receipt, _, _ = ingest(row, bounds, root=root, local=path)
            row = qualify_row(row, receipt, rights_url='https://pubs.usgs.gov/fixture')
        else:
            fetch_source(row, root/'var/seafloor/cache', local=path)
        rows.append(row)
    atomic_json(root/'catalog/surveys.json', {'surveys': rows})
    rules = read_json(ROOT/'catalog/habitat-rules.json')
    binding = deepcopy(rules['substrate_bindings'][0])
    binding.update(source_id='classes', source_sha256=rows[1]['sha256'], depth_source_ids=['depth'])
    rules['substrate_bindings'] = [binding]
    atomic_json(root/'catalog/habitat-rules.json', rules)
    atomic_json(root/'catalog/reaches.json', {'input_hash': 'grid', 'reaches': [{'id': REACH}]})
    atomic_json(root/'var/seafloor/reference/cells.json', {'input_hash': 'grid', 'cells': [{
        'id': '3310:0:0', 'reach': REACH, 'tier': 0, 'band_area_m2': 50000, 'reference_unknown_area_m2': 0}]})
    atomic_json(root/'var/seafloor/reference/run.json', {'input_hash': 'grid', 'output_hashes': {
        'cells.json': sha256(root/'var/seafloor/reference/cells.json')}})
    atomic_json(root/'dist/data/seafloor-ledger.json', {'reaches': [
        {'id': REACH, 'band_km2': .05}], 'totals': {'band_km2': .05}})
    first, _ = run(REACH, root=root)
    folder = root/'var/seafloor/reaches'/REACH
    legacy = deepcopy(first)
    legacy['inputs']['substrate_bindings']['depth']['row']['resolution_m'] = 2
    physical_inputs = deepcopy(legacy['inputs'])
    physical_inputs.pop('screen'); physical_inputs.pop('screen_implementation_sha256')
    legacy_hash = digest(physical_inputs)
    for name in ('cells.json', 'terrain.json'):
        data = read_json(folder/name); data['input_hash'] = legacy_hash
        atomic_json(folder/name, data)
    atomic_json(folder/'physical.json', {'input_hash': legacy_hash,
        'outputs': {name: sha256(folder/name) for name in PHYSICAL}})
    legacy.update(input_hash=digest(legacy['inputs']), physical_input_hash=legacy_hash,
        outputs={name: sha256(folder/name) for name in OUTPUTS})
    atomic_json(folder/'run.json', legacy)
    return folder, legacy


def snapshot(directory):
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir()) if p.is_file()}


class StagedBytesMatchAdmittedReceiptTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.folder, self.legacy = build_legacy_cache(self.root)
        self.sentinel = self.folder.parent/'sibling-sentinel.txt'
        self.sentinel.write_text('keep')
        self.ledger = (self.root/'dist/data/seafloor-ledger.json').read_bytes()
        self.hook_snapshot = None

    def migrate(self):
        return migrate_numeric_cache(REACH, root=self.root, apply=True)

    def assert_refused_untouched(self, name, *, rewrites):
        with self.assertRaisesRegex(ValueError, f'Staged output checksum mismatch.*{name}'):
            self.migrate()
        rewrites.assert_not_called()
        self.assertEqual(self.hook_snapshot, snapshot(self.folder))
        self.assertFalse((self.root/'var/seafloor/numeric-migrations').exists())
        self.assertEqual([self.folder.name], sorted(p.name for p in self.folder.parent.iterdir()
                                                    if p != self.sentinel))
        self.assertEqual('keep', self.sentinel.read_text())
        self.assertEqual(self.ledger, (self.root/'dist/data/seafloor-ledger.json').read_bytes())

    def test_candidate_changed_after_initial_admission_is_not_blessed(self):
        def ingest_then_change(*args, **kwargs):
            result = REAL_INGEST(*args, **kwargs)
            path = self.folder/'candidates.geojson'
            data = read_json(path)
            data['features'].append({'type': 'Feature', 'properties': {'unverified': True}, 'geometry': None})
            path.write_text(json.dumps(data))
            self.hook_snapshot = snapshot(self.folder)
            return result
        with patch.object(migrate_module, 'ingest', side_effect=ingest_then_change), \
                patch.object(migrate_module, 'atomic_json') as rewrites:
            self.assert_refused_untouched('candidates.geojson', rewrites=rewrites)

    def test_each_output_bound_before_rewrite(self):
        for name in OUTPUTS:
            with self.subTest(output=name):
                def verify_then_change(*args, **kwargs):
                    REAL_VERIFY(*args, **kwargs)
                    with (self.folder/name).open('ab') as out:
                        out.write(b'\n ')  # still parses; cells/terrain keep their valid input_hash
                    self.hook_snapshot = snapshot(self.folder)
                before = snapshot(self.folder)
                with patch.object(migrate_module, 'verify_sources', side_effect=verify_then_change), \
                        patch.object(migrate_module, 'atomic_json') as rewrites:
                    self.assert_refused_untouched(name, rewrites=rewrites)
                for original, data in before.items():  # restore the hook's edit for the next output
                    (self.folder/original).write_bytes(data)

    def test_copy_corruption_is_detected_from_destination(self):
        for name in ('cells.json', 'held.geojson'):
            with self.subTest(output=name):
                self.hook_snapshot = snapshot(self.folder)
                def copy_then_corrupt(src, dst, **kwargs):
                    result = REAL_COPYFILE(src, dst, **kwargs)
                    if Path(dst).name == name:
                        Path(dst).write_bytes(Path(dst).read_bytes() + b'\n ')
                    return result
                with patch.object(migrate_module.shutil, 'copyfile', side_effect=copy_then_corrupt), \
                        patch.object(migrate_module, 'atomic_json') as rewrites:
                    self.assert_refused_untouched(name, rewrites=rewrites)

    def test_unchanged_control_preserves_numeric_only_semantics(self):
        before = snapshot(self.folder)
        result = self.migrate()
        self.assertTrue(result['applied'])
        backup = self.root/'var/seafloor/numeric-migrations'/REACH/self.legacy['input_hash']
        self.assertEqual(before, snapshot(backup))
        for name in ('candidates.geojson', 'habitat.geojson', 'held.geojson', 'atlas-comparison.json'):
            self.assertEqual(before[name], (self.folder/name).read_bytes())
        receipt = read_json(self.folder/'run.json')
        self.assertEqual({name: sha256(self.folder/name) for name in OUTPUTS}, receipt['outputs'])
        physical = read_json(self.folder/'physical.json')
        self.assertEqual({name: sha256(self.folder/name) for name in PHYSICAL}, physical['outputs'])
        self.assertEqual(result['physical_input_hash'], physical['input_hash'])
        self.assertTrue(receipt['publication_prohibited'])
        self.assertTrue(result['requires_current_screen'])
        self.assertEqual(self.ledger, (self.root/'dist/data/seafloor-ledger.json').read_bytes())
        self.assertEqual([], [p for p in self.folder.parent.iterdir() if p.name.startswith('.numeric-')])

    def test_dry_run_writes_nothing(self):
        before = snapshot(self.folder)
        with patch.object(migrate_module, 'atomic_json') as rewrites:
            preview = migrate_numeric_cache(REACH, root=self.root)
        self.assertTrue(preview['changed']); self.assertFalse(preview['applied'])
        rewrites.assert_not_called()
        self.assertEqual(before, snapshot(self.folder))
        self.assertFalse((self.root/'var/seafloor/numeric-migrations').exists())
        self.assertEqual([REACH, 'sibling-sentinel.txt'], sorted(p.name for p in self.folder.parent.iterdir()))


if __name__ == '__main__':
    unittest.main()
