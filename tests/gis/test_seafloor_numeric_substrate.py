"""A legacy categorical-row spelling must not force native terrain recomputation."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.transform import from_origin

from skippercast.platform.contracts import atomic_json, read_json
from skippercast.seafloor.adopt import digest, OUTPUTS, PHYSICAL
from skippercast.seafloor.fetch import fetch_source
from skippercast.seafloor.ingest import ingest
from skippercast.seafloor.io import sha256
from skippercast.seafloor.manifest import qualify_row
from skippercast.seafloor.migrate_cache import migrate_numeric_cache
from skippercast.seafloor.run import run
from tests._support import ROOT


class NumericSubstrateMigrationTests(unittest.TestCase):
    def test_legacy_substrate_resolution_reuses_physics_but_real_changes_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
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
                with rasterio.open(path, 'w', driver='GTiff', width=160, height=160,
                        count=1, dtype='float32', crs=3310,
                        transform=from_origin(-30, 280, 2, 2), nodata=np.nan) as out:
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
            atomic_json(root/'catalog/reaches.json', {'input_hash': 'grid', 'reaches': [{'id': 'fixture-r01'}]})
            atomic_json(root/'var/seafloor/reference/cells.json', {'input_hash': 'grid', 'cells': [{
                'id': '3310:0:0', 'reach': 'fixture-r01', 'tier': 0,
                'band_area_m2': 50000, 'reference_unknown_area_m2': 0}]})
            atomic_json(root/'var/seafloor/reference/run.json', {'input_hash': 'grid', 'output_hashes': {
                'cells.json': sha256(root/'var/seafloor/reference/cells.json')}})
            atomic_json(root/'dist/data/seafloor-ledger.json', {'reaches': [
                {'id': 'fixture-r01', 'band_km2': .05}], 'totals': {'band_km2': .05}})
            first, _ = run('fixture-r01', root=root)
            folder = root/'var/seafloor/reaches/fixture-r01'
            legacy = deepcopy(first)
            legacy['inputs']['substrate_bindings']['depth']['row']['resolution_m'] = 2
            physical_inputs = deepcopy(legacy['inputs'])
            physical_inputs.pop('screen'); physical_inputs.pop('screen_implementation_sha256')
            legacy_hash = digest(physical_inputs)
            self.assertNotEqual(legacy_hash, first['physical_input_hash'])
            for name in ('cells.json', 'terrain.json'):
                data = read_json(folder/name); data['input_hash'] = legacy_hash
                atomic_json(folder/name, data)
            atomic_json(folder/'physical.json', {'input_hash': legacy_hash,
                'outputs': {name: sha256(folder/name) for name in PHYSICAL}})
            legacy.update(input_hash=digest(legacy['inputs']), physical_input_hash=legacy_hash,
                outputs={name: sha256(folder/name) for name in OUTPUTS})
            atomic_json(folder/'run.json', legacy)
            before = {name: (folder/name).read_bytes() for name in (*OUTPUTS, 'run.json')}
            preview = migrate_numeric_cache('fixture-r01', root=root)
            self.assertTrue(preview['changed']); self.assertFalse(preview['applied'])
            self.assertEqual(before, {name: (folder/name).read_bytes() for name in before})
            for field, value in (('resolution_m', 4), ('year', 2020), ('notes', 'changed evidence')):
                changed = deepcopy(rows); changed[1][field] = value
                atomic_json(root/'catalog/surveys.json', {'surveys': changed})
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Substrate inputs changed'):
                    migrate_numeric_cache('fixture-r01', root=root, apply=True)
            atomic_json(root/'catalog/surveys.json', {'surveys': rows})
            self.assertTrue(migrate_numeric_cache('fixture-r01', root=root, apply=True)['applied'])
            backup = root/'var/seafloor/numeric-migrations/fixture-r01'/legacy['input_hash']
            self.assertEqual(before, {name: (backup/name).read_bytes() for name in before})
            for name in ('candidates.geojson', 'held.geojson', 'habitat.geojson'):
                self.assertEqual(before[name], (folder/name).read_bytes())
            self.assertTrue(read_json(folder/'run.json')['publication_prohibited'])
            with patch('skippercast.seafloor.run.footprint', side_effect=AssertionError('coverage recomputed')), \
                    patch('skippercast.seafloor.run.build_candidates', side_effect=AssertionError('terrain recomputed')):
                resumed, _ = run('fixture-r01', root=root)
            self.assertTrue(resumed['physical_reused'])
            self.assertEqual(resumed['physical_input_hash'], first['physical_input_hash'])
