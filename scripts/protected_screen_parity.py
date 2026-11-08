#!/usr/bin/env python3
"""SC-PERF-PROTCHECK-1 parity check on a real habitat export: the publish-time verdicts
(src/skippercast/seafloor/protected_screen.py) against what the browser's own code answers
(scripts/protected_screen_oracle.mjs: real `initProtectedAreas` + `screenPlace`) for EVERY reef.

Usage: protected_screen_parity.py <habitat-export.geojson[.gz]> [--oracle out.json] [--limit N] [--workers N]
  --oracle   reuse an oracle result already written (otherwise node is run first)
Exit 0 only when every compared reef's verdict is identical (inside, name, distanceM, screened) and the
fingerprints match; any difference is printed and fails the run.
"""
import argparse
import gzip
import json
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'src'))
from skippercast.seafloor import protected_screen as ps  # noqa: E402


def _chunk(args):
    boundary, bounds, reefs = args
    return ps.verdicts(boundary, bounds, reefs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('export')
    ap.add_argument('--oracle')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--region', default='morro-bay')
    a = ap.parse_args()
    raw = Path(a.export).read_bytes()
    export = json.loads(gzip.decompress(raw) if a.export.endswith('.gz') else raw)
    features = export['features'][:a.limit] if a.limit else export['features']
    oracle_path = Path(a.oracle or f'/tmp/protected-screen-oracle-{a.region}.json')
    if not a.oracle:
        cmd = ['node', str(REPO/'scripts/protected_screen_oracle.mjs'), a.export, str(oracle_path)] + (['--limit', str(a.limit)] if a.limit else [])
        subprocess.run(cmd, check=True)
    oracle = json.loads(oracle_path.read_text())
    bounds, boundary, files = ps.load_screen(REPO, a.region)
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
    fp = ps.fingerprint([f['geometry'] for f in boundary], bounds)
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
    return 0 if not diffs and fp == oracle['fingerprint'] and len(reefs) == len(oracle['verdicts']) else 1


if __name__ == '__main__':
    sys.exit(main())
