"""Fail closed when the published CDFW substrate service changes classes."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
from audit_cdfw_substrate_tiles import verify_service, sector_tiles


class CdfwSubstrateTests(unittest.TestCase):
    def test_service_class_and_resolution_must_match_review(self):
        service = {'name': 'biosds3091_cru', 'spatialReference': {'wkid': 3310},
                   'tileInfo': {'format': 'LERC2D', 'rows': 256, 'cols': 256,
                                'lods': [{'level': 7, 'resolution': 40}]}}
        classes = {'features': [{'attributes': {'Value': 1, 'CLASSNAME': 'Hard'}},
                                {'attributes': {'Value': 2, 'CLASSNAME': 'Soft'}}]}
        verify_service(service, classes)
        classes['features'][0]['attributes']['CLASSNAME'] = 'Unknown'
        with self.assertRaisesRegex(ValueError, 'class table'):
            verify_service(service, classes)
        classes['features'][0]['attributes']['CLASSNAME'] = 'Hard'
        service['tileInfo']['lods'][0]['resolution'] = 80
        with self.assertRaisesRegex(ValueError, 'resolution'):
            verify_service(service, classes)

    def test_sector_tiles_are_named_by_coast(self):
        sectors = {'sectors': [{'coast': 'northern', 'bounds': [-124.4, 40.7, -124.1, 40.9]},
                               {'coast': 'southern', 'bounds': [-120.3, 34.0, -120.0, 34.2]}]}
        result = sector_tiles(sectors)
        self.assertEqual(set(result), {'northern', 'southern'})
        self.assertTrue(result['northern'])
        self.assertTrue(result['southern'])
        self.assertFalse(result['northern'] & result['southern'])


if __name__ == '__main__':
    unittest.main()
