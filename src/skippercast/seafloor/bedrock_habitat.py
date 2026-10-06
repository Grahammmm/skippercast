"""Reviewed original geology paired with bounded native depth, without rugosity.

This opt-in uses the classified-area transport, screens and fidelity contract.
It retains original record units and invalid holds. It never admits terrain
ranks, measurement credit, precise fishing positions or repaired source polygons.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
import hashlib
from io import BytesIO
from pathlib import Path
import re
import zipfile

import numpy as np
from pyproj import CRS, Transformer
import rasterio
from rasterio.windows import Window, bounds as window_bounds
import shapefile
from shapely.geometry import shape, mapping, box
from shapely.ops import transform, unary_union

from skippercast.platform.contracts import read_json, public_url
from . import bedrock_vectors as kernel
from .classified_geometry import geographic, polygon, VERSION as GEOMETRY_VERSION
from .io import sha256
from .rights import feature_rights, deployment_use

METHOD = 'original-interpreted-bedrock-v1'
PROFILE = 'original-interpreted-bedrock-area-v1'
BASELINE_VERSION = 'verified-interpreted-native-baseline-v1'
MAX_ARCHIVE_BYTES = 16_000_000
BASELINE_IMPLEMENTATION = ('coverage.py', 'terrain.py', 'run.py', 'habitat.py',
    'habitat_tiles.py', 'substrate.py', 'terrain_support.py', 'resolution_profile.py',
    'normalized.py', 'source_scope.py')


def selected(policy):
    return policy.get('interpretation_method') == METHOD


def validate_policy(p):
    review = p.get('vector_review', {})
    if (p.get('interpretation_method') != METHOD or p.get('profile') != PROFILE
            or not isinstance(p.get('reach_ids'), list) or not p['reach_ids']
            or p.get('release_license') != 'public-domain-us-gov'
            or p.get('rugose_raw_codes') is not None
            or not re.fullmatch('[a-z0-9-]+', p['id'])
            or date.fromisoformat(p['reviewed_on']) > date.today()
            or any(not re.fullmatch('[a-f0-9]{64}', p[k]) for k in
                   ('depth_source_sha256', 'classification_source_sha256', 'metadata_sha256'))
            or not all(p.get(k) for k in ('credit', 'notice', 'review_basis'))
            or review.get('original_crs') != 'EPSG:32610'
            or review.get('unit_field') != 'MapUnitAbb'
            or review.get('member_stem') != 'Geology_SanSimeon'
            or review.get('metadata_member') != 'Geology_SanSimeon_metadata.txt'
            or review.get('bedrock_units') != ['Tus', 'Tm', 'KJug', 'KJug?', 'KJf', 'Ksl', 'Jo', 'Jo?']
            or review.get('excluded_units') != ['Qms/Tus', 'Qms/KJf', 'Qms/KJug', 'Qms/KJug?']
            or type(review.get('expected_polygon_count')) is not int
            or not 1 <= review['expected_polygon_count'] <= 10000
            or not isinstance(review.get('invalid_original_records'), list)
            or any(type(i) is not int or i < 0 for i in review['invalid_original_records'])
            or len(set(review['invalid_original_records'])) != len(review['invalid_original_records'])):
        raise ValueError('Incomplete original interpreted-bedrock review')
    windows = review.get('native_windows')
    if (not isinstance(windows, list) or not windows or len(windows) > 1000
            or any(not isinstance(w, list) or len(w) != 4
                   or any(type(v) is not int for v in w) or min(w[:2]) < 0
                   or min(w[2:]) <= 0 for w in windows)
            or sum(w[2]*w[3] for w in windows) > 25_000_000):
        raise ValueError('Require bounded reviewed native bedrock windows')
    rectangles = [box(w[0],w[1],w[0]+w[2],w[1]+w[3]) for w in windows]
    if any(a.intersection(b).area > 0 for i,a in enumerate(rectangles) for b in rectangles[i+1:]):
        raise ValueError('Reviewed native bedrock windows overlap')
    public_url(p['metadata_url'])


def original_vectors(path, policy, target_crs):
    """Authenticate original bytes and native validity before transformation."""
    review = policy['vector_review']
    if Path(path).stat().st_size > MAX_ARCHIVE_BYTES or sha256(path) != policy['classification_source_sha256']:
        raise ValueError('Original bedrock archive changed')
    stem = review['member_stem']
    with zipfile.ZipFile(path) as archive:
        names = [f'{stem}.{suffix}' for suffix in ('shp', 'shx', 'dbf', 'prj')]
        names.append(review['metadata_member'])
        if (any(archive.namelist().count(name) != 1 for name in names)
                or sum(archive.getinfo(name).file_size for name in names) > MAX_ARCHIVE_BYTES):
            raise ValueError('Unbounded or ambiguous original bedrock members')
        if hashlib.sha256(archive.read(names[-1])).hexdigest() != policy['metadata_sha256']:
            raise ValueError('Original bedrock metadata changed')
        if not CRS.from_wkt(archive.read(f'{stem}.prj').decode()).equals(CRS.from_epsg(32610)):
            raise ValueError('Original bedrock CRS changed')
        reader = shapefile.Reader(**{suffix: BytesIO(archive.read(f'{stem}.{suffix}'))
                                    for suffix in ('shp', 'shx', 'dbf')})
        if len(reader) != review['expected_polygon_count']:
            raise ValueError('Original bedrock record inventory changed')
        project = Transformer.from_crs(32610, target_crs, always_xy=True).transform
        records, units, held, transformed_holds = {}, {}, [], []
        for index, item in enumerate(reader.iterShapeRecords()):
            unit = item.record.as_dict()[review['unit_field']]
            if unit not in review['bedrock_units']:
                continue  # Sediment, including sediment-over-rock, stays excluded.
            native = shape(item.shape.__geo_interface__)
            if native.geom_type not in ('Polygon', 'MultiPolygon') or native.is_empty or not native.is_valid:
                held.append(index)
                continue
            result = transform(project, native)
            if result.is_empty or not result.is_valid:
                transformed_holds.append(index)
                continue
            records[str(index)], units[str(index)] = result, unit
        if held != review['invalid_original_records']:
            raise ValueError('Original bedrock invalid-record holds changed')
    return records, units, {'invalid_original_records': held,
                           'invalid_transformed_records': transformed_holds}


def verified_baseline(root, reach, run, physical):
    """Reconstruct current canonical graded exclusion; no public tile inputs.

    The graded pipeline stores its authoritative candidate boundaries in WGS84.
    Their exact canonical projection supplies the graded exclusion. Original
    classified boundaries remain separate and are added in reviewed policy order
    by the stage's native union, including held earlier patches.
    """
    from . import classified_habitat as ch
    from .classified_geometry import project
    folder = Path(root)/'var/seafloor/reaches'/reach
    candidates = read_json(folder/'candidates.geojson')['features']
    ids = [f['properties']['id'] for f in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError('Canonical graded baseline inventory duplicated')
    native = unary_union([polygon(project(polygon(f['geometry']), 4326, 3310)) for f in candidates])
    inventory = {'version':BASELINE_VERSION, 'crs':'EPSG:3310', 'features':[
        {'id':f['properties']['id'], 'geometry':mapping(polygon(project(polygon(f['geometry']),4326,3310)))}
        for f in candidates]}
    identity = {'version':BASELINE_VERSION, 'reach':reach,
        # run.json also records legal screens and changing survey timestamps.
        # Validate it in source_context, but never let those bytes invalidate physics.
        'baseline_hashes':{name:sha256(folder/name) for name in ('physical.json','candidates.geojson','cells.json')},
        'physical_input_hash':physical['input_hash'], 'native_digest':ch.digest(inventory),
        'candidate_count':len(candidates),
        'reconstruction':'Exact canonical graded candidate projection; earlier classified native union added in stage policy order.'}
    return native, identity


def source_context(root, reach, policy, *, fetch=False):
    from . import classified_habitat as ch
    from .manifest import load_manifest
    from .source_scope import scoped_manifest
    validate_policy(policy)
    root = Path(root)
    folder = root/'var/seafloor/reaches'/reach
    run, physical = read_json(folder/'run.json'), read_json(folder/'physical.json')
    if (reach not in policy['reach_ids'] or run.get('publication_prohibited')
            or run['inputs']['reach_id'] != reach
            or run['physical_input_hash'] != physical['input_hash']
            or ch.digest({k:v for k,v in run['inputs'].items()
                          if k not in ('screen', 'screen_implementation_sha256')}) != physical['input_hash']):
        raise ValueError('Unqualified interpreted-bedrock baseline identity')
    from .run import VERSION as baseline_version
    expected_implementation = {n:sha256(Path(__file__).with_name(n)) for n in BASELINE_IMPLEMENTATION}
    if (run['inputs'].get('rule_version') != baseline_version
            or run['inputs'].get('implementation') != expected_implementation
            or run['inputs'].get('habitat_rules') != read_json(root/'catalog/habitat-rules.json')):
        raise ValueError('Bedrock graded baseline science changed; rebuild required')
    for name in ('cells.json', 'candidates.geojson', 'physical.json'):
        if run['outputs'][name] != sha256(folder/name):
            raise ValueError('Bedrock baseline output hash mismatch')
    for name, expected in physical['outputs'].items():
        if Path(name).name != name or sha256(folder/name) != expected:
            raise ValueError('Bedrock baseline physical output hash mismatch')
    manifest, scope = scoped_manifest(root, load_manifest(root))
    rows = {r['id']:r for r in manifest['surveys']}
    row, source = rows[policy['depth_source_id']], rows[policy['classification_source_id']]
    if (run['inputs'].get('source_scope') != scope or row not in run['inputs']['sources']
            or row['sha256'] != policy['depth_source_sha256'] or row['status'] != 'usable'
            or row.get('habitat_quality_hold') or row.get('habitat_quality_dependencies')
            or source['sha256'] != policy['classification_source_sha256']
            or source.get('kind') != 'substrate' or source.get('format') != 'vector'
            or source['status'] in ('hold', 'withdrawn', 'physical-only')
            or source.get('habitat_quality_hold') or source.get('habitat_quality_dependencies')
            or source.get('horizontal_crs') != 'EPSG:32610'
            or source.get('license') != policy['release_license']):
        raise ValueError('Interpreted-bedrock original source review changed')
    receipt, path = ch.normalized_depth(row, root, fetch=fetch)
    from . import terrain_support
    reference_sources = []
    for saved in run['inputs']['sources']:
        current = rows.get(saved['id'])
        if current != saved or current['status'] != 'usable':
            raise ValueError('Bedrock baseline source changed')
        feature_rights([current['id']], rows, use=deployment_use(root))
        terrain_support.validate_binding(current)
        ref_receipt, ref_path = ((receipt, path) if current['id'] == row['id']
                                 else ch.normalized_depth(current, root, fetch=fetch))
        terrain_support.verify_sources([{'row':current,'path':ref_path,'receipt':ref_receipt}],root=root)
        reference_sources.append({'source_id':current['id'], 'source_sha256':current['sha256'],
            'normalized_sha256':ref_receipt['cog_sha256'],
            'terrain_binding_sha256':terrain_support.binding_digest(current) if current.get('terrain_support') else None})
    rights = feature_rights([source['id'], *[r['id'] for r in run['inputs']['sources']]], rows, use=deployment_use(root))
    for term in rights:
        if term['source_id'] == source['id']:
            term.update(attribution=policy['credit'], notice=policy['notice'], policy_url=policy['metadata_url'])
    from .fetch import fetch_source
    archive, _ = fetch_source(source, root/'var/seafloor/cache', fetch=fetch, max_bytes=MAX_ARCHIVE_BYTES)
    with rasterio.open(path) as ds:
        records, units, holds = original_vectors(archive, policy, ds.crs)
    existing, baseline_identity = verified_baseline(root, reach, run, physical)
    mode = ch.support_mode(policy)
    support_cells = [c for c in read_json(folder/'cells.json')['cells']
        if c['tier'] == 1 and (mode == ch.PAIRED_REFERENCE_SUPPORT or c.get('source_id') == row['id'])]
    reference_ids = {c.get('source_id') for c in support_cells}
    if not reference_ids <= {r['id'] for r in run['inputs']['sources']}:
        raise ValueError('Unknown current bedrock reference contributor')
    support = unary_union([ch.cell_geometry(c) for c in support_cells])
    # Also clip to the reviewed native depth acquisition window.
    reviewed = transform(ch.TO_LOCAL, box(*receipt['requested_bounds_wgs84']))
    support = support.intersection(reviewed)
    identity = {'profile': PROFILE, 'reach': reach, 'policy': policy,
        'depth_source': row, 'classification_binding': {'row': source},
        'normalized_receipt': receipt, 'normalized_sha256': receipt['cog_sha256'],
        'source_scope': scope, 'baseline': baseline_identity, 'support_mode':mode,
        'baseline_source_dependencies':sorted(reference_sources,key=lambda r:r['source_id']),
        'baseline_physical_sha256': sha256(folder/'physical.json'),
        'baseline_cells_sha256': sha256(folder/'cells.json'),
        'original_holds': holds,
        'implementation': {n:sha256(Path(__file__).with_name(n)) for n in
                           ('bedrock_habitat.py', 'bedrock_vectors.py', 'classified_habitat.py', 'normalized.py', 'terrain_support.py', 'fetch.py')},
        'geometry_representation': ch.geometry_runtime()}
    if mode == ch.PAIRED_REFERENCE_SUPPORT:
        identity['reference_support'] = {'version':ch.PAIRED_REFERENCE_SUPPORT,
            'source_ids':sorted(reference_ids), 'sources':[r for r in sorted(reference_sources,key=lambda r:r['source_id'])
                if r['source_id'] in reference_ids], 'meaning':ch.REFERENCE_NOTICE}
    neighbor, _ = ch.neighbor_planning(root, reach, policy, baseline=run)
    if neighbor is not None:
        identity['neighbor_planning'] = neighbor
    binding = {'row': source, 'policy': policy, 'archive': archive,
               'reviewed_depth_bounds_wgs84': receipt['requested_bounds_wgs84']}
    return identity, row, binding, path, support, existing, rights


@dataclass(frozen=True)
class Patch:
    record: str
    unit: str
    geometry: object
    native_depth_area_m2: float
    native_depth_crs: str


def extract(row, binding, path, support, existing, *, root, edge=512, max_pixels=25_000_000):
    validate_policy(binding['policy'])
    if not 16 <= edge <= 512 or not 1 <= max_pixels <= 25_000_000:
        raise ValueError('Invalid bounded native bedrock processing limit')
    if support.is_empty:
        return [], {'bedrock_selected_area_km2': 0}
    with rasterio.open(path) as ds:
        if (ds.count != 1 or ds.descriptions[0] != 'depth_m_positive_down'
                or ds.transform.b != 0 or ds.transform.d != 0
                or ds.transform.a <= 0 or ds.transform.e >= 0):
            raise ValueError('Require verified normalized positive-down depth')
        records, units, _ = original_vectors(binding['archive'], binding['policy'], ds.crs)
        project = Transformer.from_crs(3310, ds.crs, always_xy=True).transform
        native_support = transform(project, support).intersection(box(*ds.bounds))
        baseline = kernel.NativeFragments(CRS.from_user_input(ds.crs), {'baseline':transform(project, existing)} if not existing.is_empty else {})
        clipped = {key:g.intersection(native_support) for key,g in records.items() if g.intersection(native_support).area > 0}
        if not clipped:
            return [], {'bedrock_selected_area_km2': 0}
        if 'reviewed_depth_bounds_wgs84' in binding:
            reviewed_scope = transform(Transformer.from_crs(4326, ds.crs, always_xy=True).transform,
                                       box(*binding['reviewed_depth_bounds_wgs84']))
        else:
            raise ValueError('Missing verified depth source window bounds')
        windows = [Window(*w) for w in binding['policy']['vector_review']['native_windows']]
        if any(w.col_off+w.width > ds.width or w.row_off+w.height > ds.height for w in windows):
            raise ValueError('Reviewed native bedrock window exceeds current depth extent')
        if sum(w.width*w.height for w in windows) > max_pixels:
            raise ValueError('Bedrock native window exceeds bounded pixel budget')
        batches, fragment_count = [], 0
        for window in windows:
            window_scope = box(*window_bounds(window,ds.transform))
            if not reviewed_scope.covers(window_scope):
                raise ValueError('Bedrock window lies outside verified depth source bounds')
            selected_records = {key:g.intersection(window_scope) for key,g in clipped.items()
                                if g.intersection(window_scope).area > 0}
            if not selected_records:
                continue
            for y in range(int(window.row_off), int(window.row_off+window.height), edge):
                for x in range(int(window.col_off), int(window.col_off+window.width), edge):
                    tile = Window(x,y,min(edge,window.col_off+window.width-x),min(edge,window.row_off+window.height-y))
                    data = ds.read(1, window=tile, masked=True).astype('float32')
                    values = data.filled(np.nan)
                    good = ~np.ma.getmaskarray(data) & np.isfinite(values)
                    batch = kernel.window_fragments(selected_records, values, good, ds.window_transform(tile), ds.crs,
                                                    depth_band_description=ds.descriptions[0])
                    batches.append(batch)
                    fragment_count += len(batch.by_record)
                    if fragment_count > 100000:
                        raise ValueError('Bedrock native fragment budget exceeded')
        assembled = kernel.assemble_components(batches, existing=baseline)
        to_local = Transformer.from_crs(ds.crs, 3310, always_xy=True).transform
        patches = [Patch(key,units[key],polygon(transform(to_local,g)),g.area,ds.crs.to_string()) for key,g in assembled]
    return patches, {'bedrock_selected_area_km2': unary_union([p.geometry for p in patches]).area/1e6,
                     'bedrock_native_depth_area_km2': unary_union([g for _,g in assembled]).area/1e6}


def features_for(patches, reach, policy, row, binding, **metadata):
    features = []
    from shapely import normalize
    for patch in patches:
        geo = geographic(patch.geometry)
        content = hashlib.sha256(normalize(patch.geometry).wkb).hexdigest()[:20]
        properties = {'id':f'bedrock-{reach}-{policy["id"]}-{patch.record}-{content}', 'reach':reach,
            'source_ids':[row['id'],binding['row']['id']], 'source_year':row.get('survey_year','unknown'),
            'resolution_m':row['resolution_m'], 'vertical_datum':row['vertical_datum'],
            'terrain':'unknown', 'fit':{'lingcod':'unknown','rockfish-reef':'unknown'},
            'depth_min_ft':25,'depth_max_ft':300,'depth_basis':'nominal-band','detail_level':'classified-area',
            'exportable':False,'tier':1,'status':'held','hold_reasons':['legal-screen-pending'],
            'area_ha':patch.geometry.area/10000,
            'substrate':{'source_id':binding['row']['id'],'interpretation':'exposed-bedrock',
                         'map_unit':patch.unit,'original_record_index':int(patch.record),
                         'lithology_uncertain':'?' in patch.unit,'independent_confirmation':False},
            'geometry_representation':{'version':GEOMETRY_VERSION,'native_crs':'EPSG:3310'},
            'classified_area':{'profile':PROFILE,'interpretation_method':METHOD,'policy_id':policy['id'],
                'metadata_sha256':policy['metadata_sha256'],'independent_confirmation':False,
                'new_measured_area_km2':0,'interpolation_mask':'unknown',
                'basis':'Original producer interpreted exposed bedrock; lithology uncertainty retained. No rugosity or fish presence inferred.',
                'native_depth_area_m2':patch.native_depth_area_m2,'native_depth_crs':patch.native_depth_crs,
                'window_notice':'Interpretation is limited to reviewed native windows; a window boundary is not an established reef edge.'}}
        properties.update({k:deepcopy(v) for k,v in metadata.items() if v is not None})
        features.append({'type':'Feature','geometry':mapping(geo),'properties':properties})
    return {'type':'FeatureCollection','features':features}


def assessment(p):
    area, substrate = p.get('classified_area',{}), p.get('substrate',{})
    if (area.get('profile') != PROFILE or area.get('interpretation_method') != METHOD
            or not area.get('policy_id') or area.get('independent_confirmation') is not False
            or area.get('new_measured_area_km2') != 0 or p.get('terrain') != 'unknown'
            or p.get('fit') != {'lingcod':'unknown','rockfish-reef':'unknown'}
            or p.get('detail_level') != 'classified-area' or p.get('depth_basis') != 'nominal-band'
            or p.get('depth_min_ft') != 25 or p.get('depth_max_ft') != 300
            or p.get('geometry_representation') != {'version':GEOMETRY_VERSION,'native_crs':'EPSG:3310'}
            or not isinstance(p.get('source_ids'),list) or len(p['source_ids']) != 2 or len(set(p['source_ids'])) != 2
            or p.get('terrain_grade','unknown') != 'unknown' or p.get('terrain_score','unknown') != 'unknown'
            or substrate.get('interpretation') != 'exposed-bedrock' or 'normalized_code' in substrate
            or not substrate.get('source_id') or substrate.get('independent_confirmation') is not False
            or substrate.get('map_unit') not in ['Tus','Tm','KJug','KJug?','KJf','Ksl','Jo','Jo?']
            or type(substrate.get('original_record_index')) is not int or substrate['original_record_index'] < 0
            or substrate.get('lithology_uncertain') is not ('?' in substrate['map_unit'])
            or p.get('metric_support_fraction') is not None or p.get('habitat_quality_hold') or p.get('habitat_quality_dependencies')):
        return None
    return area
