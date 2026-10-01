"""Private R2 recovery for original grids and per-reach state, with hash checks.

Only pipeline-owned relative paths can be restored. Raw bytes are stored under
seafloor-cache/, never the Worker feed prefixes. Inventory writes are per scope
so matrix workers cannot overwrite one another's reach state.
"""
from pathlib import Path
import json
import re

from .fetch import restore_private, upload_private
from .io import sha256

SAFE = re.compile(r'(?:reference/(?:cells|run)\.json|cache/[a-f0-9]{64}/(?:source\.(?:zip|bag|tif|tiff|tgz|tar\.gz|json)|[a-f0-9]{64}\.(?:tif|json))|(?:reaches|private-reaches)/[a-z0-9-]+/(?:cells|terrain|habitat|held|candidates|atlas-comparison|coverage-checkpoint|coverage-cells|physical|run)\.(?:json|geojson)|screen/(?:snapshot|source-receipts|refresh-failure|(?:cdfw-mpa|noaa-federal|security)-[a-f0-9]{64})\.json)')


def missing(error):
    return getattr(error, 'response', {}).get('Error', {}).get('Code') in ('NoSuchKey', '404', 'NotFound')


def scope_name(name):
    if not re.fullmatch('[a-z0-9-]+', name):
        raise ValueError('Invalid private state scope')
    return name


def allowed(name, path):
    prefixes = ('reference/', 'screen/') if name == 'shared' else ('cache/', f'reaches/{name}/', f'private-reaches/{name}/')
    return bool(SAFE.fullmatch(path)) and path.startswith(prefixes)


def save(s3, bucket, root, name, paths):
    name = scope_name(name)
    base = Path(root)/'var/seafloor'
    entries = []
    for path in sorted(set(Path(p) for p in paths)):
        relative = path.relative_to(base).as_posix()
        if not allowed(name, relative) or path.is_symlink() or not path.resolve().is_relative_to(base.resolve()):
            raise ValueError('Unreviewed private cache path')
        digest = sha256(path)
        key = f'seafloor-cache/{digest}/{path.name}'
        try:
            s3.head_object(Bucket=bucket, Key=key)
        except Exception as error:
            if not missing(error):
                raise
            upload_private(s3, bucket, path)
        entries.append({'path': relative, 'sha256': digest, 'bytes': path.stat().st_size})
    document = {'version': 1, 'scope': name, 'files': entries}
    s3.put_object(Bucket=bucket, Key=f'seafloor-cache/state/{name}.json',
                  Body=json.dumps(document).encode(), ContentType='application/json', CacheControl='private, no-store')
    return document


def restore(s3, bucket, root, name, *, include_cache=True):
    name = scope_name(name)
    try:
        with s3.get_object(Bucket=bucket, Key=f'seafloor-cache/state/{name}.json')['Body'] as stream:
            raw = stream.read(5_000_001)
    except Exception as error:
        if missing(error):
            return False
        raise
    if len(raw) > 5_000_000:
        raise ValueError('Oversized state inventory')
    data = json.loads(raw)
    if data['scope'] != name or data['version'] != 1:
        raise ValueError('Private state scope mismatch')
    base = Path(root)/'var/seafloor'
    if name == 'shared' and not any(e['path'] == 'screen/refresh-failure.json' for e in data['files']):
        (base/'screen/refresh-failure.json').unlink(missing_ok=True)
    for entry in data['files']:
        if not allowed(name, entry['path']) or not re.fullmatch('[a-f0-9]{64}', entry['sha256']):
            raise ValueError('Unreviewed private restore path')
        # Bookkeeping uses checked reach receipts, not original survey bytes.
        # Scientific processing/publication retain the default full restore.
        if not include_cache and entry['path'].startswith('cache/'):
            continue
        path = base/entry['path']
        if not path.resolve().is_relative_to(base.resolve()) or path.is_symlink():
            raise ValueError('Private restore escapes its root')
        if path.exists() and sha256(path) == entry['sha256']:
            continue
        restore_private(s3, bucket, path, entry['sha256'])
        if path.stat().st_size != entry['bytes']:
            raise ValueError('Private restore size mismatch')
    return True


def reach_paths(root, reach):
    base = Path(root)/'var/seafloor'
    scope_name(reach)
    # Do not attach every downloaded survey to every reach: that made each
    # matrix worker restore unrelated coastal archives as the catalog grew.
    folders = [base/'reaches'/reach, base/'private-reaches'/reach]
    hashes = set()
    for folder in folders:
        checkpoint = folder/'coverage-checkpoint.json'
        if checkpoint.exists():
            hashes.update(json.loads(checkpoint.read_text()).get('source_hashes', []))
        receipt = folder/'run.json'
        if receipt.exists():
            inputs = json.loads(receipt.read_text()).get('inputs', {})
            hashes.update(r['sha256'] for r in inputs.get('sources', []))
            hashes.update(b['row']['sha256'] for b in inputs.get('substrate_bindings', {}).values())
    if any(not re.fullmatch('[a-f0-9]{64}', h) for h in hashes):
        raise ValueError('Invalid source hash in private reach state')
    directories = folders + [base/'cache'/h for h in sorted(hashes)]
    return [p for directory in directories for p in directory.rglob('*')
            if p.is_file() and SAFE.fullmatch(p.relative_to(base).as_posix())]


def shared_paths(root):
    base = Path(root)/'var/seafloor'
    paths = [base/'reference/cells.json', base/'reference/run.json']
    snapshot = base/'screen/snapshot.json'
    if snapshot.exists():
        data = json.loads(snapshot.read_text())
        paths += [snapshot] + [base/'screen'/r['file'] for r in data['layers'].values()]
    paths += [base/'screen'/n for n in ('source-receipts.json', 'refresh-failure.json')
              if (base/'screen'/n).exists()]
    return paths
