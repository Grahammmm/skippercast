#!/usr/bin/env python3
"""SC-PERF-REEFDIET-1: build the full export (with publish-time verdicts) and the slim file from a real habitat export, the way publish.build does.

Usage: reef_slim_build.py <habitat-export.geojson.gz> <out-dir> [--region morro-bay]
Writes <out-dir>/habitat-export.geojson.gz, the slim file (habitat-slim-<sha16>.geojson.gz) and manifest.json (the fields the loader reads); prints sizes.
Used by scripts/reef_slim_parity.mjs and by the size / load measurements in the pull request.
"""
import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'src'))
from skippercast.seafloor.protected_screen import stamp  # noqa: E402
from skippercast.seafloor.slim import write_slim  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('export')
    ap.add_argument('out')
    ap.add_argument('--region', default='morro-bay')
    ap.add_argument('--limit', type=int)
    a = ap.parse_args()
    raw = Path(a.export).read_bytes()
    data = json.loads(gzip.decompress(raw) if a.export.endswith('.gz') else raw)
    if a.limit:
        data['features'] = data['features'][:a.limit]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    protected = stamp(REPO, a.region, data['features'])
    if protected:
        data['protected_screen'] = protected
    body = json.dumps(data, separators=(',', ':')).encode()
    packed = gzip.compress(body, mtime=0)
    (out/'habitat-export.geojson.gz').write_bytes(packed)
    sha = hashlib.sha256(packed).hexdigest()
    slim = write_slim(out, region=a.region, expires_at=data['expires_at'], export_sha256=sha, protected=protected,
                      export_features=data['features'])
    manifest = {'region': a.region, 'status': 'ready', 'archive_sha256': 'a'*64, 'expires_at': data['expires_at'],
                'built_at': data.get('built_at') or '2026-11-07T00:00:00+00:00',
                'export_file': 'habitat-export.geojson.gz', 'export_sha256': sha, 'export_bytes': len(packed),
                'export_decoded_bytes': len(body), **slim}
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(f'reefs {len(data["features"])}; full export {len(packed)} bytes gz ({len(body)} decoded); '
          f'slim {slim.get("slim_bytes")} bytes gz ({slim.get("slim_decoded_bytes")} decoded); fingerprint {protected and protected["fingerprint"]}')


if __name__ == '__main__':
    main()
