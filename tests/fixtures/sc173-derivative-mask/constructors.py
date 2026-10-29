"""Portable synthetic arrays using the original coverage fixture vocabulary.

No files are generated here. Plane/bump formulas derive from
CoverageTests.test_plane_and_bump_have_expected_terrain_and_holes_stay_unknown.
"""


def grids(np):
    yy, xx = np.indices((21, 23))
    plane = 50 + .1 * xx + .2 * yy
    true = np.ones(plane.shape, dtype=bool)
    hole = true.copy()
    hole[10, 11] = False
    nonfinite = plane.copy()
    nonfinite[7, 7] = np.nan
    nonfinite[10, 10] = np.inf
    nonfinite[13, 13] = -np.inf
    view = np.ones((42, 46), dtype=bool)[::2, ::2]
    view[10, 11] = False
    bump = 50 - 10 * np.exp(-((xx - 11)**2 + (yy - 10)**2) / 30)
    return {
        'true': (plane, true),
        'false': (plane.copy(), np.zeros(plane.shape, dtype=bool)),
        'hole': (plane.copy(), hole),
        'nonfinite': (nonfinite, true.copy()),
        'view': (plane.copy(), view),
        'bump': (bump, true.copy()),
    }


def invalid_masks(np, shape):
    mixed = np.ones(shape, dtype=np.int64)
    mixed[0, 0] = 0
    mixed[10, 11] = 2
    return {
        'int_zero': np.zeros(shape, dtype=np.int64),
        'int_one': np.ones(shape, dtype=np.int64),
        'int_two': np.full(shape, 2, dtype=np.int64),
        'int_mixed': mixed,
        'uint_one': np.ones(shape, dtype=np.uint8),
        'float': np.ones(shape, dtype=np.float64),
        'object': np.ones(shape, dtype=object),
        'scalar_bool': np.array(True),
        'scalar_int': np.array(1),
        'python_bool': True,
        'list': np.ones(shape, dtype=bool).tolist(),
        'one_dimensional': np.ones(shape[0], dtype=bool),
        'three_dimensional': np.ones((*shape, 1), dtype=bool),
        'misaligned': np.ones((shape[0], shape[1] + 1), dtype=bool),
    }
