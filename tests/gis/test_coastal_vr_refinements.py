"""Variable-resolution BAG refinements become regular GeoTIFFs without changing a cell."""
from collections import Counter
import hashlib
import json
import re

import h5py
import numpy as np
import pytest
import rasterio

from skippercast.coastal import vertical
from skippercast.coastal.handoff import mapping_input, vr_refinements as vr
from skippercast.coastal.handoff.common import ref

pytestmark = pytest.mark.gis
NODATA = np.float32(1_000_000)
META = np.dtype([('index', '<u4'), ('dimensions_x', '<u4'), ('dimensions_y', '<u4'),
                 ('resolution_x', '<f4'), ('resolution_y', '<f4'),
                 ('sw_corner_x', '<f4'), ('sw_corner_y', '<f4')])
CELLS = np.dtype([('depth', '<f4'), ('depth_uncrt', '<f4')])
# Overview: 6x6 supergrids of 10 m, west edge 432000, south edge 3701940 (EPSG:26911).
# (row, col): (nx, ny, resolution, sw_corner_x, sw_corner_y). Storage order differs
# from (row, col) order on purpose.
SUPERGRIDS = {
    (0, 0): (4, 4, 2.0, 1.0, 1.0),   # 2 m, lattice phase 0
    (4, 2): (4, 3, 2.0, 1.0, 1.0),   # 2 m, same lattice as (0, 0)
    (0, 1): (3, 2, 3.0, 1.5, 2.0),   # 3 m class
    (2, 3): (4, 4, 2.0, 1.6, 1.0),   # 2 m, x phase 0.6 m off the first lattice
}
STORAGE = [(4, 2), (0, 0), (2, 3), (0, 1)]


def make_vr_bag(path, supergrids=SUPERGRIDS, *, padding=3, tracked=False):
    from tests.gis.test_regular_bag_native_window import OriginalBagWindowTests
    xml = OriginalBagWindowTests._make_original_bag(path, spacing=10)
    meta = np.zeros((6, 6), dtype=META)
    meta['index'] = 0xFFFFFFFF
    parts, start = [], 0
    for key in [k for k in STORAGE if k in supergrids] + sorted(set(supergrids) - set(STORAGE)):
        nx, ny, res, sx, sy = supergrids[key]
        meta[key] = (start, nx, ny, res, res, sx, sy)
        cells = np.zeros(nx * ny, dtype=CELLS)
        cells['depth'] = -(100 + start + np.arange(nx * ny) * .25)
        cells['depth_uncrt'] = .5 + np.arange(nx * ny) * .01
        parts.append(cells)
        start += nx * ny
    records = np.concatenate(parts)
    records['depth'][1] = NODATA          # an empty refinement node stays empty
    records['depth_uncrt'][1] = NODATA
    records['depth'][5] = np.nan          # a NaN node passes through as a non-sounding
    pad = np.array([(NODATA, NODATA)] * padding, dtype=CELLS)
    with h5py.File(path, 'r+') as bag:
        root = bag['BAG_root']
        grids = root.create_dataset('varres_metadata', data=meta)
        resolutions = [v[2] for v in supergrids.values()]
        for axis in 'xy':
            grids.attrs['min_resolution_' + axis] = np.float32(min(resolutions))
            grids.attrs['max_resolution_' + axis] = np.float32(max(resolutions))
        root.create_dataset('varres_refinements', data=np.concatenate([records, pad])[None, :])
        root.create_dataset('varres_tracking_list', shape=(1 if tracked else 0,), maxshape=(None,),
                            dtype=[('row', '<u4'), ('col', '<u4'), ('depth', '<f4')])
    return xml


@pytest.fixture
def vr_bag(tmp_path):
    source = tmp_path / 'H11879_MB_VR_MLLW.bag'
    xml = make_vr_bag(source)
    artifact = ref(tmp_path, source, 'native-raster-v1')
    row = dict(id='synthetic-vr-bag', title=source.name, kind='bathymetry', format='bag',
               url='https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H11879/BAG/' + source.name,
               sha256=artifact['sha256'], horizontal_crs='EPSG:26911', vertical_datum='MLLW')
    return tmp_path, source, artifact, row, hashlib.sha256(xml.encode()).hexdigest()


def emit(vr_bag, placement='exact_lattice', output_dir='derived'):
    root, _, artifact, row, metadata_sha256 = vr_bag
    return vr.emit(root, artifact, source_row=row, metadata_sha256=metadata_sha256,
                   output_dir=output_dir, placement=placement)


def refinement_blocks(source):
    """Independent reader: the raw HDF5 nodes per supergrid, north-up."""
    with h5py.File(source) as bag:
        meta = bag['BAG_root']['varres_metadata'][:]
        records = bag['BAG_root']['varres_refinements'][0, :]
    blocks = {}
    for row, col in np.argwhere(meta['dimensions_x'] > 0):
        m = meta[row, col]
        nx, ny = int(m['dimensions_x']), int(m['dimensions_y'])
        blocks[(int(row), int(col))] = records[m['index']:m['index'] + nx * ny].reshape(ny, nx)[::-1]
    return blocks


def table(root, receipt):
    lines = (root / receipt['supergrid_table']['path']).read_text().splitlines()
    header = lines[0].split(',')
    return {(int(r['row']), int(r['col'])): r for r in (dict(zip(header, line.split(','))) for line in lines[1:])}


def bits(values):
    return np.ascontiguousarray(values, dtype='<f4').view('<u4')


def test_exact_lattice_classes_cells_and_receipt_agree(vr_bag):
    root, source, _, _, _ = vr_bag
    receipt = emit(vr_bag)
    ids = [o['id'] for o in receipt['outputs']]
    assert ids == ['H11879-vr-class00-lattice0000', 'H11879-vr-class00-lattice0001',
                   'H11879-vr-class01-lattice0000']
    rows = table(root, receipt)
    assert {k: rows[k]['output'] for k in rows} == {
        (0, 0): ids[0], (4, 2): ids[0], (2, 3): ids[1], (0, 1): ids[2]}
    blocks = refinement_blocks(source)
    for output in receipt['outputs']:
        path = root / output['artifact']['path']
        assert output['artifact']['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert sorted(p.name for p in path.parent.iterdir() if p.name.startswith(output['id'])) == [path.name]
        with rasterio.open(path) as ds:
            assert ds.driver == 'GTiff' and ds.count == 2 and ds.nodata == NODATA
            assert list(ds.res) == output['resolution_m'] and list(ds.shape) == output['shape']
            assert ds.tags()['vertical_datum'] == 'MLLW' and ds.tags()['not_for_navigation'] == 'true'
            elevation, uncertainty = ds.read(1), ds.read(2)
            transform = ds.transform
        covered = np.zeros(elevation.shape, dtype=bool)
        for key, line in rows.items():
            if line['output'] != output['id']:
                continue
            block = blocks[key]
            r0, c0 = int(line['row_off']), int(line['col_off'])
            window = (slice(r0, r0 + block.shape[0]), slice(c0, c0 + block.shape[1]))
            np.testing.assert_array_equal(bits(elevation[window]), bits(block['depth']))
            np.testing.assert_array_equal(bits(uncertainty[window]), bits(block['depth_uncrt']))
            covered[window] = True
            # Receipt origin is the native cell edge and the GeoTIFF puts it there exactly.
            assert (transform.c + c0 * output['resolution_m'][0], transform.f - r0 * output['resolution_m'][1]) \
                == (float(line['native_left']), float(line['native_top']))
            assert float(line['displacement_x_m']) == float(line['displacement_y_m']) == 0
            assert int(line['cells']) == block.size
            assert int(line['valid_cells']) == int((np.isfinite(block['depth']) & (block['depth'] != NODATA)).sum())
        assert output['refinement_cells'] == int(covered.sum())
        assert np.all(elevation[~covered] == NODATA) and np.all(uncertainty[~covered] == NODATA)
    assert rows[(2, 3)]['native_left'] == repr(432000 + 30 + 1.600000023841858 - 1)
    assert receipt['bag']['active_supergrids'] == 4
    assert receipt['bag']['trailing_padding_records'] == 3
    assert receipt['bag']['valid_refinement_cells'] == 16 + 12 + 6 + 16 - 2
    assert receipt['placement']['max_abs_displacement_m'] == 0
    assert receipt['placement']['science_ruling_required'] is False
    assert vr.verify(root, receipt) == dict(ok=True, placement='exact_lattice', outputs=3, supergrids=4,
                                            refinement_cells=50, valid_cells=48)
    receipt_file = root / 'derived' / 'vr-refinements-receipt.json'
    assert json.loads(receipt_file.read_text()) == json.loads(json.dumps(receipt))
    assert vr.verify(root, ref(root, receipt_file, vr.SCHEMA))['ok']


@pytest.mark.parametrize('placement', vr.PLACEMENTS)
def test_no_cell_value_is_interpolated_or_invented(vr_bag, placement):
    root, source, _, _, _ = vr_bag
    receipt = emit(vr_bag, placement)
    with h5py.File(source) as bag:
        active = bag['BAG_root']['varres_refinements'][0, :50]
    expected_e, expected_u = Counter(bits(active['depth']).tolist()), Counter(bits(active['depth_uncrt']).tolist())
    emitted_e, emitted_u = Counter(), Counter()
    nodata_bits = int(bits(np.array([NODATA]))[0])
    for output in receipt['outputs']:
        with rasterio.open(root / output['artifact']['path']) as ds:
            e, u = ds.read(1), ds.read(2)
        emitted_e.update(bits(e).ravel().tolist())
        emitted_u.update(bits(u).ravel().tolist())
    # Every emitted bit pattern is a source node; extra cells are only the BAG nodata value.
    for emitted, expected in ((emitted_e, expected_e), (emitted_u, expected_u)):
        extra = emitted - expected
        assert set(extra) <= {nodata_bits}
        assert expected - emitted == Counter()


def test_nearest_cell_is_opt_in_records_displacement_and_requires_a_ruling(vr_bag):
    root, source, _, _, _ = vr_bag
    receipt = emit(vr_bag, 'nearest_cell')
    assert [o['id'] for o in receipt['outputs']] == ['H11879-vr-class00-lattice0000',
                                                     'H11879-vr-class01-lattice0000']
    assert receipt['placement']['science_ruling_required'] is True
    rows = table(root, receipt)
    moved = rows[(2, 3)]
    assert float(moved['displacement_x_m']) == pytest.approx(-.6, abs=1e-6)
    assert float(moved['displacement_y_m']) == 0
    assert all(float(rows[k]['displacement_x_m']) == 0 for k in ((0, 0), (4, 2), (0, 1)))
    assert receipt['outputs'][0]['max_abs_displacement_m'][0] == pytest.approx(.6, abs=1e-6)
    with rasterio.open(root / receipt['outputs'][0]['artifact']['path']) as ds:
        assert ds.tags()['vr_placement'] == 'nearest_cell'
        e = ds.read(1)
    block = refinement_blocks(source)[(2, 3)]
    r0, c0 = int(moved['row_off']), int(moved['col_off'])
    np.testing.assert_array_equal(bits(e[r0:r0 + 4, c0:c0 + 4]), bits(block['depth']))
    assert vr.verify(root, receipt)['refinement_cells'] == 50


def test_mapping_input_observe_refuses_the_vr_bag_but_takes_the_emitted_tiff(vr_bag):
    root, source, artifact, row, metadata_sha256 = vr_bag
    with pytest.raises(ValueError, match='Variable-resolution BAG requires a native-refinement adapter'):
        mapping_input.observe(root, artifact, window=[0, 0, 6, 6], vertical={}, source_row=row,
                              metadata_sha256=metadata_sha256)
    receipt = emit(vr_bag)
    blocks = refinement_blocks(source)
    for output in receipt['outputs']:
        tif = output['artifact']
        with rasterio.open(root / tif['path']) as ds:
            observed = vertical.from_raster(ds, source_sha256=tif['sha256'])
        block = dict(schema='vertical-v1', **observed['facts'], conflicts=[],
                     evidence=[vertical.evidence_from_observation(observed)])
        assert vertical.resolve(block, observed)['holds'] == []
        height, width = output['shape']
        facts, holds, raw, valid, transform, _, depth = mapping_input.observe(
            root, tif, window=[0, 0, width, height], vertical=block)
        assert holds == []
        assert facts['valid_count'] == output['valid_cells']
        assert facts['vertical']['datum'] == 'MLLW' and facts['vertical']['sign'] == 'positive_up'
        np.testing.assert_array_equal(depth[valid], -raw[valid])
        assert list(transform)[:6] == output['transform']
        sources = [blocks[k]['depth'] for k, line in table(root, receipt).items() if line['output'] == output['id']]
        native = np.concatenate([b.ravel() for b in sources])
        native = native[np.isfinite(native) & (native != NODATA)]
        np.testing.assert_array_equal(np.sort(raw[valid].astype('float32')), np.sort(native))


@pytest.mark.parametrize('placement', vr.PLACEMENTS)
def test_refinements_outside_their_supergrid_are_refused_and_edge_nodes_accepted(tmp_path, placement):
    def run(name, supergrids):
        source = tmp_path / name / 'H11879_MB_VR_MLLW.bag'
        source.parent.mkdir()
        xml = make_vr_bag(source, supergrids)
        artifact = ref(tmp_path, source, 'native-raster-v1')
        row = dict(kind='bathymetry', format='bag', sha256=artifact['sha256'], vertical_datum='MLLW',
                   url='https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H11879/BAG/' + source.name)
        return vr.emit(tmp_path, artifact, source_row=row, metadata_sha256=hashlib.sha256(xml.encode()).hexdigest(),
                       output_dir=name + '-out', placement=placement)
    # (0, 0)'s 7-node rows spill 4 m past its supergrid edge onto (0, 1)'s block.
    with pytest.raises(ValueError, match='supergrid 0,0 lie outside its supergrid cell'):
        run('spill', {(0, 0): (7, 2, 2.0, 1.0, 1.0), (0, 1): (2, 2, 2.0, 1.0, 1.0)})
    # Nodes exactly on the cell edges are inside. Their half-cell footprints may reach past the
    # edge, so (0, 1) lands on another lattice (exact) or moves half a cell (nearest), never
    # onto (0, 0)'s cells.
    receipt = run('edge', {(0, 0): (5, 2, 2.0, 1.0, 1.0), (0, 1): (2, 2, 2.0, 0.0, 1.0)})
    assert vr.verify(tmp_path, receipt)['refinement_cells'] == 14
    assert len(receipt['outputs']) == (2 if placement == 'exact_lattice' else 1)


def test_gdal_supergrid_probe_catches_a_wrong_row_convention(vr_bag, monkeypatch):
    original = vr._block

    def south_up(model, sg):
        e, u = original(model, sg)
        return e[::-1], u[::-1]
    monkeypatch.setattr(vr, '_block', south_up)
    with pytest.raises(ValueError, match='differ from GDAL supergrid reader'):
        emit(vr_bag)


def test_placement_collision_is_refused_not_merged():
    # Defence in depth: a block may never overwrite another block's cells.
    block = np.zeros(4, dtype=CELLS)
    model = dict(nodata=float(NODATA), records=block)
    first = dict(row=0, col=0, index=0, nx=2, ny=2, row_off=0, col_off=0)
    second = dict(row=0, col=1, index=0, nx=2, ny=2, row_off=1, col_off=1)
    group = dict(height=3, width=3, members=[first, second])
    with pytest.raises(ValueError, match='supergrid 0,1 overlaps another refinement'):
        vr._fill(model, group)


def test_verify_rejects_changed_cells_placement_and_invented_values(vr_bag):
    root, _, _, _, _ = vr_bag
    receipt = emit(vr_bag)
    output = receipt['outputs'][0]
    path = root / output['artifact']['path']
    pristine = path.read_bytes()

    def tamper(row, col, value, expected):
        path.write_bytes(pristine)
        with rasterio.open(path, 'r+') as ds:
            e = ds.read(1)
            e[row, col] = value
            ds.write(e, 1)
        changed = json.loads(json.dumps(receipt))
        changed['outputs'][0]['artifact'] = ref(root, path, vr.OUTPUT_CONTRACT)
        with pytest.raises(ValueError, match=expected):
            vr.verify(root, changed)

    rows = table(root, receipt)
    north = rows[(4, 2)]
    assert north['output'] == output['id']
    tamper(int(north['row_off']), int(north['col_off']), np.float32(-1.5),
           'emitted cells differ from refinement cells')
    tamper(0, 0, np.float32(-7), 'outside every refinement')
    path.write_bytes(pristine)
    table_path = root / receipt['supergrid_table']['path']
    lines = table_path.read_text().splitlines()
    fields = lines[1].split(',')
    fields[13] = str(int(fields[13]) + 1)  # row_off
    table_path.write_text('\n'.join([lines[0], ','.join(fields), *lines[2:]]) + '\n')
    changed = dict(receipt, supergrid_table=ref(root, table_path, vr.TABLE_CONTRACT))
    with pytest.raises(ValueError, match='placement differs|cells differ'):
        vr.verify(root, changed)
    with pytest.raises(ValueError, match='artifact bytes/hash changed'):
        vr.verify(root, receipt)


def rebound(root, receipt, path, **output_fields):
    """The receipt an attacker would write after changing an output: fresh byte reference."""
    changed = json.loads(json.dumps(receipt))
    output = next(o for o in changed['outputs'] if o['artifact']['path'] == path.relative_to(root).as_posix())
    output['artifact'] = ref(root, path, vr.OUTPUT_CONTRACT)
    output.update(output_fields)
    return changed


def siblings(path):
    return sorted(p.name for p in path.parent.iterdir() if p.name.startswith(path.stem))


def test_external_mask_sidecar_with_unchanged_receipt_is_refused_before_gdal(vr_bag, monkeypatch):
    root = vr_bag[0]
    receipt = emit(vr_bag)
    output = receipt['outputs'][0]
    path = root / output['artifact']['path']
    pristine = path.read_bytes()
    height, width = output['shape']
    before, *_ = mapping_input.observe(root, output['artifact'], window=[0, 0, width, height], vertical={})
    assert before['valid_count'] == output['valid_cells'] > 0
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False), rasterio.open(path, 'r+') as ds:
        ds.write_mask(np.zeros(ds.shape, dtype='uint8'))
    assert path.read_bytes() == pristine and siblings(path) == [path.name, path.name + '.msk']
    # The danger: the unchanged receipt still binds the TIFF bytes, yet observe now sees no cells.
    facts, *_ = mapping_input.observe(root, output['artifact'], window=[0, 0, width, height], vertical={})
    assert facts['valid_count'] == 0
    opened = []
    real_open = rasterio.open
    monkeypatch.setattr(rasterio, 'open', lambda target, *a, **k: opened.append(str(target)) or real_open(target, *a, **k))
    with pytest.raises(ValueError, match='unbound derived GeoTIFF sidecar refused before GDAL'):
        vr.verify(root, receipt)
    assert str(path) not in opened


@pytest.mark.parametrize('suffix', ['.tif.MSK', '.tif.aux.xml', '.tif.ovr', '.tfw', '.aux', '.TIF.Aux.Xml'])
def test_every_derived_output_sidecar_variant_is_refused(vr_bag, suffix):
    root = vr_bag[0]
    receipt = emit(vr_bag)
    path = root / receipt['outputs'][1]['artifact']['path']
    path.with_name(path.stem + suffix).write_bytes(b'x')
    with pytest.raises(ValueError, match='sidecar refused before GDAL'):
        vr.verify(root, receipt)


def test_internal_mask_or_overviews_with_a_refreshed_byte_reference_are_refused(vr_bag):
    root = vr_bag[0]
    receipt = emit(vr_bag)
    path = root / receipt['outputs'][0]['artifact']['path']
    pristine = path.read_bytes()
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), rasterio.open(path, 'r+') as ds:
        ds.write_mask(np.zeros(ds.shape, dtype='uint8'))
    assert siblings(path) == [path.name] and path.read_bytes() != pristine
    with pytest.raises(ValueError, match='header differs from source-derived expectation: mask'):
        vr.verify(root, rebound(root, receipt, path))
    path.write_bytes(pristine)
    with rasterio.open(path, 'r+') as ds:
        ds.build_overviews([2])
    assert siblings(path) == [path.name]
    with pytest.raises(ValueError, match='mask/overviews'):
        vr.verify(root, rebound(root, receipt, path))
    path.write_bytes(pristine)
    assert vr.verify(root, receipt)['ok']


def test_rebound_rotated_flipped_or_shifted_grids_are_refused(vr_bag):
    from affine import Affine
    root = vr_bag[0]
    receipt = emit(vr_bag)
    output = receipt['outputs'][0]
    path = root / output['artifact']['path']
    pristine = path.read_bytes()
    a, _, c, _, e, f = output['transform']
    height = output['shape'][0]
    for forged in (Affine(0, 2, 432000, -2, 0, 3701986),           # rotated (reviewer reproduction)
                   Affine(a, 0, c, 0, -e, f + height * e),         # south-up flip of the same footprint
                   Affine(a, 0, c + a, 0, e, f),                   # whole grid one cell east
                   Affine(a * 2, 0, c, 0, e * 2, f)):              # doubled cell size
        path.write_bytes(pristine)
        with rasterio.open(path, 'r+') as ds:
            ds.transform = forged
        assert siblings(path) == [path.name]
        changed = rebound(root, receipt, path, transform=list(forged)[:6],
                          resolution_m=[abs(forged.a) or 2.0, abs(forged.e) or 2.0])
        with pytest.raises(ValueError, match='header differs from source-derived expectation: transform/shape'):
            vr.verify(root, changed)
    path.write_bytes(pristine)
    # The receipt alone cannot restate geometry either.
    for field, value in (('transform', [a, 0, c + a, 0, e, f]), ('resolution_m', [3.0, 3.0]),
                         ('lattice_anchor', [0.0, 0.0])):
        with pytest.raises(ValueError, match='receipt geometry differs'):
            vr.verify(root, rebound(root, receipt, path, **{field: value}))
    assert vr.verify(root, receipt)['ok']


def _set_tags(**tags):
    return lambda ds: ds.update_tags(**tags)


@pytest.mark.parametrize('change, problem', [
    (_set_tags(vertical_datum='NAVD88', vertical_sign='positive_down', not_for_navigation='false'),
     'vertical/lineage tags'),
    (_set_tags(vertical_datum='NAVD88'), 'vertical/lineage tags'),
    (_set_tags(vertical_sign='positive_down'), 'vertical/lineage tags'),
    (_set_tags(not_for_navigation='false'), 'vertical/lineage tags'),
    (_set_tags(scale_offset_applied='true'), 'vertical/lineage tags'),
    (_set_tags(z_units='ft'), 'vertical/lineage tags'),
    (_set_tags(vr_metadata_sha256='0' * 64), 'vertical/lineage tags'),
    (lambda ds: ds.update_tags(1, vertical_sign='positive_down'), 'vertical/lineage tags'),
    (lambda ds: ds.set_band_unit(1, 'ft'), 'units/scales/offsets/descriptions'),
    (lambda ds: setattr(ds, 'scales', (0.3048, 1.0)), 'units/scales/offsets/descriptions'),
    (lambda ds: setattr(ds, 'offsets', (-1.0, 0.0)), 'units/scales/offsets/descriptions'),
    (lambda ds: ds.set_band_description(1, 'depth'), 'units/scales/offsets/descriptions'),
    (lambda ds: setattr(ds, 'nodata', -9999.0), 'nodata'),
    (lambda ds: setattr(ds, 'crs', 'EPSG:32611'), 'crs'),
])
def test_rebound_vertical_semantics_and_prohibition_changes_are_refused(vr_bag, change, problem):
    root = vr_bag[0]
    receipt = emit(vr_bag)
    path = root / receipt['outputs'][0]['artifact']['path']
    with rasterio.open(path, 'r+') as ds:
        change(ds)
    assert siblings(path) == [path.name]
    with pytest.raises(ValueError, match='header differs from source-derived expectation: .*' + re.escape(problem)):
        vr.verify(root, rebound(root, receipt, path))


def test_receipt_semantics_must_match_the_source(vr_bag):
    root = vr_bag[0]
    receipt = emit(vr_bag)
    for field, value in (('vertical_datum', 'NAVD88'), ('nodata', -9999.0), ('vertical_wkt', 'x')):
        changed = json.loads(json.dumps(receipt))
        changed['bag'][field] = value
        with pytest.raises(ValueError, match='receipt BAG semantics differ from source'):
            vr.verify(root, changed)
    changed = json.loads(json.dumps(receipt))
    changed['outputs'].pop()
    with pytest.raises(ValueError, match='source-derived refinement classes'):
        vr.verify(root, changed)


def test_source_guards(vr_bag, tmp_path):
    root, source, artifact, row, metadata_sha256 = vr_bag
    with pytest.raises(ValueError, match='metadata hash mismatch'):
        vr.emit(root, artifact, source_row=row, metadata_sha256='0' * 64, output_dir='a')
    with pytest.raises(ValueError, match='source row hash differs'):
        vr.emit(root, artifact, source_row=dict(row, sha256='0' * 64), metadata_sha256=metadata_sha256,
                output_dir='b')
    with pytest.raises(ValueError, match='variable-resolution NOS BAG source row'):
        vr.emit(root, artifact, source_row=dict(row, url=row['url'].replace('_VR_', '_2m_')),
                metadata_sha256=metadata_sha256, output_dir='c')
    with pytest.raises(ValueError, match='placement must be one of'):
        emit(vr_bag, 'bilinear', output_dir='d')
    emit(vr_bag, output_dir='e')
    with pytest.raises(ValueError, match='new or empty'):
        emit(vr_bag, output_dir='e')
    tracked = tmp_path / 'tracked' / 'H11879_MB_VR_MLLW.bag'
    tracked.parent.mkdir()
    xml = make_vr_bag(tracked, tracked=True)
    tracked_ref = ref(root, tracked, 'native-raster-v1')
    with pytest.raises(ValueError, match='tracked/overridden'):
        vr.emit(root, tracked_ref, source_row=dict(row, sha256=tracked_ref['sha256']),
                metadata_sha256=hashlib.sha256(xml.encode()).hexdigest(), output_dir='f')


def test_plan_reports_both_placements_and_writes_nothing(vr_bag):
    root, _, artifact, row, metadata_sha256 = vr_bag
    before = sorted(p.name for p in root.iterdir())
    summary = vr.plan(root, artifact, source_row=row, metadata_sha256=metadata_sha256)
    assert sorted(p.name for p in root.iterdir()) == before
    exact, nearest = summary['placements']['exact_lattice'], summary['placements']['nearest_cell']
    assert (exact['outputs'], nearest['outputs']) == (3, 2)
    assert [c['lattices'] for c in exact['classes']] == [2, 1]
    assert exact['science_ruling_required'] is False and nearest['science_ruling_required'] is True
    assert nearest['classes'][0]['max_abs_displacement_m'] == pytest.approx(.6, abs=1e-6)
    assert exact['classes'][0]['max_abs_displacement_m'] == 0


def test_too_many_exact_lattices_are_refused_before_writing(vr_bag, monkeypatch):
    root = vr_bag[0]
    monkeypatch.setattr(vr, 'MAX_OUTPUTS', 2)
    with pytest.raises(ValueError, match='3 output lattices exceed the 2 output cap'):
        emit(vr_bag)
    assert not (root / 'derived').exists()
    assert len(emit(vr_bag, 'nearest_cell')['outputs']) == 2


def test_cli_emit_then_verify(vr_bag, capsys):
    root, source, _, row, metadata_sha256 = vr_bag
    (root / 'row.json').write_text(json.dumps(row))
    vr.main(['emit', '--root', str(root), '--source', source.name, '--source-row', str(root / 'row.json'),
             '--metadata-sha256', metadata_sha256, '--output-dir', 'cli'])
    assert json.loads(capsys.readouterr().out)['supergrids'] == 4
    vr.main(['verify', '--root', str(root), '--receipt', 'cli/vr-refinements-receipt.json'])
    assert json.loads(capsys.readouterr().out)['ok'] is True


def test_overview_fill_other_than_the_bag_null_is_refused(tmp_path):
    # Refinement nulls are 1e6 whatever the overview says; a -9999 fill would make them +1,000,000 m soundings.
    source = tmp_path / 'H11879_MB_VR_MLLW.bag'
    xml = make_vr_bag(source)
    with h5py.File(source, 'r+') as bag:
        root = bag['BAG_root']
        for name in ('elevation', 'uncertainty'):
            data, attrs = root[name][:], dict(root[name].attrs)
            del root[name]
            band = root.create_dataset(name, data=data, fillvalue=np.float32(-9999), maxshape=(None, None), chunks=True)
            for key, value in attrs.items():
                band.attrs[key] = value
    artifact = ref(tmp_path, source, 'native-raster-v1')
    row = dict(id='synthetic-vr-bag', title=source.name, kind='bathymetry', format='bag',
               url='https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H11879/BAG/' + source.name,
               sha256=artifact['sha256'], horizontal_crs='EPSG:26911', vertical_datum='MLLW')
    with pytest.raises(ValueError, match='BAG nodata must be the BAG null'):
        vr.emit(tmp_path, artifact, source_row=row, metadata_sha256=hashlib.sha256(xml.encode()).hexdigest(),
                output_dir='derived')
    assert not (tmp_path / 'derived').exists()
