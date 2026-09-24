import unittest
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from shapely.geometry import box

from scripts.build_central_sediment_context import display_parts, download_missing, thin_mask


class CentralSedimentContextTests(unittest.TestCase):
    def test_negative_interpolation_artifacts_are_not_thin_sediment(self):
        source = np.ma.array([[-1.0, 0.0, 2.5, 2.6, -9999.0]],
                             mask=[[False, False, False, False, True]])
        thin, negative, valid = thin_mask(source, -9999, 2.5)
        self.assertEqual(valid, 4)
        self.assertEqual(negative, 1)
        self.assertEqual(thin.tolist(), [[False, True, True, False, False]])

    def test_mpa_cut_is_applied_after_display_simplification(self):
        original = box(0, 0, 1000, 1000)
        exclusion = box(450, -100, 550, 1100)
        pieces = display_parts(original, exclusion, 100_000)
        self.assertEqual(len(pieces), 2)
        self.assertTrue(all(piece.intersection(exclusion).area == 0 for piece in pieces))
        self.assertAlmostEqual(sum(piece.area for piece in pieces), 900_000)

    def test_existing_source_must_match_pinned_digest(self):
        with TemporaryDirectory() as folder:
            original = Path(folder) / 'original.xml'
            original.write_bytes(b'official bytes')
            expected = hashlib.sha256(b'official bytes').hexdigest()
            download_missing('https://www.sciencebase.gov/example', original, expected, 100)
            with self.assertRaisesRegex(ValueError, 'digest changed'):
                download_missing('https://www.sciencebase.gov/example', original, '0' * 64, 100)

    def test_fetch_rejects_unapproved_source_host_before_network(self):
        with TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'Unapproved'):
                download_missing('https://example.org/source.zip', Path(folder) / 'missing.zip',
                                 '0' * 64, 100)


if __name__ == '__main__':
    unittest.main()
