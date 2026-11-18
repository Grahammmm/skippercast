"""Offline controls for F11-06: a planning square is not the measured reference footprint.

Synthetic EPSG:3310 geometry only. The detector separates two evidence roles:
planning-cell context (cell membership) and measured overlap with the verified
valid reference geometry. Baseline receipt: classify_cells() qualifies a Tier 1
cell at 25% coverage and classified_habitat.prepare() then uses the whole square
as the paired-reference support; additional_patches() keeps any patch inside it.
"""
import unittest

from shapely.geometry import box

from skippercast.seafloor import classified_habitat as ch
from skippercast.seafloor import coverage

CELL = {'id': '3310:0:0'}  # the 250 m square (0,0)-(250,250)
# Reference survey covers only the left quarter strip (25% of the square).
REFERENCE = box(0, 0, 62.5, 250)
# Candidate patches (>= 1000 m2). One sits on the reference; one lies in the
# disjoint right-hand quarter of the same cell, with no reference overlap.
ON_REFERENCE = box(10, 10, 50, 50)
OFF_REFERENCE = box(150, 50, 200, 100)


def measured_overlap_m2(patch, reference):
    return patch.intersection(reference).area


def unsupported_patches(patches, reference):
    """Patches asserted as reference-supported but with no measured overlap."""
    return [p for p in patches if measured_overlap_m2(p, reference) <= 1e-6]


def baseline_support(cells):
    # Same construction as classified_habitat.prepare() for paired-reference mode.
    from shapely.ops import unary_union
    return unary_union([coverage.cell_geometry(c) for c in cells if c['tier'] == 1])


def measured_support(cells, reference):
    """Contract: intersect the Tier 1 cell with verified valid reference geometry."""
    return baseline_support(cells).intersection(reference)


class ReferenceFootprintControls(unittest.TestCase):
    def setUp(self):
        self.cells = coverage.classify_cells(
            [CELL], [{'row': {'id': 'ref', 'resolution_m': 2, 'year': 2014},
                      'geometry': REFERENCE}])

    def test_fixture_is_tier1_at_exactly_quarter_coverage(self):
        self.assertEqual(self.cells[0]['tier'], 1)
        self.assertAlmostEqual(self.cells[0]['valid_fraction'], .25)
        self.assertEqual(self.cells[0]['source_id'], 'ref')

    def test_valid_control_intersected_footprint_keeps_only_measured_patches(self):
        support = measured_support(self.cells, REFERENCE)
        patches, _ = ch.additional_patches([ON_REFERENCE, OFF_REFERENCE], support, box(-20, -20, -10, -10))
        self.assertEqual(len(patches), 1)
        self.assertEqual(unsupported_patches(patches, REFERENCE), [])
        self.assertAlmostEqual(patches[0].area, ON_REFERENCE.area)

    def test_affected_control_whole_square_support_is_detected(self):
        # Baseline receipt: whole-square support retains the disjoint patch.
        # This test asserts the detector flags it, not that the behavior is right.
        support = baseline_support(self.cells)
        patches, _ = ch.additional_patches([ON_REFERENCE, OFF_REFERENCE], support, box(-20, -20, -10, -10))
        flagged = unsupported_patches(patches, REFERENCE)
        self.assertEqual(len(flagged), 1)
        self.assertEqual(measured_overlap_m2(flagged[0], REFERENCE), 0)
        self.assertEqual(flagged[0].bounds, OFF_REFERENCE.bounds)

    def test_cell_membership_only_is_not_measured_overlap(self):
        # Planning-cell context: the off-reference patch is inside the cell but
        # its measured overlap is zero, so it may only carry the context label.
        square = coverage.cell_geometry(CELL)
        self.assertTrue(square.contains(OFF_REFERENCE))
        self.assertEqual(measured_overlap_m2(OFF_REFERENCE, REFERENCE), 0)
        self.assertGreater(measured_overlap_m2(ON_REFERENCE, REFERENCE), 0)


if __name__ == '__main__':
    unittest.main()
