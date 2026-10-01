"""Qualified regional PMTiles and fail-closed R2 publication; never raw surveys."""
from datetime import datetime, timedelta, timezone
import gzip
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

TO_GEO = Transformer.from_crs(3310, 4326, always_xy=True).transform
NOTICE = 'Planning only. Not a navigation chart. Check current CDFW regulations.'


def flat_properties(properties):
    """MVT supports scalar values: retain nested evidence as canonical JSON."""
    result = {key: (json.dumps(value, sort_keys=True, separators=(',', ':'))
                    if isinstance(value, (dict, list)) else value) for key, value in properties.items()}
    result['terrain_grade'] = properties['terrain']['grade']
    result['terrain_score'] = properties['terrain']['score']
    result.update({'fit_'+key.replace('-', '_'): value for key, value in properties['fit'].items()})
    return result


def region_layers(root, region, *, rerun=True, now=None):
    root = Path(root)
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
            if (checkpoint.get('catalog_sha256') != sha256(root/'catalog/surveys.json')
                    or checkpoint.get('rules_sha256') != sha256(root/'catalog/habitat-rules.json')
                    or checkpoint.get('reference_sha256') != sha256(reference)):
                raise ValueError('Coverage checkpoint inputs changed; rerun required')
            if sha256(folder/'coverage-cells.json') != checkpoint['cells_sha256']:
                raise ValueError('Coverage checkpoint checksum mismatch')
            cells.update({c['id']: c for c in read_json(folder/'coverage-cells.json')['cells']})
            continue  # measured coverage only; no old habitat from a failed run
        if rerun:
            run(ident, root=root)  # validates current manifests, actual source bytes, rules and implementation
        folder = root/'var/seafloor/reaches'/ident
        receipt = read_json(folder/'run.json')
        if any(source.get('status') == 'physical-only' for source in receipt['inputs'].get('sources', [])):
            raise ValueError('Private physical source cannot enter publication')
        for name, expected in receipt['outputs'].items():
            if Path(name).name != name or sha256(folder/name) != expected:
                raise ValueError('Reach output checksum mismatch')
        screen = load_snapshot(root, ident)
        if receipt['inputs']['screen'] != input_identity(screen):
            raise ValueError('Reach screen is no longer current; rerun required')
        selected = read_json(folder/'habitat.geojson')['features']
        if selected and screen['status'] != 'ready':
            raise ValueError('Held reach cannot publish habitat')
        for f in selected:
            p = f['properties']
            if p['tier'] != 2 or p['status'] != 'habitat' or not p['exportable'] or p['screen']['status'] != 'pass':
                raise ValueError('Unqualified feature in publication input')
            if sources is None:
                sources = {s['id']: s for s in read_json(root/'catalog/surveys.json')['surveys']}
            contributors = list(p['source_ids'])
            substrate = p.get('substrate', {})
            if isinstance(substrate, dict) and substrate.get('source_id') not in (None, 'unknown'):
                contributors.append(substrate['source_id'])
            public_properties = dict(p, source_rights=feature_rights(contributors, sources,
                use=deployment_use(root)))
            habitat.append({'type': 'Feature', 'geometry': f['geometry'], 'properties': flat_properties(public_properties)})
        cells.update({c['id']: c for c in read_json(folder/'cells.json')['cells']})
        receipts[ident] = {'input_hash': receipt['input_hash'], 'run_sha256': sha256(folder/'run.json'),
                          'summary': receipt['ledger_summary']}
        if selected:
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


def build(region, *, root=REPO, tool=None, now=None):
    from scripts.build_map_tiles import build_vector_archive
    root = Path(root)
    tool = tool or os.environ.get('TIPPECANOE') or shutil.which('tippecanoe')
    if not tool:
        raise ValueError('Install pinned tippecanoe or set TIPPECANOE')
    now = now or datetime.now(timezone.utc)
    layers, receipts, expires = region_layers(root, region, now=now)
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
                'expires_at': expires.isoformat(), 'built_at': now.isoformat(),
                'archive': archive.name, 'archive_sha256': sha256(archive), 'archive_bytes': archive.stat().st_size,
                'layers': {name: len(features) for name, features in layers.items()},
                'ledger_sha256': sha256(folder/'ledger.json'),
                'export_file': export.name,
                'export_sha256': sha256(export),
                'export_bytes': export.stat().st_size,
                'export_decoded_bytes': len(export_bytes),
                'source_attribution': credits,
                'source_use_notice': 'Retain source-specific terms and credits; mixed data do not become public-domain.',
                'reach_inputs': {key: value['input_hash'] for key, value in receipts.items()},
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
