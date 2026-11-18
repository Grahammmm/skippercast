"""E2E-03c: only a source's own per-cell coverage flags certify support class 3."""
import h5py
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from skippercast.relief import normalize as norm, support_adapters as sa
from tests.gis.test_coastal_vr_refinements import make_vr_bag
from tests.gis.test_regular_bag_native_window import OriginalBagWindowTests
from tests.gis.test_relief_normalize import result_files, values

pytestmark = pytest.mark.gis

# Snapshot of the family names in the localmapq inventory (inventory.json, 2026-11-17).
INVENTORY_FAMILIES = (
    'NOAA Digital Coast topobathy DEM', 'NOAA NOS BAG survey', 'USGS CoNED compiled topobathy',
    'california_coned', 'cdfw_ds3091', 'coned_northern', 'coned_southern', 'csmp', 'csmp_doi',
    'csumb_sfml', 'cudem_ninth', 'deepsea_coral', 'digital_coast_topobathy_lidar', 'groundfish_efh',
    'kelp_canopy', 'lidar-grid', 'nbs_bluetopo', 'nccos_cinms', 'nccos_substrate', 'ncmp_laz_1178',
    'ncmp_laz_4810', 'ncmp_laz_4825', 'ncmp_laz_4826', 'ncmp_laz_4912', 'ncmp_laz_5022',
    'ncmp_laz_8892', 'ncmp_laz_9629', 'ncmp_merge_2616', 'ncmp_topobathy_2009', 'ncmp_topobathy_2010',
    'ncmp_topobathy_2011', 'ncmp_topobathy_2014', 'ncmp_topobathy_2015', 'noaa_enc',
    'noaa_morrobay_topobathy_2022', 'ocm_provenance', 'other_ccc', 'srtm15plus', 'unknown',
    'usgs_3dep_coast', 'usgs_cascadia', 'usgs_cmgds', 'usgs_marine_sb', 'usgs_of2004_1221',
    'usgs_of2005_1170')
NODATA = 1_000_000
# code: (coverage, bathy_coverage, source_survey_id) -> expected class
CONTRIBUTORS = {
    1: (('1', '1', 'H13001'), 3),               # full bathymetric coverage: measured
    2: (('1', '0', 'H13002'), 1),               # side-scan coverage, depths interpolated
    3: (('0', '0', 'NBS Generalization'), 1),   # interpolation between compiled sources
    4: (('1', '1', 'H05278.interpolated'), 1),  # survey id names interpolation: lowers only
    5: (('0', '1', 'H13005'), 2),               # contradicts the spec (coverage False => bathy False)
    6: (('', '', 'H13006'), 2),                 # flags missing: no evidence
}


def rat_xml(rows):
    fields = ('value', 'count', 'coverage', 'bathy_coverage', 'source_survey_id')
    defs = ''.join(f'<FieldDefn index="{i}"><Name>{n}</Name><Type>{2 if n == "source_survey_id" else 0}</Type>'
                   f'<Usage>0</Usage></FieldDefn>' for i, n in enumerate(fields))
    body = ''.join(f'<Row index="{i}"><F>{code}</F><F>1</F>' + ''.join(f'<F>{v}</F>' for v in row) + '</Row>'
                   for i, (code, row) in enumerate(rows.items()))
    return (f'<PAMDataset><PAMRasterBand band="3"><Description>Contributor</Description>'
            f'<GDALRasterAttributeTable tableType="thematic">{defs}{body}</GDALRasterAttributeTable>'
            f'</PAMRasterBand></PAMDataset>')


def bluetopo(tmp_path, cell=4.0, rows=None, **tags):
    """6x8 tile: one contributor per column pair, an elevation hole and a masked contributor."""
    elevation = np.full((6, 8), -30, dtype='float32')
    elevation[0, 0] = NODATA                              # empty cell
    contributor = np.repeat(np.array([[1, 1, 2, 3, 4, 5, 6, 99]], dtype='float32'), 6, axis=0)
    contributor[5, 0] = NODATA                            # valid depth, no contributor code
    src = tmp_path / 'BlueTopo_TEST0001_20261118.tiff'
    with rasterio.open(src, 'w', driver='GTiff', width=8, height=6, count=3, dtype='float32',
                       crs='EPSG:26910', transform=from_origin(685000, 3930000, cell, cell), nodata=NODATA) as dst:
        dst.write(np.stack([elevation, np.full_like(elevation, .5), contributor]))
        for band, name in enumerate(('Elevation', 'Uncertainty', 'Contributor'), 1):
            dst.set_band_description(band, name)
        dst.update_tags(**tags)
    rat = tmp_path / (src.name + '.aux.xml')
    rat.write_text(rat_xml({k: v[0] for k, v in CONTRIBUTORS.items()} if rows is None else rows))
    return src, rat


def expected_bluetopo():
    classes = np.array([[CONTRIBUTORS.get(c, (None, 2))[1] for c in (1, 1, 2, 3, 4, 5, 6, 99)]] * 6, dtype='uint8')
    classes[0, 0] = 0
    classes[5, 0] = 2
    return classes


def open_grid(src):
    """The dataset and Grid exactly as normalize.write_normalized builds them for a GeoTIFF."""
    ds = rasterio.open(src)
    meta = norm.semantics(ds, norm.CRS.from_user_input(ds.crs), None)
    raw = ds.read(1)
    valid = (ds.read_masks(1) != 0) & np.isfinite(raw)
    return ds, norm.make_grid(raw, valid, ds.transform, norm.CRS.from_user_input(ds.crs), meta)


# Contract: measured / interpolated / empty / no-evidence BlueTopo cells become
# 3 / 1 / 0 / 2 in support.tif, and the sidecar names the adapter id and digest.
# Bug caught: trusting `coverage` alone, a misread RAT column order, a shifted
# contributor band, or an unlisted code certified instead of left unknown.
def test_bluetopo_contributor_coverage_classes_through_normalize(tmp_path):
    src, rat = bluetopo(tmp_path)
    result = norm.normalize(src, tmp_path / 'cache', family='nbs_bluetopo', evidence=[rat])
    target, sidecar = result_files(result)
    _, record, _ = norm.adapter_for('nbs_bluetopo')
    assert sidecar['params']['adapter'] == record and record['id'] == sa.BLUETOPO.id
    with rasterio.open(target / 'support.tif') as ds:
        assert ds.transform == from_origin(685000, 3930000, 4, 4)
        np.testing.assert_array_equal(ds.read(1), expected_bluetopo())
    wrong = tmp_path / 'other.tiff.aux.xml'
    wrong.write_text(rat.read_text())
    ds, grid = open_grid(src)
    with ds, pytest.raises(ValueError, match='attribute table'):
        sa.bluetopo_classify(ds, grid, (wrong,))


def add_georef_layer(path, keys, records, vr_keys=None):
    fields = [('coverage', 'u1'), ('bathy_coverage', 'u1'), ('source_survey_id', h5py.string_dtype())]
    table = np.array([(0, 0, '')] + list(records), dtype=fields)
    with h5py.File(path, 'r+') as bag:
        layer = bag['BAG_root'].create_group('georef_metadata/Elevation')
        layer.create_dataset('keys', data=np.asarray(keys, dtype='u4'))
        layer.create_dataset('values', data=table)
        if vr_keys is not None:
            layer.create_dataset('varres_keys', data=np.asarray(vr_keys, dtype='u4'))


# Contract: a BAG node's class comes from its own georef-metadata key; keys are
# stored south-first and must be flipped to the north-up Grid. Bug caught: an
# unflipped key raster (classes mirrored north/south), key 0 or an out-of-range
# key treated as a record, or a BAG without the layer certified.
def test_regular_bag_georef_metadata_keys_through_normalize(tmp_path):
    plain = tmp_path / 'plain.bag'
    OriginalBagWindowTests._make_original_bag(plain)
    src = tmp_path / 'layered.bag'
    OriginalBagWindowTests._make_original_bag(src)
    north_up = np.array([[1] * 6, [1] * 6, [2] * 6, [2] * 6, [0] * 6, [7] * 6])
    add_georef_layer(src, north_up[::-1], [(1, 1, 'H13001'), (1, 0, 'H13002')])
    family = 'NOAA NOS BAG survey'
    target, sidecar = result_files(norm.normalize(src, tmp_path / 'cache', family=family))
    assert sidecar['params']['adapter']['id'] == sa.BAG.id
    expected = np.array([[3] * 6, [3] * 6, [1] * 6, [1] * 6, [2] * 6, [2] * 6], dtype='uint8')
    expected[0, 5] = 0  # the fixture's elevation nodata node
    with rasterio.open(target / 'support.tif') as ds:
        np.testing.assert_array_equal(ds.read(1), expected)
    empty, _ = result_files(norm.normalize(plain, tmp_path / 'cache', family=family))
    assert set(values(empty / 'support.tif').compressed()) == {2}


# Contract: each VR refinement node takes the record named by its own
# varres_keys entry. Bug caught: reading keys from the wrong refinement offset
# or orientation, so one supergrid's measured flag certifies another's nodes.
def test_vr_bag_refinement_keys_follow_their_own_nodes(tmp_path):
    src = tmp_path / 'variable.bag'
    make_vr_bag(src, supergrids={(0, 0): (3, 2, 2.0, 1.0, 1.0), (0, 1): (2, 2, 2.0, 1.0, 1.0)}, padding=2)
    with h5py.File(src, 'r') as bag:
        meta = bag['BAG_root/varres_metadata'][:]
        n = bag['BAG_root/varres_refinements'].shape[1]
    vr_keys = np.full(n, 2, dtype='u4')             # interpolated unless set below
    first = int(meta[0, 0]['index'])
    vr_keys[first:first + 3] = 1                     # (0, 0): its stored south row is measured
    second = int(meta[0, 1]['index'])
    vr_keys[second:second + 4] = [0, 1, 9, 2]        # (0, 1): no key, measured, unlisted, interpolated
    add_georef_layer(src, np.zeros((6, 6)), [(1, 1, 'H13001'), (1, 0, 'H13002')], vr_keys)
    with h5py.File(src, 'r') as hdf, rasterio.open(src, MODE='LOW_RES_GRID') as ds:
        crs = norm.horizontal(norm.CRS.from_user_input(ds.crs))
        sem = norm.semantics(ds, norm.CRS.from_user_input(ds.crs), None)
        got = {g.refinement: (g.valid, sa.bag_classify(ds, g, ()))
               for g in norm.bag_grids(hdf['BAG_root'], ds, crs, sem)}
    valid, classes = got[(0, 0)]
    expected = np.array([[1, 1, 1], [3, 3, 3]], dtype='uint8')  # north-up: stored south row is last
    expected[~valid] = 0                                         # make_vr_bag nulls storage nodes 1 and 5
    np.testing.assert_array_equal(classes, expected)
    valid, classes = got[(0, 1)]
    assert valid.all()
    np.testing.assert_array_equal(classes, [[2, 1], [2, 3]])


# Contract: a family without an admitted adapter has every valid cell 2, and
# only the reviewed families have adapters. Bug caught: an adapter registered
# for (or a typo matching) an unreviewed family, certifying its cells.
@pytest.mark.parametrize('family', INVENTORY_FAMILIES)
def test_families_without_adapter_stay_unknown(family):
    adapter, record, _ = norm.adapter_for(family)
    if family in {'nbs_bluetopo', 'NOAA NOS BAG survey'}:
        assert record['id'] in {sa.BLUETOPO.id, sa.BAG.id}
        return
    assert adapter is None and record is None
    for label in (None, 'measured'):
        assert norm.classify(None, None, None, (), label, []) == 2


# Contract: labels, tags and nominal resolution never raise a class; a label
# can only lower. Bug caught: an adapter that reads a "measured" source label,
# GeoTIFF metadata or a fine nominal pixel size and certifies cells with no
# per-cell evidence.
def test_labels_tags_and_resolution_never_raise_a_class(tmp_path):
    flagless = {code: ('', '', 'survey measured') for code in (1, 2, 3, 4, 5, 6)}
    for cell in (0.5, 4.0):
        folder = tmp_path / str(cell)
        folder.mkdir()
        src, rat = bluetopo(folder, cell=cell, rows=flagless, source_type='measured', label='measured',
                            nominal_resolution_m='0.5')
        ds, grid = open_grid(src)
        with ds:
            for label in (None, 'measured'):
                support = norm.classify(ds, grid, sa.BLUETOPO, (rat,), label, [])
                assert set(np.unique(support[grid.valid])) == {2}
    src, rat = bluetopo(tmp_path)
    ds, grid = open_grid(src)
    with ds:
        lowered = norm.classify(ds, grid, sa.BLUETOPO, (rat,), 'interpolated', [])
    assert set(np.unique(lowered[grid.valid])) == {1}
