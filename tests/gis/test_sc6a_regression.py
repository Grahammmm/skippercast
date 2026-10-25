"""Real build_mesh regressions. Configure an explicit fresh data root in the runner."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

DATA_ROOT = None


def load_factory():
    path = Path(__file__).resolve().parents[1] / 'fixtures' / 'sc6a' / 'factory.py'
    spec = importlib.util.spec_from_file_location('sc6a_factory', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.make_grid


class MeshIntegerTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        from skippercast.coastal.render import mesh
        self.np, self.mesh = np, mesh
        base = Path(DATA_ROOT) if DATA_ROOT is not None else Path(tempfile.mkdtemp(prefix='sc6a-'))
        self.root = base / self._testMethodName
        self.root.mkdir(parents=True, exist_ok=False)
        self.make_grid = load_factory()

    def build(self, grid, sign='positive_up'):
        # Byte equality includes original masks, nodata and header metadata even on error.
        paths = grid['paths']
        before = {path: path.read_bytes() for path in paths}
        try:
            return self.mesh.build_mesh(*paths, dict(units='m', sign=sign, datum='MSL', conflicts=[]))
        finally:
            for path, original in before.items():
                self.assertEqual(path.read_bytes(), original, f'input changed: {path.name}')

    def geometry(self, result, grid, sign):
        np = self.np
        rows, cols = np.nonzero(grid['valid'])
        np.testing.assert_array_equal(result['support'], grid['valid'])
        np.testing.assert_array_equal(result['grid_pixels'], np.c_[cols, rows])
        t = grid['transform']
        z = grid['values'][rows, cols].astype('float64')
        if sign == 'positive_down':
            z = -z
        expected = np.c_[t.c + (cols + .5) * t.a, t.f + (rows + .5) * t.e, z]
        np.testing.assert_array_equal(result['vertices'], expected)
        np.testing.assert_array_equal(result['colors'], grid['rgb'][:, rows, cols].T)
        self.assertEqual(result['vertices'].dtype, np.dtype('float64'))
        self.assertTrue(np.isfinite(result['vertices']).all())
        self.assertEqual(float(result['vertices'][0, 2]), 0.0)
        self.assertFalse(any(np.array_equal(p, [2, 2]) for p in result['grid_pixels']))
        actual = {tuple(sorted(tuple(result['grid_pixels'][i]) for i in face))
                  for face in result['faces']}
        expected_faces = set()
        for r in range(4):
            for c in range(4):
                for cells in (((c, r), (c, r + 1), (c + 1, r)),
                              ((c + 1, r), (c, r + 1), (c + 1, r + 1))):
                    if all(grid['valid'][y, x] for x, y in cells):
                        expected_faces.add(tuple(sorted(cells)))
        self.assertTrue(actual)
        self.assertEqual(actual, expected_faces)
        self.assertEqual(len(result['faces']), len(actual))

    def parity(self, dtype, sign):
        options = dict(unsigned_samples=dtype == 'uint16')
        integer = self.make_grid(self.root / 'integer', dtype, **options)
        floating = self.make_grid(self.root / 'float', 'float32', **options)
        # Run the positive first: a broken integer fill must not hide float compatibility.
        other = self.build(floating, sign)
        self.geometry(other, floating, sign)
        actual = self.build(integer, sign)
        self.geometry(actual, integer, sign)
        for key in ('vertices', 'grid_pixels', 'faces', 'colors', 'support'):
            self.np.testing.assert_array_equal(actual[key], other[key])

    def test_int16_positive_up_parity(self):
        self.parity('int16', 'positive_up')

    def test_int16_positive_down_parity(self):
        self.parity('int16', 'positive_down')

    def test_uint16_positive_up_parity(self):
        self.parity('uint16', 'positive_up')

    def test_uint16_positive_down_parity(self):
        self.parity('uint16', 'positive_down')

    def test_float32_positive_control(self):
        grid = self.make_grid(self.root / 'grid', 'float32')
        self.geometry(self.build(grid), grid, 'positive_up')

    def test_float64_nonfinite_excluded(self):
        grid = self.make_grid(self.root / 'grid', 'float64', nonfinite=True)
        self.geometry(self.build(grid), grid, 'positive_up')

    def test_fully_masked_integer_refuses(self):
        grid = self.make_grid(self.root / 'grid', 'int16', fully_masked=True)
        with self.assertRaisesRegex(ValueError, '^no_measured_support$'):
            self.build(grid)

    def test_fully_masked_float_refuses(self):
        grid = self.make_grid(self.root / 'grid', 'float32', fully_masked=True)
        with self.assertRaisesRegex(ValueError, '^no_measured_support$'):
            self.build(grid)

    def test_nonbinary_support_refuses(self):
        grid = self.make_grid(self.root / 'grid', 'int16', nonbinary=True)
        with self.assertRaisesRegex(ValueError, '^binary_support_required$'):
            self.build(grid)

    def test_packed_scale_refuses(self):
        grid = self.make_grid(self.root / 'grid', 'int16', scale=0.5)
        with self.assertRaisesRegex(ValueError, '^unapplied_terrain_packing$'):
            self.build(grid)

    def test_packed_offset_refuses(self):
        grid = self.make_grid(self.root / 'grid', 'int16', offset=10.0)
        with self.assertRaisesRegex(ValueError, '^unapplied_terrain_packing$'):
            self.build(grid)


if __name__ == '__main__':
    unittest.main()
