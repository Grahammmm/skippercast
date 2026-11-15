"""Rough-first seafloor archive: its size gate and the size receipt every build writes (R4-SC-09-F1c).

A region listed in catalog/seafloor-rough-first.json publishes a rough-first archive: z8-11 carry
habitat only, with tippecanoe's default detail and simplification, and z12-15 keep the precise
build (scripts/build_map_tiles.build_vector_archive(..., coarse_first=True)). Every other region
publishes today's archive unchanged.

publish.build() builds the control archive Rk (today's builder) and the rough-first candidate Rc
from the same region layers in the same run. ``evaluate`` judges Rc against the approved
reference sizes with the tolerance policy of the F1c REPLAN proposal (revision 2, section 4),
which G approved on 2026-11-14:

1. z8-11 payload bytes at or under reference x (1 + margin), and the opening z10 view too; an
   Rc/Rk ratio under the anomaly floor at any of z8-11 fails (a rough zoom gone missing).
3. every z12-15 tile of Rc byte-identical to Rk's, with the same tile set: tolerance 0.
4. z9-11: every habitat id in Rk is in Rc, and feature occurrences are at least 99% of Rk's.

(Item 0 of the proposal, Rk against the live archive tile by tile, was the measurement's
calibration: F1C-MEASURE matched 1097 of 1097 tiles. Once the live file is rough-first, the
in-run control Rk is the reference for item 3. Item 2, the label, is the client's.)

Any failed item, and any archive this module cannot read, fails the gate: publish.build() raises
GateFailure before anything is uploaded. Nothing here writes the reference file; changing a
reference size is a rebaseline that waits for G.

Every build, control or rough-first, writes var/seafloor/publication/<region>-tiles.json: per-zoom
payload bytes and tile counts, archive hashes and, for rough-first, each gate item. It holds sizes
and hashes only, never tiles, so the workflow may keep it as a run artifact.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys

from skippercast.platform.contracts import REPO, atomic_json, read_json

REFERENCE_FILE = 'catalog/seafloor-rough-first.json'
ROUGH_ZOOMS = (8, 9, 10, 11)
DETAIL_ZOOMS = (12, 13, 14, 15)
CONTENT_ZOOMS = (9, 10, 11)
REPORTED_ZOOMS = (8, 9, 10, 11, 12)
# The manifest field the client reads to show the rough layer first (web/map/seafloor.ts).
MANIFEST_FIELD = {'maxzoom': 11, 'detail_minzoom': 12}
REGION = re.compile('[a-z0-9-]+')
TILE = re.compile(r'(\d{1,2})/(\d+)/(\d+)')


class GateFailure(ValueError):
    """The rough-first candidate missed the approved size policy; nothing was published."""


# ---- Reference -----------------------------------------------------------------------------

def load_reference(root, region):
    """The region's approved reference, or None when the region publishes the control archive.

    A missing file or an unlisted region is the control archive. A listed region whose entry is
    malformed raises: a broken reference never quietly turns the gate off.
    """
    path = Path(root)/REFERENCE_FILE
    if not path.exists():
        return None
    entry = read_json(path).get('regions', {}).get(region)
    if entry is None:
        return None
    sizes = entry.get('rough_zoom_bytes')
    opening = entry.get('opening_view')
    valid = (isinstance(sizes, dict) and sorted(sizes) == sorted(str(z) for z in ROUGH_ZOOMS)
             and all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in sizes.values())
             and isinstance(opening, dict) and isinstance(opening.get('tiles'), list) and opening['tiles']
             and all(isinstance(t, str) and TILE.fullmatch(t) for t in opening['tiles'])
             and isinstance(opening.get('bytes'), int) and opening['bytes'] > 0
             and isinstance(entry.get('margin_per_mille'), int) and 0 <= entry['margin_per_mille'] <= 1000
             and isinstance(entry.get('anomaly_floor'), (int, float)) and 0 < entry['anomaly_floor'] < 1
             and isinstance(entry.get('occurrence_floor'), (int, float)) and 0 < entry['occurrence_floor'] <= 1)
    if not valid:
        raise ValueError(f'Invalid rough-first reference for {region}; publication not attempted')
    return entry


def ceiling(reference_bytes, margin_per_mille):
    """Pass if Rc <= this: the reference times (1 + margin), rounded down, in exact integer arithmetic."""
    return reference_bytes * (1000 + margin_per_mille) // 1000


# ---- PMTiles v3 reading (gzip directories, as tippecanoe writes) --------------------------

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
    """{(z, x, y): stored tile bytes} for a PMTiles v3 archive with gzip directories."""
    if data[:8] != b'PMTiles\x03' or len(data) < 127:
        raise ValueError('not PMTiles v3')
    h = struct.unpack_from('<11Q', data, 8)
    if data[97] != 2:
        raise ValueError('expected gzip internal compression')
    tiles = {}

    def walk(offset, length, depth=0):
        if depth > 3:
            raise ValueError('directory nesting too deep')
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
                walk(h[4] + off, size, depth + 1)
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


def identity(reference, candidate, zooms):
    """Tile-level byte identity of candidate against reference over the given zooms."""
    keys_a = {k for k in reference if k[0] in zooms}
    keys_b = {k for k in candidate if k[0] in zooms}
    same = sorted(k for k in keys_a & keys_b if reference[k] == candidate[k])
    differ = sorted(k for k in keys_a & keys_b if reference[k] != candidate[k])
    by_zoom = {str(z): {'identical': sum(k[0] == z for k in same), 'different': sum(k[0] == z for k in differ),
                        'only_reference': sum(k[0] == z for k in keys_a - keys_b),
                        'only_candidate': sum(k[0] == z for k in keys_b - keys_a)} for z in sorted(zooms)}
    return {'identical': len(same), 'addressed_reference': len(keys_a), 'addressed_candidate': len(keys_b),
            'all_identical': bool(keys_a) and keys_a == keys_b and not differ, 'by_zoom': by_zoom,
            'first_different': ['/'.join(map(str, k)) for k in sorted(differ + sorted(keys_a ^ keys_b))[:20]]}


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
    """(feature occurrences, set of ids) in one gzip MVT tile's habitat layer."""
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


# ---- Receipts ------------------------------------------------------------------------------

def _run():
    return {key: os.environ.get(name) for key, name in (
        ('commit', 'GITHUB_SHA'), ('github_run_id', 'GITHUB_RUN_ID'), ('github_run_attempt', 'GITHUB_RUN_ATTEMPT'))}


def _archive(data, tiles):
    return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
            'per_zoom': {str(z): v for z, v in per_zoom(tiles).items()} if tiles is not None else None}


def control_receipt(region, data):
    """Sizes of the control archive a region not listed for rough-first publishes; no gate applies."""
    try:
        tiles, error = read_tiles(data), None
    except (ValueError, struct.error, OSError, EOFError, IndexError) as exc:
        tiles, error = None, type(exc).__name__
    receipt = {'receipt': 'seafloor archive size receipt', 'region': region, 'mode': 'control', **_run(),
               'archive': _archive(data, tiles), 'gate': None, 'pass': True}
    if error:
        receipt['archive']['unreadable'] = error
    return receipt


def evaluate(region, control_data, candidate_data, reference, *, reference_sha256=None):
    """Section 4 items 1, 3 and 4 for Rc against Rk; ``pass`` is False on any failure or unreadable archive."""
    receipt = {'receipt': 'seafloor archive size receipt', 'region': region, 'mode': 'rough-first', **_run(),
               'policy': 'F1c REPLAN proposal revision 2, section 4 (approved by G 2026-11-14); no automatic rebaseline',
               'reference_file': REFERENCE_FILE, 'reference_sha256': reference_sha256}
    try:
        rk_tiles, rc_tiles = read_tiles(control_data), read_tiles(candidate_data)
    except (ValueError, struct.error, OSError, EOFError, IndexError) as exc:
        receipt.update(control=_archive(control_data, None), archive=_archive(candidate_data, None),
                       error=f'unreadable archive: {type(exc).__name__}', gate={}, failed=['unreadable archive'],
                       **{'pass': False})
        return receipt
    rk, rc = per_zoom(rk_tiles), per_zoom(rc_tiles)
    margin, floor = reference['margin_per_mille'], reference['anomaly_floor']
    sizes = {}
    for z in ROUGH_ZOOMS:
        ref = reference['rough_zoom_bytes'][str(z)]
        rc_bytes, rk_bytes = rc.get(z, {}).get('bytes', 0), rk.get(z, {}).get('bytes', 0)
        ratio = rc_bytes / rk_bytes if rk_bytes else None
        sizes[str(z)] = {'reference': ref, 'ceiling': ceiling(ref, margin), 'Rc_bytes': rc_bytes,
                         'Rc_tiles': rc.get(z, {}).get('tiles', 0), 'Rk_bytes': rk_bytes,
                         'Rc_vs_reference_percent': round((rc_bytes - ref) / ref * 100, 3),
                         'Rc_over_Rk': round(ratio, 4) if ratio is not None else None,
                         'within_ceiling': rc_bytes <= ceiling(ref, margin),
                         'anomaly': ratio is None or ratio < floor}
    opening_tiles = [tuple(int(v) for v in t.split('/')) for t in reference['opening_view']['tiles']]
    opening = sum(len(rc_tiles.get(k, b'')) for k in opening_tiles)
    opening_ceiling = ceiling(reference['opening_view']['bytes'], margin)
    total_rk, total_rc = sum(map(len, rk_tiles.values())), sum(map(len, rc_tiles.values()))
    detail = identity(rk_tiles, rc_tiles, set(DETAIL_ZOOMS))
    try:
        rk_content, rc_content = content(rk_tiles, REPORTED_ZOOMS), content(rc_tiles, REPORTED_ZOOMS)
        content_error = None
    except (ValueError, OSError, EOFError, IndexError, UnicodeDecodeError) as exc:
        rk_content, rc_content = {}, {}
        content_error = type(exc).__name__
    retained = {}
    for z in REPORTED_ZOOMS if rk_content else ():
        (rk_n, rk_ids), (rc_n, rc_ids) = rk_content[z], rc_content[z]
        retained[str(z)] = {'Rk_occurrences': rk_n, 'Rc_occurrences': rc_n, 'Rk_ids': len(rk_ids),
                            'Rc_ids': len(rc_ids), 'Rk_ids_missing_in_Rc': len(rk_ids - rc_ids),
                            'occurrence_ratio': round(rc_n / rk_n, 4) if rk_n else None}
    occurrence_floor = reference['occurrence_floor']
    content_pass = bool(retained) and all(
        retained[str(z)]['Rk_ids_missing_in_Rc'] == 0 and retained[str(z)]['occurrence_ratio'] is not None
        and rc_content[z][0] >= occurrence_floor * rk_content[z][0] for z in CONTENT_ZOOMS)
    gate = {
        'item1_rough_sizes': {'pass': all(s['within_ceiling'] and not s['anomaly'] for s in sizes.values())
                                      and opening <= opening_ceiling,
                              'per_zoom': sizes, 'anomaly_floor': floor,
                              'opening_view': {'tiles': reference['opening_view']['tiles'], 'Rc_bytes': opening,
                                               'reference': reference['opening_view']['bytes'],
                                               'ceiling': opening_ceiling}},
        'item3_detail_identical_z12_15': {'pass': detail['all_identical'], **detail},
        'item4_content_z9_11': {'pass': content_pass, 'by_zoom': retained, 'occurrence_floor': occurrence_floor,
                                'note': 'z8 and z12 reported, not gated',
                                **({'error': content_error} if content_error else {})},
    }
    receipt.update(control=_archive(control_data, rk_tiles), archive=_archive(candidate_data, rc_tiles), gate=gate,
                   whole_file_payload={'Rk': total_rk, 'Rc': total_rc,
                                       'saving_percent': round((1 - total_rc / total_rk) * 100, 3) if total_rk else None},
                   failed=[name for name, item in gate.items() if not item['pass']])
    receipt['pass'] = not receipt['failed']
    return receipt


def receipt_path(root, region):
    if not REGION.fullmatch(region or ''):
        raise ValueError('Invalid region')
    return Path(root)/'var/seafloor/publication'/f'{region}-tiles.json'


def write_receipt(root, region, receipt):
    path = receipt_path(root, region)
    atomic_json(path, receipt, indent=2)
    return path


def summary(receipt):
    """Markdown for the job summary: the published archive's per-zoom sizes and the gate verdict."""
    if receipt is None:
        return '\nNo seafloor size receipt: the build did not reach the archive.\n'
    archive = receipt.get('archive') or {}
    lines = ['', f"### Seafloor size receipt: {receipt.get('region')} ({receipt.get('mode')})", '',
             f"Archive {archive.get('bytes')} B, sha256 {archive.get('sha256')}."]
    if receipt.get('mode') == 'rough-first':
        verdict = 'PASS' if receipt.get('pass') else 'FAIL: nothing published (' + ', '.join(
            receipt.get('failed') or [receipt.get('error', 'unreadable')]) + ')'
        lines += [f'Rough-first gate: {verdict}. No automatic rebaseline.', '',
                  '| Zoom | Rc B | Reference B | Ceiling B | Rc / Rk |', '| ---: | ---: | ---: | ---: | ---: |']
        for z, row in sorted(((receipt.get('gate') or {}).get('item1_rough_sizes') or {}).get('per_zoom', {}).items(),
                             key=lambda item: int(item[0])):
            lines.append(f"| {z} | {row['Rc_bytes']} | {row['reference']} | {row['ceiling']} | {row['Rc_over_Rk']} |")
        opening = ((receipt.get('gate') or {}).get('item1_rough_sizes') or {}).get('opening_view')
        if opening:
            lines += ['', f"Opening view {' + '.join(opening['tiles'])}: {opening['Rc_bytes']} B "
                          f"(ceiling {opening['ceiling']} B)."]
        detail = (receipt.get('gate') or {}).get('item3_detail_identical_z12_15')
        if detail:
            lines.append(f"z12-15 identical to the control build: {detail['identical']} of "
                         f"{detail['addressed_reference']} tiles.")
    else:
        lines += ['', '| Zoom | Tiles | Payload B |', '| ---: | ---: | ---: |']
        for z, row in sorted((archive.get('per_zoom') or {}).items(), key=lambda item: int(item[0])):
            lines.append(f"| {z} | {row['tiles']} | {row['bytes']} |")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Print the seafloor size receipt for a region as Markdown')
    parser.add_argument('stage', choices=('summary',))
    parser.add_argument('--region', required=True)
    args = parser.parse_args(argv)
    path = receipt_path(REPO, args.region)
    sys.stdout.write(summary(read_json(path) if path.exists() else None))


if __name__ == '__main__':
    main()
