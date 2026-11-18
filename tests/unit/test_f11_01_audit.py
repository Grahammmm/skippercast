"""F11-01 / C1-01: native GeoTIFF admission before normalization or cache reuse."""
from zipfile import ZipFile

import pytest

pytestmark = pytest.mark.gis


@pytest.fixture
def original(tmp_path):
    import numpy as np
    from pyproj import Transformer
    import rasterio
    from rasterio.transform import from_origin

    from skippercast.seafloor.io import sha256

    def make(values, *, scale=1, offset=0, units=None, crs='EPSG:32631', archive=False):
        path = tmp_path / 'synthetic.tif'
        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), rasterio.open(
            path, 'w', driver='GTiff', width=2, height=2, count=1,
            dtype='int16', crs=crs, nodata=-9999, transform=from_origin(500000, 40, 2, 2),
        ) as dst:
            # A third, non-nodata cell holds a shallow-looking value but is explicitly masked.
            dst.write(np.array([values, [-20, -9999]], dtype='int16'), 1)
            dst.write_mask(np.array([[255, 255], [0, 0]], dtype='uint8'))
            dst.scales = (scale,)
            dst.offsets = (offset,)
            if units is not None:
                dst.set_band_unit(1, units)
        member = 'unknown'
        if archive:
            member = 'selected.tif'
            with ZipFile(path.with_suffix('.zip'), 'w') as bundle:
                bundle.write(path, member)
            path = path.with_suffix('.zip')
        row = dict(id='synthetic', url=f'https://pubs.usgs.gov/{path.name}',
                   kind='bathymetry', format='usgs-geotiff', sha256=sha256(path),
                   bytes=path.stat().st_size, vertical_datum='unknown',
                   archive_member=member, resolution_m=2)
        to_geo = Transformer.from_crs(32631, 4326, always_xy=True)
        bounds = (*to_geo.transform(499998, 34), *to_geo.transform(500006, 42))
        return path, row, bounds

    return make


@pytest.mark.parametrize('units', ['m', None])
def test_unpacked_depth_and_mask(tmp_path, original, units):
    import rasterio

    from skippercast.seafloor.ingest import ingest as legacy_ingest
    from skippercast.seafloor.source_ingest import ingest

    path, row, bounds = original((-10, -120), units=units)
    # Legacy is the byte-pinned implementation on main. Check a new build and
    # reuse of a pre-existing legacy key, not merely numeric equivalence.
    legacy_root = tmp_path / 'legacy'
    legacy, _, _ = legacy_ingest(row, bounds, root=legacy_root, local=path)
    assert ingest(row, bounds, root=legacy_root) == (legacy, False, True)
    draft = dict(row, sha256='unknown', bytes='unknown')
    saved, downloaded, reused = ingest(draft, bounds, root=tmp_path, local=path)
    assert not downloaded and not reused
    assert saved == legacy
    assert saved['valid_pixels_in_requested_bounds'] == 2
    assert saved['nominal_0_300ft_pixels_in_requested_bounds'] == 1
    folder = row['sha256']
    receipt = next(p for p in (tmp_path / 'var/seafloor/cache' / folder).glob('*.json')
                   if p.name != 'source.json')
    expected = legacy_root / 'var/seafloor/cache' / folder / receipt.name
    assert receipt.read_bytes() == expected.read_bytes()
    cog_path = receipt.with_suffix('.tif')
    assert cog_path.read_bytes() == expected.with_suffix('.tif').read_bytes()
    with rasterio.open(cog_path) as cog:
        samples = cog.read(1, masked=True)
        assert samples.compressed().tolist() == [10, 120]
        assert samples.mask.tolist() == [[False, False], [True, True]]


@pytest.mark.parametrize(('values', 'metadata', 'error'), [
    pytest.param((-100, -1200), dict(scale=0.1), 'scale/offset', id='scale-only'),
    pytest.param((50, -60), dict(offset=-60), 'scale/offset', id='offset-only'),
    pytest.param((-5, -60), dict(scale=2), 'scale/offset', id='false-shallow-120m'),
    pytest.param((-10, -120), dict(units='ft'), 'Band units', id='feet-band'),
    pytest.param((-10, -120), dict(units='m', crs='EPSG:32631+6360'), 'Vertical CRS units',
                 id='feet-crs-even-with-metre-band'),
])
def test_unsupported_geo_tiff_has_no_normalized_cache(tmp_path, original, values, metadata, error):
    from skippercast.seafloor.source_ingest import ingest

    path, row, bounds = original(values, **metadata)
    with pytest.raises(ValueError, match=error):
        ingest(row, bounds, root=tmp_path, local=path)
    folder = tmp_path / 'var/seafloor/cache' / row['sha256']
    # Raw byte-integrity receipt is allowed; neither a normalized COG nor its receipt is.
    assert {entry.name for entry in folder.iterdir()} == {'source.json', 'source.tif'}


def test_packed_archive_cannot_reuse_legacy_cog(tmp_path, original):
    from skippercast.seafloor.ingest import ingest as legacy_ingest
    from skippercast.seafloor.source_ingest import ingest

    # The selected member stores -60 for 120 m. Seed a real legacy entry to
    # catch a regression where validation only runs on a normalized cache miss.
    path, row, bounds = original((-5, -60), scale=2, archive=True)
    first, _, _ = legacy_ingest(row, bounds, root=tmp_path, local=path)
    assert first['nominal_0_300ft_pixels_in_requested_bounds'] == 2
    folder = tmp_path / 'var/seafloor/cache' / row['sha256']
    before = {entry.name: entry.read_bytes() for entry in folder.iterdir()}
    with pytest.raises(ValueError, match='scale/offset'):
        ingest(row, bounds, root=tmp_path)
    assert {entry.name: entry.read_bytes() for entry in folder.iterdir()} == before
