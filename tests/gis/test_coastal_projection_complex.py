"""RF2210-10: camera_projection refuses complex vertices instead of dropping imaginary parts."""
import math
import warnings
from unittest import mock

import numpy as np
import pytest

from skippercast.coastal.render import mesh

VERTS = [[0.0, 0.0, 1.0], [10.0, 0.0, 3.0], [0.0, 10.0, 2.0]]
FACES = np.array([[0, 1, 2]], dtype=np.int32)
COLORS = np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], dtype=np.uint8)
REFUSAL = "camera_real_vertices_required"


def _complex_cases():
    cases = {}
    for dtype in (np.complex64, np.complex128):
        for label, column in (("x", 0), ("y", 1), ("z", 2), ("all", slice(None))):
            arr = np.array(VERTS, dtype=dtype)
            arr[:, column] += 7j
            cases[f"{np.dtype(dtype).name}_{label}"] = arr
        cases[f"{np.dtype(dtype).name}_zero_imag"] = np.array(VERTS, dtype=dtype)
        nonfinite = np.array(VERTS, dtype=dtype)
        nonfinite[0, 0] = complex(1, np.nan)
        nonfinite[1, 1] = complex(2, np.inf)
        cases[f"{np.dtype(dtype).name}_nonfinite_imag"] = nonfinite
    cases["nested_list_zero_imag"] = [[complex(v, 0) for v in row] for row in VERTS]
    cases["nested_list_nonzero_imag"] = [[complex(v, 3) for v in row] for row in VERTS]
    return cases


COMPLEX = _complex_cases()


@pytest.mark.parametrize("name", list(COMPLEX))
def test_camera_refuses_complex_before_conversion(name):
    verts = COMPLEX[name]
    before = verts.copy() if isinstance(verts, np.ndarray) else [list(r) for r in verts]
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any ComplexWarning/lossy cast would fail the test
        with pytest.raises(ValueError, match=REFUSAL):
            mesh.camera_projection(verts)
    if isinstance(verts, np.ndarray):
        assert isinstance(before, np.ndarray)
        assert verts.dtype == before.dtype and verts.shape == before.shape
        assert verts.tobytes() == before.tobytes()
    else:
        assert verts == before


def test_refusal_precedes_conversion():
    with mock.patch.object(np, "asarray", side_effect=AssertionError("converted")):
        with pytest.raises(ValueError, match=REFUSAL):
            mesh.camera_projection(np.array(VERTS, dtype=np.complex128) + 1j)


@pytest.mark.parametrize("name", list(COMPLEX))
def test_render_refusal_preserves_target(name, tmp_path):
    verts = COMPLEX[name]
    existing = tmp_path / "keep.png"
    existing.write_bytes(b"sentinel")
    missing = tmp_path / "missing.png"
    faces_before, colors_before = FACES.copy(), COLORS.copy()
    mesh_in = {"vertices": verts, "faces": FACES, "colors": COLORS}
    for target in (existing, missing):
        with mock.patch.object(mesh, "write_png") as wp, \
                mock.patch.object(np, "full", side_effect=AssertionError("framebuffer")):
            with pytest.raises(ValueError, match=REFUSAL):
                mesh.render_png(mesh_in, target)
        wp.assert_not_called()
    assert existing.read_bytes() == b"sentinel"
    assert not missing.exists()
    assert np.array_equal(FACES, faces_before) and np.array_equal(COLORS, colors_before)


def test_face_validation_keeps_precedence_over_complex_refusal(tmp_path):
    verts = np.array(VERTS, dtype=np.complex128) + 1j
    bad = np.array([[0, 1, 9]], dtype=np.int32)
    with pytest.raises(ValueError, match="preview_faces_invalid"):
        mesh.render_png({"vertices": verts, "faces": bad, "colors": COLORS}, tmp_path / "x.png")


def _reference(vertices, exaggeration):
    pts = np.array(vertices, dtype=np.float64)
    pts[:, 2] *= exaggeration
    pts -= (pts.min(axis=0) + pts.max(axis=0)) / 2
    az, el = math.radians(35), math.radians(40)
    right = np.array([-math.cos(az), math.sin(az), 0.0])
    view = np.array([math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)])
    basis = np.stack((right, np.cross(view, right), view))
    proj = pts @ basis.T
    proj[:, :2] -= (proj[:, :2].min(axis=0) + proj[:, :2].max(axis=0)) / 2
    return proj, basis


@pytest.mark.parametrize("make", [
    lambda: np.array(VERTS, dtype=np.float64),
    lambda: np.array(VERTS, dtype=np.float32),
    lambda: np.array(VERTS, dtype=np.int64),
    lambda: [list(v) for v in VERTS],
    lambda: np.asfortranarray(np.array(VERTS, dtype=np.float64)),
    lambda: np.array([[x, 5.0, y, 5.0, z] for x, y, z in VERTS])[:, ::2],
])
@pytest.mark.parametrize("exaggeration", [1.0, 2.5])
def test_real_projection_compatibility(make, exaggeration):
    verts = make()
    proj, basis = mesh.camera_projection(verts, exaggeration)
    ref_proj, ref_basis = _reference(VERTS, exaggeration)
    assert np.allclose(proj, ref_proj) and np.allclose(basis, ref_basis)
    assert type(proj) is np.ndarray and proj.dtype == np.float64


def test_real_render_still_writes_png(tmp_path):
    out = tmp_path / "ok.png"
    info = mesh.render_png({"vertices": np.array(VERTS), "faces": FACES, "colors": COLORS}, out)
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert info["visible_pixels"] > 0


def test_real_input_errors_unchanged():
    with pytest.raises(ValueError, match="camera_xyz_vertices_required"):
        mesh.camera_projection(np.zeros((3, 2)))
    with pytest.raises(ValueError, match="camera_vertical_exaggeration_invalid"):
        mesh.camera_projection(np.array(VERTS), 0)
