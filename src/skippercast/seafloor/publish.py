"""Qualified regional PMTiles and fail-closed R2 publication; never raw surveys."""
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform

from skippercast.platform.contracts import REPO, atomic_json, read_json
from .coverage import cell_geometry
from .io import sha256
from .run import run
from .rights import feature_rights, deployment_use
from .screen import input_identity, load_snapshot
from .search_areas import published_contract
from .classified_habitat import stage as classified_stage, publication_features
from .source_scope import (GOVERNMENT, processing_scope, scoped_manifest,
                           validate_dependencies, validate_receipt)

TO_GEO = Transformer.from_crs(3310, 4326, always_xy=True).transform
NOTICE = 'Planning only. Not a navigation chart. Check current CDFW regulations.'


def flat_properties(properties):
    """MVT supports scalar values: retain nested evidence as canonical JSON."""
    result = {key: (json.dumps(value, sort_keys=True, separators=(',', ':'))
                    if isinstance(value, (dict, list)) else value) for key, value in properties.items()}
    terrain = properties.get('terrain')
    result['terrain_grade'] = terrain['grade'] if isinstance(terrain, dict) else 'unknown'
    result['terrain_score'] = terrain['score'] if isinstance(terrain, dict) else 'unknown'
    result.update({'fit_'+key.replace('-', '_'): value for key, value in properties['fit'].items()})
    return result


def region_layers(root, region, *, rerun=True, now=None):
    root = Path(root)
    scope = processing_scope(root)
    source_scope = None
    scoped_sources = None
    if scope == GOVERNMENT:
        complete_manifest = read_json(root/'catalog/surveys.json')
        _, source_scope = scoped_manifest(root, complete_manifest)
        scoped_sources = {s['id']: s for s in complete_manifest['surveys']}
    ledger = read_json(root/'dist/data/seafloor-ledger.json')
    rows = [r for r in ledger['reaches'] if r['region'] == region]
    if not rows or not re.fullmatch('[a-z0-9-]+', region):
        raise ValueError('Unknown region')
    reference = root/'var/seafloor/reference/cells.json'
    if sha256(reference) != ledger['reference_cells_sha256']:
        raise ValueError('Reference cells changed')
    ids = {r['id'] for r in rows}
    cells = {c['id']: c for c in read_json(reference)['cells'] if c['reach'] in ids}
    habitat, receipts, dates = [], {}, []
    sources = None
    for row in rows:
        if row['status'] == 'unassessed':
            continue
        ident = row['id']
        if row['status'] == 'terrain-pending':
            folder = root/'var/seafloor/reaches'/ident
            checkpoint = read_json(folder/'coverage-checkpoint.json')
            if source_scope is None and checkpoint.get('source_scope') is not None:
                raise ValueError('Scoped coverage cannot enter default publication')
            if (checkpoint.get('catalog_sha256') != sha256(root/'catalog/surveys.json')
                    or checkpoint.get('rules_sha256') != sha256(root/'catalog/habitat-rules.json')
                    or checkpoint.get('reference_sha256') != sha256(reference)):
                raise ValueError('Coverage checkpoint inputs changed; rerun required')
            if sha256(folder/'coverage-cells.json') != checkpoint['cells_sha256']:
                raise ValueError('Coverage checkpoint checksum mismatch')
            if source_scope is not None:
                if checkpoint.get('source_scope') != source_scope:
                    raise ValueError('Government coverage scope changed; rerun required')
                allowed_hashes = {s['sha256'] for ident, s in scoped_sources.items()
                                  if ident in source_scope['admitted_source_ids']}
                hashes = checkpoint.get('source_hashes')
                if not isinstance(hashes, list) or not set(hashes) <= allowed_hashes:
                    raise ValueError('Restricted government coverage checkpoint dependency')
                coverage_ids = sorted({c['source_id'] for c in read_json(folder/'coverage-cells.json')['cells']
                                       if c.get('source_id', 'unknown') != 'unknown'})
                validate_dependencies(coverage_ids, scoped_sources, source_scope, label='coverage')
                if not {scoped_sources[ident]['sha256'] for ident in coverage_ids} <= set(hashes):
                    raise ValueError('Government coverage source byte identity missing')
            cells.update({c['id']: c for c in read_json(folder/'coverage-cells.json')['cells']})
            continue  # measured coverage only; no old habitat from a failed run
        if rerun:
            run(ident, root=root)  # validates current manifests, actual source bytes, rules and implementation
        folder = root/'var/seafloor/reaches'/ident
        receipt = read_json(folder/'run.json')
        if source_scope is None and receipt['inputs'].get('source_scope') is not None:
            raise ValueError('Scoped physical receipt cannot enter default publication')
        if any(source.get('status') == 'physical-only' for source in receipt['inputs'].get('sources', [])):
            raise ValueError('Private physical source cannot enter publication')
        for name, expected in receipt['outputs'].items():
            if Path(name).name != name or sha256(folder/name) != expected:
                raise ValueError('Reach output checksum mismatch')
        calibration_ids = None
        if source_scope is not None:
            if 'candidates.geojson' not in receipt['outputs']:
                raise ValueError('Missing government calibration inventory; rerun required')
            calibration_ids = validate_receipt(receipt['inputs'], read_json(folder/'candidates.geojson'),
                                               complete_manifest, source_scope)
            expected_input = hashlib.sha256(json.dumps(receipt['inputs'], sort_keys=True).encode()).hexdigest()
            if receipt.get('input_hash') != expected_input:
                raise ValueError('Government run input hash is inconsistent')
        screen = load_snapshot(root, ident)
        if receipt['inputs']['screen'] != input_identity(screen):
            raise ValueError('Reach screen is no longer current; rerun required')
        if rerun:
            classified_stage(ident, root=root)
        classified, classified_receipt = publication_features(ident, root=root)
        selected = read_json(folder/'habitat.geojson')['features']
        if selected and screen['status'] != 'ready':
            raise ValueError('Held reach cannot publish habitat')
        calibration_checked = False
        for f in selected:
            p = f['properties']
            if ('classified_area' in p or p.get('detail_level') == 'classified-area'
                    or (not published_contract(p) and (p['tier'] != 2 or p['status'] != 'habitat' or not p['exportable']))
                    or p['screen']['status'] != 'pass' or p.get('hold_reasons')
                    or p.get('habitat_quality_hold') or p.get('habitat_quality_dependencies')):
                raise ValueError('Unqualified feature in publication input')
            if sources is None:
                sources = {s['id']: s for s in read_json(root/'catalog/surveys.json')['surveys']}
            if not calibration_checked:
                input_rows = {s['id']: s for s in receipt['inputs'].get('sources', [])}
                input_ids = set(input_rows)
                held_inputs = {ident for ident in input_ids if sources.get(ident, {}).get('habitat_quality_hold')}
                support_inputs = {ident for ident in input_ids if
                    sources.get(ident, {}).get('terrain_support') or input_rows[ident].get('terrain_support')}
                if held_inputs or support_inputs:
                    # Intersecting sources may lose every coverage cell. Only actual
                    # grid contributors calibrated thresholds, including contributors
                    # that produced no candidates of their own. This inventory is
                    # covered by the candidate output hash checked above.
                    if 'candidates.geojson' not in receipt['outputs']:
                        raise ValueError('Missing verified habitat calibration inventory; rerun required')
                    candidates = read_json(folder/'candidates.geojson')
                    calibration_ids = candidates.get('calibration_source_ids')
                    if (not isinstance(calibration_ids, list) or not calibration_ids
                            or any(not isinstance(ident, str) for ident in calibration_ids)
                            or len(set(calibration_ids)) != len(calibration_ids)
                            or not set(calibration_ids).issubset(input_ids)):
                        raise ValueError('Invalid habitat calibration inventory; rerun required')
                    if held_inputs.intersection(calibration_ids):
                        raise ValueError('Shared habitat threshold quality review is unresolved; rerun required')
                    if support_inputs:
                        from .terrain_support import binding_digest
                        if any(sources.get(ident, {}).get('terrain_support') != input_rows[ident].get('terrain_support')
                               for ident in calibration_ids):
                            raise ValueError('Habitat calibration terrain support changed; rerun required')
                        expected_support = {ident: binding_digest(sources[ident]) for ident in calibration_ids
                                            if sources.get(ident, {}).get('terrain_support')}
                        if candidates.get('calibration_terrain_support', {}) != expected_support:
                            raise ValueError('Missing current habitat calibration terrain support evidence; rerun required')
                calibration_checked = True
            contributors = list(p['source_ids'])
            if source_scope is not None and not set(contributors).issubset(calibration_ids):
                raise ValueError('Government feature is outside verified reach calibration')
            from .terrain_support import feature_evidence
            terrain_evidence = [feature_evidence(sources.get(ident, {})) for ident in contributors]
            terrain_evidence = [evidence for evidence in terrain_evidence if evidence is not None]
            if (len(terrain_evidence) > 1 or p.get('terrain_support') !=
                    (terrain_evidence[0] if terrain_evidence else None)):
                raise ValueError('Feature terrain support evidence is stale; rerun required')
            substrate = p.get('substrate', {})
            if isinstance(substrate, dict) and substrate.get('source_id') not in (None, 'unknown'):
                if source_scope is not None and not any(
                        receipt['inputs']['substrate_bindings'].get(ident, {}).get('row', {}).get('id') == substrate['source_id']
                        for ident in contributors):
                    raise ValueError('Government feature substrate is outside verified bindings')
                contributors.append(substrate['source_id'])
            if source_scope is not None:
                validate_dependencies(sorted(set(contributors)), scoped_sources, source_scope, label='feature')
            if any(sources.get(ident, {}).get('habitat_quality_hold') for ident in contributors):
                raise ValueError('Source habitat quality review is unresolved; rerun required')
            public_properties = dict(p, source_rights=feature_rights(contributors, sources,
                use=deployment_use(root)))
            habitat.append({'type': 'Feature', 'geometry': f['geometry'], 'properties': flat_properties(public_properties)})
        habitat.extend({'type': 'Feature', 'geometry': f['geometry'],
                        'properties': flat_properties(f['properties'])} for f in classified)
        reach_cells = read_json(folder/'cells.json')['cells']
        if source_scope is not None:
            validate_dependencies(sorted({c['source_id'] for c in reach_cells
                if c.get('source_id', 'unknown') != 'unknown'}), scoped_sources, source_scope, label='coverage')
        cells.update({c['id']: c for c in reach_cells})
        receipts[ident] = {'input_hash': receipt['input_hash'], 'run_sha256': sha256(folder/'run.json'),
                          'summary': receipt['ledger_summary']}
        if source_scope is not None:
            receipts[ident]['calibration_source_ids'] = calibration_ids
        if classified_receipt is not None:
            receipts[ident]['classified'] = classified_receipt
        if selected or classified:
            dates.extend([screen['snapshot']] + [s['checked_at'] for s in screen['layers']])
            dates.extend(s['evidence']['up_to_date_as_of']+'T00:00:00+00:00'
                         for s in screen['layers'] if s['id'] == 'security')
    features = [{'type': 'Feature', 'geometry': mapping(transform(TO_GEO, cell_geometry(c))),
                 'properties': {'id': c['id'], 'reach': c['reach'], 'tier': c['tier'],
                     'source_id': c.get('source_id', 'unknown'), 'reference_band': 'provisional',
                     'band_area_m2': c['band_area_m2'], 'planning_notice': NOTICE}}
                for c in sorted(cells.values(), key=lambda c: c['id'])]
    expires = min((datetime.fromisoformat(s.replace('Z', '+00:00'))+timedelta(days=35)
                   for s in dates), default=now or datetime.now(timezone.utc))
    return {'cells': features, 'habitat': habitat}, receipts, expires


def build(region, *, root=REPO, tool=None, now=None, scope_config=None):
    from scripts.build_map_tiles import build_vector_archive
    root = Path(root)
    if scope_config is not None:
        from .scope_paths import resolve_scope
        _, paths = resolve_scope(root, scope_config=scope_config)
        if not paths.is_central_default:
            raise ValueError('Non-central publication is disabled until its scoped ingest, legal and screen contracts are reviewed')
    tool = tool or os.environ.get('TIPPECANOE') or shutil.which('tippecanoe')
    if not tool:
        raise ValueError('Install pinned tippecanoe or set TIPPECANOE')
    now = now or datetime.now(timezone.utc)
    layers, receipts, expires = region_layers(root, region, now=now)
    source_scope = None
    if processing_scope(root) == GOVERNMENT:
        _, source_scope = scoped_manifest(root, read_json(root/'catalog/surveys.json'))
    scope_fields = ({'source_scope': source_scope,
                     'reach_calibration_source_ids': {key: value['calibration_source_ids']
                         for key, value in receipts.items()}} if source_scope is not None else {})
    folder = root/'var/seafloor/public'/region
    archive = folder/f'seafloor-{region}.pmtiles'
    credits = sorted({r['attribution'] for f in layers['habitat']
                      for r in json.loads(f['properties'].get('source_rights', '[]'))})
    build_vector_archive(tool, layers, archive, title=f'SkipperCast seafloor — {region}',
        attribution='; '.join(credits + ['CDFW / NOAA / eCFR spatial restrictions; SkipperCast']),
        description=NOTICE+' Habitat candidate, unverified. Nominal depth; verify on your sounder.', precise=True)
    ledger = read_json(root/'dist/data/seafloor-ledger.json')
    # Canonical screened boundaries, not quantized/clipped MVT fragments.
    # Only public habitat properties and producer URLs accompany them.
    sources = {s['id']: s for s in read_json(root/'catalog/surveys.json')['surveys']}
    exports = []
    for f in layers['habitat']:
        p = dict(f['properties'])
        # A broad search outline is displayed, never exported as a precise spot.
        if p.get('exportable') is False or p.get('status') in {'search-area', 'classified-area'}:
            continue
        for key in ('terrain', 'fit', 'substrate', 'screen', 'source_ids', 'independent_evidence', 'source_rights'):
            if isinstance(p.get(key), str):
                try: p[key] = json.loads(p[key])
                except json.JSONDecodeError: pass
        point = shape(f['geometry']).representative_point()
        p['waypoint'] = {'longitude': point.x, 'latitude': point.y,
                         'basis': 'Interior reference point; spot depth not separately sampled'}
        p['source_urls'] = [sources[s]['url'] for s in p.get('source_ids', []) if s in sources]
        exports.append({'type': 'Feature', 'geometry': f['geometry'], 'properties': p})
    atomic_json(folder/'habitat-export.geojson', {'type': 'FeatureCollection', 'schema_version': 1,
                'region': region, 'expires_at': expires.isoformat(), 'features': exports,
                **scope_fields,
                'geometry_basis': 'Canonical screened habitat boundaries; not a navigation route'})
    # Transport compression preserves every native coordinate, hole and part.
    # Do not simplify canonical boundaries to meet a mobile download limit.
    raw_export = folder/'habitat-export.geojson'
    export_bytes = raw_export.read_bytes()
    export = folder/'habitat-export.geojson.gz'
    export.write_bytes(gzip.compress(export_bytes, mtime=0))
    raw_export.unlink()
    if len(export_bytes) > 128*1024*1024 or export.stat().st_size > 32*1024*1024:
        raise ValueError('Canonical reef export exceeds browser limits; partition this region')
    selected = [r for r in ledger['reaches'] if r['region'] == region]
    atomic_json(folder/'ledger.json', {'region': region, 'reaches': selected, 'reference': ledger['reference']})
    manifest = {'schema_version': 1, 'region': region, 'status': 'ready' if layers['habitat'] else 'held',
                **scope_fields,
                'expires_at': expires.isoformat(), 'built_at': now.isoformat(),
                'archive': archive.name, 'archive_sha256': sha256(archive), 'archive_bytes': archive.stat().st_size,
                'layers': {name: len(features) for name, features in layers.items()},
                'habitat_counts': {status: sum(f['properties'].get('status') == status for f in layers['habitat'])
                    for status in ('habitat', 'search-area', 'classified-area')},
                'ledger_sha256': sha256(folder/'ledger.json'),
                'export_file': export.name,
                'export_sha256': sha256(export),
                'export_bytes': export.stat().st_size,
                'export_decoded_bytes': len(export_bytes),
                'source_attribution': credits,
                'source_use_notice': 'Retain source-specific terms and credits; mixed data do not become public-domain.',
                'reach_inputs': {key: value['input_hash'] for key, value in receipts.items()},
                'classified_inputs': {key: value['classified']['input_hash'] for key, value in receipts.items()
                    if 'classified' in value},
                'planning_notice': NOTICE, 'depth_basis': 'nominal',
                'tile_geometry': 'Display geometry quantized to MVT grid; not a navigable or export boundary.'}
    atomic_json(folder/'manifest.json', manifest, indent=2)
    atomic_json(root/'var/seafloor/publication'/f'{region}.json', {'manifest': manifest, 'receipts': receipts})
    return folder, manifest


def credentials():
    from scripts.publish_r2 import client
    token, account = os.environ.get('CLOUDFLARE_API_TOKEN'), os.environ.get('CLOUDFLARE_ACCOUNT_ID')
    if not token or not account:
        raise ValueError('R2 credentials required; publication was not attempted')
    return client(token, account), os.environ.get('R2_BUCKET', 'skippercast-feeds')


def publish_bundle(s3, bucket, folder, *, now=None):
    """Isolated sync prefix avoids deleting other map layers or regions.

    A ready bundle whose screen expired by ``now`` (default: the current time) is refused.
    """
    from scripts.publish_r2 import sync
    folder = Path(folder)
    manifest = read_json(folder/'manifest.json')
    if manifest.get('source_scope') is not None:
        raise ValueError('Scoped government release requires a separately reviewed publication namespace')
    region = manifest['region']
    if not re.fullmatch('[a-z0-9-]+', region):
        raise ValueError('Invalid publication region')
    expiry = datetime.fromisoformat(manifest['expires_at'])
    if manifest['status'] == 'ready' and expiry <= (now or datetime.now(timezone.utc)):
        raise ValueError('Screen expired before upload')
    if manifest['archive'] != f'seafloor-{region}.pmtiles':
        raise ValueError('Invalid publication archive path')
    archive = folder/manifest['archive']
    if archive.name != f'seafloor-{region}.pmtiles' or sha256(archive) != manifest['archive_sha256']:
        raise ValueError('Publication archive changed')
    if sha256(folder/'ledger.json') != manifest['ledger_sha256']:
        raise ValueError('Publication ledger changed')
    export_name = manifest.get('export_file')
    if export_name not in ('habitat-export.geojson', 'habitat-export.geojson.gz'):
        raise ValueError('Invalid publication export path')
    export = folder/export_name
    if sha256(export) != manifest.get('export_sha256'):
        raise ValueError('Publication export changed')
    allowed = {archive.name, 'ledger.json', 'manifest.json', export.name}
    if {p.name for p in folder.iterdir()} != allowed:
        raise ValueError('Unexpected file in public bundle')
    sync(s3, bucket, folder, f'tiles/seafloor/regions/{region}')
    # Stable URL is gated by a separate manifest in the Worker. Write a hold
    # before changing the alias, then promote only after archive read-back.
    control = f'tiles/seafloor/manifest-{region}.json'
    s3.put_object(Bucket=bucket, Key=control, Body=json.dumps({'status': 'updating'}).encode(),
                  ContentType='application/json', CacheControl='no-store')
    export_key = f'tiles/seafloor/regions/{region}/{export.name}'
    s3.put_object(Bucket=bucket, Key=export_key, Body=export.read_bytes(),
                  ContentType='application/gzip' if export.name.endswith('.gz') else 'application/geo+json', CacheControl='no-store',
                  Metadata={'sha256': manifest['export_sha256']})
    with s3.get_object(Bucket=bucket, Key=export_key)['Body'] as stream:
        import hashlib
        if hashlib.sha256(stream.read()).hexdigest() != manifest['export_sha256']:
            raise ValueError('R2 export read-back failed; alias remains held')
    key = f'tiles/seafloor/{archive.name}'
    with archive.open('rb') as stream:
        s3.put_object(Bucket=bucket, Key=key, Body=stream, ContentType='application/octet-stream',
                      CacheControl='no-store', Metadata={'sha256': manifest['archive_sha256']})
    import hashlib
    digest = hashlib.sha256()
    with s3.get_object(Bucket=bucket, Key=key)['Body'] as stream:
        for part in iter(lambda: stream.read(1024*1024), b''):
            digest.update(part)
    if digest.hexdigest() != manifest['archive_sha256']:
        raise ValueError('R2 archive read-back failed; alias remains held')
    s3.put_object(Bucket=bucket, Key=control, Body=json.dumps(manifest).encode(),
                  ContentType='application/json', CacheControl='no-store')
    return key


def upload(region, *, root=REPO):
    root = Path(root)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    main = subprocess.check_output(['git', 'rev-parse', 'origin/main'], cwd=root, text=True).strip()
    if head != main:
        raise ValueError('Deploy only the fetched main commit')
    changed = subprocess.check_output(['git', 'diff', 'HEAD', '--name-only'], cwd=root, text=True).splitlines()
    if any(path != 'dist/data/seafloor-ledger.json' for path in changed):
        raise ValueError('Publication code differs from main')
    s3, bucket = credentials()
    folder, manifest = build(region, root=root)
    key = publish_bundle(s3, bucket, folder)
    return {'key': key, 'manifest': manifest}
