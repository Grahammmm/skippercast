"""RF0520-7: camera_projection refuses NaN/inf vertices before projection arithmetic."""
import warnings
from unittest import mock

import numpy as np
import pytest

from skippercast.coastal.render import mesh

VERTS = [[0.0, 0.0, 1.0], [10.0, 0.0, 3.0], [0.0, 10.0, 2.0]]
FACES = np.array([[0, 1, 2]], dtype=np.int32)
COLORS = np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], dtype=np.uint8)
REFUSAL = "camera_finite_vertices_required"
BAD = {"nan": np.nan, "pinf": np.inf, "ninf": -np.inf}


def _cases():
    cases = {}
    for dtype in (np.float32, np.float64):
        for bname, bad in BAD.items():
            for row in (0, 1, 2):
                for col in (0, 1, 2):
                    arr = np.array(VERTS, dtype=dtype)
                    arr[row, col] = bad
                    cases[f"{np.dtype(dtype).name}_{bname}_{row}{col}"] = arr
    multi = np.array(VERTS)
    multi[0, 0], multi[2, 2] = np.nan, np.inf
    cases["multiple"] = multi
    cases["nested_list_nan"] = [[0.0, 0.0, 1.0], [float("nan"), 0.0, 3.0], [0.0, 10.0, 2.0]]
    cases["nested_list_inf"] = [[0.0, 0.0, 1.0], [10.0, float("inf"), 3.0], [0.0, 10.0, 2.0]]
    nc = np.zeros((3, 5))
    nc[:, ::2] = VERTS
    nc[1, 0] = np.nan
    cases["noncontiguous"] = nc[:, ::2]
    return cases


CASES = _cases()


def _snapshot(v):
    return (v.dtype, v.shape, v.tobytes()) if isinstance(v, np.ndarray) else [list(r) for r in v]


def _same(a, b):
    if isinstance(a, tuple):
        return a == b
    return all(np.array_equal(x, y, equal_nan=True) for x, y in zip(a, b))


@pytest.mark.parametrize("name", list(CASES))
def test_camera_refuses_nonfinite(name):
    verts = CASES[name]
    before = _snapshot(verts)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(ValueError, match=REFUSAL):
            mesh.camera_projection(verts)
        with pytest.raises(ValueError, match=REFUSAL):
            mesh.camera_projection(verts, 2.5)
    assert _same(before, _snapshot(verts))


def test_unused_nonfinite_vertex_is_not_ignored(tmp_path):
    verts = np.array(VERTS + [[np.nan, 1.0, 1.0]])
    with pytest.raises(ValueError, match=REFUSAL):
        mesh.camera_projection(verts)
    with pytest.raises(ValueError, match=REFUSAL):
        mesh.render_png({"vertices": verts, "faces": FACES, "colors": np.vstack([COLORS, COLORS[:1]])},
                        tmp_path / "x.png")


@pytest.mark.parametrize("name", ["float64_nan_10", "float64_pinf_22", "float32_ninf_01", "noncontiguous"])
def test_render_refuses_before_buffers_and_writes(name, tmp_path):
    verts = CASES[name]
    existing = tmp_path / "keep.png"
    existing.write_bytes(b"sentinel")
    missing = tmp_path / "missing.png"
    before = _snapshot(verts)
    faces_before, colors_before = FACES.copy(), COLORS.copy()
    for target in (existing, missing):
        with mock.patch.object(mesh, "write_png") as wp, \
                mock.patch.object(np, "full", side_effect=AssertionError("framebuffer")):
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                with pytest.raises(ValueError, match=REFUSAL):
                    mesh.render_png({"vertices": verts, "faces": FACES, "colors": COLORS}, target)
        wp.assert_not_called()
    assert existing.read_bytes() == b"sentinel"
    assert not missing.exists()
    assert _same(before, _snapshot(verts))
    assert np.array_equal(FACES, faces_before) and np.array_equal(COLORS, colors_before)


def test_earlier_errors_stay_earlier(tmp_path):
    bad = np.array(VERTS)
    bad[0, 0] = np.nan
    with pytest.raises(ValueError, match="preview_faces_invalid"):
        mesh.render_png({"vertices": bad, "faces": np.array([[0, 1, 9]], dtype=np.int32),
                         "colors": COLORS}, tmp_path / "x.png")
    with pytest.raises(ValueError, match="camera_unmasked_vertices_required"):
        mesh.camera_projection(np.ma.masked_invalid(bad))
    cplx = np.array(VERTS, dtype=np.complex128)
    cplx[0, 0] = complex(np.nan, 1)
    with pytest.raises(ValueError, match="camera_real_vertices_required"):
        mesh.camera_projection(cplx)
    wrong = np.full((3, 2), np.nan)
    with pytest.raises(ValueError, match="camera_xyz_vertices_required"):
        mesh.camera_projection(wrong)
    with pytest.raises(ValueError, match="camera_xyz_vertices_required"):
        mesh.camera_projection(np.empty((0, 3)))


@pytest.mark.parametrize("make", [
    lambda: np.array(VERTS, dtype=np.float64),
    lambda: np.array(VERTS, dtype=np.float32),
    lambda: np.array(VERTS, dtype=np.int64),
    lambda: [list(v) for v in VERTS],
    lambda: np.zeros((3, 3)),
    lambda: np.array([[x, 5.0, y, 5.0, z] for x, y, z in VERTS])[:, ::2],
])
@pytest.mark.parametrize("exaggeration", [1.0, 2.5])
def test_finite_controls_unchanged(make, exaggeration):
    verts = make()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        proj, basis = mesh.camera_projection(verts, exaggeration)
    pts = np.array(verts, dtype=np.float64)
    pts[:, 2] *= exaggeration
    pts -= (pts.min(axis=0) + pts.max(axis=0)) / 2
    # Independently pinned orthographic basis for azimuth 35, elevation 40.
    expected_basis = np.array([[-0.81915204, 0.57357644, 0.0],
                               [-0.36868783, -0.52654078, 0.76604444],
                               [0.43938504, 0.62750687, 0.64278761]])
    assert np.allclose(basis, expected_basis, atol=1e-6)
    ref = pts @ expected_basis.T
    ref[:, :2] -= (ref[:, :2].min(axis=0) + ref[:, :2].max(axis=0)) / 2
    assert np.allclose(proj, ref, atol=1e-6) and proj.dtype == np.float64
