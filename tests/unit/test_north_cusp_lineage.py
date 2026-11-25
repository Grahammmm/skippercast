"""Synthetic controls at the decoded-run lineage boundary."""

from scripts.relief.north_cusp_lineage import report_lineage


WEST = '12/20/30'
EAST = '12/21/30'


def test_reversed_exact_run_is_duplicate_with_both_tile_ids():
    """Orientation-sensitive matching would miss the shared seam run."""
    assert report_lineage(WEST, [[[1, 0], [1, 2], [1, 5]]], EAST, [[[1, 5], [1, 2], [1, 0]]]) == {
        'tiles': (WEST, EAST), 'duplicates': [(0, 0)], 'neighbors': [],
    }


def test_endpoint_only_neighbor_is_not_suppressed_even_when_a_duplicate_exists():
    """A first-match exit or endpoint-based deduplication would lose the adjoining run."""
    west = [[(0, 2), (1, 2)]]
    east = [[(1, 2), (0, 2)], [(2, 3), (1, 2)]]
    assert report_lineage(WEST, west, EAST, east) == {
        'tiles': (WEST, EAST), 'duplicates': [(0, 0)], 'neighbors': [(0, 1)],
    }


def test_same_ends_do_not_make_a_near_equal_run_a_duplicate():
    """Comparing only terminals or rounding away a small interior change gives a false match."""
    west = [[(1, 0), (1, 2), (1, 5)]]
    east = [[(1, 5), (1.0000001, 2), (1, 0)]]
    assert report_lineage(WEST, west, EAST, east) == {
        'tiles': (WEST, EAST), 'duplicates': [], 'neighbors': [],
    }
