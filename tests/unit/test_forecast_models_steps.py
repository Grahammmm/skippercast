"""hourly_then_3h honours its inclusive ``end`` argument."""
import unittest

from skippercast.forecast.models import ECMWF_STEPS, MODELS, hourly_then_3h

GFS_DEFAULT = tuple(range(73)) + tuple(range(75, 193, 3))
ECMWF_DEFAULT = tuple(range(0, 145, 3)) + tuple(range(150, 193, 6))


class HourlyThen3hEndTests(unittest.TestCase):
    def test_end_inside_hourly_prefix_is_hard_bound(self):
        self.assertEqual(hourly_then_3h(72, 24), list(range(25)))
        self.assertEqual(hourly_then_3h(72, 71), list(range(72)))

    def test_zero_end_contains_initialization_only(self):
        steps = hourly_then_3h(72, 0)
        self.assertEqual(steps, [0])
        self.assertIsInstance(steps, list)

    def test_transition_endpoint_is_inclusive_without_duplicate(self):
        self.assertEqual(hourly_then_3h(72, 72), list(range(73)))
        self.assertEqual(hourly_then_3h(72, 73), list(range(73)))
        self.assertEqual(hourly_then_3h(72, 74), list(range(73)))
        self.assertEqual(hourly_then_3h(72, 75), list(range(73)) + [75])

    def test_three_hour_phase_stays_anchored(self):
        self.assertEqual(hourly_then_3h(5, 12), [0, 1, 2, 3, 4, 5, 8, 11])
        self.assertEqual(hourly_then_3h(5, 3), [0, 1, 2, 3])

    def test_empty_horizon_and_zero_transition(self):
        self.assertEqual(hourly_then_3h(72, -1), [])
        self.assertEqual(hourly_then_3h(0, 6), [0, 3, 6])

    def test_configured_model_schedules_are_unchanged(self):
        gfs = [m for m in MODELS.values() if m.family == 'gfs']
        self.assertTrue(gfs)
        for m in gfs:
            self.assertEqual(tuple(m.steps), GFS_DEFAULT, m.id)
        self.assertEqual(tuple(ECMWF_STEPS), ECMWF_DEFAULT)
        self.assertEqual(tuple(hourly_then_3h(72)), GFS_DEFAULT)

    def test_integer_matrix_is_ordered_unique_and_bounded(self):
        for until in range(0, 9):
            for end in range(-1, 20):
                steps = hourly_then_3h(until, end)
                label = (until, end)
                self.assertEqual(steps, sorted(set(steps)), label)
                self.assertTrue(all(s <= end for s in steps), label)
                expected = [s for s in range(0, end + 1)
                            if s <= until or (s > until + 2 and (s - until) % 3 == 0)]
                self.assertEqual(steps, expected, label)


if __name__ == '__main__':
    unittest.main()
