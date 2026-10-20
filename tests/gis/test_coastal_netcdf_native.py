"""PC-2: the bridge-lane acquire/qualify reader accepts a local netCDF grid (NOAA CRM shape).

Synthetic .nc files are written by GDAL's own netCDF driver (CreateCopy from a
GeoTIFF) in classic and netCDF-4 form. No network. A geographic 1 arc-second
grid is read as native cells by acquire and qualify; the map stage holds it by
name rather than taking slope with degree spacing. A metric netCDF grid maps.
"""
import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

h5py = pytest.importorskip('h5py')
rasterio = pytest.importorskip('rasterio')
from pyproj import Transformer  # noqa: E402
from rasterio.shutil import copy as raster_copy  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402

from skippercast.coastal import mapping, stage_cli, vertical  # noqa: E402
from skippercast.coastal.handoff import mapping_input  # noqa: E402
from skippercast.coastal.handoff.common import (  # noqa: E402
    digest, load, native_container, ref, validate_native_source, write)

pytestmark = pytest.mark.gis
NOW = '2026-10-18T00:00:00Z'
ARC = 1 / 3600
SIDE = 8
FILL = -99999.0
# A 5 km EPSG:3310 lattice cell on the Morro Bay shelf (C1); the grid sits inside it.
X0, Y0 = -205000, -165000
SEGMENT_ID = f'seg:3310:{X0}:{Y0}:5000'


def _cell_origin_crs84():
    lon, lat = Transformer.from_crs('EPSG:3310', 'OGC:CRS84', always_xy=True).transform(X0 + 2500, Y0 + 2500)
    # Snap to the arc-second lattice, as a CRM subset would be.
    return math.floor(lon * 3600) / 3600, math.floor(lat * 3600) / 3600


def _values():
    raw = -(100 + np.arange(SIDE * SIDE, dtype='float32').reshape(SIDE, SIDE))
    raw[0, 0] = FILL
    return raw


def make_nc(path, *, fmt='NC', crs='EPSG:4326', transform=None, bands=1):
    """GDAL-written netCDF with CF attributes like CRM's: metres, positive up, MSL."""
    if transform is None:
        lon, lat = _cell_origin_crs84()
        transform = from_origin(lon, lat, ARC, ARC)
    tif = path.with_suffix('.seed.tif')
    with rasterio.open(tif, 'w', driver='GTiff', width=SIDE, height=SIDE, count=bands, dtype='float32',
                       crs=crs, transform=transform, nodata=FILL) as ds:
        for band in range(1, bands + 1):
            ds.write(_values(), band)
            ds.set_band_unit(band, 'meters')
            ds.update_tags(band, units='meters', positive='up', vertical_datum='MSL')
    raster_copy(tif, path, driver='netCDF', FORMAT=fmt)
    tif.unlink()
    return path


def vertical_block(root, artifact):
    with rasterio.open(root / artifact['path']) as ds:
        observed = vertical.from_raster(ds, source_sha256=artifact['sha256'])
    return dict(schema='vertical-v1', **observed['facts'], conflicts=[],
                evidence=[vertical.evidence_from_observation(observed)])


def segment_record():
    return dict(schema='coastal-segment-v1', segment_id=SEGMENT_ID, crs='EPSG:3310',
                bbox=[X0, Y0, X0 + 5000, Y0 + 5000], region='synthetic')


def qualified(root, artifact):
    write(root / 'segment.json', segment_record())
    write(root / 'fixture-evidence.json', dict(synthetic=True))
    document = mapping_input.produce(root, artifact, segment_id=SEGMENT_ID,
        segment=ref(root, root / 'segment.json', 'coastal-segment-v1'),
        window=[0, 0, SIDE, SIDE], vertical=vertical_block(root, artifact), output_dir='input', synthetic=True,
        rights=dict(private_use=True, evidence=[ref(root, root / 'fixture-evidence.json',
                                                    'synthetic-fixture-evidence-v1')]))
    review = dict(schema='coastal-private-input-review-v2', independent=True,
        reviewer_id='synthetic-test-reviewer', facts_digest=document['facts_digest'],
        checked_at='2026-10-17T00:00:00Z', valid_until='2026-10-19T00:00:00Z',
        decision='accept', holds_added=[])
    write(root / 'review.json', review)
    document['review'] = ref(root, root / 'review.json', review['schema'])
    return document


@pytest.mark.parametrize('fmt,container', [('NC', b'CDF\x01'), ('NC4', b'\x89HDF\r\n\x1a\n')])
def test_geographic_netcdf_cells_are_read_exactly(tmp_path, fmt, container):
    source = make_nc(tmp_path / 'crm_socal_1as_vers2_subset.nc', fmt=fmt)
    assert source.read_bytes()[:len(container)] == container
    assert native_container(source) == 'netcdf'
    artifact = ref(tmp_path, source, 'native-raster-v1')
    facts, holds, raw, valid, transform, crs, depth = mapping_input.observe(
        tmp_path, artifact, window=[0, 0, SIDE, SIDE], vertical=vertical_block(tmp_path, artifact))
    expected = _values()
    assert holds == []
    np.testing.assert_array_equal(valid, expected != FILL)
    np.testing.assert_array_equal(raw[valid], expected[valid])
    np.testing.assert_array_equal(depth[valid], -expected[valid])   # positive-up metres -> depth
    header = facts['header']
    assert header['driver'] == 'netCDF' and header['netcdf_variable'] == 'Band1'
    assert header['horizontal_units'] == 'degree' and header['resolution_m'] is None
    assert header['resolution_deg'] == pytest.approx([ARC, ARC])
    assert facts['observed_vertical']['datum'] == 'MSL' and facts['vertical']['datum'] == 'MSL'
    assert facts['support']['crs'] == 'EPSG:4326' and facts['valid_count'] == SIDE * SIDE - 1
    # Roughly 25 m x 31 m cells at 35 N; the support area is measured in EPSG:3310.
    assert 63 * 600 < facts['support']['area_m2'] < 63 * 900
    assert crs.is_geographic and transform.a == pytest.approx(ARC)


def test_qualify_verifies_netcdf_and_map_stage_holds_geographic_grid(tmp_path):
    source = make_nc(tmp_path / 'crm.nc', fmt='NC4')
    artifact = ref(tmp_path, source, 'native-raster-v1')
    document = qualified(tmp_path, artifact)
    assert document['machine_holds'] == []
    checked = mapping_input.verify(tmp_path, document, now=NOW)
    assert checked['ready'] and checked['holds'] == []
    assert checked['facts']['segment']['outside_support_area_m2'] == 0
    result = mapping.run(tmp_path, document, output_dir='mapped', now=NOW)
    assert result['state'] == 'held'
    assert result['holds'] == ['native_geographic_grid_derivatives_unsupported']
    assert not (tmp_path / 'mapped').exists()


def test_metric_netcdf_grid_maps_native_cells(tmp_path):
    source = make_nc(tmp_path / 'metric.nc', crs='EPSG:3310', transform=from_origin(X0 + 1000, Y0 + 4000, 30, 30))
    artifact = ref(tmp_path, source, 'native-raster-v1')
    document = qualified(tmp_path, artifact)
    assert document['native_facts']['header']['horizontal_units'] == 'metre'
    assert document['native_facts']['header']['resolution_m'] == [30.0, 30.0]
    result = mapping.run(tmp_path, document, output_dir='mapped', now=NOW)
    assert result['state'] == 'done', result
    expected = _values()
    valid = expected != FILL
    with rasterio.open(tmp_path / result['outputs']['terrain']['path']) as ds:
        actual = ds.read(1, masked=True)
        np.testing.assert_array_equal(~np.ma.getmaskarray(actual), valid)
        np.testing.assert_array_equal(actual.data[valid], -expected[valid])
    assert mapping.verify(tmp_path, result, now=NOW)['ready']


def test_netcdf_is_admitted_only_where_the_bridge_lane_asks(tmp_path):
    classic = ref(tmp_path, make_nc(tmp_path / 'classic.nc'), 'native-raster-v1')
    nc4 = ref(tmp_path, make_nc(tmp_path / 'nc4.nc', fmt='NC4'), 'native-raster-v1')
    # The default (authenticated lane, BAG guards) is unchanged.
    with pytest.raises(ValueError, match='signature unsupported'):
        validate_native_source(tmp_path, classic)
    with pytest.raises(ValueError, match='BAG_root must be a local hard link'):
        validate_native_source(tmp_path, nc4)
    assert validate_native_source(tmp_path, classic, netcdf=True).name == 'classic.nc'
    assert validate_native_source(tmp_path, nc4, netcdf=True).name == 'nc4.nc'


@pytest.mark.parametrize('defect', ['external_link', 'soft_link', 'sidecar', 'multi_variable'])
def test_netcdf_container_defects_are_refused_before_reading(tmp_path, defect):
    source = make_nc(tmp_path / 'crm.nc', fmt='NC4', bands=3 if defect == 'multi_variable' else 1)
    if defect == 'external_link':
        with h5py.File(source, 'r+') as handle:
            handle['untrusted'] = h5py.ExternalLink('/unavailable.h5', '/z')
        expected = 'netCDF-4 external/soft links refused'
    elif defect == 'soft_link':
        with h5py.File(source, 'r+') as handle:
            handle['alias'] = h5py.SoftLink('/Band1')
        expected = 'netCDF-4 external/soft links refused'
    elif defect == 'sidecar':
        (tmp_path / 'crm.nc.aux.xml').write_text('<PAMDataset/>')
        expected = 'netCDF sidecar refused'
    else:
        expected = 'single-variable 2-D netCDF grid required'
    artifact = ref(tmp_path, source, 'native-raster-v1')
    with pytest.raises(ValueError, match=expected):
        mapping_input.observe(tmp_path, artifact, window=[0, 0, SIDE, SIDE], vertical=None)


def test_acquire_and_qualify_stages_read_a_netcdf_native_job(tmp_path):
    """The real stage CLI: acquire observes the cached .nc; qualify writes the mapping input."""
    (tmp_path / 'sources').mkdir()
    source = make_nc(tmp_path / 'sources' / 'crm_socal_1as_vers2_subset.nc')
    artifact = ref(tmp_path, source, 'native-raster-v1')
    write(tmp_path / 'fixture-evidence.json', dict(synthetic=True))
    native = dict(schema='coastal-native-job-v1', synthetic=True, segment_id=SEGMENT_ID, source=artifact,
                  window=[0, 0, SIDE, SIDE], vertical=vertical_block(tmp_path, artifact),
                  rights=dict(private_use=True, evidence=[ref(tmp_path, tmp_path / 'fixture-evidence.json',
                                                             'synthetic-fixture-evidence-v1')]))
    write(tmp_path / 'native-job.json', native)
    now = datetime(2026, 10, 18, tzinfo=timezone.utc)
    segment = dict(segment_record(), synthetic=True)

    def job(stage, manifest_ref, name):
        params = {}
        return dict(root=str(tmp_path), stage=stage, job_id=name, lease_token='t', code_sha='c', deps_sha='d',
                    params=params, params_sha=digest(params), input_manifest=manifest_ref,
                    input_manifest_sha=manifest_ref['sha256'], segment=segment,
                    budget=dict(wall_s=60, bytes=10_000_000),
                    deadline_utc=(now + timedelta(hours=1)).timestamp())

    acquired = stage_cli.execute(job('acquire', ref(tmp_path, tmp_path / 'native-job.json', 'coastal-native-job-v1'),
                                     'acquire-1'), 'out/acquire', now=now)
    assert acquired['state'] == 'done' and acquired['holds'] == [], acquired
    observation = next(a for a in acquired['artifacts'] if a['contract'] == 'coastal-cached-observation-v1')
    observed = load(tmp_path, observation)
    assert observed['facts']['header']['driver'] == 'netCDF'
    assert observed['requests'] == 0 and observed['transferred_bytes'] == 0
    nxt = acquired['next_job']
    assert nxt['stage'] == 'qualify'
    qualified_result = stage_cli.execute(job('qualify', nxt['input_manifest'], 'qualify-1'), 'out/qualify', now=now)
    # No independent review exists for this synthetic input, so qualification holds on review only.
    assert qualified_result['state'] == 'held'
    assert qualified_result['holds'] == ['independent_review_missing']
    produced = load(tmp_path, qualified_result['artifacts'][0])
    assert produced['machine_holds'] == []
    assert produced['native_facts']['header']['horizontal_units'] == 'degree'
