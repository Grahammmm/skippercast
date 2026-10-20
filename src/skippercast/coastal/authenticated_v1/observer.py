"""Produce and remeasure private-mapping-input-v2 from native source cells.

The producer label is informational. Verification independently reopens the
source and support artifacts and recomputes every scientific fact.
"""
import hashlib
import importlib.metadata
import json
from pathlib import Path

from skippercast.coastal.handoff.common import confined, digest, load, ref, resolve, review_holds, write, validate_native_source, validate_derived_geotiff

SCHEMA = 'coastal-authenticated-observation-v1'
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
    paths = [Path(__file__), Path(__import__('skippercast.coastal.handoff.common',fromlist=['x']).__file__), Path(vertical.__file__),
             Path(bag.__file__), Path(regular_bag_window.__file__), Path(bottom_targets.__file__)]
    paths.extend(Path(__file__).with_name(name) for name in ("snapshot.py","adapter_bag.py","metadata_bag.py","planner.py","worker.py","supplement.py","authority.py","bootstrap.py","policy.py"))
    paths.append(Path(__file__).parent.parent / "_source_bootstrap.py")
    return {str(p.relative_to(Path(__file__).parent)) if p.is_relative_to(Path(__file__).parent) else p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


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


def observe_snapshot(view, root, source_ref, *, window, vertical, source_row=None, metadata_sha256=None, collector=None):
    import numpy as np
    import rasterio
    from rasterio.windows import Window
    from pyproj import CRS
    from skippercast.coastal import vertical as semantics
    from .snapshot import SealedSnapshot
    if type(view) is not SealedSnapshot:raise ValueError("registered capability required")
    provenance=view.provenance
    if source_ref["sha256"]!=provenance["sha256"] or source_ref["bytes"]!=provenance["bytes"]:
        raise ValueError("source logical identity differs from snapshot")
    if source_ref!=provenance['logical_source']:
        raise ValueError("source logical origin mismatch")
    if (not isinstance(window, list) or len(window) != 4
            or any(type(v) is not int for v in window)
            or min(window[:2]) < 0 or min(window[2:]) <= 0 or window[2]*window[3] > MAX_CELLS):
        raise ValueError('explicit bounded integer native window required')
    win = Window(*window)
    with view.open_raster() as ds:
        if ds.driver not in ('GTiff', 'BAG') or not ds.crs:
            raise ValueError('only native GeoTIFF/regular BAG supported')
        if win.col_off + win.width > ds.width or win.row_off + win.height > ds.height:
            raise ValueError('window outside source')
        auxiliary = []  # active capability open_raster already rejects every secondary source
        crs = CRS.from_user_input(ds.crs).to_2d()
        if (not crs.is_projected or any(abs(a.unit_conversion_factor-1)>1e-10 for a in crs.axis_info[:2])
                or ds.transform.b or ds.transform.d or ds.transform.a <= 0 or ds.transform.e >= 0):
            raise ValueError('native north-up metric projected grid required')
        metadata = None
        if ds.driver == 'BAG':
            from .metadata_bag import inspect_metadata
            import h5py
            with view.open_hdf() as bag:
                for name in ('elevation','uncertainty','metadata'):
                    if isinstance(bag['BAG_root'].get(name,getlink=True),h5py.ExternalLink):
                        raise ValueError('BAG external links refused')
                xml = bag['BAG_root']['metadata'][:].tobytes().decode().rstrip('\0')
            if hashlib.sha256(xml.encode()).hexdigest() != metadata_sha256:
                raise ValueError('BAG embedded metadata hash mismatch')
            from urllib.parse import urlparse
            survey_id = Path(urlparse(source_row['url']).path).name.split('_')[0]
            metadata = inspect_metadata(view, survey_id)
            from .adapter_bag import read_snapshot_window
            native = read_snapshot_window(view, source_row, win,
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
        tr = ds.window_transform(win)
        support = _support(valid, tr, crs)
        support['support_kind'] = 'native_grid_node_footprints' if ds.driver == 'BAG' else 'native_grid_cell_footprints'
        support['limitations'] = ['Nominal node/cell-associated support; no claim of measurement between observations or continuous surveyed coverage.']
        header = dict(driver=ds.driver, crs=ds.crs.to_wkt(), horizontal_crs=crs.to_string(),
                      shape=[ds.height, ds.width], window=window, transform=list(tr)[:6],
                      resolution_m=list(ds.res), dtypes=list(ds.dtypes), nodata=ds.nodata if ds.nodata is None or np.isfinite(ds.nodata) else 'NaN',
                      scales=list(ds.scales), offsets=list(ds.offsets), units=list(ds.units),
                      descriptions=list(ds.descriptions), tags=ds.tags())
        depth = semantics.to_depth(raw, block, valid=valid) if not holds and block else None
        if not valid.any():
            holds.append('native_support_empty')
        facts = dict(header=header, observed_vertical=observed, vertical=block, source=source_ref, source_auxiliary=auxiliary,
                     source_lineage=dict(source_row=source_row,metadata_sha256=metadata_sha256),
                     raw_valid_values_sha256=_array_hash(np.where(valid, raw, 0).astype('<f8')),
                     valid_count=int(valid.sum()), valid_fraction=float(valid.mean()), support=support,
                     depth_values_sha256=_array_hash(np.where(valid, depth, 0).astype('<f4')) if depth is not None else None,
                     libs=libraries(), implementation=implementation())
        if collector is not None:
            collector(dict(raw_elevation_data=native.raw_elevation_data.copy(),raw_uncertainty_data=native.raw_uncertainty_data.copy(),
                elevation_mask=native.elevation_mask.copy(),uncertainty_mask=native.uncertainty_mask.copy(),
                source_pair_valid=valid.copy(),depth=None if depth is None else depth.copy(),
                legacy_25_300ft_uncertainty_0_1m=native.qualifies_25_300ft_uncertainty_0_1m.copy()))
        return facts, sorted(set(holds)), raw, valid, tr, crs, depth



def enrich_pending(root, observed, *, segment, segment_id, rights, synthetic=True):
    """Exact ordinary enrichment; pending review NEVER an acceptance."""
    import copy
    from skippercast.coastal.handoff.mapping_input import bind_segment
    facts, holds = copy.deepcopy(observed[0]), list(observed[1])
    holds.extend(bind_segment(root,segment,segment_id,facts))
    facts.update(rights=rights,synthetic=bool(synthetic))
    if rights.get('private_use') is not True or not rights.get('evidence'):
        holds.append('private_rights_evidence_missing')
    for artifact in rights.get('evidence',[]):resolve(root,artifact)
    return dict(schema='coastal-sealed-observation-prototype-v1',facts=facts,
                facts_digest=digest(facts),machine_holds=sorted(set(holds)),
                accepted=False,qualification=False,publication_prohibited=True)

from skippercast.coastal.handoff.mapping_input import bind_segment

def produce_snapshot(view, root, source_ref, *, segment_id, window, vertical, rights, output_dir, segment=None,
            review=None, synthetic=False, source_row=None, metadata_sha256=None, collector=None, mask_writer=None, write_observation=True):
    facts, holds, _, valid, transform, crs, _ = observe_snapshot(view, root, source_ref, window=window, vertical=vertical,
                                                       source_row=source_row, metadata_sha256=metadata_sha256,collector=collector)
    holds.extend(bind_segment(root,segment,segment_id,facts))
    facts.update(rights=rights,synthetic=bool(synthetic))
    out = confined(root, output_dir, existing=False)
    out.mkdir(parents=True, exist_ok=True)
    import rasterio
    mask_path = out / 'native-support.tif'
    mask_profile=dict(driver='GTiff',width=valid.shape[1],height=valid.shape[0],
                      count=1,dtype='uint8',crs=crs,transform=transform,compress='DEFLATE',nodata=None)
    if mask_writer is None:
        with rasterio.open(mask_path,'w',**mask_profile) as ds:
            ds.write(valid.astype('uint8'),1)
            ds.set_band_description(1,'native_valid_support')
    else:
        mask_writer(mask_path,valid.astype('uint8'),mask_profile,'native_valid_support')
    mask_ref = ref(root, mask_path, 'coastal-native-support-v2')
    if rights.get('private_use') is not True or not rights.get('evidence'):
        holds.append('private_rights_evidence_missing')
    for artifact in rights.get('evidence', []):
        resolve(root, artifact)
    payload = dict(schema=SCHEMA, producer='coastal.authenticated_v1', segment_id=segment_id,
                   source=source_ref, source_row=source_row, metadata_sha256=metadata_sha256, segment=segment,
                   window=window, declared_vertical=vertical, rights=rights, synthetic=bool(synthetic),
                   native_facts=facts, valid_support=mask_ref, facts_digest=digest(facts),
                   machine_holds=sorted(set(holds)), review=review, publication_prohibited=True)
    if write_observation:write(out / 'observation.json', payload)
    return payload


def verify_snapshot(view, root, manifest, *, now, minimum_valid_until=None, collector=None):
    document = load(root, manifest, contract=SCHEMA)
    if document.get('schema') != SCHEMA:
        raise ValueError('mapping input contract mismatch')
    facts, holds, _, valid, transform, crs, _ = observe_snapshot(view, root, document['source'], window=document['window'],
                        vertical=document['declared_vertical'], source_row=document.get('source_row'),
                        metadata_sha256=document.get('metadata_sha256'),collector=collector)
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
    return dict(schema='coastal-authenticated-verification-v1',ready=not holds, holds=sorted(set(holds)), facts_digest=digest(facts), facts=facts,
                synthetic=document.get('synthetic') is True)
