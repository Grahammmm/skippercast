"""Select local relief inputs for the public scope; never publish them.

R3 pairs census files with R2 cache entries by original SHA-256. Geographic,
multiband and archive inputs need a normalized twin. The manifests carry the
support raster pin and a mandatory ceiling on its classes, not a measured flag.
"""

import argparse
from contextlib import ExitStack
import json
import math
import os
from pathlib import Path
import re
import stat

import numpy as np
import rasterio
from rasterio.warp import transform, transform_bounds
from rasterio.windows import Window

from . import receipts

REPO = Path(__file__).resolve().parents[3]
SHA = re.compile(r'[0-9a-f]{64}')
TIFF = {'.tif', '.tiff'}
DATUMS = {'MLLW', 'NAVD88', 'MSL', 'EGM2008', 'unstated', 'instantaneous_sea_level'}
UP = 'elevation_positive_up'
DOWN = 'depth_positive_down'
CAPS = {'interpolated': 1, 'unknown': 2, 'compiled': 2, 'measured': 3}
# Exact census family aliases for single known deliveries (no fuzzy match on
# distributor, attribution, or an unrelated product with the same resolution).
FAMILY_IDS = {
    'nbs_bluetopo': 'noaa-bluetopo', 'cudem_ninth': 'noaa-cudem-ca-ninth-8483',
    'ncmp_topobathy_2014': 'usace-ncmp-ca-5189', 'ncmp_topobathy_2015': 'usace-ncmp-ca-8482',
    'noaa_morrobay_topobathy_2022': 'noaa-morro-bay-topobathy-2022-9630',
    'ncmp_laz_9629': 'noaa-morro-bay-topobathy-2022-9629',
    'coned_southern': 'usgs-coned-ca-8658', 'coned_northern': 'usgs-coned-ca-9181',
    'nccos_cinms': 'noaa-cinms-bathymetry-2025',
}
NORMALIZABLE = {None, 'requires_projected_metre_grid', 'non_square_grid', 'rotated_or_south_up',
                'nontrivial_band_scale_or_offset', 'not_direct_raster', 'requires_regularization'}


def read_json(path):
    return json.loads(path.read_bytes())


def local_path(value):
    """Confine inputs to ordinary local paths without traversing symlinks."""
    if not isinstance(value, (str, Path)) or '://' in str(value):
        raise ValueError('not a local path')
    path = Path(value).expanduser().absolute()
    if ('..' in path.parts or str(path).startswith('/vsi')
            or Path('/mnt/privatevault') in (path, *path.parents)):
        raise ValueError('unsafe input path')
    for part in (*reversed(path.parents), path):
        try:
            if stat.S_ISLNK(part.lstat().st_mode):
                raise ValueError('symlink input refused')
        except FileNotFoundError:
            break
    return path


def box_of(doc):
    box = doc['bounds']
    if (not isinstance(box, list) or len(box) != 4
            or not all(type(v) in (int, float) and math.isfinite(v) for v in box)
            or not (-180 <= box[0] < box[2] <= 180 and -90 <= box[1] < box[3] <= 90)):
        raise ValueError('expected WGS84 bounds [west, south, east, north]')
    return box


def rights_index(rows):
    index = {}
    for r in rows:
        for key in {r['id'], r.get('acquisition_id'), r.get('url'), r.get('data_url')} - {None}:
            if key in index and index[key] != r:
                index[key] = None  # exact but ambiguous binding is not an approval
            else:
                index[key] = r
    return index


def registry_row(row, index):
    explicit = row.get('catalog_id') or row.get('source_id')
    if explicit:
        return index.get(explicit)
    for key in (row.get('id'), row.get('url')):
        if key in index:
            return index[key]
    return index.get(FAMILY_IDS.get(row.get('family')))


def public_rights(registry):
    if registry is None:
        return 'unknown', 'no_unambiguous_registry_binding', None
    rights = registry.get('rights', {})
    display = rights.get('public_display')
    if display == 'excluded':
        return 'excluded', 'registry_excluded', None
    # The operative decision covers display, not technical review or raw
    # redistribution. An owner record explains an allowance but cannot grant it.
    if display != 'allowed':
        return 'private', 'registry_public_display_not_allowed', None
    owner = rights.get('owner_public_display') or {}
    basis = owner.get('basis')
    if owner.get('decision') == 'allowed' and isinstance(basis, str) and basis.strip():
        return 'public', 'registry_owner_public_display_allowed', basis
    return 'public', 'registry_public_display_allowed', None


def caps_index(doc):
    # The provenance report's source_rows are constituent identities, not a
    # product-wide classification or a spatial mask. R2 applies footprint caps.
    caps = {}
    for row in doc['source_rows']:
        cap = CAPS.get(row.get('cell_label'), 3)
        for key in (row.get('source_id'), (row.get('dem_product_id'), row.get('source_name'))):
            if key and key != (None, None):
                caps[key] = min(caps.get(key, 3), cap)
    return caps


def source_policy(row, ident, raw, caps):
    product = ident.rsplit('-', 1)[-1]
    family = row.get('family', '')
    provenance = row.get('provenance_class')
    compiled = (provenance == 'compiled' or ident.startswith(('usgs-coned-', 'noaa-cudem-'))
                or family in {'nbs_bluetopo', 'ncmp_merge_2616', 'srtm15plus', 'nccos_cinms'})
    cap = min(2 if compiled else 3, caps.get(row.get('provenance_id'), 3),
              caps.get(row.get('id'), 3), caps.get((product, row.get('source_name')), 3),
              caps.get((product, raw.stem), 3), CAPS.get(provenance, 3) if provenance != 'unknown' else 3)
    if re.search(r'(?i)interpolat|void[ _-]?fill|with[ _-]?voids', raw.stem):
        cap = 1
    return compiled, cap


def twins(row, cache, sha):
    """Only look in the source's content bucket, never walk the shared cache."""
    bucket = local_path(cache / sha)
    if not bucket.is_dir():
        return []
    paths = row.get('normalised_paths') or []
    if paths:
        grids = sorted({local_path(p) for p in paths})
        if any(p.name != 'grid.tif' or p.parent.parent != bucket or not SHA.fullmatch(p.parent.name)
               for p in grids):
            raise ValueError('normalized path escapes its content bucket')
        return [p.parent for p in grids]
    return [p for p in sorted(bucket.iterdir()) if SHA.fullmatch(p.name) and not p.is_symlink()
            and local_path(p / 'sidecar.json').is_file()]


def pinned_grid(folder, sha):
    side = read_json(local_path(folder / 'sidecar.json'))
    if (side.get('schema') != 'sc-relief-normalized/1' or side.get('original_sha256') != sha
            or side.get('units') != 'm' or side.get('value_convention') != UP):
        raise ValueError('normalized sidecar does not bind this original metre elevation grid')
    pins = side['outputs']
    grid = local_path(folder / 'grid.tif')
    support = local_path(folder / 'support.tif')
    def verify(path):
        digest = pins.get(path.name)
        if not isinstance(digest, str) or not SHA.fullmatch(digest) or receipts.sha256_file(path) != digest:
            raise ValueError(f'{path.name}: normalized pin mismatch')
        return digest
    grid_sha = verify(grid)
    support_sha = verify(support) if 'support.tif' in pins or support.exists() else None
    return grid, grid_sha, support if support_sha else None, support_sha, side


def grid_metadata(ds, row, side):
    t = ds.transform
    if (ds.driver != 'GTiff' or ds.count != 1 or ds.crs is None or not ds.crs.is_projected
            or ds.crs.linear_units != 'metre' or t.a <= 0 or t.e >= 0 or t.b != 0 or t.d != 0
            or not math.isclose(t.a, -t.e, rel_tol=1e-8) or ds.scales[0] != 1 or ds.offsets[0] != 0):
        raise ValueError('not an admissible single-band projected metre elevation grid')
    if side:
        if (not math.isclose(side['resolution_m'], max(ds.res), rel_tol=1e-8)
                or side.get('transform') != list(t)[:6] or side.get('shape') != list(ds.shape)
                or rasterio.crs.CRS.from_user_input(side['crs']) != ds.crs):
            raise ValueError('normalized sidecar geometry mismatch')
        return side.get('vertical_datum', 'unstated'), UP
    units = ds.units[0] or row.get('units') or (row.get('bands') or [{}])[0].get('units')
    if str(units).lower() not in {'m', 'metre', 'metres', 'meter', 'meters'}:
        raise ValueError('raw vertical metre units are not explicit; normalize first')
    tags = ds.tags()
    return row.get('vertical_datum') or tags.get('vertical_datum', 'unstated'), (
        row.get('value_convention') or tags.get('value_convention') or UP)


def check_support(ds, support):
    if (support.driver != 'GTiff' or support.count != 1 or support.dtypes[0] != 'uint8'
            or support.crs != ds.crs or support.transform != ds.transform or support.shape != ds.shape):
        raise ValueError('support raster must be aligned uint8 on the elevation grid')


def certified_counts(ds, support, bounds):
    """Exact class-3 cell centres within the WGS84 box, in bounded windows."""
    t = ds.transform
    w, s, e, n = bounds
    a = b = 0
    for y in range(0, ds.height, 512):
        for x in range(0, ds.width, 512):
            win = Window(x, y, min(512, ds.width - x), min(512, ds.height - y))
            mask = support.read(1, window=win, masked=True)
            yy, xx = np.nonzero(np.asarray(mask.filled(0) == 3))
            if not len(xx):
                continue
            zs = ds.read(1, window=win, masked=True)[yy, xx]
            lon, lat = map(np.asarray, transform(ds.crs, 'EPSG:4326',
                                                t.c + (x + xx + .5) * t.a, t.f + (y + yy + .5) * t.e))
            keep = (~np.ma.getmaskarray(zs) & np.isfinite(zs.data)
                    & (lon >= w) & (lon <= e) & (lat >= s) & (lat <= n))
            a += int(np.count_nonzero(keep & (zs.data >= -20) & (zs.data <= 0)))
            b += int(np.count_nonzero(keep & (zs.data >= -91.44) & (zs.data < -20)))
    return a, b


def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def inspect_grid(grid, support, row, side, cap, bounds):
    with rasterio.Env(GDAL_PAM_ENABLED='NO', GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', PROJ_NETWORK='OFF'), ExitStack() as ctx:
        ds = ctx.enter_context(rasterio.open(grid, driver='GTiff'))
        datum, convention = grid_metadata(ds, row, side)
        if datum not in DATUMS or convention not in {UP, DOWN}:
            raise ValueError('unsupported vertical datum or sign')
        if not overlaps(transform_bounds(ds.crs, 'EPSG:4326', *ds.bounds), bounds):
            raise ValueError('grid does not overlap region')
        a = b = 0
        if support:
            mask = ctx.enter_context(rasterio.open(support, driver='GTiff'))
            check_support(ds, mask)
            if cap == 3:
                a, b = certified_counts(ds, mask, bounds)
        return max(ds.res), datum, convention, a, b


def native_zoom(resolution, a):
    if resolution <= 1 and a:
        return 17
    return 15 if resolution <= 2 or resolution == 5 else None


def selection(row, bound, directory, rights_reason, basis, caps, bounds):
    raw = local_path(row['path'])
    sha = receipts.sha256_file(raw)
    expected = row.get('sha256_receipt') or row.get('sha256')
    if expected and sha != expected:
        raise ValueError('original census hash changed')
    if directory is not None:
        grid, grid_sha, support, support_sha, side = pinned_grid(directory, sha)
    else:
        if row.get('admissible_now') is not True or raw.suffix.lower() not in TIFF:
            raise ValueError('no_admissible_normalized_twin')
        if any(local_path(str(raw) + suffix).exists() for suffix in ('.msk', '.aux.xml')):
            raise ValueError('external mask or auxiliary metadata requires normalization')
        grid, grid_sha, support, support_sha, side = raw, sha, None, None, None
    compiled, cap = source_policy(row, bound['id'], raw, caps)
    cap = min(cap, CAPS.get(side.get('params', {}).get('label'), 3)) if side else cap
    if not support:
        cap = min(cap, 2)
    res, datum, convention, a, b = inspect_grid(grid, support, row, side, cap, bounds)
    # Manifest IDs are unique per census path, not per registry product.
    src_id = f"{bound['id']}-{receipts.sha256_bytes(str(raw).encode())[:16]}"
    rights = bound['rights']
    attribution = rights['attribution']
    citation = bound.get('documentation_url') or rights.get('terms_url')
    if not all(isinstance(x, str) and x.strip() for x in (attribution, citation)):
        raise ValueError('registry lacks citation or attribution')
    area = {'0-20m': a * res**2, '20-91.44m': b * res**2}
    priority = 'compiled' if compiled else 'certified-support' if a or b else 'estimated'
    entry = dict(id=src_id, source_id=bound['id'], path=str(grid), sha256=grid_sha,
                 resolution_m=res, units='m', value_convention=convention, vertical_datum=datum,
                 vertical_offset_m=0, offset_note='Nominal source datum; no vertical conversion.',
                 citation=citation, attribution=attribution, rights=basis or rights_reason,
                 rights_class='public', rights_basis=basis, label='estimated', priority_class=priority,
                 support_path=str(support) if support else None, support_sha256=support_sha,
                 support_class_cap=cap, max_zoom=native_zoom(res, a))
    return entry, area


def add_parser():
    parser = argparse.ArgumentParser(prog='region.py select', description=__doc__)
    parser.add_argument('--region', required=True)
    parser.add_argument('--out', default=os.environ.get('SC_RELIEF_OUT'), required=not os.environ.get('SC_RELIEF_OUT'))
    parser.add_argument('--scope', choices=('public',), default='public')
    parser.add_argument('--cache', type=Path, default=os.environ.get('SC_RELIEF_NORM',
                        '/mnt/agentorange-backup/seafloor-relief-cache/_norm'))
    parser.add_argument('--registry', type=Path, default=REPO / 'catalog/sources.json')
    parser.add_argument('--provenance', type=Path, default=os.environ.get('SC_RELIEF_PROVENANCE',
                        'PROVENANCE-LABELS.json'))
    parser.add_argument('--region-config', type=Path, help='defaults to regions/<id>/region.json')
    return parser


def main(argv=None):
    parser = add_parser()
    args = parser.parse_args(argv)
    try:
        region = receipts.Region(local_path(args.out), args.region)
        census = local_path(region.dir / 'census.json')
        config = local_path(args.region_config or REPO / 'regions' / region.id / 'region.json')
        registry, provenance, cache = map(local_path, (args.registry, args.provenance, args.cache))
        census_receipt = local_path(region.receipt_path('census'))
        legacy = census_receipt.is_file() and read_json(census_receipt).get('scope') == 'local'
        upstream = (receipts.Ref('census'),) if census_receipt.is_file() and not legacy else ()
        planned, reports = [], []

        def plan(upstream_docs):
            inputs = [receipts.Input(p, role) for p, role in ((census, 'census'), (config, 'region'),
                                                              (registry, 'registry'), (provenance, 'provenance'))]
            if any(not Path(i.path).is_file() for i in inputs):
                return receipts.Plan(inputs=inputs)
            if upstream_docs or legacy:
                r1 = read_json(census_receipt) if legacy else upstream_docs['census']
                if (r1.get('stage') != 'census' or r1.get('region') != region.id or r1.get('status') != 'ok'
                        or not any(out['path'] in {str(census), 'census.json'}
                                   and out['sha256'] == receipts.sha256_file(census) for out in r1['outputs'])):
                    raise ValueError('census receipt does not pin this region census')
                if legacy:
                    inputs.append(receipts.Input(census_receipt, 'legacy-census-receipt'))
            doc = read_json(census)
            bounds = box_of(read_json(config))
            index = rights_index(read_json(registry)['sources'])
            caps = caps_index(read_json(provenance))
            if doc['summary']['region'] != region.id:
                raise ValueError('census region mismatch')
            seen_paths = set()
            for row in sorted(doc['files'], key=lambda r: (r['path'], receipts.canonical(r))):
                bound = registry_row(row, index)
                rights, reason, basis = public_rights(bound)
                report = dict(path=row['path'], source_id=bound['id'] if bound else None, rights_class=rights,
                              rights_basis=basis, decision='skipped', reason=reason,
                              certified_area_m2_by_depth_band={'0-20m': 0, '20-91.44m': 0})
                reports.append(report)
                if rights != 'public':
                    continue
                if row.get('kind') not in {'elevation', 'archive'} or row.get('hold_reason') not in NORMALIZABLE:
                    report['reason'] = row.get('hold_reason') or 'not_elevation'
                    continue
                try:
                    raw = local_path(row['path'])
                    if raw in seen_paths:
                        raise ValueError('duplicate_census_path')
                    seen_paths.add(raw)
                    if not raw.is_file():
                        raise ValueError('original_missing')
                    sha = row.get('sha256_receipt') or row.get('sha256') or receipts.sha256_file(raw)
                    if not isinstance(sha, str) or not SHA.fullmatch(sha):
                        raise ValueError('invalid_original_sha256')
                    found = twins(row, cache, sha)
                    if len(found) > 1:
                        raise ValueError('ambiguous_normalized_twins')
                    folder = found[0] if found else None
                    inputs.append(receipts.Input(raw, 'original'))
                    if folder:
                        inputs.extend(receipts.Input(p, f'normalized-{p.name}') for name in
                                      ('sidecar.json', 'grid.tif', 'support.tif')
                                      if (p := local_path(folder / name)).is_file())
                    planned.append((report, row, bound, folder, reason, basis, caps, bounds))
                except (OSError, ValueError) as exc:
                    report['reason'] = str(exc)
            # Paths matter to a manifest even when content is identical.
            return receipts.Plan(inputs=inputs, params={'scope': 'public', 'cache': str(cache),
                                                       'input_paths': [str(i.path) for i in inputs]})

        def produce(output):
            sources = []
            for report, row, bound, folder, reason, basis, caps, bounds in planned:
                try:
                    entry, area = selection(row, bound, folder, reason, basis, caps, bounds)
                    sources.append(entry)
                    report.update(decision='included', reason=reason, id=entry['id'],
                                  certified_area_m2_by_depth_band=area)
                except (OSError, ValueError, KeyError, rasterio.errors.RasterioError) as exc:
                    report['reason'] = str(exc)
            order = {'certified-support': 0, 'estimated': 1, 'compiled': 2}
            sources.sort(key=lambda s: (order[s['priority_class']], s['resolution_m'], s['id']))
            tables = {'sources': {'schema_version': 1, 'scope': 'public', 'sources': sources},
                      'native': [s for s in sources if s['max_zoom'] is not None],
                      'selection': {'schema_version': 1, 'scope': 'public', 'region': region.id, 'files': reports,
                                    'area_basis': 'Nominal projected cell area per file; overlaps not deduplicated.'}}
            for name, table in tables.items():
                (output / f'{name}.json').write_bytes(receipts.canonical(table))
            return {'selected': len(sources), 'census_files': len(reports)}

        stage = receipts.StageRun(region, 'select', produce, receipts.stage_digest([('select.py', __file__)]),
                                  upstream=upstream, plan=plan)
        result = receipts.run_stage(stage)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'select: {exc}\n')
    print(result.line())
    return result.exit_code
