"""C1–C3: exercise the file boundary and the exact XYZ tile decision."""
from math import pi

import numpy as np
import pytest
import rasterio
from rasterio.shutil import copy as copy_raster
from rasterio.transform import Affine

from skippercast.relief.fine_proof import FineProof, FineProofError, read, write

SENTINEL = -9999.0


def lattice(zoom, x, y):
    half_world = pi * 6378137
    pitch = (2 * half_world) / (2 ** zoom)
    return Affine(pitch / 256, 0, -half_world + x * pitch,
                  0, -pitch / 256, half_world - y * pitch)


def bands(height=256, width=256):
    return np.broadcast_to(np.array([3., -10., 1.])[:, None, None], (3, height, width)).copy()


def refused(check, call, *args):
    with pytest.raises(FineProofError, match=check) as error:
        call(*args)
    assert type(error.value) is FineProofError


@pytest.mark.parametrize('zoom,rect,class_dtype', [
    pytest.param(16, (0, 65534, 1, 65535), 'int16', id='C1: z16 multi-tile raster'),
    pytest.param(17, (131071, 0, 131071, 0), 'float64', id='C2: z17 edge tile'),
])
def test_exact_persistence_and_decode(tmp_path, zoom, rect, class_dtype):
    # An independent rasterio reopen catches a shared scaling or band-order bug.
    x0, y0, x1, y1 = rect
    height, width = 256 * (y1 - y0 + 1), 256 * (x1 - x0 + 1)
    raw = bands(height, width)
    raw[:, 0, :5] = [
        [0, 1, 2, 3, SENTINEL],
        [0, -20, -10.1234567890123, -0.25, SENTINEL],
        [1, 0.3333333333333333, 0.125, 1, SENTINEL],
    ]
    path = tmp_path / 'proof.tif'
    assert write(path, zoom, x0, y0, x1, y1, raw[0].astype(class_dtype), raw[1], raw[2]) is None
    assert list(tmp_path.iterdir()) == [path]
    mask = np.ones((height, width), dtype=bool)
    mask[0, 4] = False
    with rasterio.open(path) as ds:
        assert ds.files == [str(path)]
        assert ds.driver == 'GTiff'
        assert ds.crs.to_epsg() == 3857
        assert (ds.height, ds.width, ds.count) == (height, width, 3)
        assert ds.transform == lattice(zoom, x0, y0)
        tags = ds.tags()
        assert (tags.get('sc_fine_proof'), tags.get('zoom')) == ('1', str(zoom))
        assert ds.dtypes == ('float64',) * 3
        assert ds.scales == (1.0,) * 3
        assert ds.offsets == (0.0,) * 3
        assert ds.nodatavals == (SENTINEL,) * 3
        np.testing.assert_array_equal(ds.read_masks(), np.broadcast_to(mask, raw.shape) * 255)
        np.testing.assert_array_equal(ds.read(), raw)
    proof = read(path)
    assert (proof.zoom, proof.x0, proof.y0, proof.x1, proof.y1) == (zoom, *rect)
    assert (proof.cls.dtype, proof.elev.dtype, proof.spacing.dtype, proof.proven.dtype) == (
        np.dtype('uint8'), np.dtype('float64'), np.dtype('float64'), np.dtype('bool'),
    )
    expected_cls = np.full((height, width), 3, dtype='uint8')
    expected_cls[0, :5] = [0, 1, 2, 3, 0]
    np.testing.assert_array_equal(proof.cls, expected_cls)
    np.testing.assert_array_equal(proof.elev, raw[1])
    np.testing.assert_array_equal(proof.spacing, raw[2])
    np.testing.assert_array_equal(proof.proven, mask)


@pytest.mark.parametrize('options,check', [
    pytest.param((15, 2, 3, 2, 3), 'zoom', id='C1: z15 is not a fine zoom'),
    pytest.param((16.0, 2, 3, 2, 3), 'zoom', id='C1: zoom must be integral'),
    pytest.param((16, -1, 3, -1, 3), 'XYZ rectangle', id='C1: x before grid'),
    pytest.param((16, 2, -1, 2, -1), 'XYZ rectangle', id='C1: y before grid'),
    pytest.param((16, 65536, 3, 65536, 3), 'XYZ rectangle', id='C1: x beyond grid'),
    pytest.param((17, 2, 131072, 2, 131072), 'XYZ rectangle', id='C1: y beyond grid'),
    pytest.param((16, 2, 3, 1, 3), 'XYZ rectangle', id='C1: reversed rectangle'),
    pytest.param((16, 2.25, 3, 2.25, 3), 'XYZ rectangle', id='C1: fractional tile index'),
    pytest.param((16, 2, 3, 3, 3), 'class shape', id='C1: whole rectangle determines dimensions'),
])
def test_writer_refuses_invalid_grid_before_storage(tmp_path, options, check):
    path = tmp_path / 'proof.tif'
    refused(check, write, path, *options, *bands())
    assert not path.exists()


@pytest.mark.parametrize('band,replacement,check', [
    pytest.param(1, np.zeros((256, 255)), 'elevation shape', id='C1: mismatched band shape'),
    pytest.param(2, np.full((256, 256), '1'), 'spacing samples', id='C1: no string coercion'),
    pytest.param(0, np.ma.array(np.full((256, 256), 3), mask=True), 'class mask',
                 id='C1: concealed evidence needs explicit sentinel triples'),
])
def test_writer_refuses_invalid_band_before_storage(tmp_path, band, replacement, check):
    path = tmp_path / 'proof.tif'
    inputs = list(bands())
    inputs[band] = replacement
    refused(check, write, path, 16, 2, 3, 2, 3, *inputs)
    assert not path.exists()


@pytest.mark.parametrize('direction,check', [
    pytest.param(2, 'spacing must be in', id='C1: no narrowing into range'),
    pytest.param(0, 'exactly representable', id='C1: no rounding evidence'),
])
def test_writer_checks_wider_input_precision(tmp_path, direction, check):
    if np.finfo(np.longdouble).nmant == np.finfo(np.float64).nmant:
        pytest.skip('platform has no floating dtype wider than float64')
    path = tmp_path / 'proof.tif'
    cls, elev, spacing = bands()
    spacing = spacing.astype(np.longdouble)
    spacing[0, 0] = np.nextafter(np.longdouble(1), np.longdouble(direction))
    refused(check, write, path, 16, 2, 3, 2, 3, cls, elev, spacing)
    assert not path.exists()


def tiff(path, raw=None, *, tags=None, valid_mask=None, scales=None, offsets=None, **overrides):
    """Build independent on-disk controls, including states write() cannot emit."""
    profile: dict = dict(driver='GTiff', width=256, height=256, count=3, dtype='float64',
                   crs='EPSG:3857', transform=lattice(16, 2, 3), nodata=SENTINEL)
    profile.update(overrides)
    if raw is None:
        raw = bands(profile['height'], profile['width'])[:profile['count']]
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), rasterio.open(path, 'w', **profile) as ds:
        ds.write(raw.astype(profile['dtype']))
        ds.update_tags(**({'sc_fine_proof': '1', 'zoom': '16'} if tags is None else tags))
        if scales is not None:
            ds.scales = scales
        if offsets is not None:
            ds.offsets = offsets
        if valid_mask is not None:
            ds.write_mask(valid_mask)


@pytest.mark.parametrize('overrides,check', [
    pytest.param({'tags': {'zoom': '16'}}, 'sc_fine_proof', id='C2: missing format tag'),
    pytest.param({'tags': {'zoom': '16', 'sc_fine_proof': '2'}}, 'sc_fine_proof', id='C2: unknown format'),
    pytest.param({'tags': {'sc_fine_proof': '1'}}, 'zoom tag', id='C2: missing zoom'),
    pytest.param({'tags': {'sc_fine_proof': '1', 'zoom': '15'}, 'transform': lattice(15, 2, 3)},
                 'zoom tag', id='C2: z15 refused even with its own lattice'),
    pytest.param({'crs': 'EPSG:4326'}, 'CRS', id='C2: wrong CRS'),
    pytest.param({'width': 255}, 'dimensions', id='C2: partial tile width'),
    pytest.param({'height': 257}, 'dimensions', id='C2: partial tile height'),
    pytest.param({'transform': lattice(16, 65536, 3)}, 'XYZ rectangle', id='C2: lattice origin outside world'),
    pytest.param({'transform': lattice(16, 2, 65535), 'height': 512}, 'XYZ rectangle',
                 id='C2: aligned raster extends past world'),
    pytest.param({'transform': lattice(16, 2.5, 3)}, 'origin', id='C2: half-tile offset'),
    pytest.param({'transform': Affine.translation(0, 1.1e-6) @ lattice(16, 2, 3)}, 'origin',
                 id='C2: absolute tolerance rejects subpixel y shift'),
    pytest.param({'transform': Affine.translation(np.nan, 0) @ lattice(16, 2, 3)}, 'origin',
                 id='C2: nonfinite origin'),
    pytest.param({'transform': lattice(16, 2, 3) @ Affine.scale(1, -1)}, 'north-up', id='C2: south-up axis'),
    pytest.param({'transform': lattice(16, 2, 3) @ Affine.shear(0.000001, 0)}, 'rotation/skew',
                 id='C2: nonzero skew is not tolerated'),
    pytest.param({'transform': lattice(16, 2, 3) @ Affine.scale(1, 1.01)}, 'pixel sizes', id='C2: wrong y resolution'),
    pytest.param({'transform': lattice(16, 2, 3) @ Affine.scale(1.01, 1)}, 'pixel sizes', id='C2: wrong x resolution'),
    pytest.param({'count': 2}, 'three Float64 bands', id='C2: missing band'),
    pytest.param({'dtype': 'float32'}, 'three Float64 bands', id='C2: wrong storage dtype'),
    pytest.param({'scales': (1, 2, 1)}, 'scale/offset', id='C2: nonidentity scale'),
    pytest.param({'offsets': (0, 0, 1)}, 'scale/offset', id='C2: nonidentity offset'),
    pytest.param({'nodata': -9998}, 'nodata metadata', id='C2: incorrect nodata metadata'),
    pytest.param({'nodata': None}, 'nodata metadata', id='C2: missing nodata metadata'),
])
def test_reader_refuses_invalid_metadata(tmp_path, overrides, check):
    path = tmp_path / 'proof.tif'
    tiff(path, **overrides)
    refused(check, read, path)


@pytest.mark.parametrize('case', [pytest.param('vrt', id='C2: GTiff driver required'),
                                 pytest.param('missing', id='C2: unreadable raster')])
def test_reader_refuses_non_geotiff(tmp_path, case):
    path = tmp_path / 'proof.tif'
    if case == 'vrt':
        tiff(path)
        vrt = tmp_path / 'proof.vrt'
        copy_raster(path, vrt, driver='VRT')
        refused('driver', read, vrt)
    else:
        refused('raster read failed', read, path)


@pytest.mark.parametrize('zoom', [pytest.param(16, id='C2: tolerate sub-micrometre affine noise')])
def test_reader_recovers_grid_from_canonical_pitch(tmp_path, zoom):
    path = tmp_path / 'proof.tif'
    t = lattice(zoom, 12223, 23781)
    moved = type(t)(t.a + 0.9e-6, 0, t.c + 0.9e-6, 0, t.e - 0.9e-6, t.f - 0.9e-6)
    # With small pixel-size noise, dividing the origin by file resolution
    # instead of the canonical pitch can yield the wrong tile index.
    tiff(path, transform=moved)
    proof = read(path)
    assert (proof.zoom, proof.x0, proof.y0, proof.x1, proof.y1) == (16, 12223, 23781, 12223, 23781)


BAD_SAMPLES = [
    ('partial class sentinel', 0, SENTINEL, 'partial nodata'),
    ('partial elevation sentinel', 1, SENTINEL, 'partial nodata'),
    ('partial spacing sentinel', 2, SENTINEL, 'partial nodata'),
    ('NaN elevation', 1, np.nan, 'nonfinite'),
    ('infinite spacing', 2, np.inf, 'nonfinite'),
    ('fractional class', 0, 3 - 2**-51, 'class'),
    ('negative class', 0, -1, 'class'),
    ('unknown class', 0, 4, 'class'),
    ('too deep', 1, np.nextafter(-20., -np.inf), 'elevation'),
    ('above water', 1, 0.01, 'elevation'),
    ('zero spacing', 2, 0, 'spacing'),
    ('negative spacing', 2, -0.01, 'spacing'),
    ('too coarse', 2, np.nextafter(1., np.inf), 'spacing'),
]


@pytest.mark.parametrize('band,value,check', [pytest.param(i, v, c, id=label) for label, i, v, c in BAD_SAMPLES])
@pytest.mark.parametrize('which', [pytest.param('write', id='C1: writer'), pytest.param('read', id='C2: reader')])
def test_rejects_malformed_raw_sample(tmp_path, which, band, value, check):
    path = tmp_path / 'proof.tif'
    raw = bands()
    raw[band, 255, 255] = value
    # One bad raw cell must be refused rather than cast, clipped or dropped.
    if which == 'write':
        refused(check, write, path, 16, 2, 3, 2, 3, *raw)
        assert not path.exists()
    else:
        tiff(path, raw)
        refused(check, read, path)


@pytest.mark.parametrize('missing', [pytest.param(True, id='C2: mask exposes nodata'),
                                    pytest.param(False, id='C2: mask hides valid samples')])
def test_reader_rejects_mask_disagreement(tmp_path, missing):
    path = tmp_path / 'proof.tif'
    raw = bands()
    mask = np.full((256, 256), 255, dtype='uint8')
    if missing:
        raw[:, 0, 0] = SENTINEL
    else:
        mask[0, 0] = 0
    tiff(path, raw, valid_mask=mask)
    refused('mask disagrees', read, path)


@pytest.mark.parametrize('band', [pytest.param(3, id='C2: validate even the last band mask')])
def test_reader_checks_each_band_mask(tmp_path, band):
    path = tmp_path / 'proof.tif'
    tiff(path)
    # GDAL's per-band mask layout: only spacing disagrees, so checking the
    # class mask or the combined dataset mask would miss the defect.
    mask = np.full((3, 256, 256), 255, dtype='uint8')
    mask[band - 1, 0, 0] = 0
    with rasterio.open(path.with_suffix('.tif.msk'), 'w', driver='GTiff', width=256, height=256,
                       count=3, dtype='uint8', crs='EPSG:3857', transform=lattice(16, 2, 3)) as ds:
        ds.write(mask)
        ds.update_tags(INTERNAL_MASK_FLAGS_1='0', INTERNAL_MASK_FLAGS_2='0', INTERNAL_MASK_FLAGS_3='0')
    with rasterio.open(path) as ds:
        np.testing.assert_array_equal(ds.read_masks(), mask)
    refused(f'band {band} mask disagrees', read, path)


@pytest.mark.parametrize('zoom', [pytest.param(17, id='C3: tile-local all-pixel decision')])
def test_certified_checks_exact_tile_slice(tmp_path, zoom):
    path = tmp_path / 'proof.tif'
    raw = bands(512, 512)
    raw[1, 0, 0] = -20
    raw[1, 255, 255] = 0
    raw[:, 255, 511] = SENTINEL
    raw[0, 511, 255] = 2
    write(path, zoom, 8, 9, 9, 10, *raw)
    proof = read(path)
    assert proof.certified(17, 8, 9) is True
    assert proof.certified(17, 9, 9) is False  # one unproven pixel
    assert proof.certified(17, 8, 10) is False  # one non-3 class
    assert proof.certified(17, 9, 10) is True
    assert proof.certified(16, 8, 9) is False
    assert proof.certified(17, 7, 9) is False
    assert proof.certified(17, 10, 9) is False
    assert proof.certified(17, 8, 8) is False
    assert proof.certified(17, 8, 11) is False
    assert proof.certified(17, 8.5, 9) is False


@pytest.mark.parametrize('band,value', [
    pytest.param(1, -20.01, id='C3: one too-deep pixel vetoes the tile'),
    pytest.param(1, 0.01, id='C3: one above-water pixel vetoes the tile'),
    pytest.param(2, 1.01, id='C3: one too-coarse pixel vetoes the tile'),
    pytest.param(3, False, id='C3: the proven mask vetoes otherwise qualifying values'),
])
def test_certified_checks_decoded_values(band, value):
    # Evaluate the predicate in isolation: C1 and C2 already reject these samples.
    raw = list(bands()) + [np.ones((256, 256), bool)]
    raw[band][255, 255] = value
    proof = FineProof(16, 2, 3, 2, 3, raw[0].astype('uint8'), *raw[1:])
    assert proof.certified(16, 2, 3) is False
