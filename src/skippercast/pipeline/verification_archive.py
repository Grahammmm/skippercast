"""Bounded, checksummed storage for public prospective verification history.

Current and previous manifests reference immutable gzip shards. A missing shard
is a failed archive, never permission to restart a prospective history silently.
"""
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile

SCHEMA_VERSION = 2
MAX_ROWS = 2000
MAX_RAW_BYTES = 2 * 1024 * 1024
MAX_COMPRESSED_BYTES = MAX_RAW_BYTES + 65536
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_LEGACY_BYTES = 256 * 1024 * 1024
SAFE_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
SHARD_PATH = re.compile(r'^verification-archive/(forecasts|observations)/[A-Za-z0-9_-]{1,64}/\d{4}-\d{2}-\d{2}/[A-Za-z0-9_-]{1,64}/[0-9a-f]{64}\.json\.gz$')


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _safe_path(directory, relative):
    if not isinstance(relative, str) or not SHARD_PATH.fullmatch(relative):
        raise ValueError('Invalid verification shard path')
    path = directory.joinpath(*PurePosixPath(relative).parts)
    if not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError('Verification shard escapes archive directory')
    if any(p.is_symlink() for p in [path, *list(path.parents)[:5]]):
        raise ValueError('Verification archive cannot contain symlinks')
    return path


def _read_json(path, limit):
    if path.is_symlink() or path.stat().st_size > limit:
        raise ValueError('Verification manifest is linked or exceeds its size bound')
    return json.loads(path.read_bytes())


def _shard_bytes(directory, entry):
    path = _safe_path(directory, entry.get('path'))
    if not path.is_file():
        raise ValueError(f'Missing verification shard: {entry.get("path")}')
    size = path.stat().st_size
    if size > MAX_COMPRESSED_BYTES or size != entry.get('compressed_bytes'):
        raise ValueError('Verification shard compressed size mismatch')
    compressed = path.read_bytes()
    if _digest(compressed) != entry.get('sha256'):
        raise ValueError('Verification shard checksum mismatch')
    return compressed


def _decode(directory, region_id, entry):
    compressed = _shard_bytes(directory, entry)
    with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode='rb') as stream:
        raw = stream.read(MAX_RAW_BYTES + 1)
    if len(raw) > MAX_RAW_BYTES or len(raw) != entry.get('raw_bytes') or _digest(raw) != entry.get('raw_sha256'):
        raise ValueError('Verification shard expanded size or checksum mismatch')
    payload = json.loads(raw)
    if payload.get('schema_version') != 1 or payload.get('region_id') != region_id:
        raise ValueError('Verification shard has the wrong schema or region')
    if any(payload.get(k) != entry.get(k) for k in ('kind', 'station', 'day', 'model')):
        raise ValueError('Verification shard metadata mismatch')
    rows = payload.get('records')
    if not isinstance(rows, list) or len(rows) > MAX_ROWS or len(rows) != entry.get('count'):
        raise ValueError('Verification shard row count mismatch')
    for row in rows:
        if not isinstance(row, dict) or row.get('station') != entry['station']:
            raise ValueError('Verification shard station mismatch')
        if entry['kind'] == 'forecasts' and row.get('model') != entry['model']:
            raise ValueError('Verification shard model mismatch')
        epoch = row.get('cycle') if entry['kind'] == 'forecasts' else row.get('time')
        if datetime.fromtimestamp(epoch, timezone.utc).date().isoformat() != entry['day']:
            raise ValueError('Verification shard date mismatch')
    return rows


def load_archive(directory, region_id, required=False, *, manifest_name='verification-state.json'):
    """Return v1-shaped rows from either a legacy archive or verified v2 shards."""
    directory = Path(directory)
    if manifest_name not in ('verification-state.json', 'verification-state.previous.json'):
        raise ValueError('Invalid verification manifest filename')
    path = directory / manifest_name
    if not path.is_file():
        if required:
            raise ValueError('Prior regional feed exists but its verification archive is missing')
        return {'schema_version': 1, 'region_id': region_id, 'forecasts': [], 'observations': []}
    # v1 may be large during migration, but all new manifests are bounded.
    data = _read_json(path, MAX_LEGACY_BYTES)
    if data.get('region_id') != region_id:
        raise ValueError('Prior verification archive belongs to another region')
    if data.get('schema_version') == 1:
        if not all(isinstance(data.get(kind), list) for kind in ('forecasts', 'observations')):
            raise ValueError('Incomplete legacy verification archive')
        return data
    if data.get('schema_version') != SCHEMA_VERSION or data.get('storage') != 'gzip-shards-v1':
        raise ValueError('Unknown verification archive format')
    if path.stat().st_size > MAX_MANIFEST_BYTES or not isinstance(data.get('shards'), list):
        raise ValueError('Invalid verification shard manifest')
    output = {'schema_version': 1, 'region_id': region_id, 'forecasts': [], 'observations': []}
    paths = set()
    for entry in data['shards']:
        if not isinstance(entry, dict) or entry.get('kind') not in ('forecasts', 'observations') or entry.get('path') in paths:
            raise ValueError('Invalid or duplicate verification shard entry')
        paths.add(entry['path'])
        output[entry['kind']].extend(_decode(directory, region_id, entry))
    for kind in ('forecasts', 'observations'):
        if len(output[kind]) != data.get(kind + '_count'):
            raise ValueError('Verification archive total count mismatch')
        output[kind].sort(key=lambda row: (row['time'], row['id']))
    return output


def _write_payload(directory, metadata, rows):
    payload = {'schema_version': 1, **metadata, 'records': rows}
    raw = _json(payload)
    if len(raw) > MAX_RAW_BYTES:
        if len(rows) == 1:
            raise ValueError('A verification record exceeds the shard size bound')
        middle = len(rows) // 2
        return _write_payload(directory, metadata, rows[:middle]) + _write_payload(directory, metadata, rows[middle:])
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0, compresslevel=6) as stream:
        stream.write(raw)
    compressed = output.getvalue()
    if len(compressed) > MAX_COMPRESSED_BYTES:
        raise ValueError('Compressed verification shard exceeds its bound')
    digest = _digest(compressed)
    relative = f'verification-archive/{metadata["kind"]}/{metadata["station"]}/{metadata["day"]}/{metadata["model"]}/{digest}.json.gz'
    path = _safe_path(directory, relative)
    if path.exists():
        if path.read_bytes() != compressed:
            raise ValueError('Immutable verification shard content conflict')
    else:
        _atomic_bytes(path, compressed)
    return [{'path': relative, 'sha256': digest, 'raw_sha256': _digest(raw), 'compressed_bytes': len(compressed),
             'raw_bytes': len(raw), 'count': len(rows), **{k: metadata[k] for k in ('kind', 'station', 'day', 'model')}}]


def _write_generation(directory, region_id, forecasts, observations, now):
    grouped = defaultdict(list)
    for kind, rows in [('forecasts', forecasts), ('observations', observations)]:
        for row in rows:
            station = row.get('station')
            model = row.get('model') if kind == 'forecasts' else 'ndbc'
            if not isinstance(station, str) or not SAFE_ID.fullmatch(station) or not isinstance(model, str) or not SAFE_ID.fullmatch(model):
                raise ValueError('Invalid verification station or model identifier')
            epoch = row.get('cycle') if kind == 'forecasts' else row.get('time')
            day = datetime.fromtimestamp(epoch, timezone.utc).date().isoformat()
            grouped[(kind, station, day, model)].append(row)
    shards = []
    for (kind, station, day, model), rows in sorted(grouped.items()):
        rows.sort(key=lambda row: (row['time'], row['id']))
        metadata = {'kind': kind, 'station': station, 'day': day, 'model': model, 'region_id': region_id}
        for offset in range(0, len(rows), MAX_ROWS):
            shards += _write_payload(directory, metadata, rows[offset:offset + MAX_ROWS])
    manifest = {'schema_version': SCHEMA_VERSION, 'storage': 'gzip-shards-v1', 'region_id': region_id,
                'generated_at': datetime.fromtimestamp(now, timezone.utc).isoformat().replace('+00:00', 'Z'),
                'forecasts_count': len(forecasts), 'observations_count': len(observations),
                'retention_days': 30, 'max_shard_raw_bytes': MAX_RAW_BYTES, 'shards': shards}
    if len(_json(manifest)) > MAX_MANIFEST_BYTES:
        raise ValueError('Verification manifest exceeds its bound; split the region or migrate storage')
    return manifest


def write_archive(directory, region_id, forecasts, observations, now, previous_directory=None):
    """Write current plus one prior generation; prune only managed unreferenced blobs."""
    directory = Path(directory)
    if not SAFE_ID.fullmatch(region_id):
        raise ValueError('Invalid verification region identifier')
    previous_directory = Path(previous_directory) if previous_directory else directory
    previous_path = previous_directory / 'verification-state.json'
    previous = None
    if previous_path.is_file():
        prior = _read_json(previous_path, MAX_LEGACY_BYTES)
        if prior.get('region_id') != region_id:
            raise ValueError('Previous archive region mismatch')
        if prior.get('schema_version') == 1:
            old = load_archive(previous_directory, region_id, required=True)
            previous = _write_generation(directory, region_id, old['forecasts'], old['observations'], now)
            previous['migrated_from_schema_version'] = 1
        elif prior.get('schema_version') == SCHEMA_VERSION and prior.get('storage') == 'gzip-shards-v1':
            # Validate the full previous generation before preserving it. A
            # corrupt old archive must not become an apparently successful run.
            load_archive(previous_directory, region_id, required=True)
            previous = prior
            for entry in prior['shards']:
                dest = _safe_path(directory, entry['path'])
                data = _shard_bytes(previous_directory, entry)
                if not dest.exists():
                    _atomic_bytes(dest, data)
                elif _digest(dest.read_bytes()) != entry['sha256']:
                    raise ValueError('Existing immutable verification shard differs')
        else:
            raise ValueError('Unknown prior verification archive format')
    current = _write_generation(directory, region_id, forecasts, observations, now)
    if previous is not None:
        _atomic_bytes(directory / 'verification-state.previous.json', _json(previous) + b'\n')
    _atomic_bytes(directory / 'verification-state.json', _json(current) + b'\n')
    prune_archive(directory)
    return current


def prune_archive(directory):
    """After publishing/copying a region, retain both complete manifest generations."""
    directory = Path(directory)
    current_path = directory / 'verification-state.json'
    if not current_path.is_file():
        return 0
    current = _read_json(current_path, MAX_LEGACY_BYTES)
    if current.get('schema_version') == 1:
        return 0
    keep = set()
    for name in ('verification-state.json', 'verification-state.previous.json'):
        path = directory / name
        if not path.is_file():
            continue
        manifest = _read_json(path, MAX_MANIFEST_BYTES)
        load_archive(directory, current.get('region_id'), required=True, manifest_name=name)
        keep.update(entry['path'] for entry in manifest['shards'])
    deleted = 0
    archive = directory / 'verification-archive'
    if archive.exists():
        for path in archive.rglob('*.json.gz'):
            relative = path.relative_to(directory).as_posix()
            if SHARD_PATH.fullmatch(relative) and relative not in keep:
                _safe_path(directory, relative).unlink()
                deleted += 1
        for path in sorted(archive.rglob('*'), reverse=True):
            if path.is_dir() and not path.is_symlink():
                try:
                    path.rmdir()
                except OSError:
                    pass
    return deleted
