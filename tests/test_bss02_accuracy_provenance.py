"""Do not promote a circular terrain-class accuracy check to rock groundtruth."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.audit_bss02_accuracy_provenance import inspect


ROOT = Path(__file__).resolve().parents[1]


class AccuracyProvenanceTest(unittest.TestCase):
    def test_pinned_original_is_not_independent_rock_evidence(self):
        spec = next(source for source in json.loads(
            (ROOT / 'catalog/csumb-bss-native-sources.json').read_text())['sources']
            if source['survey_id'] == 'BSS_Block02')
        cache = ROOT / 'var/review/csumb-bss-cache'
        if not (cache / 'BSS_Block02_additional_products.tar.gz').exists():
            self.skipTest('Pinned original archive not cached locally')
        receipt = inspect(spec, cache)
        self.assertFalse(receipt['independent_seabed_observation'])
        self.assertEqual(receipt['rank_effect'], 'none')
        self.assertEqual(receipt['assessment_points'], 100)

    def test_unpinned_archive_is_rejected(self):
        spec = next(source for source in json.loads(
            (ROOT / 'catalog/csumb-bss-native-sources.json').read_text())['sources']
            if source['survey_id'] == 'BSS_Block02')
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'BSS_Block02_additional_products.tar.gz').write_bytes(b'wrong')
            with self.assertRaisesRegex(ValueError, 'pinned original'):
                inspect(spec, Path(folder))


if __name__ == '__main__':
    unittest.main()
