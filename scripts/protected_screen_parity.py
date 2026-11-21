#!/usr/bin/env python3
"""SC-PERF-PROTCHECK-1 parity check on a real habitat export: the publish-time verdicts
(src/skippercast/seafloor/protected_screen.py) against what the browser's own code answers
(scripts/protected_screen_oracle.mjs: real `initProtectedAreas` + `screenPlace`) for EVERY reef.

Use --region to select the boundary inputs and --at (ISO 8601 with timezone)
to replay at a fixed clock. By default the clock is captured once at startup.
Use --write-oracle to retain the result; --oracle replays it at the same --at.
Exit 0 only when every compared reef's verdict is identical (inside, name, distanceM, screened) and the
fingerprints match on the same pinned, current boundary inputs.
"""
import argparse
import base64
import gzip
import hashlib
import json
import re
import subprocess
import sys
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'src'))
from skippercast.seafloor import protected_screen as ps  # noqa: E402


def _chunk(args):
    boundary, bounds, reefs = args
    return ps.verdicts(boundary, bounds, reefs)


def _positive(text):
    try:
        n = int(text)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError('must be a whole number of 1 or more')
    return n


def _read_export(name, path):
    try:
        raw = Path(path).read_bytes()
        data = json.loads(gzip.decompress(raw) if path.endswith('.gz') else raw)
        if not isinstance(data, dict) or not isinstance(data.get('features'), list):
            raise ValueError('not an object with a features list')
    except (OSError, EOFError, ValueError, zlib.error) as e:     # BadGzipFile and JSONDecodeError are subclasses
        print(f'{name}: cannot read export {path}: {e}', file=sys.stderr)
        sys.exit(2)
    return data


def _epoch_ms(text):
    stamp = datetime.fromisoformat(text)
    if stamp.utcoffset() is None:
        raise ValueError('timestamp needs a timezone')
    return (stamp - datetime(1970, 1, 1, tzinfo=timezone.utc)) // timedelta(milliseconds=1)


def _clock(text):
    try:
        return _epoch_ms(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('expected an ISO 8601 timestamp with timezone') from exc


def _current(doc, now):
    try:
        age = now - _epoch_ms(doc.get('checked_at'))
    except (TypeError, ValueError):
        return False
    return -300_000 <= age <= 36 * 3_600_000


def _pin(region, now):
    if not re.fullmatch('[a-z][a-z0-9-]{1,63}', region):
        return None
    config = REPO/'dist/regions'/region/'region.json'
    if not config.is_file():
        return None
    cfg = json.loads(config.read_bytes())
    bounds = (cfg.get('mpa') or {}).get('bounds')
    assets = cfg.get('assets') or {}
    if cfg.get('id', region) != region or not assets.get('protected_areas') or not bounds:
        return None
    raw, features, current = {}, [], True
    for key in ('protected_areas', 'closures'):
        if path := assets.get(key):
            if path not in raw:
                raw[path] = (REPO/'dist'/path).read_bytes()
            doc = json.loads(raw[path])
            features.extend(doc['features'])
            current = _current(doc, now) and current
    # Node cannot re-read a newer file or select a different regional default.
    packet = json.dumps({'region': cfg, 'now': now, 'assets': {
        path: base64.b64encode(data).decode('ascii') for path, data in raw.items()
    }})
    return bounds, features, current, packet


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('export')
    output = ap.add_mutually_exclusive_group()
    output.add_argument('--oracle', help='reuse a pinned oracle result (requires the original --at)')
    output.add_argument('--write-oracle', help='retain the generated oracle result')
    ap.add_argument('--limit', type=_positive)
    ap.add_argument('--workers', type=_positive, default=4)
    ap.add_argument('--region', default='morro-bay')
    ap.add_argument('--at', type=_clock, help='ISO 8601 replay time with timezone')
    a = ap.parse_args(argv)
    now = a.at if a.at is not None else time.time_ns() // 1_000_000
    loaded = _pin(a.region, now)
    if loaded is None:
        print(f'protected-screen-parity: no protected screen for region {a.region}', file=sys.stderr)
        sys.exit(2)
    bounds, boundary, current, packet = loaded
    export = _read_export('protected-screen-parity', a.export)
    features = export['features'][:a.limit] if a.limit else export['features']
    if a.oracle:
        oracle = json.loads(Path(a.oracle).read_text())
    else:
        with TemporaryDirectory(prefix='protected-screen-oracle-') as scratch:
            oracle_path = Path(scratch)/'oracle.json'
            cmd = ['node', str(REPO/'scripts/protected_screen_oracle.mjs'), a.export, str(oracle_path)]
            if a.limit:
                cmd += ['--limit', str(a.limit)]
            if subprocess.run(cmd, input=packet, text=True).returncode:
                return 1
            oracle = json.loads(oracle_path.read_text())
    reefs = [(f['properties']['id'], f['geometry'], f['properties']['waypoint']['longitude'], f['properties']['waypoint']['latitude'])
             for f in features]
    t0 = time.time()
    size = max(1, len(reefs)//(a.workers*4))
    parts = [(boundary, bounds, reefs[i:i + size]) for i in range(0, len(reefs), size)]
    ours = {}
    with ProcessPoolExecutor(a.workers) as pool:
        for part in pool.map(_chunk, parts):
            ours.update(part)
    elapsed = time.time() - t0
    fp = ps.fingerprint([f['geometry'] for f in boundary], bounds, [ps.feature_name(f) for f in boundary])
    diffs = [(rid, ours[rid], oracle['verdicts'].get(rid)) for rid, *_ in reefs if ours[rid] != oracle['verdicts'].get(rid)]
    inside = sum(v['inside'] for v in ours.values())
    unscreened = sum(not v['screened'] for v in ours.values())
    named = sum(v['name'] is not None for v in ours.values())
    print(f'reefs compared: {len(reefs)}  (oracle has {len(oracle["verdicts"])})')
    print(f'python verdicts in {elapsed:.1f} s; oracle (node, real screen) in {oracle["ms"]/1000:.1f} s')
    print(f'verdicts: inside={inside} unscreened={unscreened} with a nearest closure={named}')
    print(f'fingerprint python={fp} browser-code={oracle["fingerprint"]} -> {"SAME" if fp == oracle["fingerprint"] else "DIFFERENT"}')
    print(f'differences: {len(diffs)}')
    for rid, mine, theirs in diffs[:20]:
        print('  DIFF', rid, 'python', mine, 'browser', theirs)
    if diffs or fp != oracle['fingerprint'] or len(reefs) != len(oracle['verdicts']):
        return 1
    if not current:
        print('protected-screen-parity: boundary snapshot is not current at the test clock', file=sys.stderr)
        return 1
    if oracle.get('inputSha256') != hashlib.sha256(packet.encode('ascii')).hexdigest():
        print('protected-screen-parity: oracle inputs or test clock do not match', file=sys.stderr)
        return 1
    if a.write_oracle:
        Path(a.write_oracle).write_text(json.dumps(oracle))
    return 0


if __name__ == '__main__':
    sys.exit(main())
