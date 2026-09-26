"""A point datum probe cannot silently qualify a 2 m fishing-depth raster."""
import json
from pathlib import Path
import unittest

from scripts.audit_csumb_vdatum_bridge import assess, compile_review, stable


ROOT = Path(__file__).resolve().parents[1]


class CsumbVdatumBridgeTests(unittest.TestCase):
    def test_rejects_api_error_and_sentinel_even_on_http_200(self):
        self.assertEqual(assess({'errorCode': 412, 'message': 'wrong frame'}, -121.2, 35.6,
                                'NAD83_1986')['status'], 'api_rejected')
        payload = {'region': 'WESTCOAST', 's_h_frame': 'NAD83_2011',
                   's_v_frame': 'NAVD88', 's_v_geoid': 'geoid09', 's_v_unit': 'm',
                   't_h_frame': 'IGS14', 't_v_frame': 'MLLW', 't_v_unit': 'm',
                   's_x': '-121.2', 's_y': '35.6', 't_x': '-121.2', 't_y': '35.6',
                   't_z': '-999999', 'uncertainty': '0.1'}
        self.assertEqual(assess(payload, -121.2, 35.6, 'NAD83_2011')['status'], 'unavailable')
        payload['t_z'] = '-0.03'
        payload['s_v_geoid'] = 'geoid18'
        self.assertEqual(assess(payload, -121.2, 35.6, 'NAD83_2011')['status'], 'invalid_response')

    def test_original_blocks_remain_unqualified_after_available_samples(self):
        sources = [json.loads((ROOT / f'dist/data/csumb-{series}-native-source-review.json').read_text())
                   for series in ('scc', 'bss')]

        def get(params):
            if params['s_h_frame'] == 'NAD83_1986':
                return {'errorCode': 412, 'message': 'Source Horizontal Frame should be NAD83_2011'}
            return {'region': 'WESTCOAST', 's_h_frame': params['s_h_frame'],
                    's_v_frame': 'NAVD88', 's_v_geoid': 'geoid09', 's_v_unit': 'm',
                    't_h_frame': 'IGS14', 't_v_frame': 'MLLW', 't_v_unit': 'm',
                    's_x': params['s_x'], 's_y': params['s_y'],
                    't_x': params['s_x'], 't_y': params['s_y'],
                    't_z': '-0.04', 'uncertainty': '0.10'}

        receipt = compile_review(sources, get=get)
        self.assertEqual(len(receipt['samples']), 9)
        self.assertTrue(all(row['status'] == 'sample_available' for row in receipt['samples']))
        self.assertEqual(receipt['alternative_horizontal_frame_probe']['status'], 'api_rejected')
        self.assertFalse(receipt['source_horizontal_realization_verified'])
        self.assertFalse(receipt['mllw_raster_converted'])
        self.assertFalse(receipt['depth_qualified'])
        self.assertFalse(receipt['fishing_target'])
        self.assertFalse(receipt['exportable'])
        later = dict(receipt, checked_at='later')
        self.assertEqual(stable(receipt), stable(later))


if __name__ == '__main__':
    unittest.main()
