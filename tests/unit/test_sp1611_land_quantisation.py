"""SP-16-v1 baseline pair for the negative shoreline-quantisation gate."""
import json
import unittest

from tests._support import FIXTURES
from tests.unit import test_land_water as producer
from skippercast.platform import land_water

BASELINE = json.loads((FIXTURES / 'sp1611_land_quantisation/baseline.json').read_text())


def published_shore(case):
    """Use the committed synthetic CUSP producer shape and mutate only pinned inputs."""
    shore = producer.shoreline(producer.mainland(), acc=case['hor_acc'])
    shore['provenance']['display_quantisation_m'] = case['display_quantisation_m']
    return shore


class BaselineTest(unittest.TestCase):
    def test_primary_regression(self):
        case = BASELINE['cases']['primary regression']
        product, lines = land_water.build_product(published_shore(case), producer.REGION)
        self.assertEqual(product['status'], case['expected_status'])
        self.assertTrue(any(case['expected_cause'] in cause for cause in product['causes']))
        self.assertIsNone(lines)

    def test_healthy_control(self):
        case = BASELINE['cases']['healthy control']
        product, lines = land_water.build_product(published_shore(case), producer.REGION)
        self.assertEqual(product['status'], case['expected_status'])
        self.assertIsNotNone(lines)


class AcceptanceTest(unittest.TestCase):
    def assert_invalid_quantum(self, value):
        shore = producer.shoreline(producer.mainland(), acc=4.31)
        shore['provenance']['display_quantisation_m'] = value
        product, lines = land_water.build_product(shore, producer.REGION)
        self.assertEqual(product['status'], 'unavailable')
        self.assertTrue(any('invalid display quantisation' in cause for cause in product['causes']))
        self.assertIsNone(lines)

    def test_a1_negative_quantum_rejects_otherwise_accepted_coast(self):
        shore = producer.shoreline(producer.mainland(), acc=20)
        shore['provenance']['display_quantisation_m'] = -20
        product, lines = land_water.build_product(shore, producer.REGION)
        self.assertEqual(product['status'], 'unavailable')
        self.assertTrue(any('invalid display quantisation' in cause for cause in product['causes']))
        self.assertIsNone(lines)

    def test_a2_invalid_and_negative_values_fail_closed(self):
        for value in (-20, -1, None, '1.96', True, float('nan'), float('inf'), float('-inf')):
            with self.subTest(value=value):
                self.assert_invalid_quantum(value)

    def test_a3_zero_normal_and_excessive_error(self):
        for acc, quantum, expected in ((4.31, 0, 'available'), (4.31, 1.96, 'available'),
                                       (20, 1.96, 'unavailable')):
            with self.subTest(acc=acc, quantum=quantum):
                shore = producer.shoreline(producer.mainland(), acc=acc)
                shore['provenance']['display_quantisation_m'] = quantum
                product, lines = land_water.build_product(shore, producer.REGION)
                self.assertEqual(product['status'], expected)
                self.assertEqual(lines is None, expected == 'unavailable')

    def test_a4_edge_error_budget_boundary_is_preserved(self):
        for quantum, expected in ((7.63, 'available'), (7.64, 'available'), (7.65, 'unavailable')):
            with self.subTest(quantum=quantum):
                shore = producer.shoreline(producer.mainland(), acc=4.31)
                shore['provenance']['display_quantisation_m'] = quantum
                product, lines = land_water.build_product(shore, producer.REGION)
                self.assertEqual(product['status'], expected)
                self.assertEqual(lines is None, expected == 'unavailable')


if __name__ == '__main__':
    unittest.main()
