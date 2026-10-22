"""Synthetic support-topology controls independent of the triangulation helper."""
from itertools import product

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from skippercast.coastal.handoff.common import ref, write
from skippercast.coastal.render import mesh as textured
from skippercast.coastal.render import terrain_demo, terrain_only
from tests.gis.test_render_terrain_triangulation import normalized_terrain
from tests.gis.test_render_deep_datum_warnings import NOW, accepted


def image(root, shape, *, finer=False, void=False):
    factor = 4 if finer else 1
    transform = from_origin(1000, 2000, 2/factor, 2/factor)
    h, w = (n*factor for n in shape)
    path = root/'imagery.tif'
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
        with rasterio.open(path, 'w', driver='GTiff', width=w, height=h, count=3,
                           dtype='uint8', crs='EPSG:26911', transform=transform) as ds:
            ds.write(np.full((3, h, w), 150, dtype='uint8'))
            valid = np.full((h, w), 255, dtype='uint8')
            if void:
                valid[4, 4] = 0  # between measured sample centres, not at a vertex
            ds.write_mask(valid)
    return path


@pytest.mark.parametrize('bits', list(product((False, True), repeat=4)))
def test_all_sixteen_quad_support_patterns(bits):
    valid = np.array(bits).reshape(2, 2)
    index = np.where(valid, np.arange(4).reshape(2, 2), -1)
    faces = textured.supported_triangles(index)
    n = sum(bits)
    assert len(faces) == (2 if n == 4 else 1 if n == 3 else 0)
    if n == 4:
        assert faces.tolist() == [[0, 2, 1], [1, 2, 3]]
    elif n == 3:
        assert set(faces[0]) == set(np.flatnonzero(valid))
        xy = np.array([[0, 0], [1, 0], [0, -1], [1, -1]])[faces[0]]
        a, b = xy[1]-xy[0], xy[2]-xy[0]
        assert a[0]*b[1]-a[1]*b[0] > 0
    assert faces.shape == (len(faces), 3)
    assert (faces >= 0).all()


@pytest.mark.parametrize('missing', range(4))
def test_both_raster_builders_keep_every_three_corner_orientation(tmp_path, missing):
    valid = np.ones((2, 2), bool)
    valid.flat[missing] = False
    document = normalized_terrain(tmp_path, np.full((2, 2), 20.0), valid)
    diagnostic = terrain_only.build_terrain(tmp_path, document)
    texture = textured.build_mesh(tmp_path/'terrain.tif', tmp_path/'mask.tif',
                                 image(tmp_path, valid.shape), document['vertical'])
    for built in (diagnostic, texture):
        assert built['faces'].shape == (1, 3)
        assert set(built['faces'][0]) == {0, 1, 2}
        assert built['meshed_support_cells'] == 3
        assert built['unmeshed_support_cells'] == 0
        assert np.array_equal(built['support'], valid)
        assert np.array_equal(built['grid_pixels'], np.argwhere(valid)[:, ::-1])


@pytest.mark.parametrize('bits', [(True, False, False, True), (False, True, True, False),
                                 (True, True, False, False), (True, False, False, False)])
def test_fewer_than_three_corners_do_not_bridge_a_gap(tmp_path, bits):
    valid = np.array(bits).reshape(2, 2)
    document = normalized_terrain(tmp_path, np.full((2, 2), 20.0), valid)
    with pytest.raises(ValueError, match='^no_measured_triangles$'):
        terrain_only.build_terrain(tmp_path, document)
    with pytest.raises(ValueError, match='^no_measured_triangles$'):
        textured.build_mesh(tmp_path/'terrain.tif', tmp_path/'mask.tif',
                            image(tmp_path, valid.shape), document['vertical'])


def test_isolated_sounding_is_reported_in_mesh_receipt_and_demo(tmp_path):
    valid = np.zeros((4, 5), bool)
    valid[:2, :2] = True
    valid[3, 4] = True
    document = normalized_terrain(tmp_path, np.full(valid.shape, 20.0), valid)
    result = terrain_only.preview(tmp_path, accepted(tmp_path, document), output_dir='preview', now=NOW)
    assert result['support_cells'] == result['vertices'] == 5
    assert result['meshed_support_cells'] == 4
    assert result['unmeshed_support_cells'] == 1
    receipt_ref = ref(tmp_path, 'preview/render-receipt.json', terrain_only.RESULT)
    payload = terrain_demo.payload(tmp_path, receipt_ref)
    assert payload['metadata']['meshed_support_cells'] == 4
    assert payload['metadata']['unmeshed_support_cells'] == 1
    demo = terrain_demo.build_demo(tmp_path, receipt_ref, output_dir='demo')
    assert demo['unmeshed_support_cells'] == 1
    # Otherwise-valid receipt, with its hash refreshed: isolate accounting validation.
    result['unmeshed_support_cells'] = 0
    write(tmp_path/'preview/render-receipt.json', result)
    with pytest.raises(ValueError, match='^mesh_support_counts_mismatch$'):
        terrain_demo.payload(tmp_path, ref(tmp_path, 'preview/render-receipt.json', terrain_only.RESULT))


def test_demo_accepts_new_triangle_but_rejects_the_old_missing_face(tmp_path):
    valid = np.ones((4, 4), bool)
    valid[1, 0] = False
    depth = np.full(valid.shape, 20.0)
    depth[0, 0] = 2
    document = normalized_terrain(tmp_path, depth, valid)
    result = terrain_only.preview(tmp_path, accepted(tmp_path, document), output_dir='preview', now=NOW)
    receipt_ref = ref(tmp_path, 'preview/render-receipt.json', terrain_only.RESULT)
    payload = terrain_demo.payload(tmp_path, receipt_ref)
    assert any(0 in face for face in payload['faces'])
    built = terrain_only.build_terrain(tmp_path, document)
    built['faces'] = built['faces'][~(built['faces'] == 0).any(axis=1)]
    terrain_only.save_mesh(tmp_path/'preview/terrain-mesh.npz', built)
    result['triangles'] = len(built['faces'])
    result['meshed_support_cells'] -= 1
    result['unmeshed_support_cells'] += 1
    result['artifacts'][0] = ref(tmp_path, 'preview/terrain-mesh.npz', 'coastal-terrain-only-mesh-v1')
    write(tmp_path/'preview/render-receipt.json', result)
    with pytest.raises(ValueError, match='^mesh_supported_triangles_mismatch$'):
        terrain_demo.payload(tmp_path, ref(tmp_path, 'preview/render-receipt.json', terrain_only.RESULT))


def test_imagery_exclusions_are_in_unmeshed_sample_count(tmp_path):
    valid = np.ones((3, 3), bool)
    document = normalized_terrain(tmp_path, np.full(valid.shape, 20.0), valid)
    built = textured.build_mesh(tmp_path/'terrain.tif', tmp_path/'mask.tif',
                               image(tmp_path, valid.shape, finer=True, void=True), document['vertical'])
    assert built['imagery_mask_excluded_triangles'] == 2
    assert built['meshed_support_cells'] == 8
    assert built['unmeshed_support_cells'] == 1
    assert set(built['faces'].ravel()) == set(range(1, 9))
