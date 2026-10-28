"""Produce and remeasure private-mapping-input-v2 from native source cells.

The producer label is informational. Verification independently reopens the
source and support artifacts and recomputes every scientific fact.
"""
import hashlib
import importlib.metadata
import json
from pathlib import Path

from .common import (confined, digest, load, ref, resolve, review_holds, write, native_container,
                     validate_native_source, validate_derived_geotiff)

SCHEMA = 'private-mapping-input-v2'
MAX_CELLS = 262_144


def libraries():
    result = {}
    for name in ('numpy', 'rasterio', 'shapely', 'pyproj', 'h5py', 'scipy'):
        result[name] = importlib.metadata.version(name)
    import rasterio
    result.update(gdal=rasterio.__gdal_version__, proj=rasterio.__proj_version__)
    return result


def implementation():
    # Bind all algorithm modules; the parent supplies an additional job code hash.
    import skippercast.coastal.vertical as vertical
    from skippercast.coastal import bag_v2 as bag
    from skippercast.seafloor.adapters import regular_bag_window
    from skippercast.platform import bottom_targets
    paths = [Path(__file__), Path(__file__).with_name('common.py'), Path(vertical.__file__),
             Path(bag.__file__), Path(regular_bag_window.__file__), Path(bottom_targets.__file__)]
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def _array_hash(values):
    import numpy as np
    a = np.ascontiguousarray(values)
    return hashlib.sha256(a.tobytes()).hexdigest()


def _support(valid, transform, crs):
    import numpy as np
    from rasterio.features import shapes
    from shapely.geometry import shape, mapping
    from shapely.ops import unary_union, transform as project
    from pyproj import Transformer
    parts = [shape(g) for g, v in shapes(valid.astype('uint8'), mask=valid, transform=transform) if v]
    geometry = unary_union(parts)
    area = project(Transformer.from_crs(crs, 'EPSG:3310', always_xy=True).transform, geometry).area
    return dict(scope='valid_cell', crs=crs.to_string(), geometry=mapping(geometry), area_m2=float(area),
                valid_cells=int(valid.sum()), mask_sha256=_array_hash(valid.astype('uint8')))


def _degree_axes(crs):
    """True for a 2-D geographic CRS whose two axes are both plain degrees."""
    import math
    axes = crs.axis_info[:2]
    return (crs.is_geographic and len(axes) == 2
            and all(abs(a.unit_conversion_factor - math.pi/180) <= 1e-12 for a in axes))


def observe(root, source_ref, *, window, vertical, source_row=None, metadata_sha256=None):
    import numpy as np
    import rasterio
    from rasterio.windows import Window
    from pyproj import CRS
    from skippercast.coastal import vertical as semantics
    source = validate_native_source(root, source_ref, netcdf=True)
    netcdf = native_container(source) == 'netcdf'
    if (not isinstance(window, list) or len(window) != 4
            or any(type(v) is not int for v in window)
            or min(window[:2]) < 0 or min(window[2:]) <= 0 or window[2]*window[3] > MAX_CELLS):
        raise ValueError('explicit bounded integer native window required')
    win = Window(*window)
    with rasterio.open(source) as ds:
        if netcdf != (ds.driver == 'netCDF'):
            raise ValueError('netCDF driver/container mismatch')
        if netcdf and (ds.count != 1 or ds.subdatasets):
            raise ValueError('single-variable 2-D netCDF grid required')
        if ds.driver not in ('GTiff', 'BAG', 'netCDF') or not ds.crs:
            raise ValueError('only native GeoTIFF/regular BAG supported')
        if win.col_off + win.width > ds.width or win.row_off + win.height > ds.height:
            raise ValueError('window outside source')
        auxiliary = [ref(root,Path(name),'native-raster-auxiliary-v1') for name in ds.files if Path(name).resolve() != source]
        crs = CRS.from_user_input(ds.crs).to_2d()
        # netCDF only: a north-up geographic (degree) grid such as NOAA CRM is
        # read as native cells; the map stage holds it rather than taking
        # derivatives with degree spacing. GeoTIFF/BAG keep the metric gate.
        geographic = netcdf and _degree_axes(crs)
        if (not (geographic or crs.is_projected)
                or (not geographic and any(abs(a.unit_conversion_factor-1)>1e-10 for a in crs.axis_info[:2]))
                or ds.transform.b or ds.transform.d or ds.transform.a <= 0 or ds.transform.e >= 0):
            raise ValueError('native north-up metric projected grid required' if not netcdf else
                             'native north-up metric projected or geographic-degree netCDF grid required')
        if geographic:
            left, bottom, right, top = ds.window_bounds(win)
            if not (-180 <= left < right <= 180 and -90 <= bottom < top <= 90):
                raise ValueError('geographic netCDF window outside longitude/latitude range')
        metadata = None
        if ds.driver == 'BAG':
            from skippercast.coastal.bag_v2 import parse_metadata
            import h5py
            with h5py.File(source) as bag:
                for name in ('elevation','uncertainty','metadata'):
                    if isinstance(bag['BAG_root'].get(name,getlink=True),h5py.ExternalLink):
                        raise ValueError('BAG external links refused')
                bag_root = bag['BAG_root']
                if 'varres_refinements' in bag_root and bag_root['varres_refinements'].size:
                    raise ValueError('Variable-resolution BAG requires a native-refinement adapter; overview rejected')
                if bag_root['metadata'].size > 1_000_000:
                    raise ValueError('Oversized BAG metadata')
                xml = bag_root['metadata'][:].tobytes().decode().rstrip('\0')
            if hashlib.sha256(xml.encode()).hexdigest() != metadata_sha256:
                raise ValueError('BAG embedded metadata hash mismatch')
            from urllib.parse import urlparse
            survey_id = Path(urlparse(source_row['url']).path).name.split('_')[0]
            metadata = parse_metadata(xml, survey_id)
            from skippercast.seafloor.adapters.regular_bag_window import read_original_regular_bag_window
            native = read_original_regular_bag_window(source, source_row, win,
                                                      expected_metadata_sha256=metadata_sha256)
            raw, valid = native.elevation_m, native.source_pair_valid
        else:
            values = ds.read(1, window=win, masked=True).astype('float64')
            raw = values.filled(np.nan).astype('float64')
            valid = ~np.ma.getmaskarray(values) & np.isfinite(raw)
        # An internal mask cannot make an explicit sentinel into a sounding.
        nodata = ds.nodatavals[0]
        if nodata is not None and np.isfinite(nodata):
            valid &= raw != nodata
        if ds.driver == 'BAG':
            uncertainty_nodata = ds.nodatavals[1]
            if uncertainty_nodata is not None and np.isfinite(uncertainty_nodata):
                valid &= native.product_uncertainty_m != uncertainty_nodata
        observed = semantics.from_raster(ds, source_sha256=source_ref['sha256'], bag_metadata=metadata)
        resolved = semantics.resolve(vertical, observed)
        block, holds = resolved['block'], list(resolved['holds'])
        depth = semantics.to_depth(raw, block, valid=valid) if not holds and block else None
        lane_trim = None
        if depth is not None and semantics.is_deep(block):
            # G3 deep-band datums: cells shallower than the lane floor are not support here.
            kept = valid & np.isfinite(depth)
            lane_trim = dict(depth_lane=block['depth_lane'],
                             lane_floor_m=semantics.LANE_FLOOR_M[block['depth_lane']],
                             cells_dropped_shallower_than_floor=int((valid & ~kept).sum()))
            valid = kept
        tr = ds.window_transform(win)
        support = _support(valid, tr, crs)
        support['support_kind'] = 'native_grid_node_footprints' if ds.driver == 'BAG' else 'native_grid_cell_footprints'
        support['limitations'] = ['Nominal node/cell-associated support; no claim of measurement between observations or continuous surveyed coverage.']
        header = dict(driver=ds.driver, crs=ds.crs.to_wkt(), horizontal_crs=crs.to_string(),
                      shape=[ds.height, ds.width], window=window, transform=list(tr)[:6],
                      resolution_m=list(ds.res), dtypes=list(ds.dtypes), nodata=ds.nodata if ds.nodata is None or np.isfinite(ds.nodata) else 'NaN',
                      scales=list(ds.scales), offsets=list(ds.offsets), units=list(ds.units),
                      descriptions=list(ds.descriptions), tags=ds.tags())
        if netcdf:
            # Degrees are never reported as metres; GeoTIFF/BAG headers are unchanged.
            header.update(netcdf_variable=ds.tags(1).get('NETCDF_VARNAME'),
                          horizontal_units='degree' if geographic else 'metre',
                          resolution_m=None if geographic else list(ds.res),
                          resolution_deg=list(ds.res) if geographic else None)
        if not valid.any():
            holds.append('native_support_empty')
        facts = dict(header=header, observed_vertical=observed, vertical=block, source=source_ref, source_auxiliary=auxiliary,
                     source_lineage=dict(source_row=source_row,metadata_sha256=metadata_sha256),
                     raw_valid_values_sha256=_array_hash(np.where(valid, raw, 0).astype('<f8')),
                     valid_count=int(valid.sum()), valid_fraction=float(valid.mean()), support=support,
                     depth_values_sha256=_array_hash(np.where(valid, depth, 0).astype('<f4')) if depth is not None else None,
                     libs=libraries(), implementation=implementation())
        if lane_trim is not None:
            facts['deep_lane_support'] = lane_trim
        return facts, sorted(set(holds)), raw, valid, tr, crs, depth


def produce(root, source_ref, *, segment_id, window, vertical, rights, output_dir, segment=None,
            review=None, synthetic=False, source_row=None, metadata_sha256=None):
    facts, holds, _, valid, transform, crs, _ = observe(root, source_ref, window=window, vertical=vertical,
                                                       source_row=source_row, metadata_sha256=metadata_sha256)
    holds.extend(bind_segment(root,segment,segment_id,facts))
    facts.update(rights=rights,synthetic=bool(synthetic))
    out = confined(root, output_dir, existing=False)
    out.mkdir(parents=True, exist_ok=True)
    import rasterio
    mask_path = out / 'native-support.tif'
    with rasterio.open(mask_path, 'w', driver='GTiff', width=valid.shape[1], height=valid.shape[0],
                       count=1, dtype='uint8', crs=crs, transform=transform, compress='DEFLATE', nodata=None) as ds:
        ds.write(valid.astype('uint8'), 1)
        ds.set_band_description(1, 'native_valid_support')
    mask_ref = ref(root, mask_path, 'coastal-native-support-v2')
    if rights.get('private_use') is not True or not rights.get('evidence'):
        holds.append('private_rights_evidence_missing')
    for artifact in rights.get('evidence', []):
        resolve(root, artifact)
    payload = dict(schema=SCHEMA, producer='coastal.handoff.mapping_input', segment_id=segment_id,
                   source=source_ref, source_row=source_row, metadata_sha256=metadata_sha256, segment=segment,
                   window=window, declared_vertical=vertical, rights=rights, synthetic=bool(synthetic),
                   native_facts=facts, valid_support=mask_ref, facts_digest=digest(facts),
                   machine_holds=sorted(set(holds)), review=review, publication_prohibited=True)
    write(out / 'mapping-input.json', payload)
    return payload


def _verify_with_observation(root, manifest, *, now, minimum_valid_until=None):
    """Return checked facts and the same freshly authenticated native arrays.

    Keep this internal: callers must honor ``ready`` before consuming arrays.
    The observation is never persisted or reused across verification calls.
    """
    document = load(root, manifest, contract=SCHEMA)
    if document.get('schema') != SCHEMA:
        raise ValueError('mapping input contract mismatch')
    if document.get('publication_prohibited') is not True:
        raise ValueError('mapping input publication prohibition required')
    observation = observe(root, document['source'], window=document['window'],
                        vertical=document['declared_vertical'], source_row=document.get('source_row'),
                        metadata_sha256=document.get('metadata_sha256'))
    facts, holds, _, valid, transform, crs, _ = observation
    holds.extend(bind_segment(root,document.get('segment'),document['segment_id'],facts))
    facts.update(rights=document.get('rights'),synthetic=document.get('synthetic'))
    if digest(facts) != document.get('facts_digest') or digest(facts) != digest(document['native_facts']):
        raise ValueError('native facts changed or forged')
    import rasterio
    import numpy as np
    with rasterio.open(validate_derived_geotiff(root, document['valid_support'], contract='coastal-native-support-v2')) as mask:
        if (mask.count != 1 or mask.dtypes != ('uint8',) or mask.crs != crs
                or mask.transform != transform or mask.shape != valid.shape
                or not np.array_equal(mask.read(1), valid.astype('uint8'))):
            raise ValueError('native support artifact differs from source cells')
    rights = document.get('rights', {})
    if rights.get('private_use') is not True or not rights.get('evidence'):
        holds.append('private_rights_evidence_missing')
    for evidence in rights.get('evidence', []):
        resolve(root, evidence)
    if sorted(set(holds)) != document.get('machine_holds'):
        raise ValueError('machine holds changed')
    holds.extend(review_holds(root, document.get('review'), digest(facts), now=now,
                              minimum_valid_until=minimum_valid_until))
    checked = dict(ready=not holds, holds=sorted(set(holds)), facts_digest=digest(facts), facts=facts,
                   synthetic=document.get('synthetic') is True)
    return checked, observation


def verify(root, manifest, *, now, minimum_valid_until=None):
    checked, _ = _verify_with_observation(root, manifest, now=now,
                                         minimum_valid_until=minimum_valid_until)
    return checked


validate_handoff = verify


def bind_segment(root, segment, segment_id, facts):
    """Authenticate geographic identity and constrain all qualified support."""
    from shapely.geometry import shape, box
    from shapely.ops import transform
    from pyproj import Transformer
    holds = []
    if segment is None:
        facts['segment'] = None
        return ['geographic_segment_record_missing']
    record = load(root, segment, contract='coastal-segment-v1')
    if (record.get('schema') != 'coastal-segment-v1' or record.get('crs') != 'EPSG:3310'
            or record.get('segment_id') != segment_id or not isinstance(record.get('region'), str)
            or not record['region']):
        raise ValueError('geographic segment record identity invalid')
    if not isinstance(segment_id,str):
        raise ValueError('canonical geographic segment ID required')
    parts = segment_id.split(':')
    try:
        if len(parts) != 5 or parts[:2] != ['seg','3310'] or parts[4] != '5000':
            raise ValueError('canonical geographic segment ID required')
        x0, y0 = int(parts[2]), int(parts[3])
        if x0 % 5000 or y0 % 5000:
            raise ValueError('geographic segment origin must use 5 km lattice')
    except (TypeError, ValueError) as error:
        raise ValueError('canonical geographic segment ID required') from error
    bounds = [x0,y0,x0+5000,y0+5000]
    if record.get('bbox') != bounds:
        raise ValueError('segment geometry differs from canonical ID')
    support = facts['support']
    project = Transformer.from_crs(support['crs'],'EPSG:3310',always_xy=True).transform
    native_geometry = transform(project,shape(support['geometry']))
    segment_geometry = box(*bounds)
    intersection_area = native_geometry.intersection(segment_geometry).area
    outside_area = native_geometry.difference(segment_geometry).area
    facts['segment'] = dict(schema='coastal-segment-v1',segment_id=segment_id,region=record['region'],
                            crs='EPSG:3310',bbox=bounds,boundary_policy='all_valid_native_support_contained',
                            halo_m=0,intersection_area_m2=float(intersection_area),
                            outside_support_area_m2=float(outside_area))
    if intersection_area <= 0:
        holds.append('native_support_disjoint_from_segment')
    if outside_area > 1e-6:
        holds.append('native_support_outside_segment')
    return holds
