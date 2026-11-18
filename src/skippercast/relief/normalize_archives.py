"""R2 archive inputs: select one bathymetry member or one indexed lidar pair.

Use ``region.py normalize-archives --family … --source … --cache …``.
For multi-grid ZIPs and ArcInfo containers pass the exact ``--member``;
for lidar pass the index as ``--source`` and select an ``--lidar-id``.
Cache receipts are per input/member, not per region or release scope.
Set the launcher's TMPDIR under its scratch root for adapter spools.
"""
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import argparse
import json
import re
import stat

import numpy as np
from pyproj import CRS
import rasterio
from rasterio.shutil import copy as copy_raster
from rasterio.warp import transform_bounds

from skippercast.seafloor.adapters import arcgrid, usgs_geotiff
from . import normalize as raster
from . import receipts

STAGE = 'normalize_archives'
TIFF = ('.tif', '.tiff')
FAMILIES = ('csmp', 'cinms', 'lidar-grid')
CINMS_MEMBER = re.compile(r'CINMS_(Northern|SBI)_(2|4|8|16|24)mXY_.+\.tiff?', re.IGNORECASE)
BATHY = re.compile(r'bathy|(?:^|[\/_. -])depth', re.IGNORECASE)
OTHER = re.compile(r'back[ _-]?scatter|hill[ _-]?shad|shaded[ _-]?relief|seafloor[ _-]?character|'
                   r'(?:^|[\/_. -])(?:cmecs|slope|counts?)(?:$|[\/_. -])', re.IGNORECASE)
PRODUCT_TAGS = {'product', 'product_type', 'title', 'long_name', 'raster_role'}
DATUM_NAMES = {'NAVD88', 'MLLW', 'MSL', 'EGM2008', 'instantaneous_sea_level', 'unstated'}


def local_path(value, root=None):
    text = str(value)
    if '://' in text or text.startswith('/vsi'):
        raise ValueError('expected a local held file')
    path = Path(text).expanduser()
    path = (root / path if root is not None else path).resolve(strict=True)
    if (root is not None and not path.is_relative_to(root)) or not path.is_file():
        raise ValueError('expected a regular file within the input root')
    return path


def select_member(source, family, member):
    is_zip = source.suffix.lower() == '.zip'
    if not is_zip and (family != 'csmp' or not source.name.lower().endswith(('.tar.gz', '.tgz'))):
        raise ValueError('expected CSMP ZIP or ArcInfo gzip tar, or a CINMS ZIP')
    if is_zip:
        with ZipFile(source) as archive:
            grids = [row for row in archive.infolist() if not row.is_dir()
                     and row.filename.lower().endswith(TIFF) and not row.filename.startswith('__MACOSX/')]
            if member in (None, 'unknown') and family == 'csmp' and len(grids) == 1:
                member = grids[0].filename
            chosen = [row for row in grids if row.filename == member]
            if member is None or len(chosen) != 1:
                raise ValueError('select one exact, unique GeoTIFF archive member')
            if stat.S_IFMT(chosen[0].external_attr >> 16) not in {0, stat.S_IFREG}:
                raise ValueError('selected TIFF member must be a regular file')
            if member + '.msk' in archive.namelist():
                raise ValueError('external ZIP member masks are not supported by the TIFF adapter')
    elif member in (None, 'unknown'):
        raise ValueError('select an exact ArcInfo grid directory')
    member = arcgrid.safe_name(member)
    leaf = PurePosixPath(member).name
    # ArcInfo distributions can bundle hillshade *alongside* the selected bathymetry.
    # Check the selected grid itself, not the title of that mixed tar/ZIP bundle.
    if OTHER.search(leaf) or (is_zip and (OTHER.search(source.name) or OTHER.search(member))):
        raise ValueError('only bathymetry is accepted (not backscatter, hillshade, or count)')
    if family == 'cinms' and not CINMS_MEMBER.fullmatch(leaf):
        raise ValueError('expected a published Northern or SBI CINMS bathymetry tier')
    if family == 'csmp' and not (BATHY.search(leaf) or (is_zip and BATHY.search(source.name))):
        raise ValueError('archive selection does not identify a bathymetry grid')
    return member, usgs_geotiff if is_zip else arcgrid


def lidar_pair(index, ident):
    document = json.loads(index.read_text())
    if (not isinstance(document, dict) or document.get('schema_version') != 1
            or not isinstance(document.get('files'), list)):
        raise ValueError('expected a lidar-grid index v1')
    rows = [r for r in document['files'] if isinstance(r, dict) and r.get('id') == ident]
    if len(rows) != 1 or rows[0].get('status') != 'gridded':
        raise ValueError('lidar ID must select one gridded index row')
    row = rows[0]
    classes, datum = row.get('classes'), row.get('vertical_datum')
    if (not isinstance(classes, list) or not classes
            or any(type(c) is not int or not 0 <= c <= 255 for c in classes)
            or not isinstance(datum, str) or datum not in DATUM_NAMES):
        raise ValueError('lidar index must record selected classes and vertical datum')
    if any(not isinstance(row.get(k), str) or not row[k] for k in ('path', 'count_path', 'sha256', 'count_sha256')):
        raise ValueError('lidar index must bind both elevation and count TIFFs by hash')
    elevation = local_path(row['path'], index.parent)
    count = local_path(row['count_path'], index.parent)
    if (elevation == count or elevation.suffix.lower() not in TIFF or count.suffix.lower() not in TIFF
            or OTHER.search(elevation.name)):
        raise ValueError('count-only TIFF refused; distinct elevation and count TIFFs are required')
    return elevation, count, dict(id=ident, classes=classes, vertical_datum=datum), (row['sha256'], row['count_sha256'])


def open_elevation(source, work, params, adapter):
    if adapter is None:
        return open_tiff(source)
    # Both adapters write next to their argument. Point them at a scratch-only
    # alias; their extraction receipts and bytes never land next to the original.
    alias = work / source.name
    alias.symlink_to(source)
    path = adapter.source_path(alias, {'archive_member': params['archive_member']})
    if adapter is arcgrid:
        return rasterio.open(path, driver='AIG')
    return open_tiff(path)


def open_tiff(path):
    return rasterio.open(path, driver='GTiff', GEOREF_SOURCES='INTERNAL')


def read_grid(ds, crs, meta, counts, window=None):
    raw = ds.read(1, window=window, masked=True)
    valid = ~np.ma.getmaskarray(raw) & np.isfinite(raw.data)
    if ds.nodata is not None:
        valid &= raw.data != ds.nodata
    if counts is not None:
        returns = counts.read(1, window=window, masked=True)
        valid &= ~np.ma.getmaskarray(returns) & (returns.data > 0)
    transform = ds.transform if window is None else ds.window_transform(window)
    return raster.make_grid(raw.data, valid, transform, crs, meta, ds.scales[0], ds.offsets[0])


def write_native(ds, crs, meta, counts, output, work, support_class):
    # Some published CINMS tiers are very large with sparse valid coverage.
    # Keep native lattices windowed rather than materializing their full extent.
    profile = dict(driver='GTiff', crs=crs.to_wkt(), transform=ds.transform, count=1,
                   width=ds.width, height=ds.height, tiled=True, blockxsize=512, blockysize=512,
                   compress='DEFLATE', BIGTIFF='IF_SAFER')
    with ExitStack() as stack:
        grid = stack.enter_context(rasterio.open(work / 'elevation.tif', 'w', **profile,
                                                 dtype='float32', nodata=float(raster.NODATA)))
        support = stack.enter_context(rasterio.open(work / 'support.tif', 'w', **profile,
                                                    dtype='uint8', nodata=0))
        grid.set_band_unit(1, 'm')
        grid.update_tags(vertical_datum=meta['vertical_datum'], value_convention=raster.VALUE_UP)
        for _, window in grid.block_windows(1):
            native = read_grid(ds, crs, meta, counts, window)
            grid.write(native.elevation, 1, window=window)
            support.write(np.where(native.valid, support_class, 0).astype('uint8'), 1, window=window)
    for name, source in [('grid.tif', 'elevation.tif'), ('support.tif', 'support.tif')]:
        copy_raster(work / source, output / name, driver='COG', COMPRESS='DEFLATE', LEVEL=1,
                    OVERVIEWS='NONE', BIGTIFF='IF_SAFER')


def produce_rasters(source, count, output, params, source_sha, code, adapter):
    with TemporaryDirectory(dir=output) as staging, ExitStack() as stack:
        work = Path(staging)
        # The index pins TIFF bytes, not arbitrary sibling worldfiles/masks.
        options = {'GDAL_DISABLE_READDIR_ON_OPEN': 'EMPTY_DIR'} if count else {}
        stack.enter_context(rasterio.Env(GDAL_PAM_ENABLED='NO', PROJ_NETWORK='OFF', **options))
        ds = stack.enter_context(open_elevation(source, work, params, adapter))
        allowed_bands = (1, 3) if count is not None else (1,)
        if not ds.crs or ds.count not in allowed_bands:
            raise ValueError('expected a georeferenced elevation product')
        tags = (v for k, v in (ds.tags() | ds.tags(1)).items() if k.lower() in PRODUCT_TAGS)
        if any(OTHER.search(text) for text in (ds.descriptions[0] or '', *tags)):
            raise ValueError('expected a georeferenced elevation product, not an ancillary product')
        counts = stack.enter_context(open_tiff(count)) if count is not None else None
        if counts is not None and (counts.count != 1 or counts.crs != ds.crs or counts.shape != ds.shape
                                   or counts.transform != ds.transform or counts.scales != (1.0,)
                                   or counts.offsets != (0.0,) or np.dtype(counts.dtypes[0]).kind not in 'ui'):
            raise ValueError('count TIFF must be an aligned single-band integer count grid')
        original = CRS.from_user_input(ds.crs)
        crs = raster.horizontal(original)
        dest = raster.target_crs(crs, ds.bounds)
        meta = raster.semantics(ds, original, params['source_value_convention'])
        if params['vertical_datum'] not in (None, 'unstated'):
            if meta['vertical_datum'] not in ('unstated', params['vertical_datum']):
                raise ValueError('declared vertical datum conflicts with the raster')
            if meta['vertical_datum'] == 'unstated':
                meta.update(vertical_datum=params['vertical_datum'], source_vertical_datum=params['vertical_datum'])
        affine = ds.transform
        cap = params['support_class']
        if crs == dest and affine.a == -affine.e > 0 and not (affine.b or affine.d):
            transform, shape, resolution = affine, ds.shape, affine.a
            write_native(ds, crs, meta, counts, output, work, cap)
        else:
            if ds.width * ds.height > raster.MAX_CELLS:
                raise ValueError('non-native projection exceeds the warp cell limit')
            grid = read_grid(ds, crs, meta, counts)
            resolution = raster.spacing(grid, dest)
            transform, shape = raster.layout([grid], dest, resolution)
            data, support = raster.warp(grid, cap, transform, shape, dest)
            raster.write_cog(output / 'grid.tif', data, dest, transform, float(raster.NODATA),
                             dict(vertical_datum=meta['vertical_datum'], value_convention=raster.VALUE_UP))
            raster.write_cog(output / 'support.tif', support, dest, transform, 0, {})
        bounds = rasterio.transform.array_bounds(*shape, transform)
        # The gridder writes mean elevation in band 1 and contributor extrema
        # in bands 2 and 3; neither extreme is the elevation surface or support.
        ignored = [dict(band=i, role=role, description=ds.descriptions[i - 1])
                   for i, role in ((2, 'contributor_min'), (3, 'contributor_max')) if ds.count == 3]
        sidecar = dict(schema='sc-relief-normalized/1', original_sha256=source_sha, normalizer_digest=code,
                       params=params, source_crs=original.to_wkt(), source_transform=list(affine)[:6],
                       source_band=1, source_scale=ds.scales[0], source_offset=ds.offsets[0], ignored_bands=ignored,
                       variable_resolution_bag=False, crs=dest.to_string(), transform=list(transform)[:6],
                       bounds_wgs84=transform_bounds(dest, 'EPSG:4326', *bounds), shape=list(shape),
                       resolution_m=resolution, units='m', value_convention=raster.VALUE_UP, **meta)
    sidecar['outputs'] = {name: receipts.sha256_file(output / name) for name in ('grid.tif', 'support.tif')}
    receipts.write_json_atomic(output / 'sidecar.json', sidecar)


def normalize_archive(source, cache, *, family, member=None, lidar_id=None, convention=None, datum=None):
    """Return a receipt result for one original archive member or one lidar pair."""
    source = local_path(source)
    if family not in FAMILIES or datum not in DATUM_NAMES | {None}:
        raise ValueError('unknown archive family or vertical datum')
    lidar, count, adapter, expected = None, None, None, None
    if family == 'lidar-grid':
        if not lidar_id or source.suffix.lower() != '.json' or member is not None or datum or convention:
            raise ValueError('lidar requires the index and a lidar ID, not a standalone/count TIFF or override')
        source, count, lidar, expected = lidar_pair(source, lidar_id)
        datum, convention = lidar['vertical_datum'], raster.VALUE_UP
    else:
        if lidar_id is not None:
            raise ValueError('lidar ID is only for indexed lidar')
        member, adapter = select_member(source, family, member)
    files = [receipts.Input(source, 'source')]
    if count is not None:
        files.append(receipts.Input(count, 'lidar-count'))
    stats = [raster.fingerprint(item.path) for item in files]
    hashes = tuple(receipts.sha256_file(item.path) for item in files)
    if expected is not None and hashes != expected:
        raise ValueError('lidar input checksum differs from the index')
    params = dict(family=family, archive_member=member, lidar=lidar, vertical_datum=datum,
                  count_sha256=hashes[1] if count is not None else None, source_value_convention=convention,
                  support_class=1 if family == 'cinms' else 2, adapter=None, gdal=rasterio.__gdal_version__)
    code_files = [__file__, raster.__file__]
    if adapter is not None:
        code_files.append(adapter.__file__)
    code = receipts.stage_digest((Path(path).name, path) for path in code_files if path is not None)
    key = receipts.sha256_bytes(receipts.canonical(dict(code=code, params=params)))
    cache = Path(cache).expanduser().resolve()
    shared = receipts.Region(cache / '_receipts' / key, hashes[0])

    def produce(output):
        produce_rasters(source, count, output, params, hashes[0], code, adapter)
        if [raster.fingerprint(item.path) for item in files] != stats:
            raise ValueError('archive or lidar inputs changed during normalization')

    return receipts.run_stage(receipts.StageRun(region=shared, stage=STAGE, build=produce,
                              code_digest=code, plan=receipts.Plan(inputs=files, params=params),
                              target=str(cache / hashes[0] / key)))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='region.py normalize-archives', description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--family', choices=FAMILIES, required=True)
    parser.add_argument('--member')
    parser.add_argument('--lidar-id')
    parser.add_argument('--convention', choices=(raster.VALUE_UP, raster.VALUE_DOWN))
    parser.add_argument('--datum', choices=sorted(DATUM_NAMES))
    args = vars(parser.parse_args(argv))
    try:
        result = normalize_archive(**args)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{STAGE}: {exc}\n')
    print(result.line())
    return result.exit_code


if __name__ == '__main__':
    raise SystemExit(main())
