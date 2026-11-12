"""Unrepresentable habitat metric integers are refused with ValueError."""

import json
import unittest

from skippercast.atlas.scoring import habitat_grade, habitat_score

KEYS = ("relief_210m_m", "rugose_or_bedrock_fraction_210m",
        "plane_residual_rms_250m_m", "rough_habitat_within_250m_ha")
BASE = dict(zip(KEYS, (15, 1, 3, 10)))
MSG = "Habitat metrics must be finite, nonnegative numbers"
HUGE = 10 ** 400


class ScoringNumbersTest(unittest.TestCase):
    def refuses(self, key, value):
        with self.assertRaises(ValueError) as ctx:
            habitat_score({**BASE, key: value})
        self.assertEqual(str(ctx.exception), MSG)

    def test_oversized_each_required_metric_refuses(self):
        for key in KEYS:
            with self.subTest(key=key):
                self.refuses(key, HUGE)

    def test_oversized_negative_and_json_values_refuse(self):
        for key in KEYS:
            for value in (-HUGE, json.loads(json.dumps(HUGE)),
                          json.loads(json.dumps(-HUGE))):
                with self.subTest(key=key, negative=value < 0):
                    self.refuses(key, value)

    def test_invalid_finite_domain_stays_closed(self):
        for key in KEYS:
            for value in (True, "5", None, float("nan"), float("inf"),
                          float("-inf"), -1):
                with self.subTest(key=key, value=value):
                    self.refuses(key, value)
        with self.assertRaises(ValueError):
            habitat_score({**BASE, KEYS[1]: 1.5})

    def test_representable_scores_unchanged(self):
        score = habitat_score(BASE)
        self.assertEqual(score, 100)
        self.assertIs(type(score), int)
        self.assertEqual(habitat_score(dict(zip(KEYS, (0, 0, 0, 0)))), 0)
        self.assertEqual(habitat_score({**BASE, KEYS[0]: 10 ** 300}), 100)
        self.assertEqual(habitat_score(dict(zip(KEYS, (7.5, 0.5, 1.5, 5)))), 50)
        self.assertEqual(habitat_grade(75), "A")
        self.assertEqual(habitat_grade(55), "B")
        self.assertEqual(habitat_grade(54), "C")

    def test_extras_and_missing_key_keep_contract(self):
        extra = {**BASE, "fleet_hours": HUGE, "evidence": -HUGE}
        self.assertEqual(habitat_score(extra), 100)
        missing = dict(BASE)
        del missing[KEYS[2]]
        with self.assertRaises(KeyError):
            habitat_score(missing)


if __name__ == "__main__":
    unittest.main()
