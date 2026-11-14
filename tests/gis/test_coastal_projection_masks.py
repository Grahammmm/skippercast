"""RF1155-8: camera_projection refuses masked vertex arrays instead of dropping the mask."""
import math
from unittest import mock

import numpy as np
import pytest

from skippercast.coastal.render import mesh

VERTS = [[0.0, 0.0, 1.0], [10.0, 0.0, 3.0], [0.0, 10.0, 2.0]]
FACES = np.array([[0, 1, 2]], dtype=np.int32)
COLORS = np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], dtype=np.uint8)


class SubMasked(np.ma.MaskedArray):
    pass


def _masks():
    data = np.array(VERTS)
    partial = np.ma.masked_array(data.copy(), mask=np.zeros((3, 3), bool))
    partial.mask[1, 2] = True
    row = np.ma.masked_array(data.copy(), mask=np.zeros((3, 3), bool))
    row.mask[2, :] = True
    nonfinite = np.ma.masked_array(data.copy(), mask=np.zeros((3, 3), bool))
    nonfinite.data[0, 0] = np.nan
    nonfinite.mask[0, 0] = True
    return {
        "partial": partial,
        "row": row,
        "all_true": np.ma.masked_array(data.copy(), mask=True),
        "all_false": np.ma.masked_array(data.copy(), mask=False),
        "nonfinite_hidden": nonfinite,
        "subclass": SubMasked(data.copy(), mask=False),
    }


@pytest.mark.parametrize("name", list(_masks()))
def test_camera_rejects_masked_before_conversion(name):
    verts = _masks()[name]
    before_data, before_mask = verts.data.copy(), np.ma.getmaskarray(verts).copy()
    with mock.patch.object(np, "asarray", side_effect=AssertionError("converted")):
        with pytest.raises(ValueError, match="camera_unmasked_vertices_required"):
            mesh.camera_projection(verts)
    assert np.array_equal(verts.data, before_data, equal_nan=True)
    assert np.array_equal(np.ma.getmaskarray(verts), before_mask)


@pytest.mark.parametrize("name", list(_masks()))
def test_render_refusal_preserves_target(name, tmp_path):
    verts = _masks()[name]
    existing = tmp_path / "keep.png"
    existing.write_bytes(b"sentinel")
    missing = tmp_path / "missing.png"
    faces_before = FACES.copy()
    mesh_in = {"vertices": verts, "faces": FACES, "colors": COLORS}
    for target in (existing, missing):
        with mock.patch.object(mesh, "write_png") as wp, \
                mock.patch.object(np, "full", side_effect=AssertionError("framebuffer")):
            with pytest.raises(ValueError, match="camera_unmasked_vertices_required"):
                mesh.render_png(mesh_in, target)
        wp.assert_not_called()
    assert existing.read_bytes() == b"sentinel"
    assert not missing.exists()
    assert np.array_equal(FACES, faces_before)


def test_face_validation_keeps_precedence_over_mask_refusal(tmp_path):
    verts = _masks()["all_false"]
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
    lambda: [list(v) for v in VERTS],
])
@pytest.mark.parametrize("exaggeration", [1.0, 2.5])
def test_unmasked_projection_compatibility(make, exaggeration):
    verts = make()
    proj, basis = mesh.camera_projection(verts, exaggeration)
    ref_proj, ref_basis = _reference(VERTS, exaggeration)
    assert np.allclose(proj, ref_proj) and np.allclose(basis, ref_basis)
    assert type(proj) is np.ndarray
    if isinstance(verts, np.ndarray):
        assert np.array_equal(verts, np.array(VERTS).astype(verts.dtype))


def test_old_errors_survive_for_unmasked_input():
    with pytest.raises(ValueError, match="camera_xyz_vertices_required"):
        mesh.camera_projection(np.zeros((3, 2)))
    with pytest.raises(ValueError, match="camera_vertical_exaggeration_invalid"):
        mesh.camera_projection(np.array(VERTS), 0)
