"""The four128 artifact review resolves its home-derived defaults when fully imported.

Companion to tests/unit/test_coastal_four128_home_paths.py, which checks the same
assignments without the numpy-backed lanes this module imports.
"""
import sys
import unittest

from tests._support import ROOT
from tests.unit.test_coastal_four128_home_paths import NAMES, PROJECT, _load


class ReviewImportDefaults(unittest.TestCase):
    def tearDown(self):
        for module in (*NAMES, "coastal_four128_resources"):
            sys.modules.pop(module, None)

    def test_imported_defaults_match_previous_literals(self):
        review, _ = _load("coastal_four128_artifact_review", {})
        self.assertEqual(str(review.PROJECT), PROJECT)
        self.assertEqual(str(review.N), PROJECT + "/outputs/ordered-four128-approved-20261011")
        self.assertEqual(review.DEFAULT_ROOT, review.N)
        self.assertEqual(str(review.W), PROJECT + "/work/source-reuse-admission-20261011")
        # The runtime it imports resolves the same root.
        self.assertEqual(str(sys.modules["coastal_four128_runtime"].PROJECT), PROJECT)

    def test_imported_overrides_still_win(self):
        review, _ = _load("coastal_four128_artifact_review", {
            "SKIPPERCAST_FOUR128_MISSION_ROOT": "/nonexistent/mission",
            "SKIPPERCAST_FOUR128_CODE_ROOT": str(ROOT)})
        self.assertEqual(str(review.N), "/nonexistent/mission")
        self.assertEqual(review.W, ROOT)


if __name__ == "__main__":
    unittest.main()
