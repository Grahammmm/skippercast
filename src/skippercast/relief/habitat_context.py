"""Build regional seafloor context from held, reviewed inputs; never publish.

Pass --exclusions a current, reviewed WGS84 FeatureCollection of closures for
this region (region_id required). Military island holds also apply independently
of that input. Use --wave-qualification with the Wave 2A qualification JSON and
--wave-root with its archive root; repeat --wave-layer to select the relevant
qualified polygon archives. --ds3091 takes the original TIFF or its distribution
ZIP with the reviewed SHA-256; --historical-kelp uses the pinned checkout's
existing CDFW-derived survey-habitat file. No access or depth clearance is implied.

R6: include layers/public/habitat/survey-habitat.geojson in layer_paths and
habitat_context in --upstream if the receipt is current and contains that output.
The FeatureCollection's sources are context provenance, not relief depth bands.
"""
from __future__ import annotations

import io
import json
from math import ceil, floor, isfinite
from pathlib import Path
import re
import tarfile

from skippercast.paths import repo_root
from skippercast.relief import receipts

TARGET = 'layers/public/habitat'
LAYER = 'survey-habitat.geojson'
WAVE_PREFIX = 'usgs-of2005-1170-'
WAVE_LAYERS = ('nanphab', 'sanahab', 'sanphab', 'secruhab')
DS3091 = 'cdfw-ds3091-predicted-substrate'
KELP = 'cdfw-kelp-2016'
MILITARY = {'san-clemente', 'san-nicolas'}
SURVEY_KIND = {'h': 'rock', 'm': 'mixed', 's': 'sediment'}
PREDICTED_KIND = {1: ('rock', 'hard'), 2: ('sediment', 'soft')}
WAVE_CITATION = 'https://pubs.usgs.gov/of/2005/1170/'
_MBARI = re.compile(r'\bmbari\b|monterey bay aquarium research institute', re.I)
_UNCLEARED_LICENSES = {'unknown', 'unlicensed', 'unresolved', 'metadata-review-needed'}


def add_arguments(parser):
    parser.add_argument('--exclusions', type=Path, required=True)
    parser.add_argument('--wave-qualification', type=Path)
    parser.add_argument('--wave-root', type=Path)
    parser.add_argument('--wave-layer', action='append', choices=WAVE_LAYERS, default=[])
    parser.add_argument('--ds3091', type=Path)
    parser.add_argument('--ds3091-sha256')
    parser.add_argument('--historical-kelp', action='store_true')


def _inputs(ctx):
    root, args = repo_root(), ctx.args
    inputs = {
        'region': root / 'regions' / ctx.region.id / 'region.json',
        'military': root / 'regions/outer-islands-borderland/region.json',
        'rights': root / 'catalog/sources.json',
        'exclusions': args.exclusions,
    }
    if args.wave_layer:
        inputs['qualification'] = args.wave_qualification
        for layer in sorted(set(args.wave_layer)):
            sid = WAVE_PREFIX + layer
            inputs[sid] = args.wave_root / 'usgs_of2005_1170' / sid / f'{layer}.tgz'
    if args.ds3091 is not None:
        inputs[DS3091] = args.ds3091
    if args.historical_kelp:
        inputs[KELP] = root / 'dist/regions/southern-california/survey-habitat.geojson'
    return inputs


def plan(ctx):
    args = ctx.args
    if (bool(args.wave_layer) != (args.wave_qualification is not None and args.wave_root is not None)
            or (not args.wave_layer and (args.wave_qualification or args.wave_root))):
        raise receipts.ReceiptError('wave input requires --wave-layer, --wave-qualification and --wave-root together')
    if args.ds3091 is not None:
        if not receipts.HEX64.fullmatch(args.ds3091_sha256 or ''):
            raise receipts.ReceiptError('--ds3091 requires a reviewed --ds3091-sha256')
    elif args.ds3091_sha256 is not None:
        raise receipts.ReceiptError('--ds3091-sha256 requires --ds3091')
    if not (args.wave_layer or args.ds3091 or args.historical_kelp):
        raise receipts.ReceiptError('at least one habitat source is required')
    return receipts.Plan([receipts.Input(path, role) for role, path in _inputs(ctx).items()],
                         params={'ds3091_sha256': args.ds3091_sha256})


def _public_source(catalog, sid):
    rows = [row for row in catalog['sources'] if row['id'] == sid]
    row = rows[0] if len(rows) == 1 else {}
    rights = row.get('rights', {})
    fields = ('license', 'attribution', 'terms_url')
    if (_MBARI.search(json.dumps(row)) or row.get('review_status') != 'approved'
            or row.get('publication_allowed') is False
            or rights.get('public_display') != 'allowed'
            or rights.get('commercial_use') != 'allowed'
            or not all(isinstance(rights.get(k), str) and rights[k].strip() for k in fields)
            or rights['license'].strip().lower() in _UNCLEARED_LICENSES):
        raise receipts.Held(f'{sid}: no approved public-display rights row')
    return {'id': sid, 'name': row['name'], 'source_url': row.get('documentation_url'),
            'rights': {k: rights[k] for k in (*fields, 'public_display', 'commercial_use')}}


def _box(bounds):
    from shapely.geometry import box

    w, s, e, n = bounds
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError('invalid WGS84 bounds')
    return box(w, s, e, n)


def _features(doc):
    if doc.get('type') != 'FeatureCollection' or 'crs' in doc or not isinstance(doc.get('features'), list):
        raise ValueError('expected an RFC 7946 FeatureCollection')
    return doc['features']


def _polygon(document, *, strict=False):
    from shapely.geometry import shape

    geom = shape(document)
    if (geom.geom_type not in ('Polygon', 'MultiPolygon') or geom.is_empty or geom.has_z
            or not all(isfinite(value) for value in geom.bounds) or (strict and not geom.is_valid)):
        raise ValueError('expected valid 2D polygon coordinates')
    return geom


def _clip_area(region, military, exclusions, region_id):
    from shapely.geometry.base import BaseGeometry
    from shapely.ops import unary_union

    if region['id'] != region_id or exclusions.get('region_id') != region_id:
        raise ValueError('region or exclusion snapshot does not match --region')
    focus = military['map']['focus_areas']
    holds = {row['id']: _box(row['bounds']) for row in focus if row['id'] in MILITARY}
    if holds.keys() != MILITARY:
        raise receipts.Held('missing military hold footprint')
    masks: list[BaseGeometry] = [*holds.values()]
    for feature in _features(exclusions):
        geom = _polygon(feature['geometry'], strict=True)
        _box(geom.bounds)  # reject projected coordinates in a WGS84 screen
        masks.append(geom)
    return _box(region['bounds']).difference(unary_union(masks))


def _polygon_parts(geom):
    if geom.is_empty:
        return
    if geom.geom_type == 'Polygon' and geom.area > 0:
        yield geom
    elif geom.geom_type in ('GeometryCollection', 'MultiPolygon'):
        for part in geom.geoms:
            yield from _polygon_parts(part)


def _wave_polygons(raw, layer, qualification, digest):
    import pyproj
    import shapefile
    from shapely import transform

    sid = WAVE_PREFIX + layer
    matches = [row for row in qualification['rows'] if row['wave2a_id'] == sid]
    row = matches[0] if qualification.get('schema') == 'habitat-2a-qualify/1' and len(matches) == 1 else {}
    if (row.get('sha256') != digest or row.get('geometry') != 'POLYGON'
            or not row.get('usable_as', '').startswith('measured habitat classes')
            or row.get('epsg') != 26910):
        raise receipts.Held(f'{sid}: archive does not match Wave 2A polygon qualification')
    # Read only the named members; never extract an archive into the workspace.
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:*') as archive:
        members = {}
        for suffix in ('shp', 'dbf', 'prj'):
            name = f'{layer}.{suffix}'
            matches = [member for member in archive.getmembers() if member.name == name]
            if len(matches) != 1 or not matches[0].isfile():
                raise ValueError(f'{sid}: missing or ambiguous {name}')
            stream = archive.extractfile(matches[0])
            if stream is None:
                raise ValueError(f'{sid}: unreadable {name}')
            with stream:
                members[suffix] = stream.read()
    crs = pyproj.CRS.from_wkt(members['prj'].decode('utf-8-sig').strip())
    if not crs.equals(pyproj.CRS.from_epsg(26910)):
        raise ValueError(f'{sid}: native CRS does not match qualification')
    project = pyproj.Transformer.from_crs(crs, 4326, always_xy=True).transform
    with shapefile.Reader(shp=io.BytesIO(members['shp']), dbf=io.BytesIO(members['dbf'])) as reader:
        for item in reader.iterShapeRecords(fields=['BOTTOM_ID', 'CODE']):
            props = item.record.as_dict()
            bottom, code = props['BOTTOM_ID'], props['CODE']
            if bottom in SURVEY_KIND and bottom in row['bottom_id_counts_by_code'].get(code, []):
                geom = transform(_polygon(item.shape.__geo_interface__), project, interleaved=False)
                yield geom, SURVEY_KIND[bottom], code, row['survey_dates']


def _predicted_polygons(path, bounds):
    import numpy as np
    import rasterio
    from rasterio.features import shapes
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, from_bounds
    from pyproj import Transformer
    from shapely import transform

    # Only local regular inputs from Path. No GDAL URL, VRT, PAM or sidecar access.
    locator = f'zip://{path.resolve()}!v1_final/tiff/ds3091.tif' if path.suffix.lower() == '.zip' else path
    with rasterio.Env(GDAL_PAM_ENABLED='NO', GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', PROJ_NETWORK='OFF'):
        with rasterio.open(locator, driver='GTiff') as ds:
            if ds.driver != 'GTiff' or ds.crs is None or ds.count != 1:
                raise ValueError('expected the single-band georeferenced ds3091 GeoTIFF')
            projected = transform_bounds('EPSG:4326', ds.crs, *bounds)
            w, s, e, n = projected
            if w >= ds.bounds.right or s >= ds.bounds.top or e <= ds.bounds.left or n <= ds.bounds.bottom:
                return
            # Boundless=False clips to dataset; expanding to integer pixel edges
            # ensures an intersecting cell cannot be lost on a region boundary.
            window = from_bounds(max(w, ds.bounds.left), max(s, ds.bounds.bottom),
                                 min(e, ds.bounds.right), min(n, ds.bounds.top), ds.transform)
            col, row = floor(window.col_off), floor(window.row_off)
            window = Window(col, row, ceil(window.col_off + window.width) - col,
                            ceil(window.row_off + window.height) - row)
            data = ds.read(1, window=window, masked=True)
            affine = ds.window_transform(window)
            project = Transformer.from_crs(ds.crs, 4326, always_xy=True).transform
    valid = ~np.ma.getmaskarray(data) & np.isin(data.data, tuple(PREDICTED_KIND))
    classes = np.where(valid, data.data, 0).astype('uint8')
    for polygon, value in shapes(classes, mask=valid, transform=affine):
        kind, source_class = PREDICTED_KIND[int(value)]
        yield transform(_polygon(polygon), project, interleaved=False), kind, source_class, None


def _historical_polygons(document):
    for feature in _features(document):
        props = feature['properties']
        if (props.get('source_id') == KELP and props.get('habitat_kind') == 'kelp'
                and props.get('evidence_kind') == 'historical-habitat-context'
                and props.get('island') not in MILITARY and props.get('military_access') in (None, 'verified')
                and props.get('fishing_target') is False
                and props.get('source_date') == '2016-09-03 to 2016-09-25'):
            yield (_polygon(feature['geometry']), 'kelp', props['native_source_codes'], props['source_date'])


def build(ctx, out_dir):
    from shapely import make_valid, normalize, orient_polygons
    from shapely.geometry import mapping

    inputs = _inputs(ctx)
    pending = receipts.read_receipt(ctx.region.receipt_path('habitat_context'))
    if pending is None:
        raise receipts.ReceiptError('missing habitat_context attempt receipt')
    pins = {row['role']: row['sha256'] for row in pending['inputs']}

    def pinned(role):
        data = inputs[role].read_bytes()
        if receipts.sha256_bytes(data) != pins[role]:
            raise ValueError(f'{role} changed during packaging')
        return data

    catalog = json.loads(pinned('rights'))
    source_ids = sorted(sid for sid in inputs if sid.startswith(WAVE_PREFIX) or sid in (DS3091, KELP))
    sources = {sid: _public_source(catalog, sid) for sid in source_ids}
    region = json.loads(pinned('region'))
    clip = _clip_area(region, json.loads(pinned('military')), json.loads(pinned('exclusions')), ctx.region.id)
    qualification = json.loads(pinned('qualification')) if 'qualification' in inputs else None
    features, represented = {}, set()
    for sid, source in sources.items():
        source['input_sha256'] = pins[sid]
        if sid.startswith(WAVE_PREFIX):
            evidence = 'measured'
            source['source_url'] = WAVE_CITATION
            source['method'] = 'USGS surveyed interpretation from sidescan, video and samples; not depth or cell certification'
            rows = _wave_polygons(pinned(sid), sid.removeprefix(WAVE_PREFIX), qualification, pins[sid])
        elif sid == DS3091:
            evidence = 'predicted'
            source['method'] = 'CDFW rugosity proxy; includes interpolated inputs; hard/soft, not surveyed substrate'
            if pins[sid] != ctx.args.ds3091_sha256:
                raise receipts.Held('ds3091 archive does not match the reviewed hash')
            rows = _predicted_polygons(inputs[sid], clip.bounds) if not clip.is_empty else ()
        else:
            evidence = 'historical'
            source['method'] = 'Dated 2016 canopy and subsurface detections; never current kelp'
            rows = _historical_polygons(json.loads(pinned(sid)))
        for geom, kind, source_class, date in rows:
            for part in _polygon_parts(make_valid(geom).intersection(clip)):
                geometry = mapping(orient_polygons(normalize(part)))
                props = {'habitat_kind': kind, 'evidence_class': evidence, 'source_id': sid,
                         'source_class': source_class, 'source_date': date, 'fishing_target': False,
                         'fishing_export': False, 'depth_qualified': False}
                ident = 'hab-' + receipts.sha256_bytes(receipts.canonical([geometry, props]))[:24]
                features[ident] = {'type': 'Feature', 'id': ident, 'geometry': geometry,
                                   'properties': dict(props, id=ident)}
                represented.add(sid)
        if sid == DS3091 and receipts.sha256_file(inputs[sid]) != pins[sid]:
            raise ValueError('ds3091 changed during polygonization')

    if features:
        document = {'type': 'FeatureCollection', 'schema_version': 1, 'layer': 'habitat',
                    'region_id': ctx.region.id, 'disclaimer': 'NOT FOR NAVIGATION',
                    'sources': [sources[sid] for sid in sorted(represented)],
                    'features': [features[key] for key in sorted(features)]}
        (out_dir / LAYER).write_bytes(receipts.canonical(document) + b'\n')
    return {'features': len(features), 'military_islands_withheld': sorted(MILITARY)}
