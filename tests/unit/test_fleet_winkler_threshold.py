"""Winkler prefix bonus applies only when the Jaro score exceeds 0.7."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from skippercast.fleet.normalize import jaro_winkler, name_similarity  # noqa: E402

WEAK_A, WEAK_B = "EXAMPLEAAAAAA", "EXAMPLEZZZZZZ"
# 7 matches, 13 chars each, no transpositions: (7/13 + 7/13 + 1) / 3
WEAK_BASE = (7 / 13 + 7 / 13 + 1) / 3


class WinklerThresholdTests(unittest.TestCase):
    def test_weak_common_prefix_is_not_boosted(self):
        self.assertAlmostEqual(jaro_winkler(WEAK_A, WEAK_B), WEAK_BASE, places=9)
        self.assertAlmostEqual(name_similarity(WEAK_A, WEAK_B), WEAK_BASE, places=9)

    def test_threshold_bracketing_keeps_only_strong_bonus(self):
        self.assertLessEqual(WEAK_BASE, 0.7)
        # "ABCDXXXX"/"ABCDYYYY": 4 matches of 8, base 2/3 -> unboosted
        self.assertAlmostEqual(jaro_winkler("ABCDXXXX", "ABCDYYYY"), (0.5 + 0.5 + 1) / 3, places=9)
        # "ABCDEFXY"/"ABCDEFYX": 8 matches, 1 transposition pair, strong -> boosted
        base = (1 + 1 + (8 - 1) / 8) / 3
        self.assertAlmostEqual(jaro_winkler("ABCDEFXY", "ABCDEFYX"), base + 4 * 0.1 * (1 - base), places=9)

    def test_reference_and_empty_controls(self):
        self.assertAlmostEqual(jaro_winkler("MARTHA", "MARHTA"), 0.961111111111, places=9)
        self.assertAlmostEqual(jaro_winkler("DIXON", "DICKSONX"), 0.813333333333, places=9)
        self.assertEqual(jaro_winkler("SAME", "SAME"), 1.0)
        self.assertEqual(jaro_winkler("", "SAME"), 0.0)
        self.assertAlmostEqual(jaro_winkler("MARTHA", "MARHTA", prefix_scale=0), 0.944444444444, places=9)

    def test_new_variant_separation_is_unchanged(self):
        self.assertEqual(name_similarity("NEWSEAFORTH", "SEAFORTH"), 0.0)


if __name__ == "__main__":
    unittest.main()
