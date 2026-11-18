"""D8-F01: native_support_by_zoom must carry a row for every attempted zoom."""
import unittest


def check_support_rows(support, minzoom, cap):
    """Same contract the gis test enforces: exactly one row per zoom in minzoom..cap."""
    expected = [str(z) for z in range(minzoom, cap + 1)]
    if sorted(support, key=int) != expected:
        raise AssertionError(f'support rows {sorted(support)} != attempted {expected}')
    for z, row in support.items():
        if row['tiles'] == 0 and row['sources']:
            raise AssertionError(f'zoom {z}: zero tiles but sources listed')


def row(tiles):
    return {'tiles': tiles, 'sources': [{'id': 'f', 'resolution_m': 1.0, 'tiles': tiles}] if tiles else []}


class SupportRowsTest(unittest.TestCase):
    def test_complete_rows_pass(self):
        check_support_rows({str(z): row(3) for z in range(13, 18)}, 13, 17)

    def test_lower_resolution_cap_passes(self):
        check_support_rows({str(z): row(3) for z in range(13, 16)}, 13, 15)

    def test_attempted_zero_support_level_passes(self):
        rows = {str(z): row(3) for z in range(13, 17)}
        rows['17'] = row(0)
        check_support_rows(rows, 13, 17)

    def test_missing_row_fails(self):
        rows = {str(z): row(3) for z in range(13, 18)}
        del rows['15']
        with self.assertRaises(AssertionError):
            check_support_rows(rows, 13, 17)

    def test_no_rows_fails(self):
        with self.assertRaises(AssertionError):
            check_support_rows({}, 13, 17)


if __name__ == '__main__':
    unittest.main()
