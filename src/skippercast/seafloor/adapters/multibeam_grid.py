"""Checked private derived support grids; never a producer raster or public feed.

This adapter consumes a reviewed preparation receipt, not research code. The
same COG/table/original identities remain bound through private processing.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import shutil

from skippercast.platform.contracts import atomic_json
from ..io import sha256

FORMAT = 'measured-multibeam-grid'
VERSION = 'measured-multibeam-grid-v1'
DESCRIPTIONS = ('depth_m_positive_down', 'original_good_sounding_count',
                'median_dispersion_m_not_uncertainty', 'contributor_depth_min_m',
                'contributor_depth_max_m')


def validate_binding(row):
    binding = deepcopy(row.get('grid_preparation', {}))
    spacing = binding.get('grid_spacing_m')
    if type(spacing) not in (int, float) or not math.isfinite(spacing) or not 0 < spacing <= 20:
        raise ValueError('Invalid derived grid spacing')
    if (row.get('format') != FORMAT or row.get('status') not in {'candidate', 'physical-only'}
            or binding.get('profile') != VERSION or binding.get('minimum_good_soundings') != 3
            or binding.get('native_sampling') != 'irregular-original-soundings'
            or row.get('resolution_m') != binding.get('grid_spacing_m')
            or row.get('license') != 'unknown' or row.get('kind') != 'bathymetry'
            or row.get('archive_member') != 'unknown'):
        raise ValueError('Derived grids require an explicit private sampling/qualification binding')
    for field in ('preparation_receipt_sha256', 'preparation_code_sha256'):
        if not re.fullmatch(r'[a-f0-9]{64}', binding.get(field, '')):
            raise ValueError('Missing preparation identity')
    binding['grid_spacing_m'] = float(binding['grid_spacing_m'])
    return binding


def reviewed_receipt(path, row):
    binding = validate_binding(row)
    if not Path(path).is_file() or Path(path).stat().st_size > 1_000_000:
        raise ValueError('Preparation receipt missing or exceeds bound')
    if sha256(path) != binding['preparation_receipt_sha256']:
        raise ValueError('Preparation receipt checksum mismatch')
    receipt = json.loads(Path(path).read_bytes())
    if (receipt.get('scope') != 'private-multibeam-grid-parity'
            or receipt.get('output_sha256') != row['sha256']
            or receipt.get('derived_bin_spacing_m') != binding['grid_spacing_m']
            or receipt.get('vertical_datum') != row['vertical_datum']
            or receipt.get('native_resolution') != 'irregular soundings'
            or receipt.get('uncertainty') != 'unknown'
            or receipt.get('count_support_mismatches') != 0
            or receipt.get('source_qualified') is not False
            or receipt.get('fishing_target') is not False or receipt.get('exportable') is not False
            or receipt.get('new_measured_km2') != 0
            or receipt.get('new_physical_candidates') != 0
            or receipt.get('new_public_locations') != 0):
        raise ValueError('Unreviewed preparation semantics or public/source claims')
    originals = receipt.get('originals', {})
    tables = receipt.get('beam_table_sha256', [])
    grids = receipt.get('grid_sha256', [])
    if (not 1 <= len(originals) <= 8 or len(tables) != len(originals) or len(grids) != 3
            or any(not re.fullmatch(r'[a-f0-9]{64}', h) for h in [*originals.values(), *tables, *grids,
                     receipt.get('grid_receipt_sha256', '')])):
        raise ValueError('Incomplete original/table/grid provenance')
    return receipt


def source_files(row, cache, local):
    """Local paired import or exact cached pair only; never fetch a landing URL."""
    validate_binding(row)
    if not re.fullmatch(r'[a-f0-9]{64}', row['sha256']) or not isinstance(row['bytes'], int) or row['bytes'] <= 0:
        raise ValueError('Derived source needs reviewed bytes and hash')
    folder = Path(cache)/row['sha256']; source = folder/'source.tif'; receipt = folder/'preparation.json'
    if source.exists() or receipt.exists():
        if not source.exists() or not receipt.exists():
            raise ValueError('Incomplete private derived source cache')
    else:
        if local is None:
            raise FileNotFoundError('Private derived grid missing; import paired --local COG and same-stem JSON receipt')
        local = Path(local); sidecar = local.with_suffix('.json')
        if local.stat().st_size != row['bytes'] or sha256(local) != row['sha256']:
            raise ValueError('Private derived COG checksum/byte mismatch')
        reviewed_receipt(sidecar, row)
        folder.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(local, source.with_suffix('.part'))
            shutil.copyfile(sidecar, receipt.with_suffix('.part'))
            source.with_suffix('.part').replace(source)
            receipt.with_suffix('.part').replace(receipt)
        finally:
            source.with_suffix('.part').unlink(missing_ok=True)
            receipt.with_suffix('.part').unlink(missing_ok=True)
    if source.stat().st_size != row['bytes'] or sha256(source) != row['sha256']:
        raise ValueError('Cached derived COG checksum/byte mismatch')
    return source, reviewed_receipt(receipt, row)


def supported_window(ds, window):
    import numpy as np
    # The preparation excludes original contributors crossing the nominal limit;
    # compare their retained float32 representations consistently here.
    ceiling = np.float32(91.44)
    values = ds.read(window=window, masked=True).astype('float32')
    a = values.filled(np.nan)
    valid = ~np.ma.getmaskarray(values).any(axis=0) & np.isfinite(a).all(axis=0)
    depth, count, dispersion, low, high = a
    # Fail corrupted diagnostics rather than quietly hiding them as no-data.
    if np.any(valid & ((count < 1) | (count != np.floor(count)) | (dispersion < 0)
                       | (low > depth) | (depth > high))):
        raise ValueError('Invalid contributor count/depth/dispersion diagnostics')
    crossing = ((low <= 0) & (high > 0)) | ((low <= ceiling) & (high > ceiling))
    supported = valid & (count >= 3) & ~crossing & (low > 0)
    return a, supported


def ingest(row, bounds, *, root, local=None):
    import numpy as np
    from pyproj import Transformer
    import rasterio
    from rasterio.shutil import copy as raster_copy
    from rasterio.windows import Window
    from ..normalized import raster_identity
    from ..raster import bounds_window, chunks
    binding = validate_binding(row)
    source, preparation = source_files(row, Path(root)/'var/seafloor/cache', local)
    inputs = {'source_id': row['id'], 'source_sha256': row['sha256'], 'bounds': list(bounds),
              'vertical_datum': row['vertical_datum'], 'grid_preparation': deepcopy(binding),
              'version': VERSION, 'implementation': {
                  'multibeam_grid.py': sha256(Path(__file__)),
                  'raster.py': sha256(Path(__file__).parents[1]/'raster.py'),
                  'normalized.py': sha256(Path(__file__).parents[1]/'normalized.py')}, 'margin_m': 100}
    key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    output = source.parent/(key+'.tif'); receipt_path = output.with_suffix('.json')
    if output.exists() or receipt_path.exists():
        if not output.exists() or not receipt_path.exists():
            raise ValueError('Incomplete private normalized grid cache')
        saved = json.loads(receipt_path.read_bytes())
        if saved['inputs'] != inputs or sha256(output) != saved['cog_sha256']:
            raise ValueError('Private normalized COG cache failed verification')
        return saved, False, True
    temporary = output.with_suffix('.working.tif'); part = output.with_suffix('.part.tif')
    valid_count = shallow_count = sparse_count = 0
    try:
        with rasterio.open(source) as ds:
            if (ds.count != 5 or ds.descriptions != DESCRIPTIONS or ds.crs is None
                    or ds.crs.to_string() != preparation['horizontal_crs']
                    or tuple(ds.res) != (binding['grid_spacing_m'],)*2
                    or any(t != 'float32' for t in ds.dtypes)
                    or ds.tags().get('interpolation') != 'none'
                    or ds.tags().get('depth_basis') != 'nominal'
                    or ds.tags().get('vertical_datum') != row['vertical_datum']):
                raise ValueError('Derived support grid does not match preparation contract')
            window = bounds_window(ds, bounds)
            if window.width*window.height > 10_000_000:
                raise ValueError('Derived support window exceeds bound')
            project = Transformer.from_crs(ds.crs, 4326, always_xy=True)
            profile = dict(driver='GTiff', width=int(window.width), height=int(window.height),
                           count=5, dtype='float32', crs=ds.crs, transform=ds.window_transform(window),
                           nodata=np.nan, tiled=True, blockxsize=512, blockysize=512, compress='DEFLATE')
            with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), rasterio.open(temporary,'w',**profile) as out:
                for chunk in chunks(window):
                    values, supported = supported_window(ds, chunk)
                    yy,xx = np.indices(supported.shape); x,y = ds.window_transform(chunk)*(xx+.5,yy+.5)
                    lon,lat = project.transform(x,y)
                    inside = (lon>=bounds[0]) & (lon<bounds[2]) & (lat>=bounds[1]) & (lat<bounds[3])
                    valid_count += int((inside & supported).sum())
                    shallow_count += int((inside & supported & (values[4]<=np.float32(91.44))).sum())
                    sparse_count += int((inside & np.isfinite(values[1]) & (values[1]<3)).sum())
                    dest = Window(chunk.col_off-window.col_off,chunk.row_off-window.row_off,chunk.width,chunk.height)
                    out.write(np.where(supported,values,np.nan),window=dest)
                    out.write_mask(supported.astype('uint8')*255,window=dest)
                for i,label in enumerate(DESCRIPTIONS,1): out.set_band_description(i,label)
                out.update_tags(vertical_datum=row['vertical_datum'],depth_basis='nominal',
                                interpolation='none',native_sampling=binding['native_sampling'],
                                grid_spacing_basis='derived bin spacing, not native resolution',
                                source_id=row['id'],adapter_version=VERSION,source_qualification='private-physical-only',
                                fishing_export='prohibited',uncertainty='unknown')
            raster_copy(temporary,part,driver='COG',COMPRESS='DEFLATE',BLOCKSIZE=512,OVERVIEWS='NONE')
            part.replace(output)
            saved = dict(inputs=inputs, adapter_version=VERSION, source_id=row['id'],source_sha256=row['sha256'],
                         source_bytes=row['bytes'],cog_sha256=sha256(output),cog_bytes=output.stat().st_size,
                         raster_identity=raster_identity(output),requested_bounds_wgs84=list(bounds),seam_margin_m=100,
                         valid_pixels_in_requested_bounds=valid_count,nominal_0_300ft_pixels_in_requested_bounds=shallow_count,
                         sparse_bins_excluded_in_requested_bounds=sparse_count,native_resolution_m='unknown',
                         grid_spacing_m=list(ds.res),native_sampling=binding['native_sampling'],horizontal_crs=ds.crs.to_string(),
                         vertical_datum=row['vertical_datum'],uncertainty_type='unknown',interpolation_mask='none',
                         preparation_receipt_sha256=binding['preparation_receipt_sha256'],
                         metadata={'originals':preparation['originals'],'beam_table_sha256':preparation['beam_table_sha256'],
                                   'grid_sha256':preparation['grid_sha256'],'preparation_code_sha256':binding['preparation_code_sha256']},
                         note='Private measured-bin habitat processing; derived spacing is not native resolution or accuracy. '
                              'Counts are contributors, not independent confirmation or calibrated uncertainty. Source rights unqualified.')
            atomic_json(receipt_path,saved,indent=2)
            return saved, False, False
    finally:
        temporary.unlink(missing_ok=True); part.unlink(missing_ok=True)
