"""Native ft-v3 window and seam contracts on synthetic GeoTIFFs."""
from contextlib import ExitStack

import pytest

pytestmark = pytest.mark.gis
CELL = 2
PAD = 8
COMMON = {'source_id': 'wet-band', 'survey_date': '2024-01-01', 'vertical_datum': 'MLLW'}


class RecordingReader:
    def __init__(self, dataset):
        self.dataset = dataset
        self.reads = []

    def __getattr__(self, name):
        return getattr(self.dataset, name)

    def read(self, band, *, window, masked):
        # Deliberately no resampling arguments; each request is a native read.
        self.reads.append(window)
        return self.dataset.read(band, window=window, masked=masked)


def band(stack, path, tool, size, offset=0, *, along_seam=False):
    import numpy as np
    import rasterio
    from pyproj import Transformer
    from rasterio.transform import from_origin
    from rasterio.windows import Window, bounds

    n = size + 2 * PAD
    row, col = np.indices((n, n), dtype='float64') + 0.5 - PAD
    # Odd profile about 60 ft: the diagonal (or vertical seam) remains the
    # 60 ft line after Gaussian smoothing, while other levels vary by sigma.
    d = col - size / 2 if along_seam else row - col + offset
    depths = (60 + 50 * np.tanh(d / 35)) / tool.dc.FEET_PER_M
    support = np.full((n, n), 3, dtype='uint8')
    provenance = np.full((n, n), tool.ec.CODES['measured'], dtype='uint8')
    # Give each validity input a real hole away from the corner control.
    depths[14:19, -28:-22] = -9999
    support[-28:-22, 14:19] = 2
    provenance[-35:-30, 19:25] = 255
    transform = from_origin(-13000000, 4200000, CELL, CELL)
    readers = []
    for name, values, nodata in [('depth', depths, -9999), ('support', support, 0),
                                 ('provenance', provenance, 255)]:
        target = path / (name + '.tif')
        with rasterio.open(target, 'w', driver='GTiff', crs='EPSG:3857', transform=transform,
                           count=1, width=n, height=n, dtype=values.dtype, nodata=nodata) as ds:
            ds.write(values, 1)
        readers.append(RecordingReader(stack.enter_context(rasterio.open(target))))
    whole = Window(PAD, PAD, size, size)
    left, bottom, right, top = bounds(whole, transform)
    ll = Transformer.from_crs('EPSG:3857', 'EPSG:4326', always_xy=True)
    # Clip a nonzero native offset and exercise the downstream lon/lat clip
    # inside the outer row/column of sampled centres too.
    extent = (*ll.transform(left + 0.75 * CELL, bottom + 0.75 * CELL),
              *ll.transform(right - 0.75 * CELL, top - 0.75 * CELL))
    return readers, {'bounds': extent}, whole


def features(tool, readers, region, view, **kwargs):
    grid, support, provenance = readers
    return list(tool.v3_grid(grid, region, view, COMMON, CELL, support=support, provenance=provenance,
                             positive_down=True, **kwargs))


@pytest.fixture
def tracer():
    from skippercast import style
    from skippercast.relief import contours

    return contours.producer(), style.load().view('contours')


@pytest.mark.parametrize('size,offset,cap,corners,along_seam', [
    pytest.param(96, 0, 5000, 1, False, id='one-corner'),
    pytest.param(192, 48, 7056, 2, False, id='two-corners'),
    pytest.param(384, 144, 7056, 4, False, id='four-corners'),
    pytest.param(96, 0, 5000, 1, True, id='on-shared-edge'),
])
def test_blocked_trace_matches_whole_window(tmp_path, tracer, size, offset, cap, corners, along_seam):
    # Losing a halo changes tier geometry; incorrect core ownership drops or
    # duplicates lines at corners and along the seam. Test both independently.
    from pyproj import Transformer
    from shapely import hausdorff_distance, transform
    from shapely.geometry import MultiLineString, Point, shape

    tool, view = tracer
    assert size * size > cap
    assert tool.preflight.MAX_PIXELS == 25_000_000
    to_xy = Transformer.from_crs('EPSG:4326', 'EPSG:3857', always_xy=True)
    with ExitStack() as stack:
        readers, region, whole = band(stack, tmp_path, tool, size, offset, along_seam=along_seam)
        reference = features(tool, readers, region, view, block_max_pixels=size * size)
        for reader in readers:
            assert reader.reads == [whole]
            reader.reads.clear()
        blocked = features(tool, readers, region, view, block_max_pixels=cap)
        assert len(readers[0].reads) > 1
        for reader in readers:
            assert reader.reads == readers[0].reads
            assert all(0 < w.width * w.height <= cap for w in reader.reads)
            assert all(PAD <= w.col_off < w.col_off + w.width <= PAD + size
                       and PAD <= w.row_off < w.row_off + w.height <= PAD + size for w in reader.reads)
        affine = readers[0].transform

    assert [f['id'] for f in blocked] == [f['id'] for f in reference]
    assert [f['properties'] for f in blocked] == [f['properties'] for f in reference]
    assert {f['properties']['tier'] for f in reference} == {'z8', 'z11', 'z13', 'z15'}
    lengths = [0.0, 0.0]
    for expected, actual in zip(reference, blocked, strict=True):
        a, b = (transform(shape(f['geometry']), to_xy.transform, interleaved=False) for f in (expected, actual))
        assert hausdorff_distance(a, b, densify=0.25) <= min(CELL, tool.CONTOUR_TOLERANCE_M), actual['id']
        lengths[0] += a.length
        lengths[1] += b.length
        if expected['properties']['depth_ft'] == 60:
            # The control really crosses the stated number of four-core
            # junctions, and is not a set of disconnected fragments there.
            hits = [Point(affine @ (PAD + x, PAD + y)) for x in range(48, size, 48)
                    for y in range(48, size, 48) if (x == size / 2 if along_seam else x == y + offset)]
            assert len(hits) == corners
            assert all(a.distance(p) < 0.01 and b.distance(p) < 0.01 for p in hits)
            assert isinstance(a, MultiLineString) and isinstance(b, MultiLineString)
            assert len(b.geoms) == len(a.geoms) == 1
            assert b.length == pytest.approx(a.length, rel=0.001)
    assert lengths[1] == pytest.approx(lengths[0], rel=0.01)


def test_default_cap_handles_overflow_but_refuses_an_unfittable_halo(tmp_path, tracer, monkeypatch):
    # Model the production cap on a tiny raster. The pin refused at 5,000;
    # even an oversized override must not bypass the hard cap at 1,368.
    tool, view = tracer
    with ExitStack() as stack:
        readers, region, _ = band(stack, tmp_path, tool, 96)
        monkeypatch.setattr(tool.preflight, 'MAX_PIXELS', 5000)
        assert features(tool, readers, region, view)
        for reader in readers:
            assert len(reader.reads) > 1 and all(w.width * w.height <= 5000 for w in reader.reads)
            reader.reads.clear()
        # The largest eligible radius is 16 cells; with the two extra cells,
        # a one-cell interior core still needs (1 + 2 * 18) ** 2 = 1,369 cells.
        monkeypatch.setattr(tool.preflight, 'MAX_PIXELS', 1368)
        with pytest.raises(ValueError, match='^ft-v3 native window exceeds 1368 pixels; use a smaller region window$'):
            features(tool, readers, region, view, block_max_pixels=1_000_000)
        assert not any(reader.reads for reader in readers)
