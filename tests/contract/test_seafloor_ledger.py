"""Dependency-light checks of the committed baseline, including CI without caches."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from skippercast.http import FakeSession
from skippercast.seafloor.io import verified_file
from tests._support import ROOT


class LedgerTests(unittest.TestCase):
    def test_all_seven_regions_have_disjoint_reaches_and_supported_claims(self):
        ledger = json.loads((ROOT / 'dist/data/seafloor-ledger.json').read_text())
        catalog = json.loads((ROOT / 'catalog/reaches.json').read_text())
        config = json.loads((ROOT / 'catalog/seafloor-scope.json').read_text())
        reaches = ledger['reaches']
        self.assertEqual({r['region'] for r in reaches}, {r['id'] for r in config['regions']})
        self.assertEqual(len(reaches), len({r['id'] for r in reaches}))
        self.assertEqual({r['id'] for r in reaches}, {r['id'] for r in catalog['reaches']})
        self.assertEqual(sorted(r['order'] for r in reaches), list(range(1, len(reaches) + 1)))
        self.assertEqual(reaches[0]['region'], 'morro-bay')
        for key, total in ledger['totals'].items():
            self.assertAlmostEqual(total, sum(r[key] for r in reaches), places=6)
        for reach in reaches:
            self.assertGreater(reach['band_km2'], 0)
            self.assertAlmostEqual(reach['band_km2'], reach['tier0_km2'] + reach['tier1_km2'], places=7)
            self.assertGreaterEqual(reach['tier2_km2'], 0)
            self.assertLessEqual(reach['tier2_km2'], reach['selected_valid_km2'])
            self.assertEqual(reach['tier3_km2'], 0)
            if reach['status'] == 'unassessed':
                self.assertEqual(reach['tier1_km2'], 0)
                self.assertEqual(reach['surveys_used'], [])
            else:
                self.assertIn(reach['status'], ('habitat-held-for-screen', 'habitat-screened', 'terrain-pending'))
                if reach['tier2_km2'] > 0:
                    self.assertEqual(reach['screen']['status'], 'ready')
                    self.assertEqual({s['id'] for s in reach['screen']['layers']},
                                     {'cdfw-mpa', 'noaa-federal', 'security'})
                    self.assertEqual(sum(reach['habitat_by_grade'].values()), reach['habitat_count'])
                    self.assertGreater(reach['habitat_count'], 0)
                self.assertIn(reach['coverage_rule_version'], ('native-coverage-habitat-v1', 'native-coverage-habitat-v2'))
                if reach['status'] == 'terrain-pending':
                    self.assertEqual(reach['tier2_km2'], 0)
                    self.assertEqual(reach['habitat_count'], 0)
                    self.assertTrue(reach['processing_incomplete'])
                    continue
                self.assertGreaterEqual(reach['held_candidate_count'], 0)
                self.assertLessEqual(reach['atlas_comparison']['reproduced_count'],
                                     reach['atlas_comparison']['applicable_outline_count'])
                self.assertRegex(reach['survey_run_hash'], '^[a-f0-9]{64}$')
                self.assertGreaterEqual(reach['selected_valid_km2'], 0)
                manifest = json.loads((ROOT / 'catalog/surveys.json').read_text())
                usable = {r['id'] for r in manifest['surveys'] if r['status'] == 'usable'}
                self.assertLessEqual(set(reach['surveys_used']), usable)
        self.assertEqual(ledger['reference']['status'], 'provisional')
        self.assertEqual(ledger['reference']['outside_reference_band_status'], 'unknown')
        self.assertEqual(ledger['input_hash'], catalog['input_hash'])
        self.assertEqual(len(ledger['reference']['tiles']), len({t['id'] for t in ledger['reference']['tiles']}))

    def test_reference_restore_cannot_overwrite_ledger_or_accept_changed_cells(self):
        from skippercast.seafloor.restore import install_verified
        with tempfile.TemporaryDirectory() as directory:
            root, staged = Path(directory)/'root', Path(directory)/'staged'
            for base in (root, staged):
                (base/'catalog').mkdir(parents=True)
                (base/'var/seafloor/reference').mkdir(parents=True)
                (base/'catalog/reaches.json').write_text('same reaches')
            cells=staged/'var/seafloor/reference/cells.json'
            cells.write_text(json.dumps({'input_hash':'baseline', 'cells':[]}))
            expected=hashlib.sha256(cells.read_bytes()).hexdigest()
            (staged/'var/seafloor/reference/run.json').write_text(json.dumps(
                {'input_hash':'baseline','output_hashes':{'cells.json':expected}}))
            (root/'dist/data').mkdir(parents=True)
            ledger=root/'dist/data/seafloor-ledger.json'
            ledger.write_text(json.dumps({'input_hash':'baseline','reference_cells_sha256':expected,'tier1_km2':12}))
            before=ledger.read_bytes()
            install_verified(root,staged)
            self.assertEqual(ledger.read_bytes(),before)
            self.assertEqual((root/'var/seafloor/reference/cells.json').read_bytes(),cells.read_bytes())
            cells.write_text('changed')
            with self.assertRaisesRegex(ValueError,'differs'):
                install_verified(root,staged)
            self.assertEqual(ledger.read_bytes(),before)

    def test_ledger_cli_needs_no_gis_or_cache(self):
        result = subprocess.run([sys.executable, '-m', 'skippercast.seafloor', 'ledger', '--region', 'morro-bay'],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('morro-bay-r', result.stdout)
        self.assertNotIn('monterey-point-sur-r', result.stdout)
        invalid = subprocess.run([sys.executable, '-m', 'skippercast.seafloor', 'ledger', '--region', 'typo'],
                                 cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(invalid.returncode, 0)

    def test_pinned_cache_never_fetches_again_and_rejects_tampering(self):
        content = b'reference fixture'
        digest = hashlib.sha256(content).hexdigest()
        url = 'https://noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com/fixture'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture'
            path.write_bytes(content)
            session = FakeSession({url: content})
            self.assertEqual(verified_file(url, digest, path, True, session=session), digest)
            self.assertEqual(session.calls, [])
            path.write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                verified_file(url, digest, path, True, session=session)
            self.assertEqual(session.calls, [])

    def test_failed_download_does_not_poison_cache(self):
        url = 'https://noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com/fixture'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture'
            session = FakeSession({url: b'bad bytes'})
            with self.assertRaises(ValueError):
                verified_file(url, '0' * 64, path, True, session=session)
            self.assertEqual(len(session.calls), 1)
            self.assertFalse(path.exists())
            self.assertFalse(path.with_suffix('.part').exists())


if __name__ == '__main__':
    unittest.main()
