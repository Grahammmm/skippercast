"""Dependency-light checks of the committed baseline, including CI without caches."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from skippercast.seafloor.io import verified_file

ROOT = Path(__file__).resolve().parents[1]


class LedgerTests(unittest.TestCase):
    def test_all_seven_regions_have_disjoint_reaches_and_zero_claims(self):
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
            self.assertEqual(reach['band_km2'], reach['tier0_km2'])
            self.assertEqual([reach[k] for k in ('tier1_km2', 'tier2_km2', 'tier3_km2')], [0, 0, 0])
            self.assertEqual(reach['surveys_used'], [])
            self.assertEqual(reach['status'], 'unassessed')
        self.assertEqual(ledger['reference']['status'], 'provisional')
        self.assertEqual(ledger['reference']['outside_reference_band_status'], 'unknown')
        self.assertEqual(ledger['input_hash'], catalog['input_hash'])
        self.assertEqual(len(ledger['reference']['tiles']), len({t['id'] for t in ledger['reference']['tiles']}))

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
            with patch('skippercast.seafloor.io.urlopen') as request:
                self.assertEqual(verified_file(url, digest, path, True), digest)
                request.assert_not_called()
                path.write_bytes(b'tampered')
                with self.assertRaises(ValueError):
                    verified_file(url, digest, path, True)
                request.assert_not_called()

    def test_failed_download_does_not_poison_cache(self):
        url = 'https://noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com/fixture'
        response = io.BytesIO(b'bad bytes')
        response.headers = {}
        response.geturl = lambda: url
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture'
            with patch('skippercast.seafloor.io.urlopen', return_value=response):
                with self.assertRaises(ValueError):
                    verified_file(url, '0' * 64, path, True)
            self.assertFalse(path.exists())
            self.assertFalse(path.with_suffix('.part').exists())


if __name__ == '__main__':
    unittest.main()
