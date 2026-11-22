"""Compare supplied North CUSP receipt bytes with the offline tile plan."""

from collections.abc import Iterable


def compare_observed_cost(plan: dict, receipts: Iterable[dict]) -> dict:
    """Compare a tile_plan report with importer-shaped {'tile', 'bytes'} rows.

    Extra tiles are reported separately and do not contribute to the total.
    If an expected tile is missing, the total is None, not a partial sum.
    This checks coverage and counts, not payload authenticity or admission.
    """
    expected = set(plan['expected_tile_ids'])
    observed = {}
    for row in receipts:
        tile, size = row['tile'], row['bytes']
        if not isinstance(tile, str) or not tile:
            raise ValueError('tile ID must be a nonempty string')
        if type(size) is not int or size < 0:
            raise ValueError('observed bytes must be a nonnegative integer')
        if tile in observed:
            raise ValueError(f'duplicate receipt for tile {tile}')
        observed[tile] = size

    missing = expected - observed.keys()
    return {
        'worst_case_bytes': plan['worst_case_bytes'],
        'observed_bytes': None if missing else sum(observed[tile] for tile in expected),
        'missing_tile_ids': sorted(missing),
        'extra_tile_ids': sorted(observed.keys() - expected),
    }
