"""SCA-592/SCA-445: a shoal component is not its bounding box.

Run this module with the survey stack to replay the original audit controls.
"""
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

POINTS = {(14, 14), (14, 15), (15, 14)}  # row, column
CORNER = (15, 15)
BBOX = [14, 14, 16, 16]  # col0, row0, col1, row1 (exclusive)
CODE = 'measured-suspect-shoal'


def _apply(root, points, *, wrong_count=None):
    import numpy as np
    from scripts import ec_apply, ec_detect
    from skippercast.platform import seafloor_ec as ec
    from tests.gis.test_ec_apply import _detect, _read, _tif

    elevations = np.full((32, 32), -20, dtype='float32')
    for point in points:
        elevations[point] = -4
    # Use the detector's real component finder. Build the envelope with the
    # existing EC2 helper rather than relaxing EC1's tiny-fixture refusal.
    pits, clusters, spikes = ec_detect.find_outliers(elevations, elevations < 0)
    assert not pits and not clusters
    spike, = spikes
    assert (spike['bbox'], spike['cells']) == (BBOX, len(points))
    if wrong_count == 'component':
        spike['cells'] -= 1  # same input bytes and bounding box, inconsistent count
    grid = _tif(root / 'grid.tif', elevations)
    detect = _detect(grid, root, holes=[], pits=[], spikes=spikes, disposition='VERIFY',
                     counts={CODE: spike['cells'] - (wrong_count == 'total'),
                             'measured': elevations.size - spike['cells']},
                     duplicate_signature=[32, 32, 'EPSG:32610', 2.0, -20, -4, float(elevations.mean())])
    inputs = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (grid, detect)}
    out = root / 'applied'
    try:
        receipt, _ = ec_apply.apply(grid, detect, out)
    except ec_apply.Refused as error:
        assert not out.exists(), 'refusal must not write any output'
        return str(error)
    finally:
        assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs} == inputs
    corrected, _, _ = _read(out / 'corrected.tif')
    codes, _, _ = _read(out / 'provenance.tif')
    np.testing.assert_array_equal(corrected, elevations)  # no smoothing, even on shoals
    assert np.isin(codes, [ec.CODES['measured'], ec.CODES[CODE]]).all()
    return {(r, c) for r, c in np.argwhere(codes == ec.CODES[CODE]).tolist()}, receipt['counts'][CODE]


@pytest.mark.gis
@pytest.mark.parametrize('points', [POINTS | {CORNER}, POINTS], ids=['filled-box', 'l-shape'])
def test_marks_only_detected_shoals_without_changing_depths(tmp_path, points):
    # Bounding-box painting would mark CORNER suspect in the L-shaped case.
    assert _apply(tmp_path, points) == (points, len(points))


@pytest.mark.gis
@pytest.mark.parametrize('wrong_count, reason', [('component', 'component bboxes or cell counts'),
                                                ('total', 'suspect-shoal total')])
def test_refuses_inconsistent_shoal_counts(tmp_path, wrong_count, reason):
    # Neither matching input bytes nor matching aggregate counts prove component membership.
    actual = _apply(tmp_path, POINTS, wrong_count=wrong_count)
    assert isinstance(actual, str) and reason in actual


def _baseline(root):
    expected = {'filled-box': (POINTS | {CORNER}, 4), 'l-shape': (POINTS, 3), 'bad-count': None}
    gap = False
    for case, wanted in expected.items():
        case_dir = root / case
        case_dir.mkdir()
        actual = _apply(case_dir, POINTS | {CORNER} if case == 'filled-box' else POINTS,
                        wrong_count='component' if case == 'bad-count' else None)
        if wanted is None:
            ok = isinstance(actual, str) and ('spike' in actual.lower() or 'shoal' in actual.lower())
            print(f'{case}: {"PASS" if ok else "GAP"}; expected component-count refusal, observed {actual}')
        else:
            ok = actual == wanted
            print(f'{case}: {"PASS" if ok else "GAP"}; expected members={sorted(wanted[0])}, '
                  f'count={wanted[1]}; observed {actual}')
        if case == 'filled-box':
            assert ok, 'valid control failed'
        gap |= not ok
    return int(gap)


if __name__ == '__main__':
    with TemporaryDirectory(prefix='f21-12-') as scratch:
        raise SystemExit(_baseline(Path(scratch)))
