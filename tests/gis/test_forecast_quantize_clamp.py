"""A forecast value the int16 tile cannot represent is stored as missing, never clamped to the range end.

Contract: `quantize` stores round(value / scale) as int16 and reserves -32768 (MISSING). A finite value whose
rounded step count lies beyond +/-32767 was never representable, so it is stored as MISSING (the sampler
already skips that code) instead of being published as the nearest representable value.
"""
import base64
import unittest

import numpy as np

from skippercast.forecast.build import MISSING, RANGES, quantize
from skippercast.forecast.models import MODELS

LIMIT = 32767

# RANGES entries whose upper bound cannot be stored at the model's scale today. Precipitation reaches
# 500 mm/h but 0.01 mm/h steps store 327.67 at most; those cells are stored as missing. A new entry that
# cannot be stored must be fixed (wider scale or tighter range) or added here deliberately.
KNOWN_UNSTORABLE = {'precipitation'}


def stored(values, scale):
    return np.frombuffer(base64.b64decode(quantize(np.asarray(values, dtype=float), scale)), '<i2').tolist()


def scales_by_field():
    found = {}
    for model in MODELS.values():
        for f in model.fields:
            found.setdefault(f.name, set()).add(f.scale)
    return found


class QuantizeUnrepresentableTests(unittest.TestCase):
    def test_precipitation_beyond_tile_range_is_missing_not_clamped(self):
        # Bug caught: np.clip publishes 400 and 500 mm/h as exactly 327.67 mm/h (32767 steps).
        self.assertEqual(stored([400.0, 500.0], 0.01), [MISSING, MISSING])

    def test_precipitation_300_is_unchanged_control(self):
        # Bug caught: a too-low cut-off (e.g. dropping everything above 100 mm/h) would hide real heavy rain.
        self.assertEqual(stored([5.0, 300.0], 0.01), [500, 30000])

    def test_exact_boundaries_stay_representable(self):
        # Bug caught: an off-by-one (`< 32767`) would drop the last representable step on either side.
        self.assertEqual(stored([327.67, -327.67], 0.01), [LIMIT, -LIMIT])

    def test_one_step_past_boundary_is_missing(self):
        # Bug caught: an off-by-one (`<= 32768`) or a clip that keeps 327.68 (32768 steps) as 32767.
        self.assertEqual(stored([327.68, -327.68], 0.01), [MISSING, MISSING])

    def test_rounds_before_bounding(self):
        # Bug caught: bounding the unrounded ratio would store 327.674 (32767.4 steps) as missing.
        self.assertEqual(stored([327.674, -327.674], 0.01), [LIMIT, -LIMIT])

    def test_negative_overflow_is_missing(self):
        # Bug caught: only the positive side handled, so -500 would still clip to -32767.
        self.assertEqual(stored([-400.0], 0.01), [MISSING])

    def test_nan_and_infinity_stay_missing(self):
        # Bug caught: the new bound check turning NaN (comparisons are False) into a real number.
        self.assertEqual(stored([np.nan, np.inf, -np.inf], 0.01), [MISSING, MISSING, MISSING])

    def test_huge_finite_value_is_missing(self):
        self.assertEqual(stored([1e300], 0.01), [MISSING])

    def test_wind_in_range_is_unaffected_control(self):
        # Bug caught: the change touching healthy fields; u10 at +/-100 is 10000 steps at 0.01.
        self.assertEqual(stored([100.0, -100.0, 0.0, 1.234], 0.01), [10000, -10000, 0, 123])

    def test_mixed_cells_only_the_unrepresentable_one_changes(self):
        # Bug caught: the whole array going missing (or the neighbour being clamped) when one cell overflows.
        self.assertEqual(stored([1.0, 500.0, np.nan, 2.0], 0.01), [100, MISSING, MISSING, 200])


class RangesFitModelScaleTests(unittest.TestCase):
    def test_every_range_bound_is_checked_against_each_model_scale(self):
        # Bug caught: a future RANGES entry (or a scale change) whose bound needs more than 32767 steps,
        # which would silently store real values as missing. The failure names the field and its scale.
        found = scales_by_field()
        unstorable = set()
        for name, (low, high) in sorted(RANGES.items()):
            for scale in sorted(found.get(name, ())):
                steps = max(abs(round(low / scale)), abs(round(high / scale)))
                if steps > LIMIT:
                    unstorable.add(name)
        self.assertEqual(unstorable, KNOWN_UNSTORABLE,
                         f'RANGES fields that cannot be stored at their scale: {sorted(unstorable)}; '
                         f'expected only {sorted(KNOWN_UNSTORABLE)}')

    def test_known_unstorable_precipitation_really_overflows(self):
        # Bug caught: the exemption list going stale after precipitation is fixed.
        (scale,) = scales_by_field()['precipitation']
        self.assertGreater(round(RANGES['precipitation'][1] / scale), LIMIT)

    def test_ranged_fields_that_fit_store_their_extremes(self):
        # Bug caught: a healthy field stored as missing at its own range limit.
        found = scales_by_field()
        for name, (low, high) in sorted(RANGES.items()):
            if name in KNOWN_UNSTORABLE:
                continue
            for scale in found.get(name, ()):
                with self.subTest(field=name, scale=scale):
                    got = stored([low, high], scale)
                    self.assertNotIn(MISSING, got)
                    self.assertEqual(got, [round(low / scale), round(high / scale)])


if __name__ == '__main__':
    unittest.main()
