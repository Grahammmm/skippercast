"""Fetch bounded, previously audited original USGS class archives for footprint review."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


HOSTS = {'pubs.usgs.gov', 'cmgds.marine.usgs.gov'}
LIMIT = 16 * 1024 * 1024


def fetch(row, cache):
    url = row['archive_url']
    if urlparse(url).scheme != 'https' or urlparse(url).hostname not in HOSTS:
        raise ValueError('Unreviewed original USGS host')
    if not 0 < row['archive_bytes'] <= LIMIT:
        raise ValueError('Original USGS archive exceeds bounded class-screen size')
    expected = row['archive_sha256']
    path = cache / f"{row['release_id']}-seafloor_character-{expected[:16]}.zip"
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.part')
        digest = hashlib.sha256()
        size = 0
        try:
            request = Request(url, headers={'User-Agent': 'SkipperCast/0.3 (public marine research)'})
            with urlopen(request, timeout=60) as source, temp.open('wb') as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > LIMIT:
                        raise ValueError('Original USGS archive exceeded byte limit')
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest() != expected or size != row['archive_bytes']:
                raise ValueError('Original USGS archive hash or size changed')
            temp.replace(path)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('Cached original USGS archive hash changed')
    return {'release_id': row['release_id'], 'archive_sha256': expected,
            'archive_bytes': row['archive_bytes'], 'source_url': url}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, default=Path('dist/data/nbs-hard-footprint-tile-inventory.json'))
    parser.add_argument('--usgs-audit', type=Path, default=Path('var/usgs-doi-native-audit.json'))
    parser.add_argument('--map-audit', type=Path, default=Path('var/usgs-native-audit.json'))
    parser.add_argument('--usgs-cache', type=Path, default=Path('var/usgs-doi-native-cache'))
    parser.add_argument('--map-cache', type=Path, default=Path('var/usgs-native-cache'))
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--output', type=Path, default=Path('var/review/nbs-hard-footprint-usgs-class-fetch.json'))
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        raise ValueError('workers must be 1–8')
    inventory = json.loads(args.inventory.read_text())
    if inventory.get('scope') != 'noaa-nbs-tiles-intersecting-displayed-usgs-hard-context':
        raise ValueError('Reviewed footprint inventory required')
    ids = {source for tile in inventory['tiles'] for source in tile['source_ids']}
    sources = []
    for path, cache, id_key in ((args.usgs_audit, args.usgs_cache, 'release_id'),
                                (args.map_audit, args.map_cache, 'block_id')):
        audit = json.loads(path.read_text())
        for original in audit['products']:
            if (original.get(id_key) in ids and original.get('kind') == 'seafloor_character'
                    and original.get('status') == 'ok'):
                sources.append(({**original, 'release_id': original[id_key]}, cache))
    results, failures = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        jobs = {executor.submit(fetch, row, cache): row for row, cache in sources}
        for future in as_completed(jobs):
            row = jobs[future]
            try:
                results.append(future.result())
            except Exception as exc:
                failures.append({'release_id': row['release_id'],
                                 'archive_sha256': row['archive_sha256'],
                                 'error': f'{type(exc).__name__}: {exc}'})
    report = {'schema_version': 1, 'scope': 'original-usgs-hard-footprint-class-archive-fetch',
              'requested': len(sources), 'verified': len(results), 'failed': len(failures),
              'status': 'complete' if not failures else 'partial',
              'fishing_target': False, 'exportable': False,
              'archives': sorted(results, key=lambda r: (r['release_id'], r['archive_sha256'])),
              'failures': sorted(failures, key=lambda r: (r['release_id'], r['archive_sha256']))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(report['verified'], '/', report['requested'], 'verified;', report['failed'], 'failed')
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
