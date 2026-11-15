"""STAGE-ONLY size receipt for the rough-first seafloor archive (F1C-MEASURE).

Lives only on the unmerged branch rb/f1c-measure. It restores private reach state
through a read-only R2 client, builds the control archive (Rk, today's builder) and
the rough-first candidate (Rc, ``coarse_first=True``) from the same region layers
into a private runner folder, reads the live archive C and its manifest, and writes
ONE file: receipt.json (per-zoom sizes, reference sizes, deltas, pass/fail and the
build input identities). Archives never leave the runner.

Stage-only switch: ``SEAFLOOR_STAGE_ONLY=1`` is required, ``refs/heads/main`` is
refused, and every R2 client handed out is wrapped so only get_object, head_object
and list_objects_v2 work. Any other client call, and every publication helper
(publish_bundle, upload, state_cache.save, upload_private, publish_r2.sync), raises
StageOnlyWrite. Acceptance policy: PROPOSAL.md section 4 (revision 2).
"""
import argparse
import functools
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

REGION = 'morro-bay'
READ_METHODS = frozenset({'get_object', 'head_object', 'list_objects_v2'})
LISTED_PREFIXES = ('tiles/seafloor/', 'seafloor-cache/', 'seafloor-review/')
# EXPERIMENT.md lines 72-76: the approved rough-first variant A1, payload bytes per zoom.
A1_BYTES = {8: 464493, 9: 477289, 10: 623177, 11: 893681, 12: 2163052}
# PROPOSAL.md section 4 item 1 (proposed policy): Rc <= A1 x 1.035, as tabulated there.
CEILINGS = {8: 480750, 9: 493994, 10: 644988, 11: 924959}
OPENING_TILES = ((10, 167, 404), (10, 168, 404))
OPENING_A1, OPENING_CEILING = 375500, 388642
ANOMALY_FLOOR = 0.15
CLAIMED_SAVING = (20.0, 32.0)


class StageOnlyWrite(RuntimeError):
    """A live write was attempted while the stage-only switch is on."""


class ReadOnlyS3:
    """Pass through read calls only; every other S3 operation raises."""

    def __init__(self, client):
        self._client = client
        self.calls = {}

    @property
    def exceptions(self):
        return self._client.exceptions

    def __getattr__(self, name):
        if name not in READ_METHODS:
            raise StageOnlyWrite(f'stage-only: S3 {name} refused')
        method = getattr(self._client, name)

        def call(*args, **kwargs):
            self.calls[name] = self.calls.get(name, 0) + 1
            return method(*args, **kwargs)
        return call


def _refuse(name):
    def refused(*args, **kwargs):
        raise StageOnlyWrite(f'stage-only: {name} refused')
    return refused


def require_stage_only(environ=os.environ):
    if environ.get('SEAFLOOR_STAGE_ONLY') != '1':
        raise StageOnlyWrite('SEAFLOOR_STAGE_ONLY=1 is required')
    if environ.get('GITHUB_REF') == 'refs/heads/main':
        raise StageOnlyWrite('stage-only measurement never runs on main')


def install_stage_only():
    """Wrap every R2 client read-only and disable the publication helpers."""
    import scripts.publish_r2 as publish_r2
    from . import fetch, publish, state_cache
    original = publish_r2.client
    if not getattr(original, 'stage_only', False):
        def client(*args, **kwargs):
            return ReadOnlyS3(original(*args, **kwargs))
        setattr(client, 'stage_only', True)
        publish_r2.client = client
    publish_r2.sync = _refuse('publish_r2.sync')
    publish.publish_bundle = _refuse('publish_bundle')
    publish.upload = _refuse('upload')
    state_cache.save = _refuse('state_cache.save')
    fetch.upload_private = _refuse('upload_private')
    state_cache.upload_private = _refuse('upload_private')


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _varint(data, pos):
    value = shift = 0
    while True:
        byte = data[pos]
        pos += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
        shift += 7


def _zxy(tile_id):
    z = 0
    while tile_id >= (4 ** (z + 1) - 1) // 3:
        z += 1
    d, x, y, s = tile_id - (4 ** z - 1) // 3, 0, 0, 1
    while s < 2 ** z:
        rx, ry = (d // 2) & 1, (d ^ (d // 2)) & 1
        if ry == 0:
            if rx:
                x, y = s - 1 - x, s - 1 - y
            x, y = y, x
        x, y, d, s = x + s * rx, y + s * ry, d // 4, s * 2
    return z, x, y


def read_tiles(data):
    """{(z, x, y): stored tile bytes} for a gzip-directory PMTiles v3 archive."""
    if data[:8] != b'PMTiles\x03':
        raise ValueError('not PMTiles v3')
    h = struct.unpack_from('<11Q', data, 8)
    if data[97] != 2:
        raise ValueError('expected gzip internal compression')
    tiles = {}

    def walk(offset, length):
        d = gzip.decompress(data[offset:offset + length])
        count, pos = _varint(d, 0)
        rows, tid = [], 0
        for _ in range(count):
            delta, pos = _varint(d, pos)
            tid += delta
            rows.append([tid, 0, 0, 0])
        for column in (1, 2, 3):
            for row in rows:
                row[column], pos = _varint(d, pos)
        for i, row in enumerate(rows):
            row[3] = rows[i - 1][3] + rows[i - 1][2] if row[3] == 0 and i else row[3] - 1
        for tid, run, size, off in rows:
            if not run:
                walk(h[4] + off, size)
                continue
            for k in range(run):
                tiles[_zxy(tid + k)] = data[h[6] + off:h[6] + off + size]
    walk(h[0], h[1])
    if len(tiles) != h[8]:
        raise ValueError('addressed tile count mismatch')
    return tiles


def per_zoom(tiles):
    out = {}
    for (z, _, _), raw in tiles.items():
        slot = out.setdefault(z, {'tiles': 0, 'bytes': 0})
        slot['tiles'] += 1
        slot['bytes'] += len(raw)
    return dict(sorted(out.items()))


def identity(a, b, zooms):
    """Tile-level byte identity of b against a over the given zooms."""
    keys_a = {k for k in a if k[0] in zooms}
    keys_b = {k for k in b if k[0] in zooms}
    same = sorted(k for k in keys_a & keys_b if a[k] == b[k])
    differ = sorted(k for k in keys_a & keys_b if a[k] != b[k])
    by_zoom = {z: {'identical': sum(k[0] == z for k in same), 'different': sum(k[0] == z for k in differ),
                   'only_reference': sum(k[0] == z for k in keys_a - keys_b),
                   'only_candidate': sum(k[0] == z for k in keys_b - keys_a)} for z in sorted(zooms)}
    return {'identical': len(same), 'addressed_reference': len(keys_a), 'addressed_candidate': len(keys_b),
            'all_identical': keys_a == keys_b and not differ, 'by_zoom': by_zoom,
            'first_different': ['/'.join(map(str, k)) for k in differ[:20]]}


def _fields(data):
    pos, out = 0, []
    while pos < len(data):
        key, pos = _varint(data, pos)
        wire, num = key & 7, key >> 3
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire == 2:
            size, pos = _varint(data, pos)
            value, pos = data[pos:pos + size], pos + size
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            value, pos = data[pos:pos + size], pos + size
        else:
            raise ValueError('unsupported protobuf wire type')
        out.append((num, value))
    return out


def habitat_ids(raw):
    """(feature occurrences, set of ids) in a gzip MVT tile's habitat layer."""
    features, ids = 0, set()
    for num, layer in _fields(gzip.decompress(raw)):
        if num != 3:
            continue
        rows = _fields(layer)
        if next((v for n, v in rows if n == 1), b'') != b'habitat':
            continue
        keys = [v.decode() for n, v in rows if n == 3]
        values = [v for n, v in rows if n == 4]
        for n, feature in rows:
            if n != 2:
                continue
            features += 1
            f = _fields(feature)
            tags_raw = next((v for k, v in f if k == 2), b'')
            tags, pos = [], 0
            while pos < len(tags_raw):
                t, pos = _varint(tags_raw, pos)
                tags.append(t)
            props = {keys[tags[i]]: values[tags[i + 1]] for i in range(0, len(tags) - 1, 2)}
            if 'id' in props:
                text = next((v for k, v in _fields(props['id']) if k == 1), None)
                ids.add(text.decode() if isinstance(text, bytes) else props['id'].hex())
            else:
                fid = next((v for k, v in f if k == 1), None)
                if fid is not None:
                    ids.add(str(fid))
    return features, ids


def content(tiles, zooms):
    out = {}
    for z in zooms:
        occurrences, ids = 0, set()
        for key, raw in tiles.items():
            if key[0] == z:
                n, found = habitat_ids(raw)
                occurrences += n
                ids |= found
        out[z] = (occurrences, ids)
    return out


def evaluate(c_tiles, rk_tiles, rc_tiles):
    """PROPOSAL.md section 4 items 0, 1, 3 and 4 (item 2, the label, is the product PR's)."""
    c, rk, rc = per_zoom(c_tiles), per_zoom(rk_tiles), per_zoom(rc_tiles)
    all_zooms = set(c) | set(rk) | set(rc)
    calibration = identity(c_tiles, rk_tiles, all_zooms)
    sizes = {}
    for z in sorted(all_zooms | set(A1_BYTES)):
        row = {'C_live': c.get(z), 'Rk_control': rk.get(z), 'Rc_candidate': rc.get(z)}
        rc_bytes = (rc.get(z) or {}).get('bytes', 0)
        if z in A1_BYTES:
            row['A1_reference'] = A1_BYTES[z]
            row['Rc_vs_A1_percent'] = round((rc_bytes - A1_BYTES[z]) / A1_BYTES[z] * 100, 3)
        if z in CEILINGS:
            ratio = rc_bytes / rk[z]['bytes'] if rk.get(z) else None
            row.update(ceiling=CEILINGS[z], within_ceiling=rc_bytes <= CEILINGS[z],
                       Rc_over_Rk=round(ratio, 4) if ratio is not None else None,
                       anomaly=ratio is None or ratio < ANOMALY_FLOOR)
        sizes[str(z)] = row
    opening = sum(len(rc_tiles.get(k, b'')) for k in OPENING_TILES)
    total_rk = sum(len(v) for v in rk_tiles.values())
    total_rc = sum(len(v) for v in rc_tiles.values())
    saving = round((1 - total_rc / total_rk) * 100, 3) if total_rk else None
    detail = identity(rk_tiles, rc_tiles, {12, 13, 14, 15})
    rk_content, rc_content = content(rk_tiles, range(8, 13)), content(rc_tiles, range(8, 13))
    retained = {}
    for z in range(8, 13):
        (rk_n, rk_ids), (rc_n, rc_ids) = rk_content[z], rc_content[z]
        retained[str(z)] = {'Rk_occurrences': rk_n, 'Rc_occurrences': rc_n,
                            'Rk_ids': len(rk_ids), 'Rc_ids': len(rc_ids), 'Rk_ids_missing_in_Rc': len(rk_ids - rc_ids),
                            'occurrence_ratio': round(rc_n / rk_n, 4) if rk_n else None}
    content_pass = all(retained[str(z)]['Rk_ids_missing_in_Rc'] == 0
                       and (retained[str(z)]['occurrence_ratio'] or 0) >= 0.99 for z in (9, 10, 11))
    size_pass = (all(sizes[str(z)].get('within_ceiling') for z in CEILINGS)
                 and opening <= OPENING_CEILING)
    anomaly = any(sizes[str(z)].get('anomaly') for z in CEILINGS)
    items = {
        'item0_calibration_Rk_vs_C': {'pass': calibration['all_identical'], **calibration},
        'item1_rough_sizes': {'pass': size_pass and not anomaly, 'sizes_within_ceilings': size_pass,
                              'anomaly_floor_hit': anomaly, 'opening_z10_bytes': opening,
                              'opening_z10_A1': OPENING_A1, 'opening_z10_ceiling': OPENING_CEILING,
                              'whole_file_payload_Rk': total_rk, 'whole_file_payload_Rc': total_rc,
                              'whole_file_saving_percent': saving,
                              'saving_inside_claimed_20_to_32': (saving is not None
                                                                 and CLAIMED_SAVING[0] <= saving <= CLAIMED_SAVING[1])},
        'item2_rough_label': {'pass': None, 'note': 'not measured here; app wiring belongs to the product PR'},
        'item3_detail_Rc_vs_Rk_z12_15': {'pass': detail['all_identical'], **detail},
        'item4_content_z9_11': {'pass': content_pass, 'by_zoom': retained,
                                'note': 'z8 and z12 reported, not gated'},
    }
    overall = all(items[k]['pass'] for k in items if items[k]['pass'] is not None)
    return {'per_zoom': sizes, 'acceptance': items, 'size_pass': size_pass and not anomaly,
            'pass': overall,
            'pass_rule': 'items 0, 1, 3 and 4 of PROPOSAL.md section 4; item 0 fails closed, no rebaseline'}


def watched_keys(region, rows):
    """Live objects a publish run would write, plus the private state inventories this run reads."""
    keys = [f'tiles/seafloor/manifest-{region}.json', f'tiles/seafloor/seafloor-{region}.pmtiles',
            f'tiles/seafloor/regions/{region}/habitat-export.geojson.gz', f'tiles/seafloor/regions/{region}/ledger.json',
            f'tiles/seafloor/regions/{region}/manifest.json', f'tiles/seafloor/regions/{region}/seafloor-{region}.pmtiles']
    return keys + [f'seafloor-cache/state/{name}.json' for name in ['shared'] + [r['id'] for r in rows]]


def snapshot(s3, bucket, keys, region=REGION):
    """Read-only bucket state: prefix listing digests (when the token may list) and HEAD of each watched key."""
    try:
        listed = listing(s3, bucket, region=region)
    except Exception as error:  # a token without ListObjects still gets the HEAD comparison
        listed = {'error': type(error).__name__}
    heads = {}
    for key in keys:
        try:
            got = s3.head_object(Bucket=bucket, Key=key)
            modified = got.get('LastModified')
            heads[key] = {'etag': got.get('ETag'), 'bytes': got.get('ContentLength'),
                          'modified': modified.isoformat() if hasattr(modified, 'isoformat') else modified,
                          'sha256_metadata': (got.get('Metadata') or {}).get('sha256')}
        except Exception as error:
            heads[key] = {'absent_or_unreadable': type(error).__name__}
    return {'listing': listed, 'heads': heads}


def listing(s3, bucket, prefixes=LISTED_PREFIXES, region=REGION):
    """Read-only listing digest per prefix; the live region objects are recorded in full."""
    out, live = {}, {}
    for prefix in prefixes:
        lines, token = [], None
        while True:
            kwargs = {'Bucket': bucket, 'Prefix': prefix, **({'ContinuationToken': token} if token else {})}
            page = s3.list_objects_v2(**kwargs)
            for item in page.get('Contents', []):
                modified = item.get('LastModified')
                lines.append('\t'.join([item['Key'], str(item.get('ETag')), str(item.get('Size')),
                                        modified.isoformat() if hasattr(modified, 'isoformat') else str(modified)]))
                if prefix == 'tiles/seafloor/' and region in item['Key'] and '/' not in item['Key'][len(prefix):]:
                    live[item['Key']] = {'etag': item.get('ETag'), 'bytes': item.get('Size'), 'modified': lines[-1].split('\t')[3]}
            if not page.get('IsTruncated'):
                break
            token = page.get('NextContinuationToken')
        lines.sort()
        out[prefix] = {'objects': len(lines), 'sha256': sha256_bytes('\n'.join(lines).encode())}
    return {'prefixes': out, 'live_region_objects': dict(sorted(live.items()))}


def _get(s3, bucket, key):
    got = s3.get_object(Bucket=bucket, Key=key)
    with got['Body'] as stream:
        return stream.read(), got.get('ETag')


def file_sha(path):
    path = Path(path)
    return sha256_bytes(path.read_bytes()) if path.exists() else None


def _git_head(root):
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def measure(root, out, *, region=REGION, tool=None):
    require_stage_only()
    install_stage_only()
    from . import publish, state_cache
    import scripts.build_map_tiles as builder
    root = Path(root)
    work = root/'var/seafloor/measure'
    work.mkdir(parents=True, exist_ok=True)
    tool = tool or os.environ.get('TIPPECANOE') or shutil.which('tippecanoe')
    if not tool:
        raise ValueError('Install pinned tippecanoe or set TIPPECANOE')
    receipt = {'receipt': 'F1C-MEASURE stage-only size receipt', 'region': region,
               'policy': 'PROPOSAL.md revision 2 section 4 (proposed policy)',
               'commit': os.environ.get('GITHUB_SHA') or _git_head(root),
               'github_run_id': os.environ.get('GITHUB_RUN_ID'), 'github_ref': os.environ.get('GITHUB_REF')}
    s3, bucket = publish.credentials()
    if not isinstance(s3, ReadOnlyS3):
        raise StageOnlyWrite('credentials() did not return the read-only client')
    rows = [r for r in json.loads((root/'dist/data/seafloor-ledger.json').read_text())['reaches']
            if r['region'] == region and r['status'] != 'unassessed']
    keys = watched_keys(region, rows)
    receipt['bucket_before'] = snapshot(s3, bucket, keys, region)
    try:
        body, etag = _get(s3, bucket, f'tiles/seafloor/manifest-{region}.json')
        live = json.loads(body)
        c_data, c_etag = _get(s3, bucket, f'tiles/seafloor/seafloor-{region}.pmtiles')
        receipt['live'] = {'manifest_sha256': sha256_bytes(body), 'manifest_etag': etag,
                           'status': live.get('status'), 'built_at': live.get('built_at'),
                           'archive_sha256': live.get('archive_sha256'), 'archive_bytes': live.get('archive_bytes'),
                           'archive_read_sha256': sha256_bytes(c_data), 'archive_etag': c_etag,
                           'reach_inputs': live.get('reach_inputs'), 'classified_inputs': live.get('classified_inputs')}
        inventories = {}
        for name in ['shared'] + [r['id'] for r in rows]:
            raw, inv_etag = _get(s3, bucket, f'seafloor-cache/state/{name}.json')
            restored = state_cache.restore(s3, bucket, root, name)
            inventories[name] = {'key': f'seafloor-cache/state/{name}.json', 'sha256': sha256_bytes(raw),
                                 'etag': inv_etag, 'files': len(json.loads(raw).get('files', [])), 'restored': restored}
        version = subprocess.run([tool, '--version'], capture_output=True, text=True)
        receipt['inputs'] = {
            'state_inventories': inventories,
            'tippecanoe': (version.stdout + version.stderr).strip(),
            'tile_join_present': Path(tool).resolve().with_name('tile-join').exists(),
            'build_options': {'control': 'precise=True', 'candidate': 'precise=True, coarse_first=True'},
            'files_sha256': {p: file_sha(root/p) for p in (
                'scripts/build_map_tiles.py', 'src/skippercast/seafloor/publish.py',
                'src/skippercast/seafloor/measure.py', 'dist/data/seafloor-ledger.json', 'catalog/surveys.json',
                'catalog/habitat-rules.json', 'catalog/classified-habitat-policy.json',
                'var/seafloor/reference/cells.json')}}
        cached = {}
        original_layers = publish.region_layers

        def same_layers(*args, **kwargs):
            if 'value' not in cached:
                cached['value'] = original_layers(*args, **kwargs)
            return cached['value']
        publish.region_layers = same_layers
        archive = root/'var/seafloor/public'/region/f'seafloor-{region}.pmtiles'
        _, rk_manifest = publish.build(region, root=root, tool=tool)
        shutil.copyfile(archive, work/'Rk.pmtiles')
        plain = builder.build_vector_archive
        builder.build_vector_archive = functools.partial(plain, coarse_first=True)
        try:
            _, rc_manifest = publish.build(region, root=root, tool=tool)
        finally:
            builder.build_vector_archive = plain
            publish.region_layers = original_layers
        shutil.copyfile(archive, work/'Rc.pmtiles')
        rk_data, rc_data = (work/'Rk.pmtiles').read_bytes(), (work/'Rc.pmtiles').read_bytes()
        receipt['archives'] = {
            'C_live': {'sha256': sha256_bytes(c_data), 'bytes': len(c_data)},
            'Rk_control': {'sha256': sha256_bytes(rk_data), 'bytes': len(rk_data), 'layers': rk_manifest['layers']},
            'Rc_candidate': {'sha256': sha256_bytes(rc_data), 'bytes': len(rc_data), 'layers': rc_manifest['layers']}}
        receipt['inputs']['reach_inputs_match_live'] = rk_manifest.get('reach_inputs') == live.get('reach_inputs')
        receipt['inputs']['classified_inputs_match_live'] = (rk_manifest.get('classified_inputs')
                                                             == live.get('classified_inputs'))
        receipt.update(evaluate(read_tiles(c_data), read_tiles(rk_data), read_tiles(rc_data)))
    except Exception as error:  # the receipt still records the attempt (a refused write too); no tracebacks
        receipt['error'] = {'type': type(error).__name__, 'message': str(error)[:300],
                            'stage_only_refusal': isinstance(error, StageOnlyWrite)}
        receipt['pass'] = False
    receipt['bucket_after'] = snapshot(s3, bucket, keys, region)
    receipt['bucket_unchanged'] = receipt['bucket_before'] == receipt['bucket_after']
    receipt['bucket_listing_available'] = 'error' not in receipt['bucket_after']['listing']
    receipt['s3_calls'] = dict(sorted(s3.calls.items()))
    Path(out).write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description='STAGE-ONLY size receipt for the rough-first seafloor archive')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--region', default=REGION)
    args = parser.parse_args()
    from skippercast.platform.contracts import REPO
    receipt = measure(REPO, args.out, region=args.region)
    summary = {k: receipt.get(k) for k in ('pass', 'size_pass', 'bucket_unchanged', 'error')}
    summary['z8'] = (receipt.get('per_zoom', {}).get('8') or {}).get('Rc_candidate')
    summary['z8_vs_A1_percent'] = (receipt.get('per_zoom', {}).get('8') or {}).get('Rc_vs_A1_percent')
    print(json.dumps(summary, sort_keys=True))
    if 'error' in receipt:
        sys.exit(1)


if __name__ == '__main__':
    main()
