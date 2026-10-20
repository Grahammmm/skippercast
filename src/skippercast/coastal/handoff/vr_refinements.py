"""Derive regular GeoTIFFs from the native refinements of a variable-resolution NOS BAG.

``mapping_input.observe`` refuses VR BAGs and stays unchanged. This module is
the bridge-lane adapter (coast campaign P10/G6, card PC-8). It reads each
active supergrid's refinement grid at its own stated resolution and writes one
regular two-band GeoTIFF (elevation, uncertainty) per uniform-resolution
refinement class. ``observe`` can then take each GeoTIFF as a native source
under its existing checks.

Cell values are copied bit for bit. Nothing is interpolated, averaged or
resampled. Cells no refinement covers hold the BAG's own nodata value. The
only geometric operation is placement:

* ``exact_lattice`` (default): a class is one (resolution_x, resolution_y)
  pair plus one lattice phase. A supergrid joins a class only when its native
  cell edges already fall on that class's lattice within
  ``LATTICE_TOLERANCE_M``, so the recorded displacement is a floating-point
  residual, never a move.
* ``nearest_cell`` (opt-in): every phase of one resolution shares one lattice,
  anchored on the first active supergrid in (row, col) order. Each whole
  supergrid block is moved rigidly by at most half a cell. The pipeline's
  no-resampling rule forbids this today, so the receipt marks it
  ``science_ruling_required``. Overlapping placements are refused, never
  merged.

The receipt records the source identity, the derivation, every output and a
per-supergrid table (origin, resolution, cell count, output offset and
displacement) bound by SHA-256. ``verify`` reopens the source BAG and checks
each emitted cell against its refinement cell.
"""
import argparse
import csv
import hashlib
import importlib.metadata
import io
import json
import math
from pathlib import Path
import re
from urllib.parse import urlparse

from .common import confined, ref, resolve, validate_derived_geotiff, validate_native_source

SCHEMA = 'coastal-vr-refinement-receipt-v1'
TABLE_CONTRACT = 'coastal-vr-refinement-supergrids-v1'
OUTPUT_CONTRACT = 'native-raster-v1'
PLACEMENTS = ('exact_lattice', 'nearest_cell')
LATTICE_TOLERANCE_M = 1e-3
MAX_REFINEMENT_RECORDS = 50_000_000
MAX_OUTPUT_CELLS = 64 * 1024 * 1024
MAX_OUTPUTS = 4096
MAX_RECEIPT_BYTES = 64 * 1024 * 1024
FILENAME = re.compile(r'([HW]\d{5})_MB_VR_MLLW(?:_\d+of\d+)?\.bag')
METADATA_FIELDS = ('index', 'dimensions_x', 'dimensions_y', 'resolution_x', 'resolution_y',
                   'sw_corner_x', 'sw_corner_y')
TABLE_COLUMNS = ('row', 'col', 'index', 'dimensions_x', 'dimensions_y', 'resolution_x',
                 'resolution_y', 'sw_corner_x', 'sw_corner_y', 'native_left', 'native_top',
                 'output', 'col_off', 'row_off', 'displacement_x_m', 'displacement_y_m',
                 'cells', 'valid_cells')
LIMITATIONS = [
    'Derived from original NOS survey refinements for private mapping input; not for navigation.',
    'Values are the BAG refinement nodes copied without interpolation; nodes are not continuous coverage.',
    'Vertical semantics are those stated in the BAG metadata (MLLW, elevation positive up, metres).',
    'Outputs on different lattices of one resolution may overlap by under one cell at supergrid edges.',
]


def implementation():
    from skippercast.platform import bottom_targets
    paths = [Path(__file__), Path(__file__).with_name('common.py'), Path(bottom_targets.__file__)]
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def libraries():
    result = {name: importlib.metadata.version(name) for name in ('numpy', 'rasterio', 'h5py', 'pyproj')}
    import rasterio
    result.update(gdal=rasterio.__gdal_version__)
    return result


def _num(value):
    """Exact decimal spelling of a float32/float64 value (round-trips)."""
    return repr(float(value))


def _bits(values):
    import numpy as np
    return np.ascontiguousarray(values, dtype='<f4').view('<u4')


def _hash_arrays(*arrays):
    import numpy as np
    h = hashlib.sha256()
    for array in arrays:
        h.update(np.ascontiguousarray(array, dtype='<f4').tobytes())
    return h.hexdigest()


def _check_row(source_ref, source_row):
    from skippercast.platform.bottom_targets import source_url_allowed
    if not isinstance(source_row, dict):
        raise ValueError('inventoried source row required')
    url = source_row.get('url', '')
    name = Path(urlparse(url).path).name
    match = FILENAME.fullmatch(name)
    if (source_row.get('kind') != 'bathymetry' or source_row.get('format') != 'bag'
            or not source_url_allowed(url) or match is None):
        raise ValueError('variable-resolution NOS BAG source row required')
    if source_row.get('sha256') != source_ref.get('sha256'):
        raise ValueError('source row hash differs from source bytes')
    if source_row.get('vertical_datum') != 'MLLW':
        raise ValueError('inventoried source datum must be MLLW')
    return match.group(1)


def _read_source(root, source_ref, source_row, metadata_sha256):
    """Authenticate the container and return the refinement model."""
    import h5py
    import numpy as np
    import rasterio
    from pyproj import CRS
    from skippercast.coastal.bag_v2 import parse_metadata
    survey_id = _check_row(source_ref, source_row)
    path = validate_native_source(root, source_ref)
    if (not isinstance(metadata_sha256, str) or len(metadata_sha256) != 64
            or any(ch not in '0123456789abcdef' for ch in metadata_sha256)):
        raise ValueError('exact reviewed embedded-metadata SHA-256 required')
    with h5py.File(path, 'r') as bag:
        bag_root = bag['BAG_root']
        for name in ('varres_metadata', 'varres_refinements'):
            if name not in bag_root or not isinstance(bag_root[name], h5py.Dataset):
                raise ValueError('variable-resolution BAG datasets required')
        if not bag_root['varres_refinements'].size:
            raise ValueError('BAG has no refinements; use the regular-grid reader')
        for name in ('tracking_list', 'varres_tracking_list'):
            if name in bag_root and bag_root[name].size:
                raise ValueError('tracked/overridden BAG needs separate review')
        xml = bag_root['metadata'][:].tobytes().decode('utf-8').rstrip('\0')
        if hashlib.sha256(xml.encode()).hexdigest() != metadata_sha256:
            raise ValueError('BAG embedded metadata hash mismatch')
        metadata = parse_metadata(xml, survey_id)
        grids = bag_root['varres_metadata']
        values = bag_root['varres_refinements']
        if (grids.shape != bag_root['elevation'].shape
                or not set(METADATA_FIELDS) <= set(grids.dtype.names or ())):
            raise ValueError('variable-resolution supergrid layout unsupported')
        if (values.ndim != 2 or values.shape[0] != 1
                or not {'depth', 'depth_uncrt'} <= set(values.dtype.names or ())
                or values.dtype['depth'] != np.dtype('<f4') or values.dtype['depth_uncrt'] != np.dtype('<f4')):
            raise ValueError('variable-resolution refinement layout unsupported')
        if values.shape[1] > MAX_REFINEMENT_RECORDS:
            raise ValueError('refinement record bound exceeded')
        grids = grids[:]
        records = values[0, :]
    with rasterio.open(path) as ds:
        if ds.driver != 'BAG' or ds.count != 2 or not ds.crs:
            raise ValueError('expected BAG overview elevation and uncertainty bands')
        if ds.shape != grids.shape or ds.transform.b or ds.transform.d:
            raise ValueError('BAG overview and supergrid indices disagree')
        crs = CRS.from_user_input(ds.crs)
        horizontal = crs.sub_crs_list[0] if crs.is_compound else crs
        horizontal = horizontal.source_crs if horizontal.is_bound else horizontal
        declared = CRS.from_wkt(metadata['horizontal_wkt'])
        declared = declared.source_crs if declared.is_bound else declared
        if not horizontal.equals(declared, ignore_axis_order=True):
            raise ValueError('BAG horizontal CRS mismatch')
        if (not horizontal.is_projected
                or any(abs(a.unit_conversion_factor - 1) > 1e-10 for a in horizontal.axis_info[:2])):
            raise ValueError('native metric projected grid required')
        nodata = tuple(ds.nodatavals)
        if nodata[0] is None or not math.isfinite(nodata[0]) or nodata[0] != nodata[1]:
            raise ValueError('one finite BAG nodata value required for both bands')
        model = dict(path=path, survey_id=survey_id, metadata=metadata, grids=grids, records=records,
                     left=float(ds.bounds.left), bottom=float(ds.bounds.bottom), top=float(ds.bounds.top),
                     right=float(ds.bounds.right), coarse=(float(ds.res[0]), float(ds.res[1])),
                     crs=horizontal, nodata=float(nodata[0]), descriptions=list(ds.descriptions))
    model['supergrids'] = _supergrids(model)
    return model


def _supergrids(model):
    """Active supergrids in (row, col) order with their native north-up origins."""
    import numpy as np
    from skippercast.platform.bottom_targets import vr_transform
    grids, records = model['grids'], model['records']
    nx_all, ny_all = grids['dimensions_x'].astype('int64'), grids['dimensions_y'].astype('int64')
    if np.any((nx_all > 0) != (ny_all > 0)):
        raise ValueError('supergrid with one empty dimension')
    active = np.argwhere(nx_all > 0)
    if not len(active):
        raise ValueError('variable-resolution BAG has no active supergrids')
    starts = grids['index'][nx_all > 0].astype('int64')
    sizes = (nx_all * ny_all)[nx_all > 0]
    order = np.argsort(starts, kind='stable')
    ends = starts[order] + sizes[order]
    if starts[order][0] != 0 or np.any(starts[order][1:] != ends[:-1]) or ends[-1] > len(records):
        raise ValueError('refinement records are incomplete or overlapping')
    model['active_records'] = int(ends[-1])
    rows = []
    cx, cy = model['coarse']
    for row, col in active:
        m = grids[row, col]
        dx, dy = float(m['resolution_x']), float(m['resolution_y'])
        sx, sy = float(m['sw_corner_x']), float(m['sw_corner_y'])
        if not all(math.isfinite(v) for v in (dx, dy, sx, sy)) or dx <= 0 or dy <= 0:
            raise ValueError('invalid refinement resolution or corner')
        nx, ny = int(m['dimensions_x']), int(m['dimensions_y'])
        tol = LATTICE_TOLERANCE_M
        if (sx < -tol or sy < -tol or sx + (nx - 1) * dx > cx + tol or sy + (ny - 1) * dy > cy + tol):
            raise ValueError(f'refinement nodes of supergrid {int(row)},{int(col)} lie outside its supergrid cell')
        t = vr_transform(model['left'], model['bottom'], cx, cy, int(row), int(col), m)
        rows.append(dict(row=int(row), col=int(col), index=int(m['index']),
                         nx=int(m['dimensions_x']), ny=int(m['dimensions_y']),
                         dx=dx, dy=dy, sx=sx, sy=sy, left=float(t.c), top=float(t.f)))
    return rows


def _block(model, sg):
    """North-up refinement block (elevation, uncertainty) exactly as stored."""
    raw = model['records'][sg['index']:sg['index'] + sg['nx'] * sg['ny']].reshape(sg['ny'], sg['nx'])[::-1, :]
    return raw['depth'], raw['depth_uncrt']


def _valid(elevation, nodata):
    import numpy as np
    return np.isfinite(elevation) & (elevation != np.float32(nodata))


def _place(model, placement):
    """Assign each supergrid an output lattice and an integer cell offset."""
    if placement not in PLACEMENTS:
        raise ValueError('placement must be one of ' + ', '.join(PLACEMENTS))
    tol = LATTICE_TOLERANCE_M
    classes = {}
    for sg in model['supergrids']:
        classes.setdefault((sg['dx'], sg['dy']), []).append(sg)
    groups = []
    for (dx, dy), members in sorted(classes.items()):
        if placement == 'nearest_cell':
            lattices = [dict(anchor=(members[0]['left'], members[0]['top']), members=members)]
        else:
            lattices, buckets = [], {}
            nqx, nqy = max(1, round(dx / tol)), max(1, round(dy / tol))
            base = (members[0]['left'], members[0]['top'])
            for sg in members:
                fx = ((sg['left'] - base[0]) / dx) % 1.0
                fy = ((base[1] - sg['top']) / dy) % 1.0
                qx, qy = round(fx * nqx) % nqx, round(fy * nqy) % nqy
                found = None
                for ax in (-1, 0, 1):
                    for ay in (-1, 0, 1):
                        for lattice in buckets.get(((qx + ax) % nqx, (qy + ay) % nqy), ()):
                            kx = (sg['left'] - lattice['anchor'][0]) / dx
                            ky = (lattice['anchor'][1] - sg['top']) / dy
                            if (abs(kx - math.floor(kx + .5)) * dx <= tol
                                    and abs(ky - math.floor(ky + .5)) * dy <= tol):
                                found = lattice if found is None or lattice['n'] < found['n'] else found
                if found is None:
                    found = dict(anchor=(sg['left'], sg['top']), members=[], n=len(lattices))
                    lattices.append(found)
                    buckets.setdefault((qx, qy), []).append(found)
                found['members'].append(sg)
        for lattice in lattices:
            ax, ay = lattice['anchor']
            for sg in lattice['members']:
                kx = math.floor((sg['left'] - ax) / dx + .5)
                ky = math.floor((ay - sg['top']) / dy + .5)
                sg['kx'], sg['ky'] = kx, ky
                sg['disp_x'] = (ax + kx * dx) - sg['left']
                sg['disp_y'] = (ay - ky * dy) - sg['top']
            kx0 = min(sg['kx'] for sg in lattice['members'])
            ky0 = min(sg['ky'] for sg in lattice['members'])
            for sg in lattice['members']:
                sg['col_off'], sg['row_off'] = sg['kx'] - kx0, sg['ky'] - ky0
            width = max(sg['col_off'] + sg['nx'] for sg in lattice['members'])
            height = max(sg['row_off'] + sg['ny'] for sg in lattice['members'])
            groups.append(dict(resolution=(dx, dy), anchor=(ax, ay), origin=(ax + kx0 * dx, ay - ky0 * dy),
                               width=width, height=height, members=lattice['members'], class_key=(dx, dy)))
    class_ids = {key: i for i, key in enumerate(sorted(classes))}
    counters = {}
    for group in groups:
        ci = class_ids[group['class_key']]
        gi = counters.get(ci, 0)
        counters[ci] = gi + 1
        group['id'] = f"{model['survey_id']}-vr-class{ci:02d}-lattice{gi:04d}"
        for sg in group['members']:
            sg['output'] = group['id']
    return groups


def _fill(model, group):
    import numpy as np
    nodata = np.float32(model['nodata'])
    elevation = np.full((group['height'], group['width']), nodata, dtype='<f4')
    uncertainty = np.full_like(elevation, nodata)
    covered = np.zeros(elevation.shape, dtype=bool)
    for sg in group['members']:
        window = (slice(sg['row_off'], sg['row_off'] + sg['ny']), slice(sg['col_off'], sg['col_off'] + sg['nx']))
        if covered[window].any():
            raise ValueError(f"supergrid {sg['row']},{sg['col']} overlaps another refinement after placement")
        e, u = _block(model, sg)
        elevation[window], uncertainty[window] = e, u
        covered[window] = True
        sg['cells'] = sg['nx'] * sg['ny']
        sg['valid_cells'] = int(_valid(e, nodata).sum())
    return elevation, uncertainty, covered


def _table_bytes(groups):
    rows = sorted((sg for g in groups for sg in g['members']), key=lambda s: (s['row'], s['col']))
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(TABLE_COLUMNS)
    for sg in rows:
        writer.writerow([sg['row'], sg['col'], sg['index'], sg['nx'], sg['ny'], _num(sg['dx']), _num(sg['dy']),
                         _num(sg['sx']), _num(sg['sy']), _num(sg['left']), _num(sg['top']), sg['output'],
                         sg['col_off'], sg['row_off'], _num(sg['disp_x']), _num(sg['disp_y']),
                         sg['cells'], sg['valid_cells']])
    return stream.getvalue().encode()


def _gdal_probe(model, sample):
    """GDAL's own BAG supergrid reader must agree on geolocation and values."""
    import numpy as np
    import rasterio
    for sg in sample:
        e, u = _block(model, sg)
        with rasterio.open(f"BAG:{model['path']}:supergrid:{sg['row']}:{sg['col']}") as grid:
            bounds = [sg['left'], sg['top'] - sg['ny'] * sg['dy'], sg['left'] + sg['nx'] * sg['dx'], sg['top']]
            if (grid.shape != (sg['ny'], sg['nx'])
                    or not np.allclose(list(grid.bounds), bounds, rtol=0, atol=1e-3)
                    or not np.array_equal(_bits(grid.read(1)), _bits(e))
                    or not np.array_equal(_bits(grid.read(2)), _bits(u))):
                raise ValueError('refinement geolocation or values differ from GDAL supergrid reader')


def _probe_sample(supergrids):
    n = len(supergrids)
    return [supergrids[i] for i in sorted({0, n // 2, n - 1})]


def _bounded(groups):
    if len(groups) > MAX_OUTPUTS:
        raise ValueError(f'{len(groups)} output lattices exceed the {MAX_OUTPUTS} output cap; '
                         'see plan() for the lattice structure')
    for group in groups:
        if group['width'] * group['height'] > MAX_OUTPUT_CELLS:
            raise ValueError(f"class grid of {group['width']}x{group['height']} cells exceeds "
                             f'the {MAX_OUTPUT_CELLS} cell cap')


def _expected_tags(model, source_sha256, metadata_sha256, placement):
    """The complete dataset tag set of an output; verify requires exactly this."""
    return dict(AREA_OR_POINT='Area', vertical_sign='positive_up',
                vertical_datum=model['metadata']['vertical_datum'], scale_offset_applied='false',
                not_for_navigation='true', vr_source_sha256=source_sha256, vr_metadata_sha256=metadata_sha256,
                vr_placement=placement, vr_receipt_schema=SCHEMA)


def _check_header(ds, model, group, tags, name):
    """Prove an opened output is the self-describing grid emit writes for ``group``.

    Every fact ``mapping_input.observe`` and ``vertical.from_raster`` read is
    fixed here from the source, not from the receipt: driver, bands, CRS,
    full north-up affine, shape, nodata, units, scales, offsets, descriptions,
    tags, and a nodata-only validity mask with no overviews or RPCs.
    """
    from pyproj import CRS
    from rasterio.enums import MaskFlags
    from rasterio.transform import from_origin
    dx, dy = group['resolution']
    expected_transform = from_origin(group['origin'][0], group['origin'][1], dx, dy)
    problems = []
    if ds.driver != 'GTiff' or ds.count != 2 or ds.dtypes != ('float32', 'float32'):
        problems.append('driver/bands')
    if not ds.crs or not CRS.from_user_input(ds.crs).equals(model['crs']):
        problems.append('crs')
    if ds.transform != expected_transform or ds.shape != (group['height'], group['width']):
        problems.append('transform/shape')
    if ds.nodatavals != (model['nodata'], model['nodata']):
        problems.append('nodata')
    if (ds.units != ('m', 'm') or ds.scales != (1.0, 1.0) or ds.offsets != (0.0, 0.0)
            or ds.descriptions != ('elevation', 'uncertainty')):
        problems.append('units/scales/offsets/descriptions')
    if ds.tags() != tags or ds.tags(1) or ds.tags(2):
        problems.append('vertical/lineage tags')
    if (any(flags != [MaskFlags.nodata] for flags in ds.mask_flag_enums)
            or ds.overviews(1) or ds.overviews(2) or ds.rpcs or ds.gcps[0]):
        problems.append('mask/overviews/rpcs')
    if problems:
        raise ValueError(f"output {name} header differs from source-derived expectation: {', '.join(problems)}")
    return expected_transform


def plan(root, source_ref, *, source_row, metadata_sha256):
    """Describe both placements of a VR BAG without writing anything.

    Science review evidence: how many lattices exact placement needs per
    resolution class, and how far nearest-cell placement would move blocks.
    """
    model = _read_source(root, source_ref, source_row, metadata_sha256)
    _gdal_probe(model, _probe_sample(model['supergrids']))
    summary = dict(schema='coastal-vr-refinement-plan-v1', source=source_ref, survey_id=model['survey_id'],
                   active_supergrids=len(model['supergrids']), active_refinement_records=model['active_records'],
                   max_outputs=MAX_OUTPUTS, max_output_cells=MAX_OUTPUT_CELLS, placements={})
    for placement in PLACEMENTS:
        groups = _place(model, placement)
        classes = {}
        for group in groups:
            row = classes.setdefault(repr(list(group['resolution'])), dict(
                resolution_m=list(group['resolution']), lattices=0, supergrids=0, largest_grid_cells=0,
                max_abs_displacement_m=0.0))
            row['lattices'] += 1
            row['supergrids'] += len(group['members'])
            row['largest_grid_cells'] = max(row['largest_grid_cells'], group['width'] * group['height'])
            row['max_abs_displacement_m'] = max(row['max_abs_displacement_m'], *(
                max(abs(sg['disp_x']), abs(sg['disp_y'])) for sg in group['members']))
        try:
            _bounded(groups)
            within = True
        except ValueError:
            within = False
        summary['placements'][placement] = dict(outputs=len(groups), within_caps=within,
                                                science_ruling_required=placement == 'nearest_cell',
                                                classes=list(classes.values()))
    return summary


def emit(root, source_ref, *, source_row, metadata_sha256, output_dir, placement='exact_lattice'):
    """Write one GeoTIFF per refinement class plus the receipt; return the receipt."""
    import rasterio
    from rasterio.transform import from_origin
    model = _read_source(root, source_ref, source_row, metadata_sha256)
    _gdal_probe(model, _probe_sample(model['supergrids']))
    groups = _place(model, placement)
    _bounded(groups)
    out = confined(root, output_dir, existing=False)
    if out.exists() and any(out.iterdir()):
        raise ValueError('output directory must be new or empty')
    out.mkdir(parents=True, exist_ok=True)
    nodata = model['nodata']
    tags = _expected_tags(model, source_ref['sha256'], metadata_sha256, placement)
    outputs = []
    for group in groups:
        elevation, uncertainty, covered = _fill(model, group)
        dx, dy = group['resolution']
        transform = from_origin(group['origin'][0], group['origin'][1], dx, dy)
        path = out / (group['id'] + '.tif')
        with rasterio.open(path, 'w', driver='GTiff', width=group['width'], height=group['height'], count=2,
                           dtype='float32', crs=model['crs'], transform=transform, nodata=nodata,
                           compress='DEFLATE', tiled=True, blockxsize=256, blockysize=256) as ds:
            ds.write(elevation, 1)
            ds.write(uncertainty, 2)
            ds.set_band_description(1, 'elevation')
            ds.set_band_description(2, 'uncertainty')
            ds.set_band_unit(1, 'm')
            ds.set_band_unit(2, 'm')
            ds.update_tags(**{k: v for k, v in tags.items() if k != 'AREA_OR_POINT'})
        artifact = ref(root, path, OUTPUT_CONTRACT)
        with rasterio.open(validate_derived_geotiff(root, artifact, contract=OUTPUT_CONTRACT)) as ds:
            _check_header(ds, model, group, tags, group['id'])
        valid = _valid(elevation, nodata)
        outputs.append(dict(
            id=group['id'], artifact=artifact,
            resolution_m=[dx, dy], lattice_anchor=list(group['anchor']), transform=list(transform)[:6],
            shape=[group['height'], group['width']], supergrids=len(group['members']),
            refinement_cells=int(covered.sum()), valid_cells=int(valid.sum()),
            max_abs_displacement_m=[max(abs(sg['disp_x']) for sg in group['members']),
                                    max(abs(sg['disp_y']) for sg in group['members'])],
            values_sha256=_hash_arrays(elevation, uncertainty)))
        del elevation, uncertainty, covered
    table = out / 'vr-supergrids.csv'
    table.write_bytes(_table_bytes(groups))
    supergrids = model['supergrids']
    receipt = dict(
        schema=SCHEMA, producer='coastal.handoff.vr_refinements', source=source_ref, source_row=source_row,
        metadata_sha256=metadata_sha256, survey_id=model['survey_id'],
        bag=dict(overview_shape=list(model['grids'].shape), overview_resolution_m=list(model['coarse']),
                 overview_bounds=[model['left'], model['bottom'], model['right'], model['top']],
                 horizontal_crs=model['crs'].to_wkt(), vertical_datum=model['metadata']['vertical_datum'],
                 vertical_wkt=model['metadata']['vertical_wkt'],
                 uncertainty_type=model['metadata']['uncertainty_type'], nodata=nodata,
                 active_supergrids=len(supergrids), refinement_records=len(model['records']),
                 active_refinement_records=model['active_records'],
                 trailing_padding_records=len(model['records']) - model['active_records'],
                 valid_refinement_cells=sum(sg['valid_cells'] for sg in supergrids),
                 resolution_classes=sorted({(sg['dx'], sg['dy']) for sg in supergrids})),
        placement=dict(policy=placement, lattice_tolerance_m=LATTICE_TOLERANCE_M, interpolation='none',
                       resampling='none', value_change='none', overlap='refused',
                       science_ruling_required=placement == 'nearest_cell',
                       max_abs_displacement_m=max(max(abs(sg['disp_x']), abs(sg['disp_y'])) for sg in supergrids)),
        outputs=outputs, supergrid_table=ref(root, table, TABLE_CONTRACT),
        convention=dict(geolocation='skippercast.platform.bottom_targets.vr_transform',
                        gdal_probe_supergrids=[[sg['row'], sg['col']] for sg in _probe_sample(supergrids)],
                        refinement_rows='HDF5 south-to-north, flipped to north-up',
                        elevation='BAG positive-up metres, copied unchanged'),
        implementation=implementation(), libs=libraries(), not_for_navigation=True,
        publication_prohibited=True, limitations=LIMITATIONS)
    (out / 'vr-refinements-receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    return receipt


def _read_table(path):
    with open(path, newline='') as stream:
        reader = csv.reader(stream)
        if tuple(next(reader)) != TABLE_COLUMNS:
            raise ValueError('supergrid table columns changed')
        return [dict(zip(TABLE_COLUMNS, line)) for line in reader]


def verify(root, receipt):
    """Reopen the source and prove every emitted cell is its refinement cell.

    ``receipt`` is the receipt dict or a byte reference to the receipt file.
    Returns a summary; raises ValueError on any disagreement.
    """
    import numpy as np
    import rasterio
    if isinstance(receipt, dict) and 'schema' not in receipt and 'path' in receipt:
        receipt = json.loads(resolve(root, receipt, cap=MAX_RECEIPT_BYTES).read_text())
    if not isinstance(receipt, dict) or receipt.get('schema') != SCHEMA:
        raise ValueError('VR refinement receipt contract mismatch')
    if receipt.get('publication_prohibited') is not True or receipt.get('not_for_navigation') is not True:
        raise ValueError('VR refinement receipt prohibitions required')
    placement = receipt['placement']['policy']
    if placement not in PLACEMENTS or receipt['placement'].get('science_ruling_required') != (placement == 'nearest_cell'):
        raise ValueError('VR placement policy invalid')
    model = _read_source(root, receipt['source'], receipt['source_row'], receipt['metadata_sha256'])
    _gdal_probe(model, _probe_sample(model['supergrids']))
    # Placement is re-derived from the source. The receipt and the outputs must
    # agree with it; they never define it.
    groups = {group['id']: group for group in _place(model, placement)}
    _bounded(list(groups.values()))
    bag = receipt.get('bag')
    if (not isinstance(bag, dict) or bag.get('vertical_datum') != model['metadata']['vertical_datum']
            or bag.get('vertical_wkt') != model['metadata']['vertical_wkt'] or bag.get('nodata') != model['nodata']
            or bag.get('horizontal_crs') != model['crs'].to_wkt()):
        raise ValueError('receipt BAG semantics differ from source')
    table = _read_table(resolve(root, receipt['supergrid_table'], contract=TABLE_CONTRACT))
    source = {(sg['row'], sg['col']): sg for sg in model['supergrids']}
    if [(int(r['row']), int(r['col'])) for r in table] != sorted(source):
        raise ValueError('supergrid table differs from the source active supergrids')
    outputs = {o['id']: o for o in receipt['outputs']}
    if len(outputs) != len(receipt['outputs']) or set(outputs) != set(groups):
        raise ValueError('receipt outputs differ from the source-derived refinement classes')
    members = {name: [] for name in outputs}
    for line in table:
        sg = source[(int(line['row']), int(line['col']))]
        expected = [sg['index'], sg['nx'], sg['ny'], sg['dx'], sg['dy'], sg['sx'], sg['sy'], sg['left'], sg['top']]
        stated = [int(line['index']), int(line['dimensions_x']), int(line['dimensions_y'])] + [
            float(line[k]) for k in ('resolution_x', 'resolution_y', 'sw_corner_x', 'sw_corner_y',
                                     'native_left', 'native_top')]
        if stated != expected or int(line['cells']) != sg['nx'] * sg['ny']:
            raise ValueError(f"supergrid {sg['row']},{sg['col']} receipt differs from source")
        if [line['output'], int(line['col_off']), int(line['row_off'])] != [sg['output'], sg['col_off'], sg['row_off']]:
            raise ValueError(f"supergrid {sg['row']},{sg['col']} placement differs from source-derived placement")
        members[line['output']].append((sg, line))
    nodata = np.float32(model['nodata'])
    tags = _expected_tags(model, receipt['source']['sha256'], receipt['metadata_sha256'], placement)
    totals = dict(outputs=0, supergrids=0, refinement_cells=0, valid_cells=0)
    for name, output in outputs.items():
        group = groups[name]
        # Self-contained bytes only: masks, PAM, overviews and world files are refused before GDAL.
        path = validate_derived_geotiff(root, output['artifact'], contract=OUTPUT_CONTRACT)
        with rasterio.open(path) as ds:
            transform = _check_header(ds, model, group, tags, name)
            elevation, uncertainty = ds.read(1), ds.read(2)
            # Validity as observe sees it: GDAL's mask, finiteness and the explicit sentinel.
            effective = (ds.read_masks(1) > 0) & _valid(elevation, nodata)
        dx, dy = group['resolution']
        if (output['transform'] != list(transform)[:6] or output['shape'] != [group['height'], group['width']]
                or output['resolution_m'] != [dx, dy] or output['lattice_anchor'] != list(group['anchor'])):
            raise ValueError(f'output {name} receipt geometry differs from source-derived placement')
        covered = np.zeros(elevation.shape, dtype=bool)
        valid_cells = 0
        for sg, line in members[name]:
            if (sg['dx'], sg['dy']) != (dx, dy):
                raise ValueError('supergrid resolution differs from its output class')
            r0, c0 = int(line['row_off']), int(line['col_off'])
            placed_left, placed_top = transform.c + c0 * dx, transform.f - r0 * dy
            disp_x, disp_y = placed_left - sg['left'], placed_top - sg['top']
            limit = (LATTICE_TOLERANCE_M,) * 2 if placement == 'exact_lattice' else (dx / 2, dy / 2)
            if (abs(disp_x) > limit[0] + 1e-9 or abs(disp_y) > limit[1] + 1e-9
                    or not math.isclose(disp_x, float(line['displacement_x_m']), rel_tol=0, abs_tol=1e-6)
                    or not math.isclose(disp_y, float(line['displacement_y_m']), rel_tol=0, abs_tol=1e-6)):
                raise ValueError(f"supergrid {sg['row']},{sg['col']} placement differs from receipt")
            window = (slice(r0, r0 + sg['ny']), slice(c0, c0 + sg['nx']))
            e, u = _block(model, sg)
            if (elevation[window].shape != e.shape or covered[window].any()
                    or not np.array_equal(_bits(elevation[window]), _bits(e))
                    or not np.array_equal(_bits(uncertainty[window]), _bits(u))):
                raise ValueError(f"supergrid {sg['row']},{sg['col']} emitted cells differ from refinement cells")
            covered[window] = True
            count = int(_valid(e, nodata).sum())
            if count != int(line['valid_cells']):
                raise ValueError(f"supergrid {sg['row']},{sg['col']} valid count differs from receipt")
            valid_cells += count
        if not (np.all(elevation[~covered] == nodata) and np.all(uncertainty[~covered] == nodata)):
            raise ValueError(f'output {name} holds values outside every refinement')
        if (int(covered.sum()) != output['refinement_cells'] or valid_cells != output['valid_cells']
                or int(_valid(elevation, nodata).sum()) != valid_cells
                or int(effective.sum()) != valid_cells
                or len(members[name]) != output['supergrids']
                or _hash_arrays(elevation, uncertainty) != output['values_sha256']):
            raise ValueError(f'output {name} totals differ from receipt')
        totals['outputs'] += 1
        totals['supergrids'] += len(members[name])
        totals['refinement_cells'] += int(covered.sum())
        totals['valid_cells'] += valid_cells
    if (totals['supergrids'] != len(model['supergrids'])
            or totals['refinement_cells'] != model['active_records']
            or totals['valid_cells'] != receipt['bag']['valid_refinement_cells']):
        raise ValueError('emitted outputs do not account for every refinement cell')
    return dict(ok=True, placement=placement, **totals)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    e = sub.add_parser('emit')
    e.add_argument('--root', type=Path, required=True)
    e.add_argument('--source', type=Path, required=True, help='root-relative VR BAG path')
    e.add_argument('--source-row', type=Path, required=True, help='JSON inventory row for the BAG')
    e.add_argument('--metadata-sha256', required=True)
    e.add_argument('--output-dir', type=Path, required=True, help='root-relative, new or empty')
    e.add_argument('--placement', choices=PLACEMENTS, default='exact_lattice')
    v = sub.add_parser('verify')
    v.add_argument('--root', type=Path, required=True)
    v.add_argument('--receipt', type=Path, required=True, help='root-relative receipt path')
    p = sub.add_parser('plan', help='report lattices and displacements per placement; writes nothing')
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True, help='root-relative VR BAG path')
    p.add_argument('--source-row', type=Path, required=True, help='JSON inventory row for the BAG')
    p.add_argument('--metadata-sha256', required=True)
    args = parser.parse_args(argv)
    if args.command == 'plan':
        print(json.dumps(plan(args.root, ref(args.root, args.source, 'native-raster-v1'),
                              source_row=json.loads(args.source_row.read_text()),
                              metadata_sha256=args.metadata_sha256), indent=2))
    elif args.command == 'emit':
        receipt = emit(args.root, ref(args.root, args.source, 'native-raster-v1'),
                       source_row=json.loads(args.source_row.read_text()),
                       metadata_sha256=args.metadata_sha256, output_dir=args.output_dir,
                       placement=args.placement)
        print(json.dumps(dict(outputs=[o['id'] for o in receipt['outputs']],
                              supergrids=receipt['bag']['active_supergrids'],
                              placement=receipt['placement'])))
    else:
        print(json.dumps(verify(args.root, ref(args.root, args.receipt, SCHEMA))))


if __name__ == '__main__':
    main()
