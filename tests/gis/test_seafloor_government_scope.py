"""An input scope must prevent mixed precedence and indirect calibration reuse."""
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin
from pyproj import Transformer

from skippercast.platform.contracts import atomic_json, read_json
from skippercast.seafloor import publish, source_scope as scope
from skippercast.seafloor.adopt import digest
from skippercast.seafloor.ingest import ingest
from skippercast.seafloor.io import sha256
from skippercast.seafloor.manifest import qualify_row
from skippercast.seafloor.substrate import resolve_bindings
from tests._support import ROOT

ENV = {'SKIPPERCAST_SOURCE_SCOPE': 'government-only', 'SKIPPERCAST_SOURCE_USE': 'for-profit'}


def isolated(root, rows):
    atomic_json(root/'catalog/surveys.json', {'surveys': rows})
    atomic_json(root/'var/seafloor/input-scope.json',
                {'version': 1, 'scope': 'government-only', 'isolated_root': str(root.resolve())})


def row(ident, license='public-domain-us-gov'):
    return {'id': ident, 'url': 'https://example.test/'+ident, 'license': license,
            'kind': 'bathymetry', 'status': 'usable', 'sha256': 'a'*64, 'derived_from': []}


def publication_fixture(root, calibration=None):
    native, restricted = row('native'), row('restricted', 'csumb-public-use-noncommercial')
    manifest = {'surveys': [native, restricted]}
    isolated(root, manifest['surveys'])
    _, audit = scope.scoped_manifest(root, manifest)
    ref = root/'var/seafloor/reference/cells.json'
    atomic_json(ref, {'cells': []})
    atomic_json(root/'dist/data/seafloor-ledger.json', {'reference_cells_sha256': sha256(ref),
        'reference': {}, 'reaches': [{'id': 'r01', 'region': 'fixture', 'status': 'partial'}]})
    out = root/'var/seafloor/reaches/r01'
    polygon = {'type': 'Polygon', 'coordinates': [[[-121,35],[-120.99,35],
        [-120.99,35.01],[-121,35.01],[-121,35]], [[-120.999,35.001],[-120.991,35.001],
        [-120.991,35.009],[-120.999,35.009],[-120.999,35.001]]]}
    props = {'id': 'reef', 'tier': 2, 'status': 'habitat', 'exportable': True,
        'screen': {'status': 'pass'}, 'source_ids': ['native'], 'hold_reasons': [],
        'terrain': {'grade': 'A', 'score': 4}, 'fit': {'lingcod': 3},
        'depth_min_ft': 40, 'depth_max_ft': 60}
    atomic_json(out/'habitat.geojson', {'features': [{'type': 'Feature', 'geometry': polygon, 'properties': props}]})
    atomic_json(out/'candidates.geojson', {'calibration_source_ids': calibration or ['native']})
    atomic_json(out/'cells.json', {'cells': []})
    inputs = {'screen': 'now', 'source_scope': audit, 'sources': [native], 'substrate_bindings': {}}
    receipt = {'input_hash': digest(inputs), 'ledger_summary': {}, 'inputs': inputs,
        'outputs': {name: sha256(out/name) for name in ('habitat.geojson', 'candidates.geojson', 'cells.json')}}
    atomic_json(out/'run.json', receipt)
    return manifest, audit, out, polygon


class GovernmentScopeTests(unittest.TestCase):
    def test_default_complete_manifest_and_catalog_bytes_are_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {}, clear=True):
            root = Path(tmp)
            manifest = {'surveys': [row('government'), row('restricted', 'csumb-public-use-noncommercial')]}
            atomic_json(root/'catalog/surveys.json', manifest)
            before = (root/'catalog/surveys.json').read_bytes()
            result, audit = scope.scoped_manifest(root, manifest)
            self.assertIs(result, manifest); self.assertIsNone(audit)
            self.assertEqual((root/'catalog/surveys.json').read_bytes(), before)

    def test_scope_rejects_lineage_laundering_and_changes_cache_identity(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', ENV, clear=True):
            root = Path(tmp)
            restricted = row('restricted', 'csumb-public-use-noncommercial')
            derived = row('derived'); derived['derived_from'] = ['restricted']
            manifest = {'surveys': [restricted, row('government'), derived]}
            isolated(root, manifest['surveys']); before = (root/'catalog/surveys.json').read_bytes()
            selected, audit = scope.scoped_manifest(root, manifest)
            self.assertEqual([x['id'] for x in selected['surveys']], ['government'])
            self.assertEqual(audit['excluded_source_ids'], ['derived', 'restricted'])
            self.assertNotEqual(digest({'sources': selected['surveys']}),
                                digest({'sources': selected['surveys'], 'source_scope': audit}))
            self.assertEqual((root/'catalog/surveys.json').read_bytes(), before)
            atomic_json(root/'catalog/surveys.json', {**manifest, 'revision': 2})
            _, changed = scope.scoped_manifest(root, manifest)
            self.assertNotEqual(digest(audit), digest(changed))

    def test_for_profit_marker_and_scope_cannot_be_silently_weakened(self):
        for case in ('missing', 'other-root', 'noncommercial', 'default', 'unknown', 'configured'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); isolated(root, [row('native')]); env = dict(ENV)
                if case == 'missing': (root/'var/seafloor/input-scope.json').unlink()
                if case == 'other-root':
                    atomic_json(root/'var/seafloor/input-scope.json', {'version': 1,
                        'scope': 'government-only', 'isolated_root': '/different-owned-root'})
                if case == 'noncommercial':
                    atomic_json(root/'deployments/production.json', {'source_use': 'noncommercial', 'monetization': 'none'})
                    env.pop('SKIPPERCAST_SOURCE_USE')
                if case == 'default': env = {}
                if case == 'unknown': env['SKIPPERCAST_SOURCE_SCOPE'] = 'anything'
                if case == 'configured':
                    atomic_json(root/'deployments/production.json', {'source_scope': 'government-only'})
                    env['SKIPPERCAST_SOURCE_SCOPE'] = 'all'
                with patch.dict('os.environ', env, clear=True), self.assertRaises(ValueError):
                    scope.processing_scope(root)

    def test_restricted_substrate_is_absent_before_any_category_read(self):
        rules = {'substrate_bindings': [{'source_id': 'restricted-classes',
                 'depth_source_ids': ['native']}]}
        manifest = {'surveys': [row('native')]}
        self.assertEqual(resolve_bindings(rules, manifest, scoped=True), {})
        with self.assertRaises(KeyError): resolve_bindings(rules, manifest)

    def test_actual_runner_never_ingests_or_calibrates_finer_restricted_depth(self):
        runner = importlib.import_module('skippercast.seafloor.run')
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', ENV, clear=True):
            root = Path(tmp); (root/'requirements-survey.txt').write_text('fixture')
            rules = read_json(ROOT/'catalog/habitat-rules.json'); rules['substrate_bindings'] = []
            atomic_json(root/'catalog/habitat-rules.json', rules)
            atomic_json(root/'dist/data/atlas.json', {'areas': [], 'targets': []})
            native = root/'original.tif'
            with rasterio.open(native, 'w', driver='GTiff', width=160, height=160, count=1,
                    dtype='float32', crs=3310, transform=from_origin(-30,280,2,2), nodata=np.nan) as out:
                out.write(np.full((160,160), -50, 'float32'), 1)
            template = deepcopy(next(r for r in read_json(ROOT/'catalog/surveys.json')['surveys']
                                     if r['status'] == 'usable' and r['license'] == scope.LICENSE))
            template.pop('adapter_review')
            template.update(id='native', url='https://pubs.usgs.gov/fixture.tif', archive_member='unknown',
                sha256=sha256(native), bytes=native.stat().st_size, derived_from=[], status='candidate')
            project = Transformer.from_crs(3310,4326,always_xy=True)
            bounds = [*project.transform(-50,-50), *project.transform(300,300)]
            checked, _, _ = ingest(template, bounds, root=root, local=native)
            government = qualify_row(template, checked, rights_url='https://pubs.usgs.gov/fixture')
            restricted = deepcopy(government)
            restricted.update(id='restricted-finer', resolution_m=1,
                              license='csumb-public-use-noncommercial', terrain_support={'must-not-read': True})
            manifest = {'surveys': [restricted, government]}; isolated(root, manifest['surveys'])
            before = (root/'catalog/surveys.json').read_bytes()
            atomic_json(root/'catalog/reaches.json', {'input_hash': 'grid', 'reaches': [{'id': 'r01'}]})
            ref = root/'var/seafloor/reference/cells.json'
            atomic_json(ref, {'input_hash': 'grid', 'cells': [{'id': '3310:0:0', 'reach': 'r01',
                'tier': 0, 'band_area_m2': 50000, 'reference_unknown_area_m2': 0}]})
            atomic_json(root/'var/seafloor/reference/run.json', {'input_hash': 'grid',
                'output_hashes': {'cells.json': sha256(ref)}})
            atomic_json(root/'dist/data/seafloor-ledger.json', {'reaches': [{'id': 'r01', 'band_km2': .05}],
                'totals': {'band_km2': .05}})
            with patch.object(runner, 'load_manifest', return_value=manifest), \
                    patch.object(runner, 'ingest', wraps=runner.ingest) as opening, \
                    patch.object(runner, 'load_snapshot', return_value={'version': 'fixture', 'status': 'held',
                        'reasons': ['screen-pending'], 'layers': []}):
                receipt, unchanged = runner.run('r01', root=root)
                self.assertFalse(unchanged)
                self.assertEqual([call.args[0]['id'] for call in opening.call_args_list], ['native'])
                self.assertEqual([s['id'] for s in receipt['inputs']['sources']], ['native'])
                folder = root/'var/seafloor/reaches/r01'
                self.assertEqual({c['source_id'] for c in read_json(folder/'cells.json')['cells']}, {'native'})
                self.assertEqual(read_json(folder/'candidates.geojson')['calibration_source_ids'], ['native'])
                self.assertEqual(receipt['inputs']['source_scope']['excluded_source_ids'], ['restricted-finer'])
                second, reused = runner.run('r01', root=root)
                self.assertTrue(reused); self.assertEqual(receipt, second)
            self.assertEqual((root/'catalog/surveys.json').read_bytes(), before)

    def test_publication_rejects_calibration_only_restricted_source_and_missing_inventory(self):
        for calibration in (['native', 'restricted'], None, ['native', 'native']):
            with self.subTest(calibration=calibration), tempfile.TemporaryDirectory() as tmp, \
                    patch.dict('os.environ', ENV, clear=True):
                root = Path(tmp); _, _, out, _ = publication_fixture(root, calibration)
                if calibration is None:
                    atomic_json(out/'candidates.geojson', {})
                    receipt = read_json(out/'run.json')
                    receipt['outputs']['candidates.geojson'] = sha256(out/'candidates.geojson')
                    atomic_json(out/'run.json', receipt)
                with self.assertRaisesRegex(ValueError, 'calibration'):
                    publish.region_layers(root, 'fixture', rerun=False)

    def test_publication_checks_substrate_and_scope_receipt_independently(self):
        for case in ('substrate', 'scope', 'metadata'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp, \
                    patch.dict('os.environ', ENV, clear=True):
                root = Path(tmp); manifest, _, out, _ = publication_fixture(root)
                receipt = read_json(out/'run.json')
                if case == 'substrate':
                    receipt['inputs']['substrate_bindings']['native'] = {'row': manifest['surveys'][1]}
                if case == 'scope': receipt['inputs']['source_scope']['scope'] = 'all'
                if case == 'metadata': receipt['inputs']['sources'][0]['sha256'] = 'b'*64
                atomic_json(out/'run.json', receipt)
                with self.assertRaises(ValueError): publish.region_layers(root, 'fixture', rerun=False)

    def test_unmapped_reach_allows_explicit_empty_calibration_and_rejects_restricted_coverage(self):
        for case in ('empty', 'coverage', 'hash'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp, \
                    patch.dict('os.environ', ENV, clear=True):
                root = Path(tmp); _, _, out, _ = publication_fixture(root)
                atomic_json(out/'habitat.geojson', {'features': []})
                atomic_json(out/'candidates.geojson', {'calibration_source_ids': []})
                if case == 'coverage':
                    atomic_json(out/'cells.json', {'cells': [{'id': '3310:0:0', 'source_id': 'restricted'}]})
                receipt = read_json(out/'run.json'); receipt['inputs']['sources'] = []
                receipt['input_hash'] = 'bad' if case == 'hash' else digest(receipt['inputs'])
                receipt['outputs'] = {name: sha256(out/name) for name in receipt['outputs']}
                atomic_json(out/'run.json', receipt)
                with patch.object(publish, 'load_snapshot', return_value={'status': 'ready'}), \
                        patch.object(publish, 'input_identity', return_value='now'):
                    if case == 'empty':
                        layers, receipts, _ = publish.region_layers(root, 'fixture', rerun=False)
                        self.assertEqual(layers, {'cells': [], 'habitat': []})
                        self.assertEqual(receipts['r01']['calibration_source_ids'], [])
                    else:
                        with self.assertRaises(ValueError): publish.region_layers(root, 'fixture', rerun=False)

    def test_scoped_export_preserves_entire_polygon_and_blocks_default_upload(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', ENV, clear=True):
            root = Path(tmp); _, audit, _, polygon = publication_fixture(root)
            def encode(tool, layers, path, **kwargs):
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'PMTiles\x03fixture')
            with patch.object(publish, 'run'), \
                    patch.object(publish, 'load_snapshot', return_value={'status': 'ready',
                        'snapshot': '2026-10-02T00:00:00Z', 'layers': []}), \
                    patch.object(publish, 'input_identity', return_value='now'), \
                    patch('scripts.build_map_tiles.build_vector_archive', side_effect=encode):
                folder, manifest = publish.build('fixture', root=root, tool='fixture',
                                                now=datetime(2026,10,3,tzinfo=timezone.utc))
            exported = json.loads(gzip.decompress((folder/manifest['export_file']).read_bytes()))
            self.assertEqual(exported['features'][0]['geometry'], polygon)
            self.assertEqual(exported['source_scope'], audit)
            self.assertEqual(manifest['reach_calibration_source_ids'], {'r01': ['native']})
            self.assertEqual(manifest['export_sha256'], sha256(folder/manifest['export_file']))
            with self.assertRaisesRegex(ValueError, 'namespace'):
                publish.publish_bundle(None, 'unused', folder)
