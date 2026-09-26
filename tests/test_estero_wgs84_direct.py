"""A direct ellipsoid-to-MLLW point response is still not a fishing depth."""
import unittest

from scripts.audit_estero_wgs84_direct import stable, vdatum_point


class EsteroWgs84DirectTests(unittest.TestCase):
    @staticmethod
    def response(params):
        return {'region': 'WESTCOAST', 's_h_frame': params['s_h_frame'],
                's_v_frame': params['s_v_frame'], 't_h_frame': params['t_h_frame'],
                't_v_frame': params['t_v_frame'], 'epoch_in': params['epoch_in'],
                'epoch_out': params['epoch_out'], 's_x': params['s_x'],
                's_y': params['s_y'], 't_x': params['s_x'], 't_y': params['s_y'],
                't_z': '35.8', 'uncertainty': '0.08'}

    def test_accepts_exact_original_ellipsoid_frame_only(self):
        point = vdatum_point(680000, 3910000, get=self.response)
        self.assertEqual(point['offset_m'], 35.8)
        self.assertEqual(point['transform_uncertainty_m'], 0.08)
        self.assertIn('s_v_frame=WGS84_G1150', point['request_url'])
        self.assertIn('epoch_in=2012.6', point['request_url'])
        with self.assertRaises(ValueError):
            vdatum_point(680000, 3910000,
                         get=lambda p: dict(self.response(p), s_v_frame='NAVD88'))
        with self.assertRaises(ValueError):
            vdatum_point(680000, 3910000,
                         get=lambda p: dict(self.response(p), t_z='-999999'))
        with self.assertRaises(ValueError):
            vdatum_point(680000, 3910000,
                         get=lambda p: {'errorCode': 412})

    def test_timestamp_is_not_evidence_change(self):
        self.assertEqual(stable({'scope': 'research', 'checked_at': 'earlier',
                                 'qualified_waypoints': 0}),
                         stable({'scope': 'research', 'checked_at': 'later',
                                 'qualified_waypoints': 0}))


if __name__ == '__main__':
    unittest.main()
