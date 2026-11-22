"""Offline controls for the Central census inventory extent comparison."""

from shapely.geometry import box

from scripts.relief.central_census_extent import compare_extent


def test_overlapping_boxes_fully_account_for_clipped_window():
    # Summing the clips double-counts the overlap; unioning without clipping
    # leaves area outside the fishing window.
    report = compare_extent([0, 0, 10, 10], [
        {'bounds': [-2, -1, 7, 11]},
        {'bounds': [3, 0, 12, 10]},
    ])

    assert report.inventory_extent.equals(box(0, 0, 10, 10))
    assert report.inventory_gap.is_empty
    assert report.unusable_box_indices == ()


def test_interior_inventory_gap_survives_full_union_bounds():
    # Replacing the union with its envelope would erase the interior gap.
    report = compare_extent([0, 0, 10, 10], [
        {'bounds': [0, 0, 10, 2]},
        {'bounds': [0, 8, 10, 10]},
        {'bounds': [0, 1, 2, 9]},
        {'bounds': [8, 1, 10, 9]},
    ])

    assert report.inventory_gap.equals(box(2, 2, 8, 8))


def test_unusable_boxes_are_flagged_but_valid_nonoverlapping_boxes_are_not():
    # Silent drops hide broken inventory rows. Normalizing reversed bounds can
    # also invent coverage, and edge touches must not add linework to the union.
    report = compare_extent([0, 0, 10, 10], [
        {'bounds': [-2, 1, 0, 5]},  # touches only
        {},
        {'bounds': [10, 0, 0, 10]},
        {'bounds': [11, 0, 12, 10]},  # disjoint
        {'bounds': ['0', 0, 10, 10]},
    ])

    assert report.unusable_box_indices == (1, 2, 4)
    assert report.inventory_extent.is_empty
    assert report.inventory_gap.equals(box(0, 0, 10, 10))
